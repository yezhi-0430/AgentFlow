// 后端当前只实现 sequential / parallel；其余模式会在创建/执行阶段被拒绝。
export const supportedWorkflowPatterns = ['sequential', 'parallel']

export const unsupportedPatternReason = '当前后端暂不支持该协作模式，创建后无法执行'

/** 协作模式中文名，用于列表与摘要展示。 */
export const workflowPatternLabels = {
  sequential: '顺序执行',
  parallel: '并行执行',
  hierarchical: '层次协作',
  debate: '辩论模式',
  voting: '投票模式',
  dynamic: '动态协作',
}

/**
 * 创建弹窗展示的协作模式。未支持的模式保留展示（合作概念仍然可见），
 * 但必须禁用并给出原因，避免用户创建成功后才在运行时失败。
 */
export const creationPatterns = [
  { value: 'sequential', label: '顺序执行', icon: 'arrow', description: '依次推进任务', supported: true },
  { value: 'parallel', label: '并行执行', icon: 'parallel', description: '同时分工协作', supported: true },
  { value: 'hierarchical', label: '层次协作', icon: 'hierarchy', description: '统筹与分层执行', supported: false, reason: unsupportedPatternReason },
  { value: 'debate', label: '辩论模式', icon: 'message', description: '讨论并汇聚共识', supported: false, reason: unsupportedPatternReason },
  { value: 'voting', label: '投票模式', icon: 'check', description: '多智能体投票决策', supported: false, reason: unsupportedPatternReason },
  { value: 'dynamic', label: '动态协作', icon: 'sliders', description: '运行时动态编排任务', supported: false, reason: unsupportedPatternReason },
]

export function isSupportedWorkflowPattern(pattern) {
  return supportedWorkflowPatterns.includes(pattern)
}

/** 预设里若带有未支持的模式，回退到可创建的顺序执行。 */
export function normalizeCreationPattern(pattern) {
  return isSupportedWorkflowPattern(pattern) ? pattern : 'sequential'
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
    { value: 'openai/gpt-6.1-sol', label: 'GPT-6.1-SOL', description: 'openai/gpt-6.1-sol', tag: '默认' },
    { value: 'deepseek/deepseek-v4-flash', label: 'DeepSeek V4 Flash', description: 'deepseek/deepseek-v4-flash' },
    { value: 'anthropic/claude-3-5-haiku', label: 'Claude 3.5 Haiku', description: 'anthropic/claude-3-5-haiku' },
    { value: 'anthropic/claude-opus-5-5', label: 'Claude Opus 5.5', description: 'anthropic/claude-opus-5-5' },
  ],
}
