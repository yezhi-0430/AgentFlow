/**
 * 独立「群聊」导航的纯逻辑：消息归一化与终态判断。
 */
export function isGroupChatTerminal(status) {
  return ['completed', 'failed', 'partial', 'stopped', 'cancelled'].includes(String(status || '').toLowerCase())
}

export function classifyGroupMessage(message) {
  if (!message || typeof message !== 'object') return null
  const visibility = message.metadata?.visibility
  if (visibility === 'internal') return null
  const content = String(message.content ?? '').trim()
  if (content.startsWith('{"done"') || content.startsWith('{"tool"')) return null
  if (visibility === 'tool') return 'tool'
  if (visibility === 'system') return 'system'
  const sender = message.sender || ''
  if (sender === 'group' || sender === 'system') return 'system'
  return 'chat'
}

export function formatGroupChatMessage(message) {
  if (!message || typeof message !== 'object') return null
  const display = message.metadata && typeof message.metadata.display_content === 'string'
    ? message.metadata.display_content
    : null
  let content = display || (typeof message.content === 'string' ? message.content : JSON.stringify(message.content ?? ''))
  if (!content.trim()) return null
  let forcedKind = null
  if (String(content).trim().startsWith('{"done"')) {
    try {
      const payload = JSON.parse(content)
      if (payload?.summary) {
        content = String(payload.summary)
        forcedKind = 'system'
      } else {
        return null
      }
    } catch {
      return null
    }
  }
  const sender = message.sender || 'system'
  const receiver = message.receiver || 'group'
  const timestamp = message.timestamp || message.created_at || ''
  return {
    id: message.id || `${sender}:${receiver}:${content.slice(0, 24)}`,
    sender,
    receiver,
    content,
    timestamp,
    metadata: message.metadata || {},
    model: message.metadata?.model || '',
    role: message.metadata?.role || '',
    runId: message.run_id || message.metadata?.run_id || '',
    kind: forcedKind || classifyGroupMessage(message),
    isAgent: sender !== 'system' && sender !== 'group' && sender !== 'human',
  }
}

export function normalizeGroupChatMessages(messages) {
  if (!Array.isArray(messages)) return []
  return messages.map(formatGroupChatMessage).filter(Boolean)
}
