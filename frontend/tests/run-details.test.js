import test from 'node:test'
import assert from 'node:assert/strict'
import {
  ERROR_TYPE_LABELS,
  RUN_STATUS_FILTERS,
  buildRunsExportPayload,
  errorTypeLabel,
  filterRunsByStatus,
  formatAttempts,
  normalizeAttempts,
  runAttempts,
  runAttemptsLabel,
  runErrorInfo,
  runsExportFileName,
  serializeRunsExport,
  statusFilterLabel,
  traceIdOf,
  truncateTraceId,
} from '../src/utils/runDetails.js'
import { copyText } from '../src/utils/clipboard.js'

test('error_type 映射为明确的中文标签，空值与未知值不伪造成功', () => {
  const expected = {
    timeout: '超时',
    rate_limit: '限流',
    auth: '鉴权失败',
    network: '网络错误',
    server: '服务端错误',
    validation: '参数/校验错误',
    provider: '模型服务错误',
    cancelled: '已取消',
    unknown: '未知',
  }
  for (const [type, label] of Object.entries(expected)) {
    assert.equal(errorTypeLabel(type), label, type)
  }
  assert.deepEqual(Object.keys(ERROR_TYPE_LABELS).sort(), Object.keys(expected).sort())
  assert.equal(errorTypeLabel(null), '')
  assert.equal(errorTypeLabel(undefined), '')
  assert.equal(errorTypeLabel(''), '')
  assert.equal(errorTypeLabel('   '), '')
  assert.equal(errorTypeLabel(123), '')
  assert.equal(errorTypeLabel('  timeout  '), '超时')
  assert.equal(errorTypeLabel('unexpected_type'), '未知')
})

test('attempts 文案只在发生重试时展示“N 次尝试”', () => {
  assert.equal(normalizeAttempts(3), 3)
  assert.equal(normalizeAttempts('4'), 4)
  assert.equal(normalizeAttempts(0), 0)
  assert.equal(normalizeAttempts(-2), 0)
  assert.equal(normalizeAttempts(1.5), 0)
  assert.equal(normalizeAttempts(null), 0)

  assert.equal(formatAttempts(2), '2 次尝试')
  assert.equal(formatAttempts(3), '3 次尝试')
  assert.equal(formatAttempts('2'), '2 次尝试')
  assert.equal(formatAttempts(1), '')
  assert.equal(formatAttempts(0), '')
  assert.equal(formatAttempts(-1), '')
  assert.equal(formatAttempts(1.5), '')
  assert.equal(formatAttempts(undefined), '')
})

test('运行级 attempts 取步骤最大值，缺失时不伪造重试', () => {
  assert.equal(runAttempts({}), 1)
  assert.equal(runAttempts(null), 1)
  assert.equal(runAttempts({ attempts: 2 }), 2)
  assert.equal(runAttempts({ step_results: [{ attempts: 1 }, { attempts: 3 }, {}] }), 3)
  assert.equal(runAttempts({ attempts: 2, step_results: [{ attempts: 5 }] }), 5)
  assert.equal(runAttempts({ step_results: [{ attempts: 'invalid' }, { attempts: 0 }] }), 1)
  assert.equal(runAttemptsLabel({ attempts: 2 }), '2 次尝试')
  assert.equal(runAttemptsLabel({ attempts: 1 }), '')
})

test('失败/超时原因优先使用后端错误文本，缺失时按 error_type 归因', () => {
  assert.deepEqual(runErrorInfo(null), { type: '', typeLabel: '', reason: '', shortReason: '' })

  const timedOut = runErrorInfo({ error_type: 'timeout', error: 'request timed out after 30s' })
  assert.equal(timedOut.type, 'timeout')
  assert.equal(timedOut.typeLabel, '超时')
  assert.equal(timedOut.reason, 'request timed out after 30s')

  const stepFailure = runErrorInfo({
    status: 'failed',
    step_results: [
      { status: 'completed', attempts: 1 },
      { status: 'failed', error_type: 'rate_limit', error: '429 Too Many Requests', attempts: 2 },
    ],
  })
  assert.equal(stepFailure.typeLabel, '限流')
  assert.match(stepFailure.reason, /429/)
  assert.equal(stepFailure.shortReason, '429 Too Many Requests')

  const noText = runErrorInfo({ error_type: 'network' })
  assert.equal(noText.typeLabel, '网络错误')
  assert.match(noText.reason, /网络/)

  assert.equal(runErrorInfo({ status: 'completed', step_results: [{ status: 'completed' }] }).typeLabel, '')
  const longReason = runErrorInfo({ error: 'x'.repeat(60) })
  assert.equal(longReason.shortReason.length, 25)
  assert.match(longReason.shortReason, /…$/)
})

test('状态筛选保留对应状态并返回副本', () => {
  const runs = [
    { run_id: 'a', status: 'completed' },
    { run_id: 'b', status: 'failed' },
    { run_id: 'c', status: 'partial' },
  ]
  assert.deepEqual(filterRunsByStatus(runs, 'all').map(run => run.run_id), ['a', 'b', 'c'])
  assert.notEqual(filterRunsByStatus(runs, 'all'), runs)
  assert.deepEqual(filterRunsByStatus(runs, 'failed').map(run => run.run_id), ['b'])
  assert.deepEqual(filterRunsByStatus(runs, 'stopped'), [])
  assert.deepEqual(filterRunsByStatus(null, 'failed'), [])
  assert.deepEqual(RUN_STATUS_FILTERS.map(item => item.value), ['all', 'completed', 'failed', 'partial', 'stopped'])
  assert.deepEqual(RUN_STATUS_FILTERS.map(item => item.label), ['全部', '已完成', '失败', '部分完成', '已停止'])
  assert.equal(statusFilterLabel('partial'), '部分完成')
  assert.equal(statusFilterLabel('all'), '全部')
})

test('导出 JSON 包含筛选条件、工作流与运行快照', () => {
  const runs = [
    {
      run_id: 'run-1',
      status: 'failed',
      trace_id: 'trace-1',
      error_type: 'timeout',
      step_results: [{ attempts: 2, error_type: 'timeout' }],
    },
  ]
  const text = serializeRunsExport(runs, { workflowId: 'wf-1', filter: 'failed' }, Date.UTC(2026, 0, 2, 3, 4, 5))
  const payload = JSON.parse(text)
  assert.equal(payload.exported_at, '2026-01-02T03:04:05.000Z')
  assert.equal(payload.filter, 'failed')
  assert.equal(payload.workflow_id, 'wf-1')
  assert.equal(payload.total, 1)
  assert.deepEqual(payload.runs, runs)
  assert.equal(buildRunsExportPayload(null, {}).total, 0)
  assert.equal(buildRunsExportPayload(null, {}).filter, 'all')

  assert.match(runsExportFileName('failed', Date.UTC(2026, 0, 2, 3, 4, 5)), /^runs-failed-\d{8}-\d{6}\.json$/)
  assert.match(runsExportFileName(undefined, Date.UTC(2026, 0, 2, 3, 4, 5)), /^runs-all-/)
})

test('Trace ID 从 run.trace_id 读取并截断展示', () => {
  assert.equal(traceIdOf({ trace_id: ' abcdef ' }), 'abcdef')
  assert.equal(traceIdOf({ trace_id: null }), '')
  assert.equal(traceIdOf({ trace_id: 123 }), '')
  assert.equal(traceIdOf({}), '')
  assert.equal(truncateTraceId('abcdefghijklmnop', 8), 'abcdefgh…')
  assert.equal(truncateTraceId('short', 8), 'short')
  assert.equal(truncateTraceId('', 8), '-')
  assert.equal(truncateTraceId(null), '-')
})

test('剪贴板不可用时降级为手动复制，不静默失败', async () => {
  const copied = []
  const success = await copyText('trace-1', {
    navigator: { clipboard: { writeText: async text => copied.push(text) } },
  })
  assert.deepEqual(success, { method: 'clipboard', text: 'trace-1' })
  assert.deepEqual(copied, ['trace-1'])

  const denied = await copyText('trace-2', {
    navigator: { clipboard: { writeText: async () => { throw new Error('denied') } } },
  })
  assert.deepEqual(denied, { method: 'manual', text: 'trace-2' })

  const unavailable = await copyText('trace-3', {})
  assert.deepEqual(unavailable, { method: 'manual', text: 'trace-3' })

  assert.deepEqual(await copyText('', {}), { method: 'none', text: '' })
})
