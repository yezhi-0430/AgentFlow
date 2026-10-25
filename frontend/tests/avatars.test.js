import test from 'node:test'
import assert from 'node:assert/strict'
import { avatarFor } from '../src/utils/avatars.js'
import { classifyGroupMessage, formatChatTime, formatGroupChatMessage } from '../src/utils/groupChat.js'

test('avatarFor is stable and uses initials', () => {
  const first = avatarFor('member_1', 'openai/gpt-5')
  assert.deepEqual(first, avatarFor('member_1', 'openai/gpt-5'))
  assert.equal(first.initials.length >= 1, true)
  assert.match(first.color, /^#[0-9a-f]{6}$/i)
})

test('lead summary JSON is converted to a readable system message', () => {
  const message = formatGroupChatMessage({
    sender: 'lead',
    content: '{"done": true, "summary": "最终结论"}',
    metadata: { visibility: 'system' },
  })
  assert.equal(message.content, '最终结论')
  assert.equal(message.kind, 'system')
})

test('classifyGroupMessage hides legacy Lead JSON variants', () => {
  assert.equal(formatGroupChatMessage({ sender: 'lead', content: '{"next":"member_1","task":"x"}' }), null)
  assert.equal(formatGroupChatMessage({ sender: 'lead', content: '```json\n{"done":false,"next":"member_1"}\n```' }), null)
})

test('formatChatTime treats backend timestamps as seconds', () => {
  assert.match(formatChatTime(1_700_000_000), /^\d{2}:\d{2}$/)
})

test('classifyGroupMessage hides raw lead JSON and keeps tool cards', () => {
  assert.equal(classifyGroupMessage({ metadata: { visibility: 'internal' } }), null)
  assert.equal(classifyGroupMessage({ sender: 'lead', content: '{"done":false,"next":"member_1"}' }), null)
  assert.equal(classifyGroupMessage({ metadata: { visibility: 'tool' } }), 'tool')
  assert.equal(classifyGroupMessage({ metadata: { visibility: 'system' } }), 'system')
  assert.equal(classifyGroupMessage({ sender: 'member_1', content: 'hi' }), 'chat')
})
