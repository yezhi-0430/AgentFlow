// 后端已实现全部七种协作模式，创建、导入与执行阶段均按此列表放行。
export const supportedWorkflowPatterns = ['sequential', 'parallel', 'hierarchical', 'debate', 'voting', 'dynamic', 'group_chat']

/** 创建弹窗与创建接口统一的智能体数量上限。 */
export const MAX_AGENT_COUNT = 10

/** 各模式的最少智能体数量：协调者/裁判/群聊需要独立成员。 */
export const MIN_AGENTS_BY_PATTERN = {
  sequential: 1,
  parallel: 1,
  hierarchical: 2,
  debate: 3,
  voting: 3,
  dynamic: 2,
  group_chat: 2,
}

/** 群聊模式最多 6 人，避免上下文和成本失控。 */
export const MAX_AGENTS_BY_PATTERN = {
  group_chat: 6,
}

/** 协作模式中文名，用于列表与摘要展示。 */
export const workflowPatternLabels = {
  sequential: '顺序执行',
  parallel: '并行执行',
  hierarchical: '层次协作',
  debate: '辩论模式',
  voting: '投票模式',
  dynamic: '动态协作',
  group_chat: '群聊协作',
}

/**
 * 创建弹窗展示的协作模式。roleHint 说明该模式的团队角色构成，
 * minAgents/maxAgents 与后端 validate_pattern_agents 保持一致。
 */
export const creationPatterns = [
  { value: 'sequential', label: '顺序执行', icon: 'arrow', description: '依次推进任务', roleHint: '全部为工作者', minAgents: 1, maxAgents: 10, supported: true },
  { value: 'parallel', label: '并行执行', icon: 'parallel', description: '同时分工协作', roleHint: '全部为工作者', minAgents: 1, maxAgents: 10, supported: true },
  { value: 'hierarchical', label: '层次协作', icon: 'hierarchy', description: '统筹与分层执行', roleHint: '1 位协调者 + 若干工作者', minAgents: 2, maxAgents: 10, supported: true },
  { value: 'debate', label: '辩论模式', icon: 'message', description: '讨论并汇聚共识', roleHint: '多位辩手 + 1 位裁判', minAgents: 3, maxAgents: 10, supported: true },
  { value: 'voting', label: '投票模式', icon: 'check', description: '多智能体投票决策', roleHint: '多位候选者 + 1 位裁判', minAgents: 3, maxAgents: 10, supported: true },
  { value: 'dynamic', label: '动态协作', icon: 'sliders', description: '运行时动态编排任务', roleHint: '1 位协调者 + 若干工作者', minAgents: 2, maxAgents: 10, supported: true },
  { value: 'group_chat', label: '群聊协作', icon: 'message', description: '共享群聊、互相点名', roleHint: '可选 Lead + 群聊成员', minAgents: 2, maxAgents: 6, supported: true },
]

export function isSupportedWorkflowPattern(pattern) {
  return supportedWorkflowPatterns.includes(pattern)
}

/** 预设里若带有未知模式，回退到可创建的顺序执行。 */
export function normalizeCreationPattern(pattern) {
  return isSupportedWorkflowPattern(pattern) ? pattern : 'sequential'
}

/** 返回某模式的最少智能体数量；未知模式按顺序执行处理。 */
export function minAgentsForPattern(pattern) {
  const minimum = MIN_AGENTS_BY_PATTERN[pattern]
  return Number.isInteger(minimum) ? minimum : 1
}

/** 返回某模式的最多智能体数量；未知模式按全局上限处理。 */
export function maxAgentsForPattern(pattern) {
  const maximum = MAX_AGENTS_BY_PATTERN[pattern]
  return Number.isInteger(maximum) ? maximum : MAX_AGENT_COUNT
}

/** 切换模式时把低于下限的数量抬到下限；合法数量保持不变。 */
export function ensureMinimumAgents(pattern, count) {
  const minimum = minAgentsForPattern(pattern)
  return Number.isInteger(count) && count >= minimum ? count : minimum
}

/** 把数量收敛到 [minAgents, maxAgents]，非法值回落到下限。 */
export function clampAgentCount(pattern, count) {
  const minimum = minAgentsForPattern(pattern)
  const maximum = maxAgentsForPattern(pattern)
  const value = Number.isInteger(count) ? count : minimum
  return Math.min(maximum, Math.max(minimum, value))
}

export const providerOptions = [
  { value: 'openai', label: 'OpenAI', symbol: 'O', description: 'OpenAI API' },
  { value: 'anthropic', label: 'Anthropic', symbol: 'A', description: 'Claude 模型服务' },
  { value: 'deepseek', label: 'DeepSeek', symbol: 'D', description: 'DeepSeek 模型服务' },
  { value: 'openrouter', label: 'OpenRouter', symbol: 'R', description: '通过一个接口连接不同模型' },
  { value: 'local', label: '本地模型', symbol: 'L', description: '使用本地模型配置' },
]

// Keep the existing backend model identifiers unchanged.
export const modelOptions = {
  openai: [{ value: 'gpt-6.1-sol', label: 'GPT-6.1-SOL', description: 'gpt-6.1-sol', tag: '默认' }],
  anthropic: [
    { value: 'claude-3-5-haiku', label: 'Claude 3.5 Haiku', description: 'claude-3-5-haiku', tag: '默认' },
    { value: 'claude-opus-5-5', label: 'Claude Opus 5.5', description: 'claude-opus-5-5' },
  ],
  deepseek: [{ value: 'deepseek-v4-flash', label: 'DeepSeek V4 Flash', description: 'deepseek-v4-flash', tag: '默认' }],
  openrouter: [
    { value: 'openai/gpt-4o', label: 'GPT-4o', description: 'openai/gpt-4o', tag: '默认' },
    { value: 'anthropic/claude-3.5-sonnet', label: 'Claude 3.5 Sonnet', description: 'anthropic/claude-3.5-sonnet' },
    { value: 'google/gemini-2.0-flash-001', label: 'Gemini 2.0 Flash', description: 'google/gemini-2.0-flash-001' },
    { value: 'deepseek/deepseek-chat', label: 'DeepSeek Chat', description: 'deepseek/deepseek-chat' },
    { value: 'qwen/qwen-2.5-72b-instruct', label: 'Qwen 2.5 72B', description: 'qwen/qwen-2.5-72b-instruct' },
    { value: 'x-ai/grok-2-1212', label: 'Grok 2', description: 'x-ai/grok-2-1212' },
    { value: 'mistralai/mistral-large', label: 'Mistral Large', description: 'mistralai/mistral-large' },
    { value: 'meta-llama/llama-3.3-70b-instruct', label: 'Llama 3.3 70B', description: 'meta-llama/llama-3.3-70b-instruct' },
    { value: 'moonshotai/kimi-k2', label: 'Kimi K2', description: 'moonshotai/kimi-k2' },
    { value: 'z-ai/glm-4.5', label: 'GLM 4.5', description: 'z-ai/glm-4.5' },
    { value: 'minimax/minimax-m2', label: 'MiniMax M2', description: 'minimax/minimax-m2' },
    { value: 'cohere/command-a', label: 'Command A', description: 'cohere/command-a' },
  ],
}
