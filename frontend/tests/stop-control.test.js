import test from 'node:test'
import assert from 'node:assert/strict'
import { normalizeStopStatus, resolveStopOutcome } from '../src/utils/stopControl.js'

test('停止状态归一化覆盖 stopping/stopped/cancelled 与终态', () => {
  assert.equal(normalizeStopStatus('stopping'), 'stopping')
  assert.equal(normalizeStopStatus('STOPPING'), 'stopping')
  assert.equal(normalizeStopStatus('stop_requested'), 'stopping')
  assert.equal(normalizeStopStatus('stopped'), 'stopped')
  assert.equal(normalizeStopStatus('STOPPED'), 'stopped')
  assert.equal(normalizeStopStatus('cancelled'), 'stopped')
  assert.equal(normalizeStopStatus('completed'), 'completed')
  assert.equal(normalizeStopStatus('failed'), 'failed')
  assert.equal(normalizeStopStatus('partial'), 'partial')
  assert.equal(normalizeStopStatus(undefined), 'stopping')
})

test('200 stopping 返回继续轮询，200 stopped 才表示已停止', () => {
  const stopping = resolveStopOutcome({ status: 'stopping' })
  assert.equal(stopping.kind, 'stopping')
  assert.equal(stopping.status, 'stopping')
  assert.match(stopping.message, /已请求停止/)

  const stopped = resolveStopOutcome({ status: 'stopped' })
  assert.equal(stopped.kind, 'stopped')
  assert.equal(stopped.status, 'stopped')

  const acceptedWithoutStatus = resolveStopOutcome({})
  assert.equal(acceptedWithoutStatus.kind, 'stopping')
  assert.equal(acceptedWithoutStatus.status, 'stopping')

  assert.equal(resolveStopOutcome({ status: 'cancelled' }).kind, 'stopped')
  assert.equal(resolveStopOutcome({ status: 'completed' }).kind, 'terminal')
})

test('409 表示没有活动运行，不伪造停止成功', () => {
  const outcome = resolveStopOutcome({ httpStatus: 409, detail: 'No active run to stop' })
  assert.equal(outcome.kind, 'no-active-run')
  assert.equal(outcome.status, 'unknown')
  assert.match(outcome.message, /没有正在运行的执行/)
})

test('404/鉴权/服务端/网络错误不会被显示成已停止', () => {
  const notFound = resolveStopOutcome({ httpStatus: 404 })
  assert.equal(notFound.kind, 'not-found')
  assert.match(notFound.message, /该工作流已不存在/)

  assert.equal(resolveStopOutcome({ httpStatus: 401 }).kind, 'auth')
  assert.equal(resolveStopOutcome({ httpStatus: 403 }).kind, 'auth')

  const serverError = resolveStopOutcome({ httpStatus: 500, detail: 'boom' })
  assert.equal(serverError.kind, 'error')
  assert.match(serverError.message, /boom/)

  const networkError = resolveStopOutcome({ networkError: true })
  assert.equal(networkError.kind, 'network')
  assert.equal(networkError.status, 'stopping')
  assert.match(networkError.message, /网络异常/)

  for (const outcome of [notFound, serverError, networkError]) {
    assert.notEqual(outcome.status, 'stopped')
  }
})
