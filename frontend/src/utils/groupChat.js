/**
 * 独立「群聊」导航的纯逻辑：消息归一化与终态判断。
 */
export function isGroupChatTerminal(status) {
  return ['completed', 'failed', 'partial', 'stopped', 'cancelled'].includes(String(status || '').toLowerCase())
}

export function formatGroupChatMessage(message) {
  if (!message || typeof message !== 'object') return null
  const display = message.metadata && typeof message.metadata.display_content === 'string'
    ? message.metadata.display_content
    : null
  const content = display || (typeof message.content === 'string' ? message.content : JSON.stringify(message.content ?? ''))
  if (!content.trim()) return null
  const sender = message.sender || 'system'
  const receiver = message.receiver || 'group'
  const timestamp = message.timestamp || message.created_at || ''
  return {
    id: message.id || `${sender}:${receiver}:${content.slice(0, 24)}`,
    sender,
    receiver,
    content,
    timestamp,
    isAgent: sender !== 'system' && sender !== 'group' && sender !== 'human',
  }
}

export function normalizeGroupChatMessages(messages) {
  if (!Array.isArray(messages)) return []
  return messages.map(formatGroupChatMessage).filter(Boolean)
}
