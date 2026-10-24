<template>
  <div class="experiment-panel">
    <button
      class="rail-button"
      :class="{ 'is-on': isOpen }"
      title="实验对比 · 候选配置、通过率与执行证据"
      aria-label="打开实验对比"
      @click="toggle"
    >
      <AppIcon name="experiment" />
      <span class="nav-label">实验对比</span>
      <span class="nav-count">{{ experiments.length }}</span>
    </button>

    <div v-if="isOpen" class="experiment-sidebar" role="dialog" aria-modal="true" aria-label="实验对比面板">
      <header class="experiment-header">
        <div class="experiment-heading">
          <span class="eyebrow">HARNESS²-LITE</span>
          <h2>{{ activeRunId ? '运行详情' : '实验对比' }}</h2>
          <p>{{ activeRunId ? '复用运行详情查看本次 case 的完整步骤与用量。' : '配置指纹 · 脱敏证据 · 独立评分 · 候选对比' }}</p>
        </div>
        <div class="experiment-header-actions">
          <template v-if="activeRunId">
            <button class="btn btn-secondary" type="button" @click="closeRunDetail"><AppIcon name="chevron" :size="13" />返回对比</button>
          </template>
          <template v-else>
            <button v-if="store.selectedId" class="btn btn-quiet" type="button" @click="backToList">实验列表</button>
            <button class="btn btn-secondary" type="button" :disabled="store.listLoading || store.detailLoading" @click="refreshAll">
              <AppIcon name="refresh" :size="14" />{{ store.listLoading || store.detailLoading ? '刷新中…' : '刷新' }}
            </button>
            <button class="btn btn-secondary" type="button" :disabled="!view || !view.hasCandidates" @click="exportComparison">
              <AppIcon name="download" :size="14" />导出 JSON
            </button>
          </template>
          <button class="icon-button" type="button" aria-label="关闭实验对比" @click="close"><AppIcon name="close" :size="18" /></button>
        </div>
      </header>

      <div ref="body" class="experiment-body">
        <div v-if="exportNotice" class="export-notice" role="status">{{ exportNotice }}</div>
        <div v-if="store.listError && experiments.length" class="export-notice is-error" role="status">{{ store.listError }}</div>

        <template v-if="activeRunId">
          <section class="experiment-run-detail" aria-label="运行详情">
            <RunDetail :run-id="activeRunId" @close="closeRunDetail" />
          </section>
        </template>

        <template v-else>
          <div v-if="listState === 'loading'" class="state-block">正在加载实验列表…</div>

          <div v-else-if="listState === 'error'" class="state-block is-error">
            <p>{{ store.listError }}</p>
            <button class="btn btn-secondary" type="button" @click="refreshAll">重试</button>
          </div>

          <div v-else-if="listState === 'empty'" class="empty-state">
            <span class="eyebrow">HARNESS²-LITE</span>
            <h3>还没有实验记录</h3>
            <p>实验对比用于回答“同一组任务下哪套配置更好”：每个候选都带配置指纹，每个 case 保存脱敏证据，通过率的分母固定为全部 case。</p>
            <p class="empty-hint">运行一次 Harness²-lite 实验并写入实验 / 候选 / 运行记录后，这里会显示候选对比表、case × 候选矩阵和证据入口。失败与缺失评分不会被统计为通过。</p>
            <button class="btn btn-secondary" type="button" :disabled="store.listLoading" @click="refreshAll">重新加载</button>
          </div>

          <section v-else-if="!store.selectedId" aria-label="实验列表">
            <p class="list-intro">选择一个实验，查看候选对比、case 矩阵与执行证据。</p>
            <div class="table-scroll">
              <table class="experiment-table">
                <thead>
                  <tr>
                    <th>实验</th>
                    <th>数据集</th>
                    <th>评分器</th>
                    <th>候选</th>
                    <th>运行数</th>
                    <th>创建时间</th>
                    <th class="col-open"></th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="experiment in experiments" :key="experiment.experimentId" class="experiment-row" @click="openExperiment(experiment)">
                    <td>
                      <strong>{{ experiment.name }}</strong>
                      <code :title="experiment.experimentId">{{ truncateId(experiment.experimentId, 20) }}</code>
                    </td>
                    <td>
                      <span>{{ experiment.datasetId || '—' }}</span>
                      <small v-if="experiment.datasetVersion">v{{ experiment.datasetVersion }}</small>
                    </td>
                    <td>
                      <span v-if="experiment.scorerVersion">v{{ experiment.scorerVersion }}</span>
                      <span v-else>{{ experiment.scorerId || '—' }}</span>
                    </td>
                    <td>{{ experiment.candidateCount ?? '—' }}</td>
                    <td>{{ experiment.runCount ?? '—' }}</td>
                    <td>{{ experiment.createdAt === null ? '—' : formatTimestamp(experiment.createdAt) }}</td>
                    <td class="col-open"><AppIcon name="chevron" :size="14" /></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <template v-else>
            <div v-if="store.detailLoading" class="state-block">正在加载实验对比…</div>

            <div v-else-if="store.detailError" class="state-block is-error">
              <p>{{ store.detailError }}</p>
              <button class="btn btn-secondary" type="button" @click="refreshAll">重试</button>
            </div>

            <template v-else-if="view">
              <section class="experiment-summary" aria-label="实验信息">
                <div>
                  <button class="back-link" type="button" @click="backToList">← 全部实验</button>
                  <h3>{{ view.experiment.name }}</h3>
                  <div class="meta-chips">
                    <span v-if="view.experiment.datasetId">数据集 <code>{{ view.experiment.datasetId }}</code><template v-if="view.experiment.datasetVersion"> · v{{ view.experiment.datasetVersion }}</template></span>
                    <span v-if="view.experiment.scorerVersion">评分器 v{{ view.experiment.scorerVersion }}</span>
                    <span v-if="view.experiment.createdAt !== null">创建 {{ formatTimestamp(view.experiment.createdAt) }}</span>
                    <span>候选 {{ view.candidates.length }}</span>
                    <span>case {{ view.matrix.rows.length }}</span>
                  </div>
                </div>
                <p class="summary-note">通过率 = 通过数 / 全部 case；失败、部分完成与缺失评分不计为通过。</p>
              </section>

              <div v-if="!view.hasCandidates" class="state-block">该实验还没有候选配置。</div>

              <template v-else>
                <section class="experiment-section" aria-label="候选对比">
                  <h4>候选对比</h4>
                  <div class="table-scroll">
                    <table class="candidate-table">
                      <thead>
                        <tr>
                          <th>候选配置</th>
                          <th>指纹</th>
                          <th>完成数</th>
                          <th>通过率</th>
                          <th>平均分</th>
                          <th>Token</th>
                          <th>耗时</th>
                          <th>Trace</th>
                          <th>失败类型</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="candidate in view.candidates" :key="candidate.candidateId">
                          <td class="candidate-cell">
                            <strong>{{ candidate.name }}</strong>
                            <code :title="candidate.candidateId">{{ truncateId(candidate.candidateId, 16) }}</code>
                          </td>
                          <td>
                            <button
                              v-if="candidate.fingerprint"
                              class="fingerprint-copy"
                              type="button"
                              :title="'点击复制完整配置指纹：' + candidate.fingerprint"
                              @click="copyValue(candidate.fingerprint, '配置指纹')"
                            >{{ candidate.shortFingerprint }}</button>
                            <span v-else class="muted">—</span>
                            <span v-if="copiedValue && copiedValue === candidate.fingerprint" class="copied">已复制</span>
                          </td>
                          <td>{{ candidate.metrics.completionText }}</td>
                          <td>
                            <strong class="pass-rate">{{ candidate.metrics.passRateText }}</strong>
                            <small v-if="candidate.metrics.passedText !== '—'" class="cell-note">{{ candidate.metrics.passedText }} 通过</small>
                          </td>
                          <td>{{ candidate.metrics.meanScoreText }}</td>
                          <td>{{ candidate.metrics.totalTokensText }}</td>
                          <td>
                            {{ candidate.metrics.totalSecondsText }}<span v-if="candidate.metrics.totalSeconds !== null" class="unit"> 秒</span>
                          </td>
                          <td>{{ candidate.metrics.traceText }}</td>
                          <td>
                            <span v-if="!candidate.metrics.failureTypes.length" class="muted">—</span>
                            <span
                              v-for="failure in candidate.metrics.failureTypes"
                              :key="failure.type"
                              class="failure-chip"
                              :title="failure.type"
                            >{{ failure.label }} × {{ failure.count }}</span>
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </section>

                <section class="experiment-section" aria-label="case 与候选矩阵">
                  <div class="section-heading">
                    <h4>case × 候选矩阵</h4>
                    <span class="section-hint">点击单元格查看执行证据</span>
                  </div>

                  <div v-if="!view.hasCases" class="state-block compact">该实验还没有 case 运行记录。</div>

                  <template v-else>
                    <div class="matrix-legend" aria-label="单元格状态图例">
                      <span v-for="kind in legendKinds" :key="kind.kind" class="legend-item">
                        <i :class="'tone-' + kind.tone"></i>{{ kind.label }}
                      </span>
                    </div>
                    <div class="table-scroll matrix-scroll">
                      <table class="matrix-table">
                        <thead>
                          <tr>
                            <th class="case-column">Case</th>
                            <th v-for="candidate in view.candidates" :key="candidate.candidateId">
                              <span class="matrix-candidate">{{ candidate.name }}</span>
                              <code :title="candidate.fingerprint">{{ candidate.shortFingerprint }}</code>
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr v-for="row in view.matrix.rows" :key="row.caseId">
                            <th scope="row" class="case-column" :title="row.caseId">{{ row.caseId }}</th>
                            <td v-for="candidate in view.candidates" :key="candidate.candidateId">
                              <button
                                class="matrix-cell"
                                :class="'tone-' + cellOf(row, candidate).tone"
                                type="button"
                                :aria-label="cellAria(row, candidate)"
                                :title="cellAria(row, candidate)"
                                @click="openEvidence(row.caseId, candidate, cellOf(row, candidate))"
                              >
                                <span class="cell-state">{{ cellOf(row, candidate).label }}</span>
                                <span v-if="cellOf(row, candidate).scoreText" class="cell-score">{{ cellOf(row, candidate).scoreText }}</span>
                                <span v-if="cellOf(row, candidate).errorTypeLabel" class="cell-error">{{ cellOf(row, candidate).errorTypeLabel }}</span>
                              </button>
                            </td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </template>
                </section>
              </template>
            </template>
          </template>
        </template>
      </div>

      <aside v-if="evidenceCell" class="evidence-drawer" role="dialog" aria-modal="true" aria-label="执行证据">
        <header class="evidence-header">
          <div>
            <span class="eyebrow">EVIDENCE</span>
            <h3>{{ evidenceCell.caseId }} · {{ evidenceCell.candidateName }}</h3>
          </div>
          <button class="icon-button" type="button" aria-label="关闭证据" @click="closeEvidence"><AppIcon name="close" :size="18" /></button>
        </header>

        <div class="evidence-body">
          <div class="evidence-meta">
            <div class="meta-row">
              <span>状态</span>
              <span class="cell-badge" :class="'tone-' + evidenceCell.cell.tone">{{ evidenceCell.cell.label }}</span>
            </div>
            <div class="meta-row">
              <span>运行 ID</span>
              <code :title="evidenceCell.cell.runId">{{ evidenceCell.cell.runId ? truncateId(evidenceCell.cell.runId, 18) : '—' }}</code>
            </div>
            <div class="meta-row">
              <span>Trace ID</span>
              <TraceId v-if="evidenceCell.cell.traceId" :trace-id="evidenceCell.cell.traceId" :length="16" />
              <span v-else class="muted">—</span>
            </div>
            <div class="meta-row">
              <span>配置指纹</span>
              <button
                v-if="evidenceFingerprint"
                class="fingerprint-copy"
                type="button"
                :title="'点击复制完整配置指纹：' + evidenceFingerprint"
                @click="copyValue(evidenceFingerprint, '配置指纹')"
              >{{ shortFingerprint(evidenceFingerprint) }}</button>
              <span v-else class="muted">—</span>
              <span v-if="copiedValue && copiedValue === evidenceFingerprint" class="copied">已复制</span>
            </div>
            <div class="meta-row">
              <span>评分</span>
              <span>{{ evidenceCell.cell.scoreText || '—' }}<template v-if="evidenceCell.cell.scoreStatusLabel"> · {{ evidenceCell.cell.scoreStatusLabel }}</template></span>
            </div>
            <div class="meta-row">
              <span>错误类型</span>
              <span>{{ evidence?.errorTypeLabel || evidenceCell.cell.errorTypeLabel || '—' }}</span>
            </div>
            <div class="meta-row">
              <span>证据引用</span>
              <code>{{ evidenceCell.cell.evidenceRef || '—' }}</code>
            </div>
          </div>

          <div v-if="!evidenceCell.cell.runId" class="state-block compact">该 case 没有 run_id，无法读取执行证据。</div>
          <div v-else-if="evidenceLoading" class="state-block compact">正在读取执行证据…</div>
          <div v-else-if="evidenceError" class="state-block compact is-error">
            <p>{{ evidenceError }}</p>
            <button class="btn btn-secondary" type="button" @click="retryEvidence">重试</button>
          </div>

          <template v-else-if="evidence">
            <section class="evidence-section">
              <h4>请求消息 <small v-if="evidence.request.model">{{ evidence.request.model }}</small></h4>
              <div v-if="evidence.request.hasMessages" class="message-list">
                <div v-for="(message, index) in evidence.request.messages" :key="index" class="message-card">
                  <span class="message-role">{{ message.role }}</span>
                  <pre class="message-content">{{ message.content }}</pre>
                </div>
              </div>
              <p v-else class="muted">证据中没有请求消息。</p>
              <p v-if="evidence.request.temperature !== null || evidence.request.maxTokens !== null" class="meta-line">
                <span v-if="evidence.request.temperature !== null">temperature {{ evidence.request.temperature }}</span>
                <span v-if="evidence.request.maxTokens !== null">max tokens {{ evidence.request.maxTokens }}</span>
              </p>
            </section>

            <section class="evidence-section">
              <h4>响应 <small v-if="evidence.response.model">{{ evidence.response.model }}</small></h4>
              <pre v-if="evidence.response.hasContent" class="evidence-pre">{{ evidence.response.content }}</pre>
              <p v-else class="muted">证据中没有响应内容。</p>
              <p v-if="evidence.response.finishReason" class="meta-line">结束原因：{{ evidence.response.finishReason }}</p>
            </section>

            <section class="evidence-section">
              <h4>用量与执行</h4>
              <dl class="evidence-grid">
                <div><dt>Prompt tokens</dt><dd>{{ formatTokens(evidence.usage.promptTokens) }}</dd></div>
                <div><dt>Completion tokens</dt><dd>{{ formatTokens(evidence.usage.completionTokens) }}</dd></div>
                <div><dt>总 tokens</dt><dd>{{ formatTokens(evidence.usage.totalTokens) }}</dd></div>
                <div><dt>用量类型</dt><dd>{{ evidence.usage.usageTypeLabel || '—' }}</dd></div>
                <div><dt>尝试次数</dt><dd>{{ evidence.attempts ?? '—' }}</dd></div>
                <div><dt>耗时</dt><dd>{{ evidence.duration === null ? '—' : evidence.durationText + ' 秒' }}</dd></div>
              </dl>
              <div v-if="evidence.error || evidence.errorTypeLabel" class="evidence-error">
                <strong>{{ evidence.errorTypeLabel || '错误' }}</strong>
                <span>{{ evidence.error || '该运行执行失败。' }}</span>
              </div>
            </section>

            <section class="evidence-section">
              <h4>评分与评审</h4>
              <dl class="evidence-grid">
                <div><dt>分数</dt><dd>{{ evidence.scoreText }}</dd></div>
                <div><dt>结论</dt><dd>{{ evidence.score?.passed === true ? '通过' : evidence.score?.passed === false ? '未通过' : '—' }}</dd></div>
                <div><dt>评分状态</dt><dd>{{ evidence.scoreStatusLabel || '—' }}</dd></div>
                <div><dt>评审模式</dt><dd>{{ evidence.judge?.mode || '—' }}</dd></div>
                <div><dt>评审模型</dt><dd>{{ evidence.judge?.model || '—' }}</dd></div>
                <div><dt>评审状态</dt><dd>{{ evidence.judge?.status || '—' }}</dd></div>
              </dl>
              <details v-if="evidence.score?.details" class="evidence-details">
                <summary>评分明细</summary>
                <pre>{{ JSON.stringify(evidence.score.details, null, 2) }}</pre>
              </details>
              <details v-if="evidence.judge?.details" class="evidence-details">
                <summary>评审明细</summary>
                <pre>{{ JSON.stringify(evidence.judge.details, null, 2) }}</pre>
              </details>
            </section>
          </template>
        </div>

        <footer class="evidence-footer">
          <button class="btn btn-primary" type="button" :disabled="!evidenceCell.cell.runId" @click="openRunDetail(evidenceCell.cell.runId)">
            <AppIcon name="history" :size="14" />查看运行详情
          </button>
          <button class="btn btn-secondary" type="button" @click="closeEvidence">关闭</button>
        </footer>
      </aside>
    </div>
  </div>

  <Teleport to="body">
    <Transition name="modal">
      <div v-if="manualCopy" class="modal-overlay experiment-copy-overlay" :style="{ zIndex: 1400 }" @click.self="manualCopy = null">
        <section class="modal-content experiment-copy-modal" role="dialog" aria-modal="true" aria-labelledby="experiment-copy-title">
          <header class="modal-header">
            <div>
              <span class="eyebrow">MANUAL COPY</span>
              <h2 id="experiment-copy-title">{{ manualCopy.title }}</h2>
              <p>{{ manualCopy.hint }}</p>
            </div>
            <button class="icon-button modal-close" type="button" aria-label="关闭" @click="manualCopy = null"><AppIcon name="close" :size="19" /></button>
          </header>
          <div class="modal-body">
            <textarea class="experiment-copy-text" :value="manualCopy.text" readonly rows="8" aria-label="手动复制内容" @focus="$event.target.select()"></textarea>
          </div>
          <footer class="modal-footer">
            <span class="modal-footnote">内容来自后端脱敏响应，不含 API Key。</span>
            <button class="btn btn-secondary" type="button" @click="manualCopy = null">关闭</button>
          </footer>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import RunDetail from './RunDetail.vue'
import TraceId from './TraceId.vue'
import { useExperimentsStore } from '../stores/experiments.js'
import { copyText } from '../utils/clipboard.js'
import { saveDefinitionText } from '../utils/definitionTransfer.js'
import { formatTimestamp, truncateId } from '../utils/runStatus.js'
import {
  CASE_CELL_META,
  experimentExportFileName,
  experimentListState,
  formatTokens,
  normalizeCaseCell,
  serializeExperimentExport,
  shortFingerprint,
} from '../utils/experimentDetails.js'

const store = useExperimentsStore()

const isOpen = ref(false)
const activeRunId = ref('')
const evidenceCell = ref(null)
const manualCopy = ref(null)
const exportNotice = ref('')
const copiedValue = ref('')
const body = ref(null)
let copyTimer

const experiments = computed(() => store.experiments)
const view = computed(() => store.detail)
const listState = computed(() => experimentListState({
  experiments: store.experiments,
  loading: store.listLoading,
  error: store.listError,
}))
const legendKinds = ['passed', 'failed_score', 'failed', 'partial', 'missing_score', 'scoring_error', 'not_scored', 'no_run']
  .map(key => CASE_CELL_META[key])

const evidence = computed(() => {
  const runId = evidenceCell.value?.cell?.runId
  return runId ? store.evidenceByRun[runId] || null : null
})
const evidenceLoading = computed(() => Boolean(
  evidenceCell.value?.cell?.runId
  && store.evidenceLoading
  && store.evidenceRunId === evidenceCell.value.cell.runId
))
const evidenceError = computed(() => (
  evidenceCell.value?.cell?.runId && store.evidenceRunId === evidenceCell.value.cell.runId
    ? store.evidenceError
    : ''
))
const evidenceFingerprint = computed(() => (
  evidence.value?.fingerprint || evidenceCell.value?.candidateFingerprint || ''
))

function open() {
  isOpen.value = true
  exportNotice.value = ''
  store.loadExperiments()
}

function close() {
  isOpen.value = false
  activeRunId.value = ''
  evidenceCell.value = null
  manualCopy.value = null
  exportNotice.value = ''
  store.clearEvidenceState()
}

function toggle() {
  if (isOpen.value) close()
  else open()
}

async function refreshAll() {
  exportNotice.value = ''
  store.clearEvidenceState()
  const list = await store.loadExperiments()
  if (!store.selectedId) return
  if (list.some(experiment => experiment.experimentId === store.selectedId)) {
    await store.selectExperiment(store.selectedId)
  } else {
    store.clearSelection()
  }
}

async function openExperiment(experiment) {
  if (!experiment?.experimentId) return
  activeRunId.value = ''
  evidenceCell.value = null
  exportNotice.value = ''
  store.clearEvidenceState()
  await store.selectExperiment(experiment.experimentId)
  scrollToTop()
}

function backToList() {
  activeRunId.value = ''
  evidenceCell.value = null
  exportNotice.value = ''
  store.clearSelection()
  store.clearEvidenceState()
}

function scrollToTop() {
  nextTick(() => {
    if (body.value) body.value.scrollTop = 0
  })
}

function cellOf(row, candidate) {
  return row.cells?.[candidate.candidateId] || normalizeCaseCell(null)
}

function cellAria(row, candidate) {
  const cell = cellOf(row, candidate)
  const parts = [row.caseId, candidate.name, cell.label]
  if (cell.scoreText) parts.push('分数 ' + cell.scoreText)
  if (cell.errorTypeLabel) parts.push(cell.errorTypeLabel)
  parts.push('查看执行证据')
  return parts.join('，')
}

async function copyValue(value, label) {
  const text = typeof value === 'string' ? value.trim() : ''
  if (!text) return
  const result = await copyText(text)
  if (result.method === 'clipboard') {
    copiedValue.value = text
    clearTimeout(copyTimer)
    copyTimer = setTimeout(() => { copiedValue.value = '' }, 1800)
  } else if (result.method === 'manual') {
    manualCopy.value = {
      title: '手动复制' + label,
      hint: '当前浏览器无法自动写入剪贴板，请选中下方文本复制。',
      text: result.text || text,
    }
  }
}

async function exportComparison() {
  if (!view.value?.hasCandidates) return
  exportNotice.value = ''
  const text = serializeExperimentExport(view.value)
  try {
    const result = await saveDefinitionText(text, experimentExportFileName(view.value))
    if (result.method === 'download') {
      exportNotice.value = '已下载当前实验对比 JSON。'
    } else if (result.method === 'clipboard') {
      exportNotice.value = '当前浏览器不支持自动下载，实验对比 JSON 已复制到剪贴板。'
    } else {
      manualCopy.value = {
        title: '手动复制实验对比 JSON',
        hint: '当前浏览器不支持自动下载或剪贴板，请选中下方文本复制并保存为 .json 文件。',
        text: result.text || text,
      }
      exportNotice.value = '已降级为手动复制。'
    }
  } catch {
    manualCopy.value = {
      title: '手动复制实验对比 JSON',
      hint: '导出失败，已降级为手动复制；请选中下方文本保存为 .json 文件。',
      text,
    }
    exportNotice.value = '导出失败，已降级为手动复制。'
  }
}

function openEvidence(caseId, candidate, cell) {
  activeRunId.value = ''
  store.clearEvidenceState()
  evidenceCell.value = {
    caseId,
    candidateId: candidate.candidateId,
    candidateName: candidate.name,
    candidateFingerprint: candidate.fingerprint,
    cell,
  }
  if (cell?.runId) store.loadEvidence(cell.runId)
}

function closeEvidence() {
  evidenceCell.value = null
  store.clearEvidenceState()
}

function retryEvidence() {
  const runId = evidenceCell.value?.cell?.runId
  if (runId) store.loadEvidence(runId)
}

function openRunDetail(runId) {
  if (!runId) return
  evidenceCell.value = null
  store.clearEvidenceState()
  activeRunId.value = runId
  scrollToTop()
}

function closeRunDetail() {
  activeRunId.value = ''
  scrollToTop()
}

onMounted(() => {
  // 与工作流库一致：进入应用时同步一次实验数量；失败时静默保留 0，打开面板再提示重试。
  store.loadExperiments()
})

onBeforeUnmount(() => {
  clearTimeout(copyTimer)
})

defineExpose({ open, close })
</script>

<style scoped>
.experiment-panel {
  display: contents;
}

.experiment-sidebar {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 130;
  width: min(1120px, 100vw);
  display: flex;
  flex-direction: column;
  background: #ffffff;
  border-left: 1px solid #e5e5e5;
  box-shadow: -18px 0 55px rgba(0, 0, 0, 0.14);
}

.experiment-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  padding: 20px 26px 18px;
  border-bottom: 1px solid #ededed;
  flex-shrink: 0;
  background: #ffffff;
}

.experiment-heading h2 {
  margin-top: 7px;
  font-size: 21px;
  font-weight: 600;
  letter-spacing: -0.5px;
  color: #202020;
}

.experiment-heading p {
  margin-top: 6px;
  font-size: 12px;
  color: #858585;
}

.experiment-header-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 7px;
  min-width: 0;
}

.experiment-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 20px 26px 34px;
}

.export-notice {
  margin-bottom: 15px;
  padding: 9px 12px;
  border: 1px solid #d8e6d3;
  background: #f3f9f1;
  border-radius: 6px;
  color: #3f6b3a;
  font-size: 12px;
}

.export-notice.is-error {
  border-color: #f0d6d6;
  background: #fdf3f3;
  color: #9c2b2b;
}

.list-intro {
  margin-bottom: 14px;
  font-size: 12px;
  color: #858585;
}

.table-scroll {
  width: 100%;
  overflow-x: auto;
}

.experiment-table,
.candidate-table,
.matrix-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.experiment-table th,
.candidate-table th {
  padding: 10px 12px;
  text-align: left;
  font-size: 11px;
  font-weight: 550;
  color: #828282;
  letter-spacing: 0.3px;
  border-bottom: 1px solid #e8e8e8;
  white-space: nowrap;
}

.experiment-table td,
.candidate-table td {
  padding: 12px;
  border-bottom: 1px solid #f0f0f0;
  vertical-align: middle;
}

.experiment-row {
  cursor: pointer;
  transition: background-color 150ms ease;
}

.experiment-row:hover {
  background: #f8f8f8;
}

.experiment-row td:first-child strong,
.candidate-cell strong {
  display: block;
  font-size: 13px;
  font-weight: 550;
  color: #2c2c2c;
}

.experiment-row code,
.candidate-cell code {
  display: block;
  margin-top: 4px;
  font: 11px ui-monospace, Consolas, monospace;
  color: #9a9a9a;
}

.experiment-row td small {
  display: block;
  margin-top: 3px;
  font-size: 10px;
  color: #9a9a9a;
}

.col-open {
  width: 28px;
  color: #b0b0b0;
}

.state-block {
  padding: 56px 24px;
  text-align: center;
  color: #777777;
  font-size: 13px;
}

.state-block.compact {
  padding: 26px 12px;
}

.state-block.is-error p {
  margin-bottom: 14px;
  color: #9c2b2b;
}

.empty-state {
  max-width: 620px;
  margin: 34px auto 0;
  padding: 40px 30px;
  border: 1px solid #e7e7e7;
  border-radius: 12px;
  background: #fcfcfc;
  text-align: center;
}

.empty-state h3 {
  margin-top: 10px;
  font-size: 20px;
  font-weight: 550;
  letter-spacing: -0.4px;
  color: #2b2b2b;
}

.empty-state p {
  margin-top: 12px;
  font-size: 13px;
  line-height: 1.9;
  color: #7c7c7c;
}

.empty-state .empty-hint {
  padding: 12px 14px;
  border-radius: 8px;
  background: #f4f4f4;
  font-size: 12px;
  text-align: left;
}

.empty-state .btn {
  margin-top: 18px;
}

.experiment-summary {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 22px;
  padding-bottom: 18px;
  margin-bottom: 20px;
  border-bottom: 1px solid #ededed;
}

.back-link {
  border: 0;
  background: none;
  padding: 0;
  margin-bottom: 8px;
  color: #7d7d7d;
  font-size: 12px;
  cursor: pointer;
}

.back-link:hover {
  color: #222222;
}

.experiment-summary h3 {
  font-size: 19px;
  font-weight: 600;
  letter-spacing: -0.4px;
  color: #242424;
}

.meta-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 10px;
}

.meta-chips span {
  padding: 4px 8px;
  border-radius: 5px;
  background: #f4f4f4;
  color: #767676;
  font-size: 11px;
}

.meta-chips code {
  font: 11px ui-monospace, Consolas, monospace;
}

.summary-note {
  max-width: 260px;
  padding: 9px 11px;
  border: 1px solid #ededed;
  border-radius: 7px;
  background: #fafafa;
  color: #8a8a8a;
  font-size: 11px;
  line-height: 1.8;
}

.experiment-section {
  margin-bottom: 26px;
}

.experiment-section h4,
.section-heading h4 {
  margin-bottom: 11px;
  font-size: 14px;
  font-weight: 550;
  color: #2f2f2f;
}

.section-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}

.section-hint {
  font-size: 11px;
  color: #9a9a9a;
}

.candidate-table {
  min-width: 860px;
}

.candidate-table tbody tr:hover {
  background: #fafafa;
}

.candidate-table .muted,
.muted {
  color: #b0b0b0;
}

.fingerprint-copy {
  padding: 3px 7px;
  border: 1px solid #e0e0e0;
  border-radius: 5px;
  background: #ffffff;
  color: #4b5563;
  font: 11px ui-monospace, Consolas, monospace;
  cursor: pointer;
}

.fingerprint-copy:hover {
  border-color: #b8b8b8;
  background: #f7f7f7;
}

.copied {
  margin-left: 6px;
  font-size: 11px;
  color: #2f7d4f;
  white-space: nowrap;
}

.pass-rate {
  display: block;
  font-size: 14px;
  font-weight: 600;
  color: #2f6b3a;
}

.cell-note {
  display: block;
  margin-top: 3px;
  font-size: 10px;
  color: #9a9a9a;
}

.unit {
  color: #9a9a9a;
  font-size: 11px;
}

.failure-chip {
  display: inline-block;
  margin: 2px 4px 2px 0;
  padding: 2px 6px;
  border-radius: 4px;
  background: #fdf1f1;
  color: #9c2b2b;
  font-size: 10px;
  white-space: nowrap;
}

.matrix-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 5px 14px;
  margin-bottom: 11px;
  padding: 8px 11px;
  border: 1px solid #ededed;
  border-radius: 7px;
  background: #fbfbfb;
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: #7d7d7d;
}

.legend-item i {
  width: 9px;
  height: 9px;
  border-radius: 3px;
  border: 1px solid transparent;
}

.matrix-table {
  border-collapse: separate;
  border-spacing: 3px;
  min-width: 620px;
}

.matrix-table thead th {
  padding: 8px;
  text-align: left;
  font-size: 11px;
  font-weight: 550;
  color: #7b7b7b;
  white-space: nowrap;
}

.matrix-candidate {
  display: block;
  font-size: 11px;
  color: #4f4f4f;
}

.matrix-table thead code {
  display: block;
  margin-top: 3px;
  font: 10px ui-monospace, Consolas, monospace;
  color: #a5a5a5;
}

.matrix-table .case-column {
  width: 116px;
  min-width: 116px;
  max-width: 180px;
  padding: 8px;
  text-align: left;
  font: 11px ui-monospace, Consolas, monospace;
  color: #666666;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  position: sticky;
  left: 0;
  background: #ffffff;
  z-index: 1;
}

.matrix-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  width: 100%;
  min-width: 108px;
  min-height: 46px;
  padding: 6px 9px;
  border: 1px solid transparent;
  border-radius: 6px;
  text-align: left;
  cursor: pointer;
  transition: border-color 150ms ease, transform 150ms ease;
}

.matrix-cell:hover {
  border-color: #9a9a9a;
  transform: translateY(-1px);
}

.cell-state {
  font-size: 11px;
  font-weight: 550;
}

.cell-score {
  font: 11px ui-monospace, Consolas, monospace;
  opacity: 0.9;
}

.cell-error {
  font-size: 10px;
  opacity: 0.8;
}

.tone-success { background: #eef7ee; border-color: #dcebd8; color: #2f6b3a; }
.tone-warning { background: #fdf6e8; border-color: #f0e3c5; color: #8a6519; }
.tone-error { background: #fdf0f0; border-color: #f0d6d6; color: #9c2b2b; }
.tone-scored { background: #f2f5fa; border-color: #dbe4f0; color: #3b5b86; }
.tone-running { background: #eef4fb; border-color: #d9e5f4; color: #245b9c; }
.tone-pending { background: #f6f6f6; border-color: #ededed; color: #777777; }
.tone-neutral { background: #f4f4f4; border-color: #e9e9e9; color: #666666; }
.tone-empty { background: #fbfbfb; border: 1px dashed #e2e2e2; color: #aaaaaa; }
.tone-unknown { background: #f7f7f7; border-color: #ececec; color: #777777; }

.evidence-drawer {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 5;
  width: min(590px, 100%);
  display: flex;
  flex-direction: column;
  background: #ffffff;
  border-left: 1px solid #e5e5e5;
  box-shadow: -20px 0 48px rgba(0, 0, 0, 0.12);
}

.evidence-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  padding: 19px 22px;
  border-bottom: 1px solid #ededed;
  flex-shrink: 0;
}

.evidence-header h3 {
  margin-top: 7px;
  font-size: 16px;
  font-weight: 600;
  color: #252525;
  overflow-wrap: anywhere;
}

.evidence-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 18px 22px 26px;
}

.evidence-meta {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 13px 14px;
  margin-bottom: 18px;
  border: 1px solid #ededed;
  border-radius: 8px;
  background: #fbfbfb;
}

.meta-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}

.meta-row > span:first-child {
  width: 70px;
  flex-shrink: 0;
  color: #8f8f8f;
}

.meta-row code {
  font: 11px ui-monospace, Consolas, monospace;
  color: #4f4f4f;
  overflow-wrap: anywhere;
}

.cell-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid transparent;
  font-size: 11px;
  font-weight: 550;
}

.evidence-section {
  margin-bottom: 22px;
}

.evidence-section h4 {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 9px;
  font-size: 13px;
  font-weight: 550;
  color: #333333;
}

.evidence-section h4 small {
  font: 10px ui-monospace, Consolas, monospace;
  color: #9a9a9a;
}

.message-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.message-card {
  border: 1px solid #ededed;
  border-radius: 7px;
  background: #fafafa;
  overflow: hidden;
}

.message-role {
  display: block;
  padding: 5px 10px;
  border-bottom: 1px solid #ededed;
  background: #f4f4f4;
  font: 10px ui-monospace, Consolas, monospace;
  color: #7b7b7b;
  letter-spacing: 0.4px;
}

.message-content,
.evidence-pre {
  margin: 0;
  padding: 10px 12px;
  max-height: 260px;
  overflow: auto;
  font: 12px/1.75 ui-monospace, Consolas, monospace;
  color: #3d3d3d;
  white-space: pre-wrap;
  word-break: break-word;
}

.evidence-pre {
  border: 1px solid #ededed;
  border-radius: 7px;
  background: #fafafa;
}

.meta-line {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 7px;
  font-size: 11px;
  color: #909090;
}

.evidence-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.evidence-grid > div {
  padding: 8px 10px;
  border: 1px solid #f0f0f0;
  border-radius: 6px;
  background: #fcfcfc;
}

.evidence-grid dt {
  font-size: 10px;
  color: #9a9a9a;
}

.evidence-grid dd {
  margin-top: 3px;
  font: 12px ui-monospace, Consolas, monospace;
  color: #3d3d3d;
  overflow-wrap: anywhere;
}

.evidence-error {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 11px;
  padding: 10px 12px;
  border: 1px solid #f0d6d6;
  border-radius: 7px;
  background: #fdf3f3;
  color: #9c2b2b;
  font-size: 12px;
  line-height: 1.7;
}

.evidence-details {
  margin-top: 10px;
  font-size: 12px;
}

.evidence-details summary {
  cursor: pointer;
  color: #5d5d5d;
  user-select: none;
}

.evidence-details pre {
  margin-top: 7px;
  padding: 10px;
  max-height: 240px;
  overflow: auto;
  border: 1px solid #ededed;
  border-radius: 6px;
  background: #fafafa;
  font: 11px/1.7 ui-monospace, Consolas, monospace;
  white-space: pre-wrap;
  word-break: break-word;
}

.evidence-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 14px 22px;
  border-top: 1px solid #ededed;
  flex-shrink: 0;
  background: #fcfcfc;
}

.experiment-run-detail :deep(.run-detail) {
  box-shadow: none;
  padding: 4px;
}

.experiment-copy-modal {
  width: 700px;
}

.experiment-copy-text {
  display: block;
  width: 100%;
  min-height: 180px;
  max-height: 300px;
  resize: vertical;
  padding: 12px;
  border: 1px solid #dedede;
  border-radius: 8px;
  background: #ffffff;
  color: #333333;
  font: 12px/1.7 ui-monospace, Consolas, monospace;
}

.experiment-copy-text:focus {
  outline: none;
  border-color: #727272;
  box-shadow: 0 0 0 3px #00000005;
}
</style>
