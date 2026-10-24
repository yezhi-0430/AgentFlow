import test from 'node:test'
import assert from 'node:assert/strict'
import { createPinia, setActivePinia } from 'pinia'
import api from '../src/services/api.js'
import { useWorkflowStore } from '../src/stores/workflow.js'
import { useRunsStore } from '../src/stores/runs.js'

function useAdapter(handler) {
  setActivePinia(createPinia())
  const requests = []
  api.defaults.adapter = async config => {
    requests.push(config)
    const data = await handler(config)
    return { data, status: 200, statusText: 'OK', headers: {}, config }
  }
  return requests
}

function workflowStoreWithRun() {
  const store = useWorkflowStore()
  store.setWorkflow({ workflow_id: 'wf-runs', name: '运行测试', pattern: 'sequential', agents: [{ name: 'worker_1' }], status: 'created' })
  return { store }
}

test('执行响应里的 run_id 会被保留，供界面展示与后续查询', async () => {
  const requests = useAdapter(async config => {
    if (config.url.endsWith('/execute')) return { status: 'executing', run_id: 'run-from-execute' }
    if (config.url.endsWith('/status')) return { status: 'running', current_step: 1, total_steps: 1 }
    if (config.url === '/api/agents') return { agents: [] }
    return { messages: [] }
  })
  const { store } = workflowStoreWithRun()
  try {
    assert.equal(await store.startExecution('写一篇短文'), true)
    assert.equal(store.currentRunId, 'run-from-execute')
    assert.equal(store.runStatus, 'running')
    assert.equal(requests.filter(request => request.url.endsWith('/execute')).length, 1)
  } finally {
    store.disposeExecution()
  }
})

test('运行终态以后端运行记录为准：failed / partial / stopped / stopping 不会展示成成功', async () => {
  const cases = [
    { workflowStatus: 'completed', runStatus: 'partial', expected: 'partial' },
    { workflowStatus: 'stopped', runStatus: 'stopped', expected: 'stopped' },
    { workflowStatus: 'failed', runStatus: 'failed', expected: 'failed' },
    { workflowStatus: 'partial', runStatus: 'partial', expected: 'partial' },
    { workflowStatus: 'stopping', runStatus: 'running', expected: 'stopping' },
    { workflowStatus: 'completed', runStatus: 'completed', expected: 'completed' },
    { workflowStatus: 'cancelled', runStatus: 'cancelled', expected: 'cancelled' },
  ]
  for (const item of cases) {
    useAdapter(async config => {
      if (config.url.endsWith('/status')) {
        return {
          status: item.workflowStatus,
          current_step: 1,
          total_steps: 1,
          current_run: { run_id: `run-${item.runStatus}`, status: item.runStatus },
        }
      }
      if (config.url === '/api/agents') return { agents: [] }
      return { messages: [] }
    })
    const { store } = workflowStoreWithRun()
    try {
      await store.refreshExecution()
      assert.equal(store.runStatus, item.runStatus)
      assert.equal(store.currentRunId, `run-${item.runStatus}`)
      assert.equal(store.status, item.expected)
    } finally {
      store.disposeExecution()
    }
  }
})

test('执行并发冲突（409）不伪造失败，并保留后端真实状态同步', async () => {
  useAdapter(async config => {
    if (config.url.endsWith('/execute')) {
      throw { response: { status: 409, data: { detail: 'A run is already executing for this workflow; concurrent runs are not supported' } } }
    }
    if (config.url.endsWith('/status')) return { status: 'running', current_step: 1, total_steps: 2 }
    if (config.url === '/api/agents') return { agents: [] }
    return { messages: [] }
  })
  const { store } = workflowStoreWithRun()
  try {
    assert.equal(await store.startExecution('再次运行'), false)
    assert.equal(store.status, 'running')
    assert.equal(store.isRunning, true)
    assert.match(store.executionError, /已有运行中的任务/)
  } finally {
    store.disposeExecution()
  }
})

test('失败运行的原因从后端记录读取并展示', async () => {
  useAdapter(async config => {
    if (config.url.endsWith('/status')) {
      return {
        status: 'failed',
        current_step: 1,
        total_steps: 1,
        current_run: { run_id: 'run-failed', status: 'failed', error: 'provider returned 500' },
      }
    }
    if (config.url === '/api/agents') return { agents: [] }
    return { messages: [] }
  })
  const { store } = workflowStoreWithRun()
  try {
    await store.refreshExecution()
    assert.equal(store.status, 'failed')
    assert.equal(store.currentRunId, 'run-failed')
    assert.match(store.executionError, /provider returned 500/)
  } finally {
    store.disposeExecution()
  }
})

test('最近运行从后端列表读取，按 created_at 取最新记录', async () => {
  const requests = useAdapter(async config => {
    if (config.url.endsWith('/runs')) {
      return {
        workflow_id: 'wf-runs',
        runs: [
          { run_id: 'run-old', status: 'completed', created_at: 100, total_tokens: 10, total_duration: 1.5 },
          { run_id: 'run-latest', status: 'failed', created_at: 300, total_tokens: 20, total_duration: 2.25 },
        ],
        total: 2,
        limit: 1,
        offset: 0,
      }
    }
    throw { response: { status: 404 } }
  })
  const runsStore = useRunsStore()
  const latest = await runsStore.loadLatestRun('wf-runs')
  assert.equal(latest.run_id, 'run-latest')
  assert.equal(runsStore.latestRun.status, 'failed')
  const request = requests.find(item => item.url === '/api/workflows/wf-runs/runs')
  assert.equal(request.params.limit, 1)
  assert.equal(request.params.offset, 0)
})

test('后端没有运行记录或请求失败时不伪造最近运行', async () => {
  useAdapter(async config => {
    if (config.url.endsWith('/runs')) return { runs: [], total: 0, limit: 1, offset: 0 }
    throw { response: { status: 404 } }
  })
  const runsStore = useRunsStore()
  assert.equal(await runsStore.loadLatestRun('wf-runs'), null)
  assert.equal(runsStore.latestRun, null)

  api.defaults.adapter = async () => {
    throw { response: { status: 500 } }
  }
  runsStore.latestRun = { run_id: 'stale-run', status: 'completed' }
  assert.equal(await runsStore.loadLatestRun('wf-runs'), null)
  assert.equal(runsStore.latestRun, null)
  assert.ok(runsStore.latestRunError)
})

test('运行列表使用与后端一致的状态样式与耗时展示', () => {
  useAdapter(async () => ({}))
  const runsStore = useRunsStore()
  runsStore.runs = [
    { run_id: 'run-failed', status: 'failed', created_at: 1700000000, total_tokens: 5, total_duration: 1.5 },
    { run_id: 'run-partial', status: 'partial', created_at: 1700000100, total_tokens: 8, total_duration: 2 },
  ]
  const formatted = runsStore.formattedRuns
  assert.equal(formatted[0].statusClass, 'status-error')
  assert.equal(formatted[1].statusClass, 'status-warning')
  assert.equal(formatted[0].duration, '1.50')
})
