import test from 'node:test'
import assert from 'node:assert/strict'
import {
  creationPatterns,
  isSupportedWorkflowPattern,
  normalizeCreationPattern,
  supportedWorkflowPatterns,
  unsupportedPatternReason,
} from '../src/utils/workflowOptions.js'

test('创建弹窗只允许选择后端已实现的协作模式', () => {
  assert.deepEqual(supportedWorkflowPatterns, ['sequential', 'parallel'])
  const supported = creationPatterns.filter(pattern => pattern.supported).map(pattern => pattern.value)
  assert.deepEqual(supported, ['sequential', 'parallel'])
})

test('未实现的模式仍然可见但被标记为暂不支持并带原因', () => {
  const unsupported = creationPatterns.filter(pattern => !pattern.supported)
  assert.deepEqual(
    unsupported.map(pattern => pattern.value),
    ['hierarchical', 'debate', 'voting', 'dynamic'],
  )
  for (const pattern of unsupported) {
    assert.equal(pattern.reason, unsupportedPatternReason)
    assert.match(pattern.reason, /暂不支持/)
  }
})

test('模式判断与创建回退逻辑与后端能力一致', () => {
  assert.equal(isSupportedWorkflowPattern('sequential'), true)
  assert.equal(isSupportedWorkflowPattern('parallel'), true)
  for (const pattern of ['hierarchical', 'debate', 'voting', 'dynamic', undefined, '']) {
    assert.equal(isSupportedWorkflowPattern(pattern), false)
    assert.equal(normalizeCreationPattern(pattern), 'sequential')
  }
  assert.equal(normalizeCreationPattern('parallel'), 'parallel')
})
