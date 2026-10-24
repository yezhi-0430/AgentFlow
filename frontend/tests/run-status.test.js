import test from 'node:test'
import assert from 'node:assert/strict'
import {
  formatDuration,
  formatTimestamp,
  isTerminalExecutionStatus,
  isTerminalRunStatus,
  pickLatestRun,
  runStatusMeta,
  statusClass,
  statusLabel,
  statusTone,
  truncateId,
} from '../src/utils/runStatus.js'

test('后端运行状态映射为明确的中文状态，失败/停止不会显示成成功', () => {
  assert.equal(statusLabel('completed'), '已完成')
  assert.equal(statusLabel('failed'), '失败')
  assert.equal(statusLabel('partial'), '部分完成')
  assert.equal(statusLabel('stopped'), '已停止')
  assert.equal(statusLabel('cancelled'), '已取消')
  assert.equal(statusLabel('stopping'), '停止中')
  assert.equal(statusLabel('running'), '运行中')

  assert.equal(statusClass('completed'), 'status-success')
  assert.equal(statusClass('failed'), 'status-error')
  assert.equal(statusClass('partial'), 'status-warning')
  assert.equal(statusClass('stopped'), 'status-stopped')
  assert.equal(statusClass('cancelled'), 'status-stopped')

  assert.notEqual(statusClass('failed'), statusClass('completed'))
  assert.notEqual(statusTone('stopped'), 'success')
  assert.notEqual(statusTone('stopping'), 'success')
})

test('未知状态保留原始值，不伪造为成功', () => {
  assert.equal(statusLabel('archived'), 'archived')
  assert.equal(statusClass('archived'), 'status-default')
  assert.equal(statusTone('archived'), 'unknown')
  assert.deepEqual(runStatusMeta(null), {
    label: '未知状态',
    className: 'status-default',
    tone: 'unknown',
    terminal: false,
  })
})

test('终态判断覆盖执行器的 error 与运行记录的 failed/cancelled', () => {
  for (const status of ['completed', 'failed', 'partial', 'stopped', 'cancelled']) {
    assert.equal(isTerminalRunStatus(status), true, status)
    assert.equal(isTerminalExecutionStatus(status), true, status)
  }
  for (const status of ['running', 'pending', 'stopping']) {
    assert.equal(isTerminalRunStatus(status), false, status)
    assert.equal(isTerminalExecutionStatus(status), false, status)
  }
  assert.equal(isTerminalExecutionStatus('error'), true)
  assert.equal(isTerminalExecutionStatus('paused'), false)
})

test('最新运行按 created_at 选择，而不是依赖数组顺序', () => {
  const runs = [
    { run_id: 'older', status: 'completed', created_at: 100 },
    { run_id: 'newest', status: 'failed', created_at: 300 },
    { run_id: 'middle', status: 'partial', created_at: 200 },
  ]
  assert.equal(pickLatestRun(runs)?.run_id, 'newest')
  assert.equal(pickLatestRun([{ run_id: 'only', created_at: 5 }])?.run_id, 'only')
  assert.equal(pickLatestRun([]), null)
  assert.equal(pickLatestRun(null), null)
  assert.equal(pickLatestRun([{ status: 'completed' }]), null)
})

test('时间与耗时展示对缺失值保持安全', () => {
  const timestamp = 1_700_000_000.5
  assert.equal(formatTimestamp(timestamp), new Date(timestamp * 1000).toLocaleString())
  assert.equal(formatTimestamp('2024-01-02T03:04:05Z'), new Date('2024-01-02T03:04:05Z').toLocaleString())
  assert.equal(formatTimestamp(null), '-')
  assert.equal(formatTimestamp('not-a-date'), '-')

  assert.equal(formatDuration(1.234), '1.23')
  assert.equal(formatDuration(0), '0.00')
  assert.equal(formatDuration(undefined), '-')
})

test('运行 ID 前缀展示不会把空值伪装成有效 id', () => {
  assert.equal(truncateId('12345678-abcd', 8), '12345678…')
  assert.equal(truncateId('short', 8), 'short')
  assert.equal(truncateId(''), '-')
  assert.equal(truncateId(null), '-')
})
