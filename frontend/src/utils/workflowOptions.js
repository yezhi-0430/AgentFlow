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
