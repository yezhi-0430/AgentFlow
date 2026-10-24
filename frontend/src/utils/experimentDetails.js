/**
 * Harness²-lite 实验对比展示工具。
 *
 * 全部是纯函数：不访问网络、不写本地存储、不打印任何密钥。
 * 约束：
 * - 通过率的分母永远是“全部 case”，失败/部分完成/缺失评分绝不统计为通过；
 * - 后端字段缺失或形状变化时安全降级为“— / 未评分 / 无运行”，不伪造成功；
 * - 指纹、trace_id、证据内容只读展示，完整值由界面提供复制入口。
 */
import { errorTypeLabel, formatAttempts } from './runDetails.js'

/** case × 候选单元格的状态分类。 */
export const EXPERIMENT_CELL_KINDS = Object.freeze({
  passed: 'passed',
  failedScore: 'failed_score',
  scored: 'scored',
  failed: 'failed',
  partial: 'partial',
  stopped: 'stopped',
  running: 'running',
  pending: 'pending',
  missingScore: 'missing_score',
  scoringError: 'scoring_error',
  notScored: 'not_scored',
  judgeDisabled: 'judge_disabled',
  noRun: 'no_run',
  unknown: 'unknown',
})

/** 每种单元格状态对应的中文标签与色调（tone 由组件映射为样式）。 */
export const CASE_CELL_META = Object.freeze({
  passed: Object.freeze({ kind: 'passed', label: '通过', tone: 'success' }),
  failed_score: Object.freeze({ kind: 'failed_score', label: '未通过', tone: 'warning' }),
  scored: Object.freeze({ kind: 'scored', label: '已评分', tone: 'scored' }),
  failed: Object.freeze({ kind: 'failed', label: '执行失败', tone: 'error' }),
  partial: Object.freeze({ kind: 'partial', label: '部分完成', tone: 'warning' }),
  stopped: Object.freeze({ kind: 'stopped', label: '已停止', tone: 'neutral' }),
  running: Object.freeze({ kind: 'running', label: '运行中', tone: 'running' }),
  pending: Object.freeze({ kind: 'pending', label: '等待执行', tone: 'pending' }),
  missing_score: Object.freeze({ kind: 'missing_score', label: '缺失评分', tone: 'warning' }),
  scoring_error: Object.freeze({ kind: 'scoring_error', label: '评分失败', tone: 'error' }),
  not_scored: Object.freeze({ kind: 'not_scored', label: '未评分', tone: 'neutral' }),
  judge_disabled: Object.freeze({ kind: 'judge_disabled', label: '评分未开启', tone: 'neutral' }),
  no_run: Object.freeze({ kind: 'no_run', label: '无运行', tone: 'empty' }),
  unknown: Object.freeze({ kind: 'unknown', label: '未知状态', tone: 'unknown' }),
})

/** 评分状态 -> 中文标签。 */
export const SCORE_STATUS_LABELS = Object.freeze({
  scored: '已评分',
  missing_score: '缺失评分',
  scoring_error: '评分失败',
  judge_disabled: '评分未开启',
  not_scored: '未评分',
  execution_failed: '执行失败未评分',
})

const USAGE_TYPE_LABELS = Object.freeze({
  actual: '实际',
  estimated: '估算',
  partial: '部分',
  unknown: '未知',
})

const FAILED_STATUSES = new Set(['failed', 'error', 'cancelled'])
const RUNNING_STATUSES = new Set(['running', 'executing', 'stopping', 'started', 'pausing'])
const PENDING_STATUSES = new Set(['pending', 'created', 'idle', 'queued'])

function asObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : null
}

function toFiniteNumber(value) {
  if (value === null || value === undefined || value === '') return null
  // 布尔值不是指标数值，避免 true 被 Number() 当成 1 冒充 trace 数/通过数。
  if (typeof value === 'boolean') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function firstNumberOf(...values) {
  for (const value of values) {
    const number = toFiniteNumber(value)
    if (number !== null) return number
  }
  return null
}

function trimmedText(value) {
  return typeof value === 'string' ? value.trim() : ''
}

function lowerText(value) {
  return trimmedText(value).toLowerCase()
}

function metaOf(kind) {
  return CASE_CELL_META[kind] || CASE_CELL_META.unknown
}

/** 指纹过长时展示短码；空值返回 '—'。完整值由调用方通过 title/复制按钮提供。 */
export function shortFingerprint(fingerprint, length = 8) {
  const value = trimmedText(fingerprint)
  if (!value) return '—'
  const size = Math.max(4, Math.min(Number(length) || 8, 64))
  return value.length > size ? value.slice(0, size) : value
}

/** 0–1 比例格式化为百分比；兼容后端直接给出 0–100 的百分比数值。 */
export function formatPercent(ratio, unknown = '—') {
  const value = toFiniteNumber(ratio)
  if (value === null) return unknown
  const percent = value > 1 && value <= 100 ? value : value * 100
  return `${Number(percent.toFixed(1))}%`
}

/** 分数展示：保留最多两位小数，整数不补 0。 */
export function formatScore(value, unknown = '—') {
  const number = toFiniteNumber(value)
  if (number === null) return unknown
  return String(Math.round(number * 100) / 100)
}

/** token 数展示：千分位；空值返回 '—'。 */
export function formatTokens(value, unknown = '—') {
  const number = toFiniteNumber(value)
  if (number === null) return unknown
  const integer = Math.trunc(number)
  return String(integer).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

/** 秒数展示：与运行详情一致保留两位小数。 */
export function formatSeconds(value, unknown = '—') {
  const number = toFiniteNumber(value)
  return number === null ? unknown : number.toFixed(2)
}

function formatCount(value, unknown = '—') {
  const number = toFiniteNumber(value)
  return number === null ? unknown : String(Math.trunc(number))
}

/**
 * 失败类型分布归一化：兼容 {"timeout":2}、[{type,count}]、["timeout"] 三种形状。
 * 结果按次数降序、类型名升序稳定排序。
 */
export function normalizeFailureTypes(value) {
  const counter = new Map()
  const bump = (type, count) => {
    const key = trimmedText(type)
    if (!key) return
    counter.set(key, (counter.get(key) || 0) + Math.max(1, Math.trunc(count || 1)))
  }

  if (Array.isArray(value)) {
    for (const item of value) {
      if (typeof item === 'string') {
        bump(item, 1)
      } else if (asObject(item)) {
        bump(item.type || item.error_type || item.name, item.count || item.value || 1)
      }
    }
  } else if (asObject(value)) {
    for (const [type, count] of Object.entries(value)) bump(type, count)
  }

  return [...counter.entries()]
    .map(([type, count]) => ({ type, label: errorTypeLabel(type), count }))
    .sort((left, right) => right.count - left.count || left.type.localeCompare(right.type))
}

/**
 * 候选指标归一化。
 *
 * 后端契约字段：cases / completed / failed / passed / pass_rate_all_cases /
 * mean_score / total_tokens / total_seconds / trace_id_present / failure_types。
 * fallback 由 case 矩阵派生，仅在字段缺失时使用；通过率分母始终是全部 case。
 */
export function normalizeCandidateMetrics(metrics, fallback = {}) {
  const raw = asObject(metrics) || {}

  const cases = firstNumberOf(raw.cases, raw.case_count, raw.total_cases, fallback.cases)
  const completed = firstNumberOf(raw.completed, raw.completed_count, fallback.completed)
  const failed = firstNumberOf(raw.failed, raw.failed_count, fallback.failed)
  const passed = firstNumberOf(raw.passed, raw.passed_count, fallback.passed)

  let passRate = firstNumberOf(raw.pass_rate_all_cases, raw.passRateAllCases, raw.pass_rate)
  if (passRate === null && passed !== null && cases !== null && cases > 0) {
    passRate = passed / cases
  }

  const meanScore = firstNumberOf(raw.mean_score, fallback.meanScore)
  const totalTokens = firstNumberOf(raw.total_tokens, raw.tokens, fallback.totalTokens)
  const totalSeconds = firstNumberOf(raw.total_seconds, raw.total_duration, fallback.totalSeconds)

  const traceNumber = firstNumberOf(raw.trace_id_present, raw.trace_id_present_count, raw.trace_count, fallback.traceCount)
  const traceFlag = typeof raw.trace_id_present === 'boolean' ? raw.trace_id_present : null
  const traceText = traceNumber !== null
    ? (cases !== null ? `${formatCount(traceNumber)} / ${formatCount(cases)}` : formatCount(traceNumber))
    : (traceFlag === null ? '—' : (traceFlag ? '有' : '无'))

  const failureTypes = normalizeFailureTypes(raw.failure_types ?? raw.failureTypes ?? fallback.failureTypes)

  return {
    cases,
    completed,
    failed,
    passed,
    passRate,
    meanScore,
    totalTokens,
    totalSeconds,
    traceCount: traceNumber,
    traceIdPresent: traceFlag,
    failureTypes,
    casesText: formatCount(cases),
    completedText: formatCount(completed),
    failedText: formatCount(failed),
    passedText: formatCount(passed),
    passRateText: formatPercent(passRate),
    meanScoreText: formatScore(meanScore),
    totalTokensText: formatTokens(totalTokens),
    totalSecondsText: formatSeconds(totalSeconds),
    traceText,
    completionText: cases === null
      ? formatCount(completed)
      : `${formatCount(completed)} / ${formatCount(cases)}`,
  }
}

/**
 * 单元格状态分类。执行失败/部分完成/已停止优先于评分字段，
 * 即使后端意外带回分数也不会显示为“通过”。
 */
export function classifyCaseCell(cell = {}) {
  const status = lowerText(cell.status)
  const scoreStatus = lowerText(cell.scoreStatus ?? cell.score_status)
  const runId = trimmedText(cell.runId ?? cell.run_id)
  const scoreValue = cell.scoreValue !== undefined
    ? toFiniteNumber(cell.scoreValue)
    : toFiniteNumber(cell.score)
  const hasScore = scoreValue !== null
  const passed = typeof cell.passed === 'boolean' ? cell.passed : null

  if (!runId && !status && !hasScore && !scoreStatus) return metaOf('no_run')
  if (FAILED_STATUSES.has(status)) return metaOf('failed')
  if (status === 'stopped') return metaOf('stopped')
  if (status === 'partial') return metaOf('partial')
  if (RUNNING_STATUSES.has(status)) return metaOf('running')
  if (PENDING_STATUSES.has(status)) return metaOf('pending')
  if (status && status !== 'completed') return metaOf('unknown')

  if (scoreStatus === 'missing_score' || cell.missingScore === true) return metaOf('missing_score')
  if (scoreStatus === 'scoring_error') return metaOf('scoring_error')
  if (scoreStatus === 'judge_disabled') return metaOf('judge_disabled')
  if (scoreStatus === 'execution_failed') return metaOf('failed')
  if (scoreStatus === 'not_scored') return metaOf('not_scored')

  if (hasScore) {
    if (passed === true) return metaOf('passed')
    if (passed === false) return metaOf('failed_score')
    return metaOf('scored')
  }
  if (passed === true) return metaOf('passed')
  return metaOf('not_scored')
}

/** 单元格归一化：保留原始展示/跳转字段，并附加分类标签。 */
export function normalizeCaseCell(cell) {
  const raw = asObject(cell) || {}
  const scoreSource = raw.score
  const scoreObject = asObject(scoreSource)
  const scoreValue = scoreObject ? toFiniteNumber(scoreObject.score ?? scoreObject.value) : toFiniteNumber(scoreSource)
  const passed = typeof raw.passed === 'boolean'
    ? raw.passed
    : (typeof scoreObject?.passed === 'boolean' ? scoreObject.passed : null)
  const errorType = trimmedText(raw.error_type ?? raw.errorType)
  const scoreStatus = trimmedText(raw.score_status ?? raw.scoreStatus)

  const normalized = {
    runId: trimmedText(raw.run_id ?? raw.runId),
    status: trimmedText(raw.status),
    scoreStatus,
    scoreValue,
    passed,
    missingScore: raw.missing_score === true,
    traceId: trimmedText(raw.trace_id ?? raw.traceId),
    evidenceRef: trimmedText(raw.evidence_ref ?? raw.evidenceRef),
    tokens: firstNumberOf(raw.tokens, raw.total_tokens),
    errorType,
    errorTypeLabel: errorTypeLabel(errorType),
    error: trimmedText(raw.error),
    scoreText: scoreValue === null ? '' : formatScore(scoreValue),
    scoreStatusLabel: SCORE_STATUS_LABELS[scoreStatus] || scoreStatus,
  }

  const meta = classifyCaseCell(normalized)
  return {
    ...normalized,
    kind: meta.kind,
    label: meta.label,
    tone: meta.tone,
    hasRun: Boolean(normalized.runId),
    hasScore: scoreValue !== null,
  }
}

/** 构造 case × 候选矩阵；缺失的候选单元格显示为“无运行”。 */
export function buildCaseMatrix(cases, candidates) {
  const caseList = Array.isArray(cases) ? cases : []
  const candidateIds = (Array.isArray(candidates) ? candidates : [])
    .map(candidate => trimmedText(candidate?.candidateId))
    .filter(Boolean)

  const rows = caseList.map(item => {
    const sourceCells = asObject(item?.cells) || {}
    const cells = {}
    for (const candidateId of candidateIds) {
      cells[candidateId] = sourceCells[candidateId] || normalizeCaseCell(null)
    }
    return { caseId: trimmedText(item?.caseId), cells }
  })

  return {
    candidateIds,
    caseIds: rows.map(row => row.caseId),
    rows,
  }
}

/** 实验摘要归一化（列表与详情共用）。 */
export function normalizeExperimentSummary(raw) {
  const value = asObject(raw) || {}
  return {
    experimentId: trimmedText(value.experiment_id ?? value.experimentId ?? value.id),
    name: trimmedText(value.name) || '未命名实验',
    datasetId: trimmedText(value.dataset_id ?? value.datasetId),
    datasetVersion: trimmedText(value.dataset_version ?? value.datasetVersion),
    scorerId: trimmedText(value.scorer_id ?? value.scorerId),
    scorerVersion: trimmedText(value.scorer_version ?? value.scorerVersion),
    createdAt: toFiniteNumber(value.created_at ?? value.createdAt),
    candidateCount: toFiniteNumber(value.candidate_count ?? value.candidateCount),
    runCount: toFiniteNumber(value.run_count ?? value.runCount),
    notes: trimmedText(value.notes),
  }
}

/** GET /api/experiments 的响应归一化；null/异常结构返回空数组。 */
export function normalizeExperimentList(payload) {
  const items = Array.isArray(payload)
    ? payload
    : (Array.isArray(payload?.experiments) ? payload.experiments : [])
  return items
    .map(normalizeExperimentSummary)
    .filter(experiment => Boolean(experiment.experimentId))
}

/** 列表空状态判定：loading / error / empty / ready。已加载列表时刷新失败保留列表。 */
export function experimentListState({ experiments, loading, error } = {}) {
  const items = Array.isArray(experiments) ? experiments : []
  if (error && !items.length) return 'error'
  if (loading && !items.length) return 'loading'
  if (!items.length) return 'empty'
  return 'ready'
}

function deriveCandidateFallback(matrix, candidateId) {
  if (!matrix || !Array.isArray(matrix.rows) || !matrix.rows.length) return {}
  const stats = {
    cases: matrix.rows.length,
    completed: 0,
    failed: 0,
    passed: 0,
    scoreSum: 0,
    scoreCount: 0,
    tokens: 0,
    traceCount: 0,
    failureTypes: {},
  }
  let hasPassedInfo = false

  for (const row of matrix.rows) {
    const cell = row.cells[candidateId]
    if (!cell) continue
    const status = lowerText(cell.status)
    if (status === 'completed') stats.completed += 1
    if (FAILED_STATUSES.has(status)) {
      stats.failed += 1
      if (cell.errorType) stats.failureTypes[cell.errorType] = (stats.failureTypes[cell.errorType] || 0) + 1
    }
    if (typeof cell.passed === 'boolean') hasPassedInfo = true
    if (status === 'completed' && cell.passed === true) stats.passed += 1
    // 失败/部分完成的分数不计入派生平均分，避免把未成功的执行算成质量。
    if (status === 'completed' && cell.scoreValue !== null && cell.scoreValue !== undefined) {
      stats.scoreSum += cell.scoreValue
      stats.scoreCount += 1
    }
    if (cell.tokens !== null && cell.tokens !== undefined) stats.tokens += cell.tokens
    if (cell.traceId) stats.traceCount += 1
  }

  return {
    cases: stats.cases,
    completed: stats.completed,
    failed: stats.failed,
    passed: hasPassedInfo ? stats.passed : null,
    meanScore: stats.scoreCount ? stats.scoreSum / stats.scoreCount : null,
    totalTokens: stats.tokens || null,
    traceCount: stats.traceCount,
    failureTypes: stats.failureTypes,
  }
}

function normalizeCandidate(raw) {
  const value = asObject(raw) || {}
  const fingerprint = trimmedText(value.fingerprint)
  return {
    candidateId: trimmedText(value.candidate_id ?? value.candidateId),
    name: trimmedText(value.name) || trimmedText(value.candidate_id ?? value.candidateId) || '未命名候选',
    fingerprint,
    shortFingerprint: shortFingerprint(fingerprint),
    config: asObject(value.config) || {},
    rawMetrics: asObject(value.metrics) || {},
  }
}

/**
 * GET /api/experiments/{id}（或 /report）响应归一化。
 * 返回 {experiment, candidates, cases, matrix, ...}；metrics 缺失时由矩阵派生。
 */
export function normalizeExperimentDetail(payload) {
  const raw = asObject(payload) || {}
  const experiment = normalizeExperimentSummary(raw.experiment ?? raw)
  const candidateList = (Array.isArray(raw.candidates) ? raw.candidates : [])
    .map(normalizeCandidate)
    .filter(candidate => Boolean(candidate.candidateId))

  const caseList = (Array.isArray(raw.cases) ? raw.cases : []).map(item => {
    const value = asObject(item) || {}
    const rawCells = asObject(value.candidates) || asObject(value.cells) || {}
    const cells = {}
    for (const [candidateId, cell] of Object.entries(rawCells)) {
      cells[trimmedText(candidateId)] = normalizeCaseCell(cell)
    }
    return {
      caseId: trimmedText(value.case_id ?? value.caseId),
      cells,
    }
  })

  const matrix = buildCaseMatrix(caseList, candidateList)
  const candidates = candidateList.map(candidate => {
    const fallback = deriveCandidateFallback(matrix, candidate.candidateId)
    return {
      ...candidate,
      metrics: normalizeCandidateMetrics(candidate.rawMetrics, fallback),
    }
  })

  const hasRuns = matrix.rows.some(row => matrix.candidateIds.some(candidateId => row.cells[candidateId]?.hasRun))

  return {
    experiment,
    candidates,
    cases: matrix.rows,
    matrix,
    candidateIds: matrix.candidateIds,
    caseIds: matrix.caseIds,
    hasCandidates: candidates.length > 0,
    hasCases: matrix.rows.length > 0,
    hasRuns,
  }
}

function normalizeMessages(value) {
  if (typeof value === 'string') {
    const content = value.trim()
    return content ? [{ role: 'user', content }] : []
  }
  if (!Array.isArray(value)) return []
  return value
    .map(item => {
      if (typeof item === 'string') return { role: 'user', content: item }
      const message = asObject(item)
      if (!message) return null
      const content = typeof message.content === 'string'
        ? message.content
        : (message.content === null || message.content === undefined ? '' : JSON.stringify(message.content))
      if (!content) return null
      return { role: trimmedText(message.role) || 'user', content }
    })
    .filter(Boolean)
}

function normalizeScore(source) {
  if (source === null || source === undefined || source === '') return null
  if (typeof source !== 'object') {
    const value = toFiniteNumber(source)
    return value === null ? null : { value, passed: null, details: null }
  }
  const value = asObject(source)
  const numeric = toFiniteNumber(value.score ?? value.value)
  const passed = typeof value.passed === 'boolean' ? value.passed : null
  if (numeric === null && passed === null) return null
  return { value: numeric, passed, details: value }
}

function normalizeJudge(source) {
  const value = asObject(source)
  if (!value || !Object.keys(value).length) return null
  return {
    mode: trimmedText(value.mode ?? value.judge_mode ?? value.judgeMode),
    model: trimmedText(value.model ?? value.judge_model),
    status: trimmedText(value.status),
    details: value,
  }
}

function normalizeUsage(source, fallbackTotal) {
  const value = asObject(source) || {}
  const promptTokens = firstNumberOf(value.prompt_tokens, value.promptTokens)
  const completionTokens = firstNumberOf(value.completion_tokens, value.completionTokens)
  let totalTokens = firstNumberOf(value.total_tokens, value.totalTokens, fallbackTotal)
  if (totalTokens === null && (promptTokens !== null || completionTokens !== null)) {
    totalTokens = (promptTokens || 0) + (completionTokens || 0)
  }
  const usageType = trimmedText(value.usage_type ?? value.usageType)
  return {
    promptTokens,
    completionTokens,
    totalTokens,
    usageType,
    usageTypeLabel: USAGE_TYPE_LABELS[usageType] || usageType,
    hasUsage: promptTokens !== null || completionTokens !== null || totalTokens !== null,
  }
}

/**
 * 证据归一化（GET /api/evidence/{run_id}）。
 * 兼容两种形状：
 * 1) 契约扁平形状：request/response/usage/attempts/error/score/judge；
 * 2) 后端落盘形状：run（WorkflowRun.to_dict）+ scoring + judge。
 */
export function normalizeEvidence(payload) {
  const evidence = asObject(payload) || {}
  const run = asObject(evidence.run) || {}
  const request = asObject(evidence.request) || {}
  const responseValue = evidence.response
  const response = asObject(responseValue) || {}
  const steps = Array.isArray(run.step_results) ? run.step_results.filter(asObject) : []
  const firstStep = steps[0] || {}
  const lastStep = steps.length ? steps[steps.length - 1] : {}

  const runId = trimmedText(evidence.run_id ?? run.run_id)
  const traceId = trimmedText(evidence.trace_id ?? run.trace_id)
  const fingerprint = trimmedText(evidence.fingerprint ?? run.fingerprint)
  const experimentId = trimmedText(evidence.experiment_id ?? run.experiment_id)
  const candidateId = trimmedText(evidence.candidate_id ?? run.candidate_id)
  const caseId = trimmedText(evidence.case_id ?? run.case_id)

  let messages = normalizeMessages(
    request.messages
      ?? evidence.request_messages
      ?? evidence.messages
      ?? (typeof evidence.request === 'string' ? evidence.request : undefined)
  )
  if (!messages.length && trimmedText(firstStep.input_text)) {
    messages = [{ role: 'user', content: trimmedText(firstStep.input_text) }]
  }
  if (!messages.length && trimmedText(run.task_input)) {
    messages = [{ role: 'user', content: trimmedText(run.task_input) }]
  }

  let responseContent = trimmedText(responseValue)
  if (!responseContent) responseContent = trimmedText(response.content)
  if (!responseContent) responseContent = trimmedText(run.final_result)
  if (!responseContent) responseContent = trimmedText(lastStep.output_text ?? lastStep.output)

  const responseModel = trimmedText(response.model) || trimmedText(lastStep.model)
  const finishReason = trimmedText(response.finish_reason) || trimmedText(lastStep.finish_reason)

  const stepTokenTotal = steps.reduce((total, step) => {
    const stepTotal = firstNumberOf(step?.usage?.total_tokens)
    return total + (stepTotal || 0)
  }, 0)
  // 后端证据把 usage 放在 run.step_results[*].usage；按步骤聚合 prompt/completion，
  // 避免证据抽屉里只有 total 而 prompt/completion 显示为空。
  const aggregatedStepUsage = steps.reduce((acc, step) => {
    const stepUsage = asObject(step?.usage)
    if (step?.usage_type) acc.usage_type = step.usage_type
    if (!stepUsage) return acc
    const prompt = firstNumberOf(stepUsage.prompt_tokens)
    const completion = firstNumberOf(stepUsage.completion_tokens)
    if (prompt !== null) acc.prompt_tokens = (acc.prompt_tokens || 0) + prompt
    if (completion !== null) acc.completion_tokens = (acc.completion_tokens || 0) + completion
    return acc
  }, {})
  const usageSource = Object.keys(aggregatedStepUsage).length ? aggregatedStepUsage : evidence.usage
  const usage = normalizeUsage(
    usageSource,
    firstNumberOf(run.total_tokens, evidence.total_tokens, stepTokenTotal || null)
  )

  const stepAttempts = steps.reduce((max, step) => Math.max(max, firstNumberOf(step?.attempts) || 0), 0)
  const attempts = firstNumberOf(evidence.attempts, run.attempts, stepAttempts || null)

  const failedStep = steps.find(step => trimmedText(step.error) || trimmedText(step.error_type))
  const error = trimmedText(evidence.error) || trimmedText(run.error) || trimmedText(failedStep?.error)
  const errorType = trimmedText(evidence.error_type) || trimmedText(run.error_type) || trimmedText(failedStep?.error_type)

  const scoringSource = evidence.scoring ?? evidence.score ?? (Object.prototype.hasOwnProperty.call(run, 'score') ? run : null)
  const score = normalizeScore(scoringSource)
  const scoringObject = asObject(evidence.scoring)
  // 后端评分结果可能用 status / score_status 两种字段名（rubric 与独立 judge 一致）。
  const scoreStatus = trimmedText(
    evidence.score_status
      ?? run.score_status
      ?? scoringObject?.score_status
      ?? scoringObject?.status
  )

  const judge = normalizeJudge(evidence.judge ?? asObject(evidence.scoring)?.judge)

  const startedAt = firstNumberOf(evidence.started_at, run.started_at)
  const completedAt = firstNumberOf(evidence.completed_at, run.completed_at)
  let duration = firstNumberOf(evidence.duration, run.total_duration, evidence.elapsed_seconds)
  if (duration === null && startedAt !== null && completedAt !== null) duration = completedAt - startedAt

  return {
    evidenceSchemaVersion: firstNumberOf(evidence.evidence_schema_version),
    experimentId,
    candidateId,
    caseId,
    fingerprint,
    shortFingerprint: shortFingerprint(fingerprint),
    runId,
    traceId,
    dataset: asObject(evidence.dataset) || {},
    scorer: asObject(evidence.scorer) || {},
    request: {
      model: trimmedText(request.model) || trimmedText(firstStep.model),
      temperature: firstNumberOf(request.temperature),
      maxTokens: firstNumberOf(request.max_tokens, request.maxTokens),
      messages,
      hasMessages: messages.length > 0,
    },
    response: {
      content: responseContent,
      model: responseModel,
      finishReason,
      hasContent: Boolean(responseContent),
    },
    usage,
    attempts: attempts === null ? null : Math.trunc(attempts),
    attemptsLabel: attempts === null ? '' : formatAttempts(attempts),
    error,
    errorType,
    errorTypeLabel: errorTypeLabel(errorType),
    score,
    scoreText: score?.value === null || score?.value === undefined ? '—' : formatScore(score.value),
    scoreStatus,
    scoreStatusLabel: SCORE_STATUS_LABELS[scoreStatus] || scoreStatus,
    judge,
    startedAt,
    completedAt,
    duration,
    durationText: formatSeconds(duration),
  }
}

/**
 * 导出当前实验对比为 JSON 载荷。
 * 保留后端的实验/候选/矩阵结构，并附加每个单元格的归一化判定（outcome），
 * 便于离线核对“通过/失败/缺失评分”没有被混淆。
 */
export function buildExperimentExportPayload(view, exportedAt = Date.now()) {
  const detail = asObject(view) || {}
  const experiment = normalizeExperimentSummary(detail.experiment)
  const candidates = Array.isArray(detail.candidates) ? detail.candidates : []
  const rows = Array.isArray(detail.matrix?.rows)
    ? detail.matrix.rows
    : (Array.isArray(detail.cases) ? detail.cases : [])
  const candidateIds = Array.isArray(detail.candidateIds) && detail.candidateIds.length
    ? detail.candidateIds
    : candidates.map(candidate => candidate.candidateId)

  return {
    exported_at: new Date(exportedAt).toISOString(),
    experiment: {
      experiment_id: experiment.experimentId,
      name: experiment.name,
      dataset_id: experiment.datasetId,
      dataset_version: experiment.datasetVersion,
      scorer_id: experiment.scorerId,
      scorer_version: experiment.scorerVersion,
      created_at: experiment.createdAt,
      candidate_count: experiment.candidateCount,
      run_count: experiment.runCount,
    },
    candidates: candidates.map(candidate => ({
      candidate_id: candidate.candidateId,
      name: candidate.name,
      fingerprint: candidate.fingerprint,
      metrics: {
        cases: candidate.metrics?.cases ?? null,
        completed: candidate.metrics?.completed ?? null,
        failed: candidate.metrics?.failed ?? null,
        passed: candidate.metrics?.passed ?? null,
        pass_rate_all_cases: candidate.metrics?.passRate ?? null,
        mean_score: candidate.metrics?.meanScore ?? null,
        total_tokens: candidate.metrics?.totalTokens ?? null,
        total_seconds: candidate.metrics?.totalSeconds ?? null,
        trace_id_present: candidate.metrics?.traceCount ?? null,
        failure_types: candidate.metrics?.failureTypes || [],
      },
      config: asObject(candidate.config) || {},
    })),
    cases: rows.map(row => ({
      case_id: row.caseId,
      candidates: Object.fromEntries(candidateIds.map(candidateId => {
        const cell = row.cells?.[candidateId] || normalizeCaseCell(null)
        return [candidateId, {
          run_id: cell.runId || null,
          status: cell.status || null,
          score: cell.scoreValue,
          score_status: cell.scoreStatus || null,
          passed: cell.passed,
          outcome: cell.kind,
          trace_id: cell.traceId || null,
          evidence_ref: cell.evidenceRef || null,
          tokens: cell.tokens,
          error_type: cell.errorType || null,
        }]
      })),
    })),
    totals: {
      candidate_count: candidates.length,
      case_count: rows.length,
    },
  }
}

export function serializeExperimentExport(view, exportedAt = Date.now()) {
  return JSON.stringify(buildExperimentExportPayload(view, exportedAt), null, 2)
}

/** 导出文件名：experiment-<名称或 ID>-<本地时间戳>.json。 */
export function experimentExportFileName(view, exportedAt = Date.now()) {
  const experiment = asObject(view?.experiment) || {}
  const label = trimmedText(experiment.name) || trimmedText(experiment.experimentId).replace(/^experiment-/, '') || 'comparison'
  const slug = label
    .replace(/[^\p{L}\p{N}_.-]+/gu, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40)
  const date = new Date(exportedAt)
  const pad = value => String(value).padStart(2, '0')
  const stamp = `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`
  return `experiment-${slug || 'comparison'}-${stamp}.json`
}
