import test from 'node:test'
import assert from 'node:assert/strict'
import { createPinia, setActivePinia } from 'pinia'
import api from '../src/services/api.js'
import { useWorkflowStore } from '../src/stores/workflow.js'
import { useMessageStore } from '../src/stores/messages.js'

function setup(handler) {
  setActivePinia(createPinia())
  const requests = []
  api.defaults.adapter = async config => {
    requests.push(config)
    const data = await handler(config)
    return { data, status: 200, statusText: 'OK', headers: {}, config }
  }
  const store = useWorkflowStore()
  store.setWorkflow({ workflow_id: 'wf-test', name: '写一篇文章', pattern: 'sequential', agents: [{ name: 'worker_1' }, { name: 'worker_2' }], status: 'created' })
  return { store, messages: useMessageStore(), requests }
}
test('created workflows have a usable step count and execution sends the task once', async () => {
  let release
  const gate = new Promise(resolve => { release = resolve })
  const { store, requests } = setup(async config => {
    if (config.url.endsWith('/execute')) { await gate; return { status: 'executing' } }
    if (config.url.endsWith('/status')) return { status: 'running', current_step: 1, total_steps: 2 }
    if (config.url === '/api/agents') return { agents: [] }
    return { messages: [] }
  })
  try {
    assert.equal(store.totalSteps, 2)
    const first = store.startExecution('  写一篇文章  ')
    assert.equal(await store.startExecution('重复任务'), false)
    release()
    assert.equal(await first, true)
    const calls = requests.filter(r => r.url.endsWith('/execute'))
    assert.equal(calls.length, 1)
    assert.deepEqual(JSON.parse(calls[0].data), { task: '写一篇文章' })
    assert.equal(store.isRunning, true)
  } finally { store.disposeExecution() }
})
test('polling reads the correct message endpoint and updates progress, output and agent state', async () => {
  const { store, messages, requests } = setup(async config => {
    if (config.url.endsWith('/status')) return { status: 'completed', current_step: 2, total_steps: 2 }
    if (config.url === '/api/agents') return { agents: [{ workflow_id: 'wf-test', name: 'worker_2', status: 'completed', messages_processed: 1, total_tokens: 123 }] }
    return { messages: [{ id: 'response-1', sender: 'worker_2', receiver: 'system', content: '完整文章结果', message_type: 'response' }] }
  })
  try {
    await store.refreshExecution()
    assert.equal(store.status, 'completed')
    assert.equal(store.currentStep, 2)
    assert.equal(messages.messages[0].content, '完整文章结果')
    assert.equal(store.agents[1].status, 'completed')
    assert.equal(store.agents[1].tokens_used, 123)
    const request = requests.find(r => r.url === '/api/messages')
    assert.equal(request.params.workflow_id, 'wf-test')
  } finally { store.disposeExecution() }
})
test('provider errors in messages are surfaced instead of reporting completion', async () => {
  const { store } = setup(async config => {
    if (config.url.endsWith('/status')) return { status: 'completed', current_step: 2, total_steps: 2 }
    if (config.url === '/api/agents') return { agents: [] }
    return { messages: [{ id: 'error-1', content: 'Error: invalid API key', metadata: { error: true } }] }
  })
  try {
    await store.refreshExecution()
    assert.equal(store.status, 'error')
    assert.match(store.executionError, /密钥校验未通过/)
  } finally { store.disposeExecution() }
})
test('an API rejection is visible and allows retry', async () => {
  const { store } = setup(async config => {
    if (config.url.endsWith('/execute')) throw { response: { data: { detail: 'Workflow not found' }, status: 404 } }
    return { messages: [] }
  })
  try {
    assert.equal(await store.startExecution('写文章'), false)
    assert.match(store.executionError, /Workflow not found/)
    assert.equal(store.isRunning, false)
  } finally { store.disposeExecution() }
})
test('late responses cannot overwrite a newly selected workflow', async () => {
  let release
  const gate = new Promise(resolve => { release = resolve })
  const { store, messages } = setup(async config => {
    await gate
    if (config.url.endsWith('/status')) return { status: 'completed', current_step: 2, total_steps: 2 }
    if (config.url === '/api/agents') return { agents: [] }
    return { messages: [{ content: '旧任务结果' }] }
  })
  try {
    const refresh = store.refreshExecution()
    store.setWorkflow({ workflow_id: 'new', name: '新任务', agents: [] })
    release()
    await refresh
    assert.equal(store.currentWorkflow.workflow_id, 'new')
    assert.equal(store.currentStep, 0)
    assert.equal(messages.messages.length, 0)
  } finally { store.disposeExecution() }
})
test('blank tasks and local demos never send execute requests', async () => {
  const { store, requests } = setup(async () => ({ messages: [] }))
  try {
    assert.equal(await store.startExecution('  '), false)
    store.setWorkflow({ name: '示例', isDemo: true, agents: [] })
    assert.equal(await store.startExecution('任务'), false)
    assert.equal(requests.length, 0)
  } finally { store.disposeExecution() }
})

test('a successful rerun is not marked as failed by an older attempt after refresh', async () => {
  const { store } = setup(async config => {
    if (config.url.endsWith('/status')) return { status: 'completed', current_step: 2, total_steps: 2 }
    if (config.url === '/api/agents') return { agents: [] }
    return { messages: [
      { message_type: 'task', metadata: { step_index: 0 }, content: '旧任务' },
      { message_type: 'response', metadata: { error: true }, content: '旧调用失败' },
      { message_type: 'task', metadata: { step_index: 0 }, content: '新任务' },
      { message_type: 'response', content: '新结果' },
    ] }
  })
  try {
    await store.refreshExecution()
    assert.equal(store.status, 'completed')
    assert.equal(store.executionError, '')
  } finally { store.disposeExecution() }
})
