/**
 * 工作流定义 JSON 的导出、导入校验与密钥字段清洗。
 *
 * 与后端 agentflow/core/definition.py 的校验规则保持一致（schema_version=1），
 * 目的只是尽早给出中文提示，最终仍以后端校验为准。
 * 定义里永远不应该出现密钥；清洗函数只移除字段，不会打印字段值。
 */
import { isSupportedWorkflowPattern, supportedWorkflowPatterns, minAgentsForPattern, maxAgentsForPattern, workflowPatternLabels } from './workflowOptions.js'

export const DEFINITION_SCHEMA_VERSION = 1

// 与后端 validate_pattern_agents 保持一致：创建/导入最多 10 个 agent
const MAX_AGENTS = 10
const MAX_STEPS = 100
const MAX_SECRET_PATHS = 20

const SECRET_KEY = /^(api[_-]?key|apikey|secret|secret[_-]?key|access[_-]?key|access[_-]?token|token|password|authorization|auth)$/i

function isPlainObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function text(value) {
  return typeof value === 'string' ? value : (value === null || value === undefined ? '' : String(value))
}

function isSecretFieldName(key) {
  const normalized = String(key).trim().toLowerCase().replace(/\s+/g, '_')
  return SECRET_KEY.test(normalized) || normalized.endsWith('_key') || normalized.endsWith('_secret') || normalized.endsWith('_token')
}

/** 递归移除疑似密钥字段，返回新对象；不修改入参。 */
export function stripSecretFields(value) {
  if (Array.isArray(value)) return value.map(item => stripSecretFields(item))
  if (!isPlainObject(value)) return value
  const cleaned = {}
  for (const [key, item] of Object.entries(value)) {
    if (isSecretFieldName(key)) continue
    cleaned[key] = stripSecretFields(item)
  }
  return cleaned
}

/** 列出疑似密钥字段的路径（只返回字段路径，绝不返回值）。 */
export function detectSecretFields(value, path = '', found = []) {
  if (found.length >= MAX_SECRET_PATHS) return found
  if (Array.isArray(value)) {
    value.forEach((item, index) => detectSecretFields(item, `${path}[${index}]`, found))
    return found
  }
  if (!isPlainObject(value)) return found
  for (const [key, item] of Object.entries(value)) {
    const nextPath = path ? `${path}.${key}` : key
    if (isSecretFieldName(key)) found.push(nextPath)
    else detectSecretFields(item, nextPath, found)
    if (found.length >= MAX_SECRET_PATHS) break
  }
  return found
}

function failure(error) {
  return { ok: false, error }
}

/**
 * 解析并校验导入文本。
 * 返回 { ok:true, value, warnings } 或 { ok:false, error }。
 */
export function parseWorkflowDefinition(rawText) {
  if (typeof rawText !== 'string' || !rawText.trim()) return failure('请先选择或粘贴工作流定义 JSON。')

  let parsed
  try {
    parsed = JSON.parse(rawText)
  } catch {
    return failure('JSON 格式不正确，请检查内容是否为完整的工作流定义。')
  }

  // 兼容 { "definition": {...} } 包装（后端同样支持）。
  const definition = isPlainObject(parsed) && isPlainObject(parsed.definition) ? parsed.definition : parsed
  if (!isPlainObject(definition)) return failure('工作流定义必须是一个 JSON 对象。')

  const warnings = detectSecretFields(definition)
  const secretWarning = warnings.length
    ? `定义中包含疑似密钥字段（${warnings.slice(0, 3).join('、')}${warnings.length > 3 ? ' 等' : ''}），导入时会被自动移除，不会保存。`
    : ''

  if (definition.schema_version !== undefined) {
    const version = Number(definition.schema_version)
    if (!Number.isInteger(version)) return failure('schema_version 必须是整数。')
    if (version !== DEFINITION_SCHEMA_VERSION) {
      return failure(`不支持的定义版本 schema_version=${version}，当前仅支持 ${DEFINITION_SCHEMA_VERSION}。`)
    }
  }

  if (!text(definition.workflow_id).trim()) return failure('定义缺少 workflow_id（导出的定义会自带该字段）。')
  if (!text(definition.name).trim()) return failure('定义缺少工作流名称 name。')

  const pattern = text(definition.pattern).trim() || 'sequential'
  if (!isSupportedWorkflowPattern(pattern)) {
    return failure(`未知的协作模式 ${pattern}，支持：${supportedWorkflowPatterns.join(' / ')}。`)
  }

  if (!Array.isArray(definition.agents) || !definition.agents.length) return failure('agents 必须是非空数组。')
  if (definition.agents.length > MAX_AGENTS) return failure(`agents 数量过多（最多 ${MAX_AGENTS} 个）。`)
  const minimumAgents = minAgentsForPattern(pattern)
  if (definition.agents.length < minimumAgents) {
    return failure(`协作模式 ${workflowPatternLabels[pattern] || pattern} 至少需要 ${minimumAgents} 个智能体，当前定义只有 ${definition.agents.length} 个。`)
  }
  const maximumAgents = maxAgentsForPattern(pattern)
  if (definition.agents.length > maximumAgents) {
    return failure(`协作模式 ${workflowPatternLabels[pattern] || pattern} 最多支持 ${maximumAgents} 个智能体，当前定义有 ${definition.agents.length} 个。`)
  }
  if (!Array.isArray(definition.steps) || !definition.steps.length) return failure('steps 必须是非空数组。')
  if (definition.steps.length > MAX_STEPS) return failure(`steps 数量过多（最多 ${MAX_STEPS} 个）。`)

  const agentNames = new Set()
  for (const agent of definition.agents) {
    if (!isPlainObject(agent)) return failure('每个 agent 必须是对象。')
    const name = text(agent.name).trim()
    if (!name) return failure('每个 agent 都必须有 name。')
    if (agentNames.has(name)) return failure(`agent 名称重复：${name}。`)
    agentNames.add(name)
  }

  const stepIds = new Set()
  for (const step of definition.steps) {
    if (!isPlainObject(step)) return failure('每个 step 必须是对象。')
    const id = text(step.id).trim()
    if (!id) return failure('每个 step 都必须有 id。')
    if (stepIds.has(id)) return failure(`step id 重复：${id}。`)
    stepIds.add(id)
    if (!agentNames.has(text(step.agent_name).trim())) {
      return failure(`step ${id} 引用了不存在的 agent：${text(step.agent_name) || '（空）'}。`)
    }
  }
  for (const step of definition.steps) {
    const inputFrom = text(step.input_from).trim()
    if (inputFrom && !stepIds.has(inputFrom)) {
      return failure(`step ${text(step.id)} 的 input_from 引用了不存在的 step：${inputFrom}。`)
    }
  }

  return {
    ok: true,
    value: stripSecretFields(definition),
    warnings: secretWarning ? [secretWarning] : [],
  }
}

export function workflowDefinitionSummary(definition) {
  const pattern = text(definition?.pattern).trim() || 'sequential'
  return {
    name: text(definition?.name),
    pattern,
    patternLabel: workflowPatternLabels[pattern] || pattern,
    agentCount: Array.isArray(definition?.agents) ? definition.agents.length : 0,
    stepCount: Array.isArray(definition?.steps) ? definition.steps.length : 0,
  }
}

/** 导出文本：先清洗密钥字段，再格式化。 */
export function serializeDefinition(definition) {
  return JSON.stringify(stripSecretFields(definition), null, 2)
}

/** 生成安全的下载文件名（保留中文，只替换文件系统保留字符）。 */
export function definitionFileName(definition) {
  const base = text(definition?.name)
    .replace(/[\\/:*?"<>|]/g, '-')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^[-.]+|[-.]+$/g, '')
    .slice(0, 60) || 'workflow'
  const id = text(definition?.workflow_id).replace(/[^a-zA-Z0-9-]/g, '').slice(0, 8)
  return `agentflow-${base}${id ? `-${id}` : ''}.json`
}
