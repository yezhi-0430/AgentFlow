/**
 * 运行状态与时间展示工具。
 *
 * 这里的 status 取值必须与后端保持一致：
 * 运行记录 pending / running / completed / failed / stopped / partial / cancelled
 * 工作流执行 status 另含 idle / created / stopping
 * 不在枚举中的值按原样显示，避免把未知状态伪造成成功。
 */

export const RUN_STATUS_META = {
  pending: { label: '等待执行', className: 'status-pending', tone: 'pending', terminal: false },
  running: { label: '运行中', className: 'status-running', tone: 'running', terminal: false },
  stopping: { label: '停止中', className: 'status-running', tone: 'neutral', terminal: false },
  completed: { label: '已完成', className: 'status-success', tone: 'success', terminal: true },
  failed: { label: '失败', className: 'status-error', tone: 'error', terminal: true },
  stopped: { label: '已停止', className: 'status-stopped', tone: 'neutral', terminal: true },
  partial: { label: '部分完成', className: 'status-warning', tone: 'warning', terminal: true },
  cancelled: { label: '已取消', className: 'status-stopped', tone: 'neutral', terminal: true },
}

/** 执行器层面的终态（执行器使用 error 表示历史状态，运行记录使用 failed）。 */
const EXECUTION_TERMINAL_STATUSES = new Set(['completed', 'failed', 'partial', 'stopped', 'cancelled', 'error'])

export function runStatusMeta(status) {
  return RUN_STATUS_META[status] || {
    label: status || '未知状态',
    className: 'status-default',
    tone: 'unknown',
    terminal: false,
  }
}

export function statusLabel(status) {
  return runStatusMeta(status).label
}

export function statusClass(status) {
  return runStatusMeta(status).className
}

export function statusTone(status) {
  return runStatusMeta(status).tone
}

export function isTerminalRunStatus(status) {
  return Boolean(RUN_STATUS_META[status]?.terminal)
}

/** 工作流执行状态也会出现 error（对应运行记录的 failed）。 */
export function isTerminalExecutionStatus(status) {
  return EXECUTION_TERMINAL_STATUSES.has(status)
}

function toMilliseconds(value) {
  if (value === null || value === undefined || value === '') return Number.NaN
  if (typeof value === 'number') return value * 1000
  return Date.parse(value)
}

/** 后端时间戳为秒（float），也兼容 ISO 字符串。 */
export function formatTimestamp(timestamp) {
  const ms = toMilliseconds(timestamp)
  if (!Number.isFinite(ms)) return '-'
  return new Date(ms).toLocaleString()
}

export function formatDuration(seconds) {
  const value = Number(seconds)
  return Number.isFinite(value) ? value.toFixed(2) : '-'
}

/** 运行 ID 较长，列表里展示前缀，完整值通过 title 提供。 */
export function truncateId(id, length = 8) {
  if (!id) return '-'
  return id.length > length ? `${id.slice(0, length)}…` : id
}

/**
 * 从运行列表里选出真正的最新一条（按 created_at，而不是数组顺序）。
 * 返回 null 表示没有任何可展示的真实记录。
 */
export function pickLatestRun(runs) {
  if (!Array.isArray(runs)) return null
  return runs
    .filter(run => run && run.run_id)
    .reduce((latest, run) => {
      if (!latest) return run
      return toMilliseconds(run.created_at) >= toMilliseconds(latest.created_at) ? run : latest
    }, null)
}
