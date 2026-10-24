import test from 'node:test'
import assert from 'node:assert/strict'
import { createPinia, setActivePinia } from 'pinia'
import api from '../src/services/api.js'
import { useWorkflowStore } from '../src/stores/workflow.js'
import { statusLabel, statusTone } from '../src/utils/runStatus.js'

function setup(handler) {
  setActivePinia(createPinia())
  const requests = []
  api.defaults.adapter = async config => {
    requests.push(config)
    const data = await handler(config)
    return { data, status: 200, statusText: 'OK', headers: {}, config }
  }
  const store = useWorkflowStore()
  store.setWorkflow({
    workflow_id: 'wf-stop',
    name: '停止测试',
    pattern: 'sequential',
    agents: [{ name: 'worker_1' }],
    status: 'running',
  })
  return { store, requests }
}

test('停止请求成功后轮询到 stopped，不显示成成功', async () => {
  let stopCalled = false
  const { store, requests } = setup(async config => {
    if (config.url.endsWith('/stop')) {
      stopCalled = true
      return { message: 'Stop requested', status: 'stopping' }
    }
    if (config.url.endsWith('/status')) {
      return stopCalled
        ? {
            status: 'stopped',
            current_step: 1,
            total_steps: 1,
            current_run: { run_id: 'run-stop', status: 'stopped', stop_requested: true, error: 'stopped by request' },
          }
        : {
            status: 'running',
            current_step: 1,
            total_steps: 1,
            current_run: { run_id: 'run-stop', status: 'running' },
          }
    }
    if (config.url === '/api/agents') return { agents: [] }
    return { messages: [] }
  })
  try {
    assert.equal(store.isRunning, true)
    assert.equal(await store.stopExecution(), true)

    assert.equal(store.status, 'stopped')
    assert.equal(store.runStatus, 'stopped')
    assert.equal(store.currentRunId, 'run-stop')
    assert.equal(store.isRunning, false)
    assert.equal(store.isStopping, false)
    assert.equal(store.stopError, '')
    assert.equal(store.stopRequested, true)
    assert.equal(statusLabel(store.status), '已停止')
    assert.notEqual(statusTone(store.status), 'success')

    const stopRequests = requests.filter(request => request.url.endsWith('/stop'))
    assert.equal(stopRequests.length, 1)
    assert.equal(stopRequests[0].method, 'post')
  } finally {
    store.disposeExecution()
  }
})

test('200 stopping 且后端仍在运行时保持停止中，继续轮询到 stopped', async () => {
  let phase = 'running'
  const { store } = setup(async config => {
    if (config.url.endsWith('/stop')) {
      phase = 'stopping'
      return { message: 'Stop requested', status: 'stopping' }
    }
    if (config.url.endsWith('/status')) {
      if (phase === 'stopping') {
        return {
          status: 'running',
          current_run: { run_id: 'run-stop', status: 'running', stop_requested: true },
        }
      }
      return {
        status: 'stopped',
        current_run: { run_id: 'run-stop', status: 'stopped', stop_requested: true },
      }
    }
    if (config.url === '/api/agents') return { agents: [] }
    return { messages: [] }
  })
  try {
    await store.stopExecution()
    assert.equal(store.status, 'stopping')
    // 最近运行仍以后端运行记录为准（后端尚未落定 stopped）。
    assert.equal(store.runStatus, 'running')
    assert.equal(store.stopRequested, true)
    assert.equal(store.isRunning, true)
    assert.equal(statusLabel(store.status), '停止中')
    assert.notEqual(statusTone(store.status), 'success')

    // 模拟下一次轮询：后端已落定终态。
    phase = 'stopped'
    await store.refreshExecution()
    assert.equal(store.status, 'stopped')
    assert.equal(store.isRunning, false)
    assert.notEqual(statusTone(store.status), 'success')
  } finally {
    store.disposeExecution()
  }
})

test('停止接口直接返回 stopped 时立即落终态', async () => {
  const { store } = setup(async config => {
    if (config.url.endsWith('/stop')) return { message: 'Stopped', status: 'stopped' }
    if (config.url.endsWith('/status')) {
      return {
        status: 'stopped',
        current_run: { run_id: 'run-stop', status: 'stopped', stop_requested: true },
      }
    }
    if (config.url === '/api/agents') return { agents: [] }
    return { messages: [] }
  })
  try {
    assert.equal(await store.stopExecution(), true)
    assert.equal(store.status, 'stopped')
    assert.equal(store.stopRequested, true)
    assert.equal(store.isRunning, false)
  } finally {
    store.disposeExecution()
  }
})

test('409 表示没有活动运行，只同步真实状态而不伪造失败/成功', async () => {
  const { store, requests } = setup(async config => {
    if (config.url.endsWith('/stop')) {
      throw { response: { status: 409, data: { detail: 'No active run to stop' } } }
    }
    if (config.url.endsWith('/status')) {
      return {
        status: 'completed',
        current_step: 1,
        total_steps: 1,
        current_run: { run_id: 'run-done', status: 'completed' },
      }
    }
    if (config.url === '/api/agents') return { agents: [] }
    return { messages: [] }
  })
  try {
    assert.equal(await store.stopExecution(), false)
    assert.match(store.stopError, /没有正在运行的执行/)
    assert.equal(store.status, 'completed')
    assert.equal(store.runStatus, 'completed')
    assert.equal(store.isRunning, false)
    assert.equal(store.stopRequested, false)
    assert.equal(requests.filter(request => request.url.endsWith('/stop')).length, 1)
  } finally {
    store.disposeExecution()
  }
})

test('网络错误保留真实运行状态并给出中文提示', async () => {
  const { store } = setup(async config => {
    if (config.url.endsWith('/stop')) throw new Error('Network Error')
    if (config.url.endsWith('/status')) {
      return {
        status: 'running',
        current_run: { run_id: 'run-stop', status: 'running', stop_requested: false },
      }
    }
    if (config.url === '/api/agents') return { agents: [] }
    return { messages: [] }
  })
  try {
    assert.equal(await store.stopExecution(), false)
    assert.match(store.stopError, /停止请求失败：网络异常/)
    assert.equal(store.status, 'running')
    assert.equal(store.isRunning, true)
    assert.notEqual(statusTone(store.status), 'success')
  } finally {
    store.disposeExecution()
  }
})

test('工作流不存在时停止请求给出明确提示，并以状态同步为准', async () => {
  const { store } = setup(async config => {
    if (config.url.endsWith('/stop')) {
      throw { response: { status: 404, data: { detail: 'Workflow not found' } } }
    }
    if (config.url.endsWith('/status')) throw { response: { status: 404 } }
    if (config.url === '/api/agents') return { agents: [] }
    return { messages: [] }
  })
  try {
    assert.equal(await store.stopExecution(), false)
    assert.match(store.stopError, /该工作流已不存在/)
    assert.equal(store.status, 'error')
    assert.equal(store.isRunning, false)
  } finally {
    store.disposeExecution()
  }
})

test('切换/创建工作流时重置停止相关状态', async () => {
  const { store } = setup(async () => ({ messages: [] }))
  store.stopping = true
  store.stopRequested = true
  store.stopError = '停止请求失败'
  store.status = 'stopping'

  store.setWorkflow({ workflow_id: 'wf-new', name: '新工作流', pattern: 'sequential', agents: [] })

  assert.equal(store.stopping, false)
  assert.equal(store.stopRequested, false)
  assert.equal(store.stopError, '')
  assert.equal(store.isStopping, false)
  assert.equal(store.isRunning, false)
  assert.equal(store.status, 'idle')
  store.disposeExecution()
})
