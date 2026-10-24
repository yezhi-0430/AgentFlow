/**
 * 当前工作流的本地展示快照。
 *
 * 只保存界面展示需要的字段（id/名称/描述/模式/智能体展示信息/步骤），
 * **绝不保存 API Key、连接配置或任何密钥**。存储优先 localStorage，
 * 不可用时退回 sessionStorage（隐私模式或旧数据仍可工作）。
 */

export const WORKFLOW_STORAGE_KEY = 'agentflow.current-workflow'

const AGENT_FIELDS = ['name', 'role', 'model', 'system_prompt', 'status']

function isPlainObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function text(value) {
  return typeof value === 'string' ? value : ''
}

function agentSnapshot(agent) {
  const snapshot = {}
  for (const field of AGENT_FIELDS) {
    if (agent[field] !== undefined && agent[field] !== null) snapshot[field] = agent[field]
  }
  return snapshot
}

/** 生成可安全写入本地存储的工作流快照：字段白名单，密钥字段没有入口。 */
export function workflowSnapshot(workflow) {
  if (!isPlainObject(workflow)) return null
  const workflowId = text(workflow.workflow_id)
  if (!workflowId) return null
  return {
    workflow_id: workflowId,
    name: text(workflow.name),
    description: text(workflow.description),
    pattern: text(workflow.pattern),
    agents: Array.isArray(workflow.agents) ? workflow.agents.filter(isPlainObject).map(agentSnapshot) : [],
    steps: Array.isArray(workflow.steps)
      ? workflow.steps.filter(isPlainObject).map(step => ({
        id: text(step.id),
        agent_name: text(step.agent_name),
        input_from: step.input_from ? text(step.input_from) : null,
      }))
      : [],
  }
}

function availableStorages(scope) {
  const storages = []
  for (const name of ['localStorage', 'sessionStorage']) {
    try {
      const storage = scope?.[name]
      if (storage && typeof storage.getItem === 'function' && typeof storage.setItem === 'function') storages.push(storage)
    } catch {
      // 浏览器可能因隐私/安全策略禁止访问存储，忽略并尝试下一个。
    }
  }
  return storages
}

/**
 * 读取记住的当前工作流。
 * hasValue=false 表示从未记录；empty=true 表示用户主动清空了工作区（存了 "null"）。
 */
export function readStoredWorkflow(scope = globalThis) {
  for (const storage of availableStorages(scope)) {
    let raw
    try {
      raw = storage.getItem(WORKFLOW_STORAGE_KEY)
    } catch {
      continue
    }
    if (raw === null || raw === undefined) continue
    if (raw === 'null') return { hasValue: true, empty: true, workflow: null }
    try {
      // 即使存储被外部写入，也按白名单重新清洗，避免把密钥带回界面。
      return { hasValue: true, empty: false, workflow: workflowSnapshot(JSON.parse(raw)) }
    } catch {
      return { hasValue: true, empty: false, workflow: null }
    }
  }
  return { hasValue: false, empty: false, workflow: null }
}

/** 写入展示快照；传 null 记录"空工作区"，刷新后不自动打开其他工作流。 */
export function writeStoredWorkflow(workflow, scope = globalThis) {
  const snapshot = workflow ? workflowSnapshot(workflow) : null
  const payload = snapshot ? JSON.stringify(snapshot) : 'null'
  for (const storage of availableStorages(scope)) {
    try {
      storage.setItem(WORKFLOW_STORAGE_KEY, payload)
      return true
    } catch {
      // 配额或隐私限制：尝试下一个存储。
    }
  }
  return false
}
