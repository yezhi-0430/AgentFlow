import test from 'node:test'
import assert from 'node:assert/strict'
import {
  CREDENTIAL_BADGE,
  CREDENTIAL_HINT,
  CREDENTIAL_NOTICE,
  MISSING_KEY_MESSAGE,
  mergeWorkflowDisplay,
  missingCredentialMessage,
  normalizeExecutionStatus,
  pickRestoredWorkflow,
  requiresCredentials,
} from '../src/utils/credentialState.js'
import {
  WORKFLOW_STORAGE_KEY,
  readStoredWorkflow,
  workflowSnapshot,
  writeStoredWorkflow,
} from '../src/utils/workflowStorage.js'

function createStorage(initial = {}) {
  const map = new Map(Object.entries(initial))
  return {
    map,
    getItem: key => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => map.set(key, String(value)),
    removeItem: key => map.delete(key),
  }
}

test('requires_credentials 状态与提示文案清晰说明密钥未保存', () => {
  assert.equal(requiresCredentials({ requires_credentials: true }), true)
  assert.equal(requiresCredentials({ requires_credentials: false }), false)
  assert.equal(requiresCredentials(null), false)
  assert.match(CREDENTIAL_BADGE, /API Key/)
  assert.match(CREDENTIAL_NOTICE, /需要重新输入 API Key/)
  assert.match(CREDENTIAL_NOTICE, /密钥未保存/)
  assert.match(CREDENTIAL_HINT, /不会写入本地存储/)
})

test('恢复/导入的工作流在真正执行前不显示历史终态', () => {
  const restored = { requires_credentials: true }
  for (const status of ['completed', 'failed', 'partial', 'stopped', 'cancelled', 'error']) {
    assert.equal(normalizeExecutionStatus(status, restored), 'idle', status)
  }
  assert.equal(normalizeExecutionStatus('imported', restored), 'idle')
  assert.equal(normalizeExecutionStatus('unavailable', restored), 'idle')
  assert.equal(normalizeExecutionStatus('running', restored), 'running')
  assert.equal(normalizeExecutionStatus('created', restored), 'created')
  assert.equal(normalizeExecutionStatus(null, restored), 'idle')

  // 已经提供过密钥的工作流保留真实终态。
  const ready = { requires_credentials: false }
  assert.equal(normalizeExecutionStatus('completed', ready), 'completed')
  assert.equal(normalizeExecutionStatus('failed', ready), 'failed')
  assert.equal(normalizeExecutionStatus('completed', null), 'completed')
})

test('后端 400 缺少密钥时转换为中文提示，其他错误原样保留', () => {
  assert.equal(
    missingCredentialMessage({ response: { status: 400, data: { detail: 'This workflow was restored after restart and needs an API key. Provide api_key.' } } }),
    MISSING_KEY_MESSAGE,
  )
  assert.match(MISSING_KEY_MESSAGE, /需要重新提供 API Key/)
  assert.equal(missingCredentialMessage({ response: { status: 400, data: { detail: 'API key is required' } } }), MISSING_KEY_MESSAGE)
  assert.equal(missingCredentialMessage({ response: { status: 400, data: { detail: 'Unknown workflow pattern' } } }), '')
  assert.equal(missingCredentialMessage({ response: { status: 500, data: { detail: 'needs an API key' } } }), '')
  assert.equal(missingCredentialMessage(new Error('network')), '')
})

test('恢复时优先打开记住的 workflow_id，失效时退回最近一个', () => {
  const workflows = [
    { workflow_id: 'old', name: '旧' },
    { workflow_id: 'latest', name: '最新' },
  ]
  assert.equal(pickRestoredWorkflow('old', workflows).workflow_id, 'old')
  assert.equal(pickRestoredWorkflow('deleted', workflows).workflow_id, 'latest')
  assert.equal(pickRestoredWorkflow(undefined, workflows).workflow_id, 'latest')
  assert.equal(pickRestoredWorkflow('old', []), null)
  assert.equal(pickRestoredWorkflow('old', null), null)
})

test('合并本地快照与服务端数据时服务端字段优先，并保留展示用智能体信息', () => {
  const saved = {
    workflow_id: 'wf', name: '本地名称', pattern: 'sequential',
    agents: [{ name: 'worker_1', system_prompt: '本地提示' }],
    api_key: 'sk-must-not-survive',
  }
  const latest = {
    workflow_id: 'wf', name: '服务端名称', status: 'idle', requires_credentials: true,
    agents: [{ name: 'worker_1', model: 'gpt-4', status: 'unavailable' }],
  }
  const merged = mergeWorkflowDisplay(saved, latest)
  assert.equal(merged.name, '服务端名称')
  assert.equal(merged.requires_credentials, true)
  assert.equal(merged.agents[0].system_prompt, '本地提示')
  assert.equal(merged.agents[0].status, 'unavailable')
  assert.equal(mergeWorkflowDisplay(null, null), null)
})

test('用于本地存储的快照只保留展示字段，密钥字段没有入口', () => {
  const workflow = {
    workflow_id: 'wf-1',
    name: '工作流',
    description: '描述',
    pattern: 'parallel',
    workflow_id_extra: 'ignored',
    isDemo: false,
    connection: { provider: 'openai', api_key: 'sk-connection' },
    api_key: 'sk-root',
    agents: [
      { name: 'worker_1', role: 'worker', model: 'gpt-4', status: 'idle', api_key: 'sk-agent', metadata: { token: 'secret' } },
    ],
    steps: [{ id: 'step_1', agent_name: 'worker_1', api_key: 'sk-step' }],
  }
  const snapshot = workflowSnapshot(workflow)
  const serialized = JSON.stringify(snapshot)
  assert.doesNotMatch(serialized, /sk-/)
  assert.doesNotMatch(serialized, /connection/)
  assert.doesNotMatch(serialized, /isDemo/)
  assert.deepEqual(snapshot.steps, [{ id: 'step_1', agent_name: 'worker_1', input_from: null }])
  assert.deepEqual(snapshot.agents[0], { name: 'worker_1', role: 'worker', model: 'gpt-4', status: 'idle' })
  assert.equal(workflowSnapshot({ name: '缺少 id' }), null)
  assert.equal(workflowSnapshot(null), null)
})

test('本地存储优先 localStorage，并在不可用时退回 sessionStorage', () => {
  const local = createStorage()
  const session = createStorage()
  const scope = { localStorage: local, sessionStorage: session }
  assert.equal(writeStoredWorkflow({ workflow_id: 'w1', name: '一' }, scope), true)
  assert.ok(local.map.has(WORKFLOW_STORAGE_KEY))
  assert.equal(session.map.size, 0)

  const read = readStoredWorkflow(scope)
  assert.equal(read.hasValue, true)
  assert.equal(read.empty, false)
  assert.equal(read.workflow.workflow_id, 'w1')
  assert.equal(read.workflow.name, '一')

  // 记住"空工作区"时写入 null 标记，刷新后不会被自动恢复。
  writeStoredWorkflow(null, scope)
  assert.equal(local.map.get(WORKFLOW_STORAGE_KEY), 'null')
  assert.deepEqual(readStoredWorkflow(scope), { hasValue: true, empty: true, workflow: null })
})

test('localStorage 被禁用时退回 sessionStorage，损坏数据不会抛错', () => {
  const blocked = {
    getItem: () => { throw new Error('blocked') },
    setItem: () => { throw new Error('blocked') },
  }
  const session = createStorage()
  const scope = { localStorage: blocked, sessionStorage: session }
  assert.equal(writeStoredWorkflow({ workflow_id: 'w2', name: '二' }, scope), true)
  assert.equal(session.map.get(WORKFLOW_STORAGE_KEY).includes('w2'), true)
  assert.equal(readStoredWorkflow(scope).workflow.workflow_id, 'w2')

  session.map.set(WORKFLOW_STORAGE_KEY, 'not-json')
  assert.deepEqual(readStoredWorkflow(scope), { hasValue: true, empty: false, workflow: null })

  assert.equal(writeStoredWorkflow({ workflow_id: 'w3' }, {}), false)
  assert.deepEqual(readStoredWorkflow({}), { hasValue: false, empty: false, workflow: null })
})

test('外部写入本地存储的密钥字段在读取时也会被清洗掉', () => {
  const local = createStorage({
    [WORKFLOW_STORAGE_KEY]: JSON.stringify({ workflow_id: 'w1', name: '注入', api_key: 'sk-injected', connection: { api_key: 'sk-injected' } }),
  })
  const read = readStoredWorkflow({ localStorage: local })
  assert.equal(read.hasValue, true)
  assert.equal(read.workflow.workflow_id, 'w1')
  assert.doesNotMatch(JSON.stringify(read.workflow), /sk-injected/)
})
