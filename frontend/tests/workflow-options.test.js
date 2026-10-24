import test from 'node:test'
import assert from 'node:assert/strict'
import {
  MAX_AGENT_COUNT,
  MIN_AGENTS_BY_PATTERN,
  clampAgentCount,
  creationPatterns,
  ensureMinimumAgents,
  isSupportedWorkflowPattern,
  minAgentsForPattern,
  normalizeCreationPattern,
  supportedWorkflowPatterns,
} from '../src/utils/workflowOptions.js'

const patterns = ['sequential', 'parallel', 'hierarchical', 'debate', 'voting', 'dynamic']

test('六种协作模式全部可创建，不再展示暂不支持原因或徽标', () => {
  assert.deepEqual(supportedWorkflowPatterns, patterns)
  assert.deepEqual(creationPatterns.map(pattern => pattern.value), patterns)
  for (const pattern of creationPatterns) {
    assert.equal(pattern.supported, true, pattern.value)
    assert.equal('reason' in pattern, false, pattern.value)
  }
  assert.doesNotMatch(JSON.stringify(creationPatterns), /暂不支持/)
})

test('每种模式都声明最少智能体数量与团队角色说明', () => {
  const expected = {
    sequential: { minAgents: 1, roleHint: '全部为工作者' },
    parallel: { minAgents: 1, roleHint: '全部为工作者' },
    hierarchical: { minAgents: 2, roleHint: '1 位协调者 + 若干工作者' },
    debate: { minAgents: 3, roleHint: '多位辩手 + 1 位裁判' },
    voting: { minAgents: 3, roleHint: '多位候选者 + 1 位裁判' },
    dynamic: { minAgents: 2, roleHint: '1 位协调者 + 若干工作者' },
  }
  for (const pattern of creationPatterns) {
    assert.equal(pattern.minAgents, expected[pattern.value].minAgents, pattern.value)
    assert.equal(pattern.roleHint, expected[pattern.value].roleHint, pattern.value)
    assert.ok(pattern.roleHint.length > 0)
  }
  assert.deepEqual(MIN_AGENTS_BY_PATTERN, {
    sequential: 1,
    parallel: 1,
    hierarchical: 2,
    debate: 3,
    voting: 3,
    dynamic: 2,
  })
  for (const pattern of patterns) {
    assert.equal(minAgentsForPattern(pattern), expected[pattern].minAgents)
  }
})

test('模式判断与创建回退逻辑：未知值仍回退顺序执行', () => {
  for (const pattern of patterns) {
    assert.equal(isSupportedWorkflowPattern(pattern), true)
    assert.equal(normalizeCreationPattern(pattern), pattern)
  }
  for (const pattern of ['consensus', 'single', undefined, '', null]) {
    assert.equal(isSupportedWorkflowPattern(pattern), false)
    assert.equal(normalizeCreationPattern(pattern), 'sequential')
    assert.equal(minAgentsForPattern(pattern), 1)
  }
})

test('切换模式时低于下限的数量会自动抬升，合法数量保持不变', () => {
  assert.equal(ensureMinimumAgents('sequential', 1), 1)
  assert.equal(ensureMinimumAgents('parallel', 6), 6)
  assert.equal(ensureMinimumAgents('hierarchical', 1), 2)
  assert.equal(ensureMinimumAgents('dynamic', 2), 2)
  assert.equal(ensureMinimumAgents('debate', 1), 3)
  assert.equal(ensureMinimumAgents('voting', 2), 3)
  assert.equal(ensureMinimumAgents('debate', 4), 4)
  assert.equal(ensureMinimumAgents('debate', ''), 3)
  assert.equal(ensureMinimumAgents('debate', 2.5), 3)
})

test('创建数量收敛在 [minAgents, 10]，非法值回落到当前模式下限', () => {
  assert.equal(MAX_AGENT_COUNT, 10)
  assert.equal(clampAgentCount('debate', 1), 3)
  assert.equal(clampAgentCount('voting', 99), 10)
  assert.equal(clampAgentCount('hierarchical', '2'), 2)
  assert.equal(clampAgentCount('parallel', 0), 1)
  assert.equal(clampAgentCount('parallel', 7), 7)
})
