import test from 'node:test'
import assert from 'node:assert/strict'
import { createPinia, setActivePinia } from 'pinia'
import api from '../src/services/api.js'
import { useWorkflowStore } from '../src/stores/workflow.js'
import { WORKFLOW_STORAGE_KEY } from '../src/utils/workflowStorage.js'
import { parseWorkflowDefinition } from '../src/utils/workflowDefinition.js'

function createStorage() {
  const map = new Map()
  return {
    map,
    getItem: key => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => map.set(key, String(value)),
    removeItem: key => map.delete(key),
  }
}

function setupStore(handler) {
  setActivePinia(createPinia())
  const local = createStorage()
  const session = createStorage()
  globalThis.localStorage = local
  globalThis.sessionStorage = session
  const requests = []
  api.defaults.adapter = async config => {
    requests.push(config)
    const data = await handler(config)
    return { data, status: 200, statusText: 'OK', headers: {}, config }
  }
  return { store: useWorkflowStore(), requests, local, session }
}

function restoredWorkflow() {
  return {
    workflow_id: 'wf-restored',
    name: '重启前的工作流',
    description: '重启前保存的任务',
    pattern: 'sequential',
    status: 'idle',
    requires_credentials: true,
    agents: [{ name: 'worker_1', role: 'worker', model: 'gpt-4' }],
  }
}

function restoredHandler(statusOverride = {}) {
  const workflow = restoredWorkflow()
  return async config => {
    if (config.url === '/api/workflows') return { workflows: [workflow] }
    if (config.url === '/api/workflows/wf-restored') {
      return { ...workflow, connection: { provider: 'openai' }, agents: [{ name: 'worker_1', role: 'worker', model: 'gpt-4', status: 'unavailable' }] }
    }
    if (config.url === '/api/workflows/wf-restored/status') {
      return { status: 'idle', requires_credentials: true, description: '重启前保存的任务', current_step: 0, total_steps: 1, ...statusOverride }
    }
    if (config.url === '/api/messages') return { messages: [] }
    if (config.url === '/api/agents') return { agents: [] }
    return {}
  }
}

test('刷新后从列表恢复记住的工作流，并明确标记需要重新输入密钥', async () => {
  const { store } = setupStore(restoredHandler())
  localStorage.setItem(WORKFLOW_STORAGE_KEY, JSON.stringify({ workflow_id: 'wf-restored', name: '本地快照名', agents: [{ name: 'worker_1', system_prompt: '本地提示' }] }))
  await store.restoreWorkflow()
  assert.equal(store.currentWorkflow.workflow_id, 'wf-restored')
  assert.equal(store.requiresCredentials, true)
  assert.equal(store.workflows.length, 1)
  assert.equal(store.agents[0].status, 'unavailable')
  assert.equal(store.agents[0].system_prompt, '本地提示')
  assert.equal(store.status, 'idle')
  store.disposeExecution()
})

test('记住的工作流已被删除时退回最近一个已保存工作流', async () => {
  const older = { workflow_id: 'wf-old', name: '旧', pattern: 'sequential', status: 'idle', requires_credentials: false, agents: [] }
  const latest = restoredWorkflow()
  const { store } = setupStore(async config => {
    if (config.url === '/api/workflows') return { workflows: [older, latest] }
    if (config.url === '/api/workflows/wf-restored') return { ...latest, connection: { provider: 'openai' }, agents: [] }
    if (config.url === '/api/workflows/wf-restored/status') return { status: 'idle', requires_credentials: true, current_step: 0, total_steps: 0 }
    if (config.url === '/api/messages') return { messages: [] }
    if (config.url === '/api/agents') return { agents: [] }
    return {}
  })
  localStorage.setItem(WORKFLOW_STORAGE_KEY, JSON.stringify({ workflow_id: 'wf-deleted' }))
  await store.restoreWorkflow()
  assert.equal(store.currentWorkflow.workflow_id, 'wf-restored')
  store.disposeExecution()
})

test('主动清空的工作区刷新后保持空白，不自动打开别的工作流', async () => {
  const { store, requests } = setupStore(restoredHandler())
  localStorage.setItem(WORKFLOW_STORAGE_KEY, 'null')
  await store.restoreWorkflow()
  assert.equal(store.currentWorkflow, null)
  assert.equal(requests.length, 0)
})

test('恢复的工作流即使后端带历史终态，执行前也不显示已完成', async () => {
  const { store } = setupStore(restoredHandler({ status: 'completed', current_step: 1, total_steps: 1 }))
  localStorage.setItem(WORKFLOW_STORAGE_KEY, JSON.stringify({ workflow_id: 'wf-restored' }))
  await store.restoreWorkflow()
  assert.equal(store.requiresCredentials, true)
  assert.equal(store.status, 'idle')
  store.disposeExecution()
})

test('执行时随请求提交 API Key，成功后不再要求密钥，且密钥不进入任何本地存储', async () => {
  const key = 'sk-test-only-never-persist-123'
  const { store, requests, local, session } = setupStore(async config => {
    if (config.url === '/api/messages') return { messages: [] }
    if (config.url.endsWith('/execute')) return { run_id: 'run-1', status: 'executing' }
    if (config.url.endsWith('/status')) return { status: 'completed', requires_credentials: false, current_step: 1, total_steps: 1 }
    if (config.url === '/api/agents') return { agents: [] }
    return {}
  })
  store.setWorkflow(restoredWorkflow())
  const executed = await store.startExecution('写一篇文章', `  ${key}  `)
  assert.equal(executed, true)
  const execute = requests.find(request => String(request.url).endsWith('/execute'))
  assert.deepEqual(JSON.parse(execute.data), { task: '写一篇文章', api_key: key })
  assert.equal(store.requiresCredentials, false)
  assert.equal(store.status, 'completed')

  const persisted = JSON.stringify([...local.map.values(), ...session.map.values()])
  assert.doesNotMatch(persisted, new RegExp(key))
  assert.doesNotMatch(JSON.stringify(store.$state), new RegExp(key))
  store.disposeExecution()
})

test('缺少密钥的 400 转换为中文提示，并保持可重试状态', async () => {
  const { store, requests } = setupStore(async config => {
    if (config.url === '/api/messages') return { messages: [] }
    if (config.url.endsWith('/execute')) {
      throw { response: { status: 400, data: { detail: 'This workflow was restored after restart and needs an API key. Provide api_key in the execute request.' } } }
    }
    return {}
  })
  store.setWorkflow(restoredWorkflow())
  const executed = await store.startExecution('写一篇文章')
  assert.equal(executed, false)
  const execute = requests.find(request => String(request.url).endsWith('/execute'))
  assert.deepEqual(JSON.parse(execute.data), { task: '写一篇文章' })
  assert.match(store.executionError, /需要重新提供 API Key/)
  assert.match(store.executionError, /密钥未保存/)
  assert.equal(store.status, 'idle')
  assert.equal(store.requiresCredentials, true)
  store.disposeExecution()
})

test('导入定义调用导入接口并选中新工作流，导入后要求重新输入密钥', async () => {
  const imported = {
    workflow_id: 'wf-imported',
    name: '导入的工作流',
    description: '来自定义',
    pattern: 'parallel',
    status: 'imported',
    requires_credentials: true,
    agents: [{ name: 'worker_1', role: 'worker', model: 'gpt-4' }],
  }
  const { store, requests } = setupStore(async config => {
    if (config.url === '/api/workflows/import') return imported
    if (config.url === '/api/workflows/wf-imported') {
      return { ...imported, connection: { provider: 'openai' }, agents: [{ name: 'worker_1', role: 'worker', model: 'gpt-4', status: 'unavailable' }] }
    }
    if (config.url === '/api/workflows') return { workflows: [imported] }
    return {}
  })
  const parsed = parseWorkflowDefinition(JSON.stringify({
    schema_version: 1,
    workflow_id: 'incoming',
    name: '导入的工作流',
    pattern: 'parallel',
    agents: [{ name: 'worker_1', role: 'worker', model: 'gpt-4', api_key: 'sk-import-secret' }],
    steps: [{ id: 'step_1', agent_name: 'worker_1' }],
  }))
  assert.equal(parsed.ok, true)
  const result = await store.importDefinition(parsed.value)
  assert.equal(result.workflow_id, 'wf-imported')

  const importRequest = requests.find(request => request.url === '/api/workflows/import')
  assert.doesNotMatch(importRequest.data, /sk-import-secret/)
  assert.equal(store.currentWorkflow.workflow_id, 'wf-imported')
  assert.equal(store.requiresCredentials, true)
  assert.equal(store.status, 'idle')
  assert.equal(store.workflows.length, 1)
  store.disposeExecution()
})

test('导出当前工作流定义时调用定义接口并原样返回后端数据', async () => {
  const definition = { schema_version: 1, workflow_id: 'wf-1', name: '导出我', pattern: 'sequential', agents: [], steps: [] }
  const { store, requests } = setupStore(async config => {
    if (config.url === '/api/workflows/wf-1/definition') return definition
    return {}
  })
  store.setWorkflow({ workflow_id: 'wf-1', name: '导出我', pattern: 'sequential', agents: [], status: 'idle' })
  const result = await store.exportCurrentDefinition()
  assert.deepEqual(result, definition)
  assert.equal(requests.filter(request => String(request.url).endsWith('/definition')).length, 1)
  store.disposeExecution()
})

test('打开工作流库里的其他工作流会切换到详情并保留恢复标记', async () => {
  const other = { workflow_id: 'wf-other', name: '另一个', pattern: 'parallel', status: 'idle', requires_credentials: true, agents: [{ name: 'a' }] }
  const { store } = setupStore(async config => {
    if (config.url === '/api/workflows/wf-other') return { ...other, connection: { provider: 'openai' }, agents: [{ name: 'a', status: 'unavailable' }] }
    if (config.url === '/api/workflows/wf-other/status') return { status: 'idle', requires_credentials: true, current_step: 0, total_steps: 1 }
    if (config.url === '/api/messages') return { messages: [] }
    if (config.url === '/api/agents') return { agents: [] }
    return {}
  })
  assert.equal(await store.openWorkflow('wf-other'), true)
  assert.equal(store.currentWorkflow.workflow_id, 'wf-other')
  assert.equal(store.requiresCredentials, true)
  assert.equal(store.status, 'idle')
  store.disposeExecution()
})
