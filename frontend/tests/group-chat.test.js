import test from 'node:test'
import assert from 'node:assert/strict'
import {
  formatGroupChatMessage,
  isGroupChatTerminal,
  normalizeGroupChatMessages,
} from '../src/utils/groupChat.js'

test('群聊终态判断覆盖完成/失败/部分/停止', () => {
  for (const status of ['completed', 'failed', 'partial', 'stopped', 'cancelled']) {
    assert.equal(isGroupChatTerminal(status), true, status)
  }
  for (const status of ['running', 'executing', 'idle', '', null]) {
    assert.equal(isGroupChatTerminal(status), false, String(status))
  }
})

test('群聊消息归一化保留 sender/receiver/content 并过滤空消息', () => {
  const messages = normalizeGroupChatMessages([
    { id: '1', sender: 'lead', receiver: 'member_1', content: '先分析问题', timestamp: '2026-10-25T00:00:00Z' },
    { sender: 'member_1', receiver: 'group', content: '分析结果' },
    { sender: 'member_2', receiver: 'group', content: '   ' },
    null,
  ])
  assert.equal(messages.length, 2)
  assert.equal(messages[0].sender, 'lead')
  assert.equal(messages[0].receiver, 'member_1')
  assert.equal(messages[0].isAgent, true)
  assert.equal(messages[1].content, '分析结果')
  assert.equal(formatGroupChatMessage(null), null)
})

test('群聊系统消息不标记为 Agent 发言', () => {
  assert.equal(formatGroupChatMessage({ sender: 'group', receiver: 'lead', content: '请开始' }).isAgent, false)
  assert.equal(formatGroupChatMessage({ sender: 'system', receiver: 'lead', content: '系统' }).isAgent, false)
})
