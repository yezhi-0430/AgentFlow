import test from 'node:test'
import assert from 'node:assert/strict'
import {
  CASE_CELL_META,
  buildCaseMatrix,
  buildExperimentExportPayload,
  classifyCaseCell,
  experimentExportFileName,
  experimentListState,
  formatPercent,
  formatScore,
  formatSeconds,
  formatTokens,
  normalizeCandidateMetrics,
  normalizeCaseCell,
  normalizeEvidence,
  normalizeExperimentDetail,
  normalizeExperimentList,
  normalizeFailureTypes,
  serializeExperimentExport,
  shortFingerprint,
} from '../src/utils/experimentDetails.js'

const EXPORTED_AT = Date.UTC(2026, 0, 2, 3, 4, 5)

function detailPayload() {
  return {
    experiment: {
      experiment_id: 'experiment-1',
      name: 'Harness²-lite 对比',
      dataset_id: 'dataset-v2',
      dataset_version: '2',
      scorer_id: 'rubric',
      scorer_version: '2',
      created_at: 1760000000,
      candidate_count: 2,
      run_count: 6,
    },
    candidates: [
      {
        candidate_id: 'single',
        name: '单智能体',
        fingerprint: '1111222233334444',
        config: { pattern: 'single' },
        metrics: {
          cases: 3,
          completed: 3,
          failed: 0,
          passed: 2,
          pass_rate_all_cases: 0.6667,
          mean_score: 0.7,
          total_tokens: 1200,
          total_seconds: 12.5,
          trace_id_present: 2,
          failure_types: { timeout: 1 },
        },
      },
      {
        candidate_id: 'sequential',
        name: '顺序协作',
        fingerprint: 'aaaabbbbccccdddd',
        config: { pattern: 'sequential' },
      },
    ],
    cases: [
      {
        case_id: 'case-001',
        candidates: {
          single: { run_id: 'run-1', status: 'completed', score: 0.9, score_status: 'scored', passed: true, trace_id: 'trace-1', evidence_ref: 'evidence/1.json', tokens: 400 },
          sequential: { run_id: 'run-2', status: 'failed', score: null, score_status: 'execution_failed', trace_id: 'trace-2', tokens: 100, error_type: 'timeout' },
        },
      },
      {
        case_id: 'case-002',
        candidates: {
          single: { run_id: 'run-3', status: 'completed', score: 0.4, score_status: 'scored', passed: false, trace_id: null, tokens: 350 },
          sequential: { run_id: 'run-4', status: 'completed', score_status: 'missing_score', missing_score: true, tokens: 300 },
        },
      },
      {
        case_id: 'case-003',
        candidates: {
          single: { run_id: 'run-5', status: 'completed', score_status: 'scoring_error', scoring_error: 'rubric failed', tokens: 250 },
          sequential: { run_id: 'run-6', status: 'completed', score: 0.95, score_status: 'scored', passed: true, trace_id: 'trace-6', tokens: 500 },
        },
      },
    ],
  }
}

test('短指纹只展示前缀，空值不伪造', () => {
  assert.equal(shortFingerprint('1111222233334444'), '11112222')
  assert.equal(shortFingerprint('1111222233334444', 12), '111122223333')
  assert.equal(shortFingerprint('abc'), 'abc')
  assert.equal(shortFingerprint(''), '—')
  assert.equal(shortFingerprint(null), '—')
  assert.equal(shortFingerprint(undefined), '—')
  assert.equal(shortFingerprint(12345678), '—')
})

test('百分比/分数/token/秒数格式化在缺失时返回破折号', () => {
  assert.equal(formatPercent(null), '—')
  assert.equal(formatPercent(undefined), '—')
  assert.equal(formatPercent(0), '0%')
  assert.equal(formatPercent(0.4), '40%')
  assert.equal(formatPercent(0.6667), '66.7%')
  assert.equal(formatPercent(1), '100%')
  assert.equal(formatPercent(85.7), '85.7%')

  assert.equal(formatScore(0.95), '0.95')
  assert.equal(formatScore(85), '85')
  assert.equal(formatScore(85.555), '85.56')
  assert.equal(formatScore(null), '—')

  assert.equal(formatTokens(1234), '1,234')
  assert.equal(formatTokens(0), '0')
  assert.equal(formatTokens(null), '—')

  assert.equal(formatSeconds(45.6), '45.60')
  assert.equal(formatSeconds(null), '—')
})

test('失败类型分布兼容对象/数组/字符串并稳定排序', () => {
  assert.deepEqual(normalizeFailureTypes({ timeout: 2, provider: 1 }), [
    { type: 'timeout', label: '超时', count: 2 },
    { type: 'provider', label: '模型服务错误', count: 1 },
  ])
  assert.deepEqual(normalizeFailureTypes(['timeout', 'timeout', 'rate_limit']), [
    { type: 'timeout', label: '超时', count: 2 },
    { type: 'rate_limit', label: '限流', count: 1 },
  ])
  assert.deepEqual(normalizeFailureTypes([{ type: 'auth', count: 3 }]), [
    { type: 'auth', label: '鉴权失败', count: 3 },
  ])
  assert.deepEqual(normalizeFailureTypes(null), [])
  assert.deepEqual(normalizeFailureTypes(''), [])
})

test('候选指标归一化：通过率分母固定为全部 case', () => {
  const metrics = normalizeCandidateMetrics({
    cases: 10,
    completed: 8,
    failed: 2,
    passed: 4,
    pass_rate_all_cases: 0.4,
    mean_score: 0.72,
    total_tokens: 1234,
    total_seconds: 45.6,
    trace_id_present: 7,
    failure_types: { timeout: 2, provider: 1 },
  })
  assert.equal(metrics.cases, 10)
  assert.equal(metrics.completed, 8)
  assert.equal(metrics.failed, 2)
  assert.equal(metrics.passed, 4)
  assert.equal(metrics.passRate, 0.4)
  assert.equal(metrics.passRateText, '40%')
  assert.equal(metrics.completionText, '8 / 10')
  assert.equal(metrics.meanScoreText, '0.72')
  assert.equal(metrics.totalTokensText, '1,234')
  assert.equal(metrics.totalSecondsText, '45.60')
  assert.equal(metrics.traceText, '7 / 10')
  assert.deepEqual(metrics.failureTypes.map(item => item.type), ['timeout', 'provider'])

  // 后端只给 passed 时，分母仍是全部 10 个 case，而不是 8 个完成项。
  const derived = normalizeCandidateMetrics({ cases: 10, completed: 8, failed: 2, passed: 3 })
  assert.equal(derived.passRate, 0.3)
  assert.equal(derived.passRateText, '30%')

  // 兼容后端直接返回 0–100 百分比。
  assert.equal(normalizeCandidateMetrics({ cases: 4, passed: 1, pass_rate_all_cases: 25 }).passRateText, '25%')

  assert.equal(normalizeCandidateMetrics({ cases: 2, trace_id_present: true }).traceText, '有')
  assert.equal(normalizeCandidateMetrics({ cases: 2, trace_id_present: false }).traceText, '无')
  assert.equal(normalizeCandidateMetrics({ cases: 2, trace_id_present: 2 }).traceText, '2 / 2')

  const empty = normalizeCandidateMetrics(null)
  assert.equal(empty.cases, null)
  assert.equal(empty.passRateText, '—')
  assert.equal(empty.completionText, '—')
  assert.equal(empty.traceText, '—')
  assert.deepEqual(empty.failureTypes, [])
})

test('单元格分类：失败/部分完成/缺失评分/评分失败绝不显示为通过', () => {
  assert.equal(classifyCaseCell({}).kind, 'no_run')
  assert.equal(classifyCaseCell({ status: 'failed', scoreValue: 1, passed: true }).kind, 'failed')
  assert.equal(classifyCaseCell({ status: 'partial', scoreValue: 1, passed: true }).kind, 'partial')
  assert.equal(classifyCaseCell({ status: 'completed', scoreValue: 0.8, passed: true }).kind, 'passed')
  assert.equal(classifyCaseCell({ status: 'completed', scoreValue: 0.2, passed: false }).kind, 'failed_score')
  assert.equal(classifyCaseCell({ status: 'completed', scoreValue: 0.8 }).kind, 'scored')
  assert.equal(classifyCaseCell({ status: 'completed', scoreStatus: 'missing_score', missingScore: true }).kind, 'missing_score')
  assert.equal(classifyCaseCell({ status: 'completed', scoreStatus: 'scoring_error' }).kind, 'scoring_error')
  assert.equal(classifyCaseCell({ status: 'completed', scoreStatus: 'judge_disabled' }).kind, 'judge_disabled')
  assert.equal(classifyCaseCell({ status: 'completed' }).kind, 'not_scored')
  assert.equal(classifyCaseCell({ status: 'weird' }).kind, 'unknown')

  assert.equal(CASE_CELL_META.passed.label, '通过')
  assert.equal(CASE_CELL_META.failed.label, '执行失败')
  assert.equal(CASE_CELL_META.missing_score.label, '缺失评分')
  assert.equal(CASE_CELL_META.scoring_error.label, '评分失败')
  assert.equal(CASE_CELL_META.no_run.label, '无运行')
})

test('实验详情归一化：候选指标、矩阵与单元格状态', () => {
  const view = normalizeExperimentDetail(detailPayload())
  assert.equal(view.experiment.experimentId, 'experiment-1')
  assert.equal(view.experiment.datasetId, 'dataset-v2')
  assert.equal(view.experiment.candidateCount, 2)
  assert.equal(view.hasCandidates, true)
  assert.equal(view.hasCases, true)
  assert.equal(view.hasRuns, true)

  assert.deepEqual(view.candidateIds, ['single', 'sequential'])
  assert.deepEqual(view.caseIds, ['case-001', 'case-002', 'case-003'])

  const single = view.candidates[0]
  assert.equal(single.shortFingerprint, '11112222')
  assert.equal(single.metrics.passed, 2)
  assert.equal(single.metrics.passRateText, '66.7%')
  assert.equal(single.metrics.totalTokensText, '1,200')
  assert.equal(single.metrics.traceText, '2 / 3')

  // 第二个候选没有 metrics，全部由 case 矩阵派生；失败/缺失评分不计为通过。
  const sequential = view.candidates[1]
  assert.equal(sequential.metrics.cases, 3)
  assert.equal(sequential.metrics.completed, 2)
  assert.equal(sequential.metrics.failed, 1)
  assert.equal(sequential.metrics.passed, 1)
  assert.equal(sequential.metrics.passRateText, '33.3%')
  assert.equal(sequential.metrics.meanScoreText, '0.95')
  assert.equal(sequential.metrics.totalTokensText, '900')
  assert.equal(sequential.metrics.traceText, '2 / 3')
  assert.deepEqual(sequential.metrics.failureTypes, [{ type: 'timeout', label: '超时', count: 1 }])

  assert.equal(view.matrix.rows[0].cells.single.kind, 'passed')
  assert.equal(view.matrix.rows[0].cells.sequential.kind, 'failed')
  assert.equal(view.matrix.rows[1].cells.single.kind, 'failed_score')
  assert.equal(view.matrix.rows[1].cells.sequential.kind, 'missing_score')
  assert.equal(view.matrix.rows[2].cells.single.kind, 'scoring_error')
  assert.equal(view.matrix.rows[2].cells.sequential.kind, 'passed')
})

test('矩阵构建保持候选顺序，缺失单元格显示无运行', () => {
  const matrix = buildCaseMatrix(
    [
      {
        caseId: 'case-x',
        cells: {
          single: normalizeCaseCell({ run_id: 'run-x', status: 'completed', score: 0.8, score_status: 'scored' }),
        },
      },
    ],
    [{ candidateId: 'single' }, { candidateId: 'sequential' }]
  )
  assert.deepEqual(matrix.candidateIds, ['single', 'sequential'])
  assert.deepEqual(matrix.caseIds, ['case-x'])
  assert.equal(matrix.rows[0].cells.single.kind, 'scored')
  assert.equal(matrix.rows[0].cells.sequential.kind, 'no_run')

  assert.deepEqual(buildCaseMatrix(null, null), { candidateIds: [], caseIds: [], rows: [] })
})

test('派生指标不会把 failed/partial 的分数或通过标记统计为成功', () => {
  const view = normalizeExperimentDetail({
    experiment: { experiment_id: 'experiment-tricky', name: 'tricky' },
    candidates: [{ candidate_id: 'c1', name: '候选 1', fingerprint: 'ffffffffffffffff' }],
    cases: [
      { case_id: 'a', candidates: { c1: { run_id: 'r1', status: 'failed', score: 1, passed: true, score_status: 'scored' } } },
      { case_id: 'b', candidates: { c1: { run_id: 'r2', status: 'partial', score: 1, passed: true, score_status: 'scored' } } },
      { case_id: 'c', candidates: { c1: { run_id: 'r3', status: 'completed', score_status: 'missing_score', missing_score: true } } },
    ],
  })
  const metrics = view.candidates[0].metrics
  assert.equal(metrics.cases, 3)
  assert.equal(metrics.completed, 1)
  assert.equal(metrics.passed, 0)
  assert.equal(metrics.passRate, 0)
  assert.equal(metrics.passRateText, '0%')
  assert.equal(metrics.meanScore, null)
  assert.equal(metrics.meanScoreText, '—')
})

test('证据归一化兼容契约扁平结构与后端 run 嵌套结构', () => {
  const flat = normalizeEvidence({
    experiment_id: 'experiment-1',
    candidate_id: 'single',
    case_id: 'case-001',
    fingerprint: '1111222233334444',
    run_id: 'run-1',
    trace_id: 'trace-1',
    request: {
      model: 'gpt-test',
      temperature: 0.2,
      max_tokens: 500,
      messages: [{ role: 'user', content: '请完成这个任务' }],
    },
    response: { content: '这是回答', model: 'gpt-test', finish_reason: 'stop' },
    usage: { prompt_tokens: 10, completion_tokens: 20, total_tokens: 30, usage_type: 'actual' },
    attempts: 2,
    score: { score: 0.9, passed: true },
    judge: { mode: 'llm', model: 'judge-test' },
    started_at: 100,
    completed_at: 102.5,
  })
  assert.equal(flat.experimentId, 'experiment-1')
  assert.equal(flat.candidateId, 'single')
  assert.equal(flat.caseId, 'case-001')
  assert.equal(flat.runId, 'run-1')
  assert.equal(flat.traceId, 'trace-1')
  assert.equal(flat.shortFingerprint, '11112222')
  assert.deepEqual(flat.request.messages, [{ role: 'user', content: '请完成这个任务' }])
  assert.equal(flat.request.model, 'gpt-test')
  assert.equal(flat.request.temperature, 0.2)
  assert.equal(flat.request.maxTokens, 500)
  assert.equal(flat.response.content, '这是回答')
  assert.equal(flat.response.finishReason, 'stop')
  assert.equal(flat.usage.totalTokens, 30)
  assert.equal(flat.usage.usageTypeLabel, '实际')
  assert.equal(flat.attempts, 2)
  assert.equal(flat.attemptsLabel, '2 次尝试')
  assert.equal(flat.score.value, 0.9)
  assert.equal(flat.score.passed, true)
  assert.equal(flat.scoreText, '0.9')
  assert.equal(flat.scoreStatus, '')
  assert.equal(flat.judge.mode, 'llm')
  assert.equal(flat.durationText, '2.50')

  const nested = normalizeEvidence({
    experiment_id: 'experiment-1',
    candidate_id: 'sequential',
    case_id: 'case-002',
    fingerprint: 'aaaabbbbccccdddd',
    run: {
      run_id: 'run-2',
      trace_id: 'trace-2',
      task_input: '保存的任务输入',
      final_result: '最终回答',
      total_tokens: 42,
      total_duration: 3.5,
      step_results: [
        {
          input_text: '步骤输入',
          output_text: '步骤输出',
          attempts: 3,
          model: 'step-model',
          finish_reason: 'stop',
          usage: { total_tokens: 42 },
          error_type: 'timeout',
        },
      ],
    },
    scoring: { score: 0.5, passed: false, status: 'scored' },
    judge: { mode: 'deterministic', status: 'scored' },
  })
  assert.equal(nested.runId, 'run-2')
  assert.equal(nested.traceId, 'trace-2')
  assert.deepEqual(nested.request.messages, [{ role: 'user', content: '步骤输入' }])
  assert.equal(nested.response.content, '最终回答')
  assert.equal(nested.response.model, 'step-model')
  assert.equal(nested.usage.totalTokens, 42)
  assert.equal(nested.attempts, 3)
  assert.equal(nested.attemptsLabel, '3 次尝试')
  assert.equal(nested.errorTypeLabel, '超时')
  assert.equal(nested.score.value, 0.5)
  assert.equal(nested.score.passed, false)
  assert.equal(nested.scoreStatus, 'scored')
  assert.equal(nested.scoreStatusLabel, '已评分')
  assert.equal(nested.judge.mode, 'deterministic')
  assert.equal(nested.judge.status, 'scored')
  assert.equal(nested.durationText, '3.50')

  const empty = normalizeEvidence(null)
  assert.equal(empty.runId, '')
  assert.equal(empty.traceId, '')
  assert.equal(empty.request.hasMessages, false)
  assert.equal(empty.response.hasContent, false)
  assert.equal(empty.attempts, null)
  assert.equal(empty.scoreText, '—')
  assert.equal(empty.durationText, '—')
})

test('实验列表与空状态归一化', () => {
  assert.deepEqual(normalizeExperimentList(null), [])
  assert.deepEqual(normalizeExperimentList({}), [])
  assert.deepEqual(normalizeExperimentList({ experiments: [{ name: '缺少 ID' }] }), [])

  const list = normalizeExperimentList({
    experiments: [
      { experiment_id: 'e1', name: '实验一', dataset_id: 'd1', candidate_count: 2, run_count: 6 },
    ],
  })
  assert.equal(list.length, 1)
  assert.equal(list[0].experimentId, 'e1')
  assert.equal(list[0].datasetVersion, '')
  assert.equal(list[0].candidateCount, 2)

  assert.equal(experimentListState({ experiments: [], loading: false, error: '' }), 'empty')
  assert.equal(experimentListState({ experiments: [], loading: true, error: '' }), 'loading')
  assert.equal(experimentListState({ experiments: [], loading: false, error: '网络错误' }), 'error')
  assert.equal(experimentListState({ experiments: [{ experimentId: 'e1' }], loading: false }), 'ready')
  assert.equal(experimentListState({ experiments: [{ experimentId: 'e1' }], loading: true }), 'ready')
  // 已有列表时刷新失败：保留列表，由界面用非阻塞提示展示错误。
  assert.equal(experimentListState({ experiments: [{ experimentId: 'e1' }], loading: false, error: '刷新失败' }), 'ready')
  assert.equal(formatPercent(undefined), '—')
})

test('空实验详情与空导出不伪造数据', () => {
  const empty = normalizeExperimentDetail(null)
  assert.equal(empty.hasCandidates, false)
  assert.equal(empty.hasCases, false)
  assert.equal(empty.hasRuns, false)
  assert.deepEqual(empty.candidates, [])
  assert.deepEqual(empty.matrix.rows, [])

  const payload = buildExperimentExportPayload(empty, EXPORTED_AT)
  assert.equal(payload.exported_at, '2026-01-02T03:04:05.000Z')
  assert.deepEqual(payload.candidates, [])
  assert.deepEqual(payload.cases, [])
  assert.deepEqual(payload.totals, { candidate_count: 0, case_count: 0 })
})

test('导出序列化包含实验、候选指标、矩阵判定与稳定时间戳', () => {
  const view = normalizeExperimentDetail(detailPayload())
  const payload = buildExperimentExportPayload(view, EXPORTED_AT)
  assert.equal(payload.exported_at, '2026-01-02T03:04:05.000Z')
  assert.equal(payload.experiment.experiment_id, 'experiment-1')
  assert.equal(payload.experiment.dataset_id, 'dataset-v2')
  assert.equal(payload.experiment.dataset_version, '2')
  assert.equal(payload.experiment.scorer_version, '2')
  assert.equal(payload.candidates.length, 2)
  assert.equal(payload.candidates[0].candidate_id, 'single')
  assert.equal(payload.candidates[0].fingerprint, '1111222233334444')
  assert.equal(payload.candidates[0].metrics.pass_rate_all_cases, 0.6667)
  assert.equal(payload.candidates[0].metrics.passed, 2)
  assert.equal(payload.candidates[1].metrics.passed, 1)
  assert.equal(payload.cases.length, 3)
  assert.equal(payload.cases[0].case_id, 'case-001')
  assert.equal(payload.cases[0].candidates.single.outcome, 'passed')
  assert.equal(payload.cases[0].candidates.sequential.outcome, 'failed')
  assert.equal(payload.cases[1].candidates.sequential.outcome, 'missing_score')
  assert.equal(payload.cases[2].candidates.single.outcome, 'scoring_error')
  assert.deepEqual(payload.totals, { candidate_count: 2, case_count: 3 })

  const text = serializeExperimentExport(view, EXPORTED_AT)
  assert.deepEqual(JSON.parse(text), payload)
  assert.equal(serializeExperimentExport(view, EXPORTED_AT), text)

  assert.match(experimentExportFileName({ experiment: { name: 'Demo Run', experimentId: 'experiment-1' } }, EXPORTED_AT), /^experiment-Demo-Run-\d{8}-\d{6}\.json$/)
  assert.match(experimentExportFileName({ experiment: { experimentId: 'experiment-abc' } }, EXPORTED_AT), /^experiment-abc-\d{8}-\d{6}\.json$/)
  assert.match(experimentExportFileName(null, EXPORTED_AT), /^experiment-comparison-\d{8}-\d{6}\.json$/)
})
