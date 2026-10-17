import test from 'node:test'
import assert from 'node:assert/strict'
import { createPinia, setActivePinia } from 'pinia'
import api from '../src/services/api.js'
import { useWorkflowStore } from '../src/stores/workflow.js'
import { useMessageStore } from '../src/stores/messages.js'

function setup(handler = async () => ({})) {
  setActivePinia(createPinia())
  const storage = new Map()
  globalThis.sessionStorage = {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: key => storage.delete(key),
  }
  const requests = []
  api.defaults.adapter = async config => {
    requests.push(config)
    return { data: await handler(config), status: 200, statusText: 'OK', headers: {}, config }
  }
  const store = useWorkflowStore()
  store.setWorkflow({ workflow_id: 'to-delete', name: '待删除工作流', status: 'idle', agents: [{ name: 'worker_1' }] })
  const messages = useMessageStore()
  messages.addMessage({ id: 'message-1', content: '原消息' })
  return { store, messages, requests, storage }
}
test('deleting a workflow calls the backend and clears selection, messages and stored id', async () => {
  const { store, messages, requests, storage } = setup(async () => ({ status: 'completed' }))
  store.selectAgent('worker_1')
  assert.equal(await store.deleteCurrentWorkflow(), true)
  assert.equal(requests.filter(request => request.method === 'delete' && request.url === '/api/workflows/to-delete').length, 1)
  assert.equal(store.currentWorkflow, null)
  assert.equal(store.agents.length, 0)
  assert.equal(store.selectedAgent, undefined)
  assert.equal(store.totalSteps, 0)
  assert.equal(messages.messages.length, 0)
  assert.doesNotMatch(storage.get('agentflow.current-workflow'), /to-delete/)
  const count = requests.length
  await store.restoreWorkflow()
  assert.equal(requests.length, count, 'refreshing after deletion should keep the empty workspace')
})
test('failed deletion retains the original workflow and messages', async () => {
  const { store, messages } = setup(async config => {
    if (config.method === 'delete') throw { response: { status: 500, data: { detail: '删除服务暂时不可用' } } }
    return { status: 'idle' }
  })
  assert.equal(await store.deleteCurrentWorkflow(), false)
  assert.equal(store.currentWorkflow.workflow_id, 'to-delete')
  assert.equal(messages.messages.length, 1)
  assert.match(store.deletionError, /删除服务暂时不可用/)
  assert.equal(store.deleting, false)
})
test('local running state prevents deletion requests', async () => {
  const { store, requests } = setup()
  store.updateStatus('running')
  assert.equal(await store.deleteCurrentWorkflow(), false)
  assert.equal(requests.length, 0)
})
test('server running state prevents deletion even when the local state is idle', async () => {
  const { store, requests } = setup(async () => ({ status: 'running' }))
  assert.equal(await store.deleteCurrentWorkflow(), false)
  assert.equal(requests.filter(request => request.method === 'delete').length, 0)
  assert.equal(store.currentWorkflow.workflow_id, 'to-delete')
  assert.match(store.deletionError, /运行/)
})
test('already removed workflows can be cleared from the workspace', async () => {
  const { store } = setup(async () => { throw { response: { status: 404, data: {} } } })
  assert.equal(await store.deleteCurrentWorkflow(), true)
  assert.equal(store.currentWorkflow, null)
})
test('a duplicate click sends one deletion request and execution is blocked while deleting', async () => {
  let release
  const gate = new Promise(resolve => { release = resolve })
  const { store, requests } = setup(async config => {
    if (config.method === 'delete') await gate
    return { status: 'idle' }
  })
  const first = store.deleteCurrentWorkflow()
  assert.equal(store.deleting, true)
  assert.equal(await store.deleteCurrentWorkflow(), false)
  assert.equal(await store.startExecution('不能启动'), false)
  release()
  assert.equal(await first, true)
  assert.equal(requests.filter(request => request.method === 'delete').length, 1)
})
test('deleting an old selection cannot clear a newly selected workflow', async () => {
  let release
  const gate = new Promise(resolve => { release = resolve })
  const { store } = setup(async config => {
    if (config.method === 'delete') await gate
    return { status: 'idle' }
  })
  const pending = store.deleteCurrentWorkflow()
  await new Promise(resolve => setImmediate(resolve))
  store.setWorkflow({ workflow_id: 'new-selection', name: '新工作流', agents: [] })
  release()
  assert.equal(await pending, true)
  assert.equal(store.currentWorkflow.workflow_id, 'new-selection')
})
test('local demos can be removed without calling the backend', async () => {
  const { store, requests } = setup()
  store.setWorkflow({ name: '本地示例', isDemo: true, agents: [] })
  assert.equal(await store.deleteCurrentWorkflow(), true)
  assert.equal(requests.length, 0)
  assert.equal(store.currentWorkflow, null)
})
