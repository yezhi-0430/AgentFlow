import test from 'node:test'
import assert from 'node:assert/strict'
import { MODEL_CATEGORY_ORDER, RECOMMENDED_TEAM, modelProfile, sortModelOptions } from '../src/utils/modelProfiles.js'

test('recommended models are sorted before regular models', () => {
  const options = sortModelOptions([
    { value: 'cohere/command-a-plus', label: 'Command A+' },
    { value: 'openai/gpt-6.1-sol', label: 'GPT-6.1 Sol' },
    { value: 'openai/gpt-6-luna', label: 'GPT-6 Luna' },
  ])
  assert.equal(options[0].value, 'openai/gpt-6.1-sol')
  assert.ok(options.slice(0, 2).every(option => modelProfile(option.value).recommended))
})

test('model profiles expose category, Chinese note and recommended team', () => {
  const profile = modelProfile('openai/gpt-6.1-sol:batch')
  assert.equal(profile.category, '综合旗舰')
  assert.match(profile.note, /旗舰/)
  assert.ok(MODEL_CATEGORY_ORDER.includes(profile.category))
  assert.equal(RECOMMENDED_TEAM.lead, 'openai/gpt-6.1-sol')
  assert.ok(RECOMMENDED_TEAM.members.length >= 3)
})
