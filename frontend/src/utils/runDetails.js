/**
 * 运行记录展示细节：错误类型、重试次数、Trace ID、状态筛选与导出序列化。
 *
 * 全部是纯函数：不访问网络、不写本地存储、不打印任何密钥。
 * 后端字段缺失时保持安全降级，不伪造成功或次数。
 */

/** 后端约定的 error_type 枚举 -> 中文标签。 */
export const ERROR_TYPE_LABELS = Object.freeze({
  timeout: '超时',
  rate_limit: '限流',
  auth: '鉴权失败',
  network: '网络错误',
  server: '服务端错误',
  validation: '参数/校验错误',
  provider: '模型服务错误',
  cancelled: '已取消',
  unknown: '未知',
})

/** 运行历史状态筛选（全部 + 后端运行终态）。 */
export const RUN_STATUS_FILTERS = Object.freeze([
  Object.freeze({ value: 'all', label: '全部' }),
  Object.freeze({ value: 'completed', label: '已完成' }),
  Object.freeze({ value: 'failed', label: '失败' }),
  Object.freeze({ value: 'partial', label: '部分完成' }),
  Object.freeze({ value: 'stopped', label: '已停止' }),
])

/** 只有 error_type 没有错误文本时，用固定中文说明补出原因。 */
const DEFAULT_ERROR_REASONS = Object.freeze({
  timeout: '调用模型超时。',
  rate_limit: '请求被模型服务限流。',
  auth: '鉴权失败，请检查模型提供商与密钥是否匹配。',
  network: '网络连接失败。',
  server: '服务端返回错误。',
  validation: '请求参数或校验未通过。',
  provider: '模型服务返回错误。',
  cancelled: '运行已取消。',
  unknown: '发生未知错误。',
})

/** 把 error_type 映射为中文标签；null/空字符串返回空字符串。 */
export function errorTypeLabel(errorType) {
  const value = typeof errorType === 'string' ? errorType.trim() : ''
  if (!value) return ''
  return ERROR_TYPE_LABELS[value] || ERROR_TYPE_LABELS.unknown
}

/** 步骤尝试次数：合法值为 >=1 的整数。 */
export function normalizeAttempts(value) {
  const attempts = Number(value)
  if (!Number.isInteger(attempts) || attempts < 1) return 0
  return attempts
}

/** 只有发生重试（attempts >= 2）时才展示“2 次尝试”。 */
export function formatAttempts(attempts) {
  const value = normalizeAttempts(attempts)
  return value > 1 ? `${value} 次尝试` : ''
}

/**
 * 运行级尝试次数：优先 run.attempts，否则取各步骤 attempts 的最大值。
 * 没有任何字段时返回 1（表示一次执行），不伪造重试。
 */
export function runAttempts(run) {
  const candidates = [run?.attempts]
  if (Array.isArray(run?.step_results)) {
    candidates.push(...run.step_results.map(step => step?.attempts))
  }
  return candidates.reduce((max, item) => Math.max(max, normalizeAttempts(item)), 1)
}

export function runAttemptsLabel(run) {
  return formatAttempts(runAttempts(run))
}

/** 失败/超时原因：优先 run.error，其次第一个失败步骤，最后按 error_type 给出说明。 */
export function runErrorInfo(run) {
  if (!run || typeof run !== 'object') {
    return { type: '', typeLabel: '', reason: '', shortReason: '' }
  }
  const steps = Array.isArray(run.step_results) ? run.step_results : []
  const failedStep = steps.find(step => step && (step.error || step.error_type))
  const type = String(run.error_type || failedStep?.error_type || '')
  const reason = String(run.error || failedStep?.error || DEFAULT_ERROR_REASONS[type] || '')
  return {
    type,
    typeLabel: errorTypeLabel(type),
    reason,
    shortReason: truncateText(reason, 24),
  }
}

/** 从 run 记录读取 trace_id；只接受字符串，避免把对象渲染成 [object Object]。 */
export function traceIdOf(run) {
  const value = run?.trace_id
  return typeof value === 'string' ? value.trim() : ''
}

/** Trace ID 较长，列表里截断显示，完整值通过 title / 复制按钮提供。 */
export function truncateTraceId(traceId, length = 12) {
  const value = typeof traceId === 'string' ? traceId.trim() : ''
  if (!value) return '-'
  return value.length > length ? `${value.slice(0, length)}…` : value
}

/** 通用文本截断，空值返回空字符串。 */
export function truncateText(text, length = 24) {
  const value = String(text ?? '')
  return value.length > length ? `${value.slice(0, length)}…` : value
}

/** 按状态筛选运行列表；'all'/空值返回副本，未知状态返回空数组。 */
export function filterRunsByStatus(runs, status = 'all') {
  if (!Array.isArray(runs)) return []
  if (!status || status === 'all') return runs.slice()
  return runs.filter(run => run?.status === status)
}

export function statusFilterLabel(value) {
  return RUN_STATUS_FILTERS.find(item => item.value === value)?.label || value || '全部'
}

/**
 * 导出当前筛选结果的 JSON 结构。
 * exportedAt 由调用方注入毫秒时间戳，便于测试得到稳定结果。
 */
export function buildRunsExportPayload(runs, { workflowId = null, filter = 'all' } = {}, exportedAt = Date.now()) {
  const items = Array.isArray(runs) ? runs : []
  return {
    exported_at: new Date(exportedAt).toISOString(),
    filter: filter || 'all',
    workflow_id: workflowId || null,
    total: items.length,
    runs: items,
  }
}

export function serializeRunsExport(runs, meta = {}, exportedAt = Date.now()) {
  return JSON.stringify(buildRunsExportPayload(runs, meta, exportedAt), null, 2)
}

/** 导出文件名：runs-<筛选>-<本地时间戳>.json。 */
export function runsExportFileName(filter = 'all', exportedAt = Date.now()) {
  const date = new Date(exportedAt)
  const pad = value => String(value).padStart(2, '0')
  const stamp = `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`
  return `runs-${filter || 'all'}-${stamp}.json`
}
