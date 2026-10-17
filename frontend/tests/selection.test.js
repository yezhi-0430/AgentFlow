import test from 'node:test'
import assert from 'node:assert/strict'
import { moveOptionIndex, findOptionMatch } from '../src/utils/selection.js'

test('arrow navigation wraps through the available options', () => {
  assert.equal(moveOptionIndex(2, 3, 'ArrowDown'), 0)
  assert.equal(moveOptionIndex(0, 3, 'ArrowUp'), 2)
})
test('Home and End select the first and last options', () => {
  assert.equal(moveOptionIndex(1, 4, 'Home'), 0)
  assert.equal(moveOptionIndex(1, 4, 'End'), 3)
})

test('navigation starts at the appropriate end when nothing is selected', () => {
  assert.equal(moveOptionIndex(-1, 3, 'ArrowDown'), 0)
  assert.equal(moveOptionIndex(-1, 3, 'ArrowUp'), 2)
})
test('empty selects have no active option', () => {
  assert.equal(moveOptionIndex(0, 0, 'ArrowDown'), -1)
  assert.equal(findOptionMatch([], 'open'), -1)
})
test('typeahead is case insensitive and wraps after the current option', () => {
  const options = [{ label: 'OpenAI' }, { label: 'Anthropic' }, { label: 'OpenRouter' }]
  assert.equal(findOptionMatch(options, 'op', 0), 2)
  assert.equal(findOptionMatch(options, 'OP', 2), 0)
})
test('typeahead also matches the visible option value', () => {
  assert.equal(findOptionMatch([{ label: 'GPT', value: 'openai/gpt' }], 'openai'), 0)
  assert.equal(findOptionMatch([{ label: 'GPT' }], 'missing'), -1)
})
