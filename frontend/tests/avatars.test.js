import test from 'node:test'
import assert from 'node:assert/strict'
import { avatarFor } from '../src/utils/avatars.js'
import { classifyGroupMessage } from '../src/utils/groupChat.js'

test('avatarFor is stable and uses initials', () => {
  const first = avatarFor('member_1', 'openai/gpt-5')
  assert.deepEqual(first, avatarFor('member_1', 'openai/gpt-5'))
  assert.equal(first.initials.length >= 1, true)
  assert.match(first.color, /^#[0-9a-f]{6}$/i)
})

test('classifyGroupMessage hides raw lead JSON and keeps tool cards', () => {
  assert.equal(classifyGroupMessage({ metadata: { visibility: 'internal' } }), null)
  assert.equal(classifyGroupMessage({ sender: 'lead', content: '{"done":true,"summary":"x"}' }), null)
  assert.equal(classifyGroupMessage({ metadata: { visibility: 'tool' } }), 'tool')
  assert.equal(classifyGroupMessage({ metadata: { visibility: 'system' } }), 'system')
  assert.equal(classifyGroupMessage({ sender: 'member_1', content: 'hi' }), 'chat')
})
