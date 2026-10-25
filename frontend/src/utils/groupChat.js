/**
 * 独立「群聊」导航的纯逻辑：消息归一化与终态判断。
 */
export function isGroupChatTerminal(status) {
  return ['completed', 'failed', 'partial', 'stopped', 'cancelled'].includes(String(status || '').toLowerCase())
}

export function formatChatTime(value) {
  if (!value) return ''
  const raw = typeof value === 'number' ? value * 1000 : value
  const date = new Date(raw)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function parseLeadPayload(content) {
  const text = String(content || '').trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '')
  if (!text.startsWith('{')) return null
  try {
    const payload = JSON.parse(text)
    if (payload && typeof payload === 'object' && ('done' in payload || 'next' in payload || 'worker' in payload || 'tool' in payload)) {
      return payload
    }
  } catch {
    return null
  }
  return null
}

export function classifyGroupMessage(message) {
  if (!message || typeof message !== 'object') return null
  const visibility = message.metadata?.visibility
  if (visibility === 'internal') return 'internal'
  const content = String(message.content ?? '').trim()
  const payload = parseLeadPayload(content)
  if (payload) return payload.done === true && payload.summary ? 'system' : null
  if (visibility === 'tool') return 'tool'
  if (visibility === 'system') return 'system'
  const sender = message.sender || ''
  if (sender === 'group' || sender === 'system') return 'system'
  return 'chat'
}

const BUBBLE_COLORS = [
  ['#ffffff', '#e6e6e6'],
  ['#f2f7ff', '#d7e5fb'],
  ['#f3fbf6', '#d3ecdc'],
  ['#fff8ed', '#f1dfc2'],
  ['#faf4ff', '#e5d8f7'],
  ['#fff3f3', '#f0d5d5'],
  ['#f2fbfb', '#d0e8e8'],
]

export function bubbleStyleFor(model = '', sender = '') {
  let hash = 0
  for (const char of `${model}|${sender}`) hash = (hash * 31 + char.charCodeAt(0)) >>> 0
  if (sender === 'lead') return { background: '#191919', borderColor: '#191919', color: '#fff' }
  const [background, borderColor] = BUBBLE_COLORS[hash % BUBBLE_COLORS.length]
  return { background, borderColor, color: '#191919' }
}

export function formatGroupChatMessage(message) {
  if (!message || typeof message !== 'object') return null
  const display = message.metadata && typeof message.metadata.display_content === 'string'
    ? message.metadata.display_content
    : null
  let content = display || (typeof message.content === 'string' ? message.content : JSON.stringify(message.content ?? ''))
  if (!content.trim()) return null
  let forcedKind = null
  if (message.metadata?.visibility === 'internal') {
    forcedKind = 'internal'
  } else {
    const payload = parseLeadPayload(content)
    if (payload) {
      if (payload.done === true && payload.summary) {
        content = String(payload.summary)
        forcedKind = 'system'
      } else {
        return null
      }
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
    rawContent: typeof message.content === 'string' ? message.content : '',
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
