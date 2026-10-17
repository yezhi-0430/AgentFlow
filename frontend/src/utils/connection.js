export function validateConnection(provider, key) {
  const trimmed = key?.trim() || ''
  if (!trimmed) return '请输入所选模型提供商的 API Key。'
  if (trimmed.startsWith('sk-or-') && provider !== 'openrouter') return '检测到 OpenRouter 密钥，请将模型提供商切换为 OpenRouter。'
  return ''
}

export function formatExecutionError(value) {
  const text = String(value || '')
  const authenticationError = /invalid_api_key|incorrect api key|invalid api key|\b401\b/i.test(text)
  if (authenticationError && /sk-or-/.test(text) && /incorrect api key provided|platform\.openai\.com/i.test(text)) {
    return '模型连接失败（401）：OpenRouter 密钥被发送到了 OpenAI 接口。请重新配置模型，选择 OpenRouter，并重新输入对应密钥。'
  }
  if (authenticationError) return '模型连接失败（401）：密钥校验未通过。请检查模型提供商是否匹配，以及密钥是否有效，再重新配置模型。'
  return text.replace(/sk-[a-zA-Z0-9_*.-]+/g, '[密钥已隐藏]')
}
