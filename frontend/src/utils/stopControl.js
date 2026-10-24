/**
 * 停止运行接口的结果归一化。
 *
 * 后端契约：POST /api/workflows/{id}/stop
 * - 有活动运行：200 {"status": "stopping"}（也可能直接返回 stopped）
 * - 没有活动运行：409
 * 网络错误与 401/403/404/5xx 也需要区分，避免把“停止失败”显示成“已停止”。
 */
import { isTerminalExecutionStatus } from './runStatus.js'

/** 把停止接口/状态接口里的 status 归一化为停止流程关心的值。 */
export function normalizeStopStatus(status) {
  const value = String(status || '').trim().toLowerCase()
  if (value === 'stopped' || value === 'cancelled' || value === 'canceled') return 'stopped'
  if (value === 'stopping' || value === 'stop_requested' || value === 'requested') return 'stopping'
  if (isTerminalExecutionStatus(value)) return value
  return 'stopping'
}

/**
 * 归一化停止结果：{ kind, status, message }。
 * kind ∈ stopping | stopped | terminal | no-active-run | not-found | auth | error | network
 */
export function resolveStopOutcome({ httpStatus = null, status = '', detail = '', networkError = false } = {}) {
  if (networkError) {
    return { kind: 'network', status: 'stopping', message: '停止请求失败：网络异常，正在继续同步运行状态。' }
  }
  if (httpStatus === 409) {
    return { kind: 'no-active-run', status: 'unknown', message: '当前没有正在运行的执行，已同步最新状态。' }
  }
  if (httpStatus === 404) {
    return { kind: 'not-found', status: 'error', message: '该工作流已不存在（可能已被删除）。' }
  }
  if (httpStatus === 401 || httpStatus === 403) {
    return { kind: 'auth', status: 'error', message: '停止请求被拒绝：鉴权失败，请检查访问令牌配置。' }
  }
  if (httpStatus && httpStatus >= 400) {
    return { kind: 'error', status: 'error', message: `停止请求失败：${detail || `HTTP ${httpStatus}`}` }
  }

  const normalized = normalizeStopStatus(status)
  if (normalized === 'stopped') {
    return { kind: 'stopped', status: 'stopped', message: '运行已停止。' }
  }
  if (isTerminalExecutionStatus(normalized)) {
    return { kind: 'terminal', status: normalized, message: '运行已结束。' }
  }
  return { kind: 'stopping', status: 'stopping', message: '已请求停止，等待当前调用结束…' }
}
