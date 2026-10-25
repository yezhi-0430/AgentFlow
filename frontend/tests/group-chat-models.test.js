import test from 'node:test'
import assert from 'node:assert/strict'
import { buildGroupChatConfig } from '../src/utils/groupChatConfig.js'

test('buildGroupChatConfig carries member and lead models', () => {
  const config = buildGroupChatConfig({
    enableLead: true,
    leadModel: 'anthropic/claude-sonnet-4.5',
    members: [
      { name: 'member_1', model: 'openai/gpt-5' },
      { name: 'member_2', model: 'google/gemini-2.5-pro' },
    ],
  })
  assert.deepEqual(config.members.map(member => member.model), ['openai/gpt-5', 'google/gemini-2.5-pro'])
  assert.equal(config.lead_model, 'anthropic/claude-sonnet-4.5')
})

test('buildGroupChatConfig omits lead model when lead is off', () => {
  const config = buildGroupChatConfig({
    enableLead: false,
    leadModel: 'unused',
    members: [{ name: 'member_1', model: 'a' }, { name: 'member_2', model: 'b' }],
  })
  assert.equal('lead_model' in config, false)
})
