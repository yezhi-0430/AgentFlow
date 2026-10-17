import test from 'node:test'
import assert from 'node:assert/strict'
import { validateConnection, formatExecutionError } from '../src/utils/connection.js'

test('OpenRouter keys are rejected when an official provider is selected', () => {
  assert.match(validateConnection('openai', 'sk-or-v1-test-only'), /OpenRouter/)
  assert.match(validateConnection('anthropic', ' sk-or-v1-test-only '), /OpenRouter/)
  assert.equal(validateConnection('openrouter', 'sk-or-v1-test-only'), '')
})
test('remote providers require a key and accept other key formats without guessing', () => {
  assert.match(validateConnection('openai', ' '), /API Key/)
  assert.equal(validateConnection('openai', 'test-openai-key'), '')
})
test('a cross-provider 401 explains how to repair the connection without echoing the key', () => {
  const result = formatExecutionError("Error: Error code: 401 - Incorrect API key provided: sk-or-v1-test-only, code: invalid_api_key")
  assert.match(result, /OpenRouter/)
  assert.match(result, /OpenAI/)
  assert.doesNotMatch(result, /sk-or-v1-test-only/)
})
test('other authentication failures give an actionable message', () => {
  const result = formatExecutionError('401 invalid_api_key')
  assert.match(result, /提供商/)
  assert.match(result, /密钥/)
})
test('non-authentication errors keep their useful details and redact credentials', () => {
  assert.equal(formatExecutionError('Model unavailable: test-model'), 'Model unavailable: test-model')
  assert.doesNotMatch(formatExecutionError('failure with sk-or-v1-sensitive-value'), /sensitive-value/)
})
