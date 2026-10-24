/**
 * 重启恢复 / 导入工作流时的凭据状态推导。
 *
 * 后端只持久化工作流定义，API Key 永远不落库；服务重启或导入后的工作流
 * `requires_credentials=true`，执行前必须重新输入密钥。这里的纯函数只处理
 * 状态与文案，不接触、不保存任何密钥。
 */
import { isTerminalExecutionStatus } from './runStatus.js'

export const CREDENTIAL_BADGE = '需要重新输入 API Key'

export const CREDENTIAL_NOTICE = '需要重新输入 API Key：连接配置已保留，密钥未保存。'

export const CREDENTIAL_HINT = '连接配置已保留，但 API Key 不会随工作流保存。密钥仅在本次执行请求中提交，执行结束后输入框会清空，也不会写入本地存储。'

export const MISSING_KEY_MESSAGE = '该工作流在重启或导入后需要重新提供 API Key：连接配置已保留，密钥未保存。请输入 API Key 后再运行。'

export function requiresCredentials(workflow) {
  return Boolean(workflow?.requires_credentials)
}

/**
 * 展示用执行状态。
 * 恢复/导入的工作流在真正执行前即使带着历史终态也不应显示"已完成"。
 */
export function normalizeExecutionStatus(status, workflow) {
  if (!status || status === 'imported' || status === 'unavailable') return 'idle'
  if (requiresCredentials(workflow) && isTerminalExecutionStatus(status)) return 'idle'
  return status
}

/** 400 且 detail 说明缺少密钥时，返回中文提示；其他错误返回空字符串。 */
export function missingCredentialMessage(error) {
  const status = error?.response?.status
  const detail = String(error?.response?.data?.detail || '')
  if (status !== 400) return ''
  if (/needs an api key|api key is required|missing api key/i.test(detail)) return MISSING_KEY_MESSAGE
  return ''
}

/** 从工作流列表里选出要恢复的工作流：优先记住的 id，否则最近一个。 */
export function pickRestoredWorkflow(savedWorkflowId, workflows) {
  if (!Array.isArray(workflows) || !workflows.length) return null
  if (savedWorkflowId) {
    const match = workflows.find(workflow => workflow?.workflow_id === savedWorkflowId)
    if (match) return match
  }
  return workflows.at(-1) || null
}

/** 合并本地展示快照与服务端最新数据，服务端字段优先。 */
export function mergeWorkflowDisplay(saved, latest) {
  if (!latest) return saved ? { ...saved } : null
  const savedAgents = Array.isArray(saved?.agents) ? saved.agents : []
  const agents = Array.isArray(latest.agents)
    ? latest.agents.map(agent => ({ ...savedAgents.find(item => item?.name === agent?.name), ...agent }))
    : []
  return { ...saved, ...latest, agents }
}
