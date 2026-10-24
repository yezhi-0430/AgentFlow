<template>
  <div class="run-history">
    <div class="run-history-header">
      <h2>运行历史</h2>
      <div class="run-history-actions">
        <label class="run-filter">
          <span>状态筛选</span>
          <select :value="statusFilter" aria-label="按状态筛选运行历史" @change="onFilterChange">
            <option v-for="filter in statusFilters" :key="filter.value" :value="filter.value">
              {{ filter.label }}
            </option>
          </select>
        </label>
        <span class="run-count">当前 {{ visibleRuns.length }} 条</span>
        <button
          v-if="selectedRuns.length > 1 && selectedRuns.length <= 5"
          @click="compareSelected"
          class="btn-secondary"
        >
          对比选中 ({{ selectedRuns.length }})
        </button>
        <button class="btn-secondary" :disabled="!visibleRuns.length" @click="exportRuns">
          导出 JSON
        </button>
        <button @click="refresh" class="btn-secondary" :disabled="loading">
          刷新
        </button>
      </div>
    </div>

    <div v-if="exportNotice" class="export-notice" role="status">{{ exportNotice }}</div>

    <div v-if="loading" class="loading-state">
      加载中...
    </div>

    <div v-else-if="error" class="error-state">
      <p>{{ error }}</p>
      <button @click="refresh" class="btn-primary">重试</button>
    </div>

    <div v-else-if="!hasRuns" class="empty-state">
      <p>暂无运行记录</p>
    </div>

    <div v-else-if="!visibleRuns.length" class="empty-state">
      <p>当前筛选没有运行记录</p>
      <button @click="clearFilter" class="btn-secondary">显示全部</button>
    </div>

    <div v-else class="run-list">
      <table class="run-table">
        <thead>
          <tr>
            <th class="col-checkbox">
              <input
                type="checkbox"
                @change="toggleSelectAll"
                :checked="allSelected"
              />
            </th>
            <th class="col-status">状态</th>
            <th class="col-run-id">运行 ID</th>
            <th class="col-trace">Trace ID</th>
            <th class="col-time">创建时间</th>
            <th class="col-duration">耗时(秒)</th>
            <th class="col-tokens">Token</th>
            <th class="col-attempts">尝试</th>
            <th class="col-steps">步骤数</th>
            <th class="col-actions">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="run in visibleRuns"
            :key="run.run_id"
            @click="viewDetail(run.run_id)"
            class="run-row"
          >
            <td class="col-checkbox" @click.stop>
              <input
                type="checkbox"
                :value="run.run_id"
                v-model="selectedRuns"
              />
            </td>
            <td class="col-status">
              <span :class="['status-badge', run.statusClass]">
                {{ statusLabel(run.status) }}
              </span>
              <small
                v-if="run.errorInfo.typeLabel"
                class="run-error-type"
                :title="run.errorInfo.reason || run.errorInfo.typeLabel"
              >{{ run.errorInfo.typeLabel }}</small>
              <small
                v-if="run.errorInfo.shortReason"
                class="run-error-reason"
                :title="run.errorInfo.reason"
              >{{ run.errorInfo.shortReason }}</small>
            </td>
            <td class="col-run-id"><code class="run-id" :title="run.run_id">{{ truncateId(run.run_id) }}</code></td>
            <td class="col-trace" @click.stop><TraceId :trace-id="run.traceId" /></td>
            <td class="col-time">{{ run.createdAtFormatted }}</td>
            <td class="col-duration">{{ run.duration }}</td>
            <td class="col-tokens">{{ run.total_tokens }}</td>
            <td class="col-attempts">{{ run.attemptsLabel || '-' }}</td>
            <td class="col-steps">{{ run.step_results?.length || 0 }}</td>
            <td class="col-actions" @click.stop>
              <button
                @click="viewDetail(run.run_id)"
                class="btn-link"
                title="查看详情"
              >
                查看
              </button>
              <button
                @click="confirmDelete(run.run_id)"
                class="btn-link btn-danger"
                title="删除"
              >
                删除
              </button>
            </td>
          </tr>
        </tbody>
      </table>

      <!-- 分页 -->
      <div v-if="pagination.total > pagination.limit" class="pagination">
        <button
          @click="prevPage"
          :disabled="pagination.offset === 0"
          class="btn-secondary"
        >
          上一页
        </button>
        <span class="pagination-info">
          {{ pagination.offset + 1 }} - {{ Math.min(pagination.offset + pagination.limit, pagination.total) }} / {{ pagination.total }}
        </span>
        <button
          @click="nextPage"
          :disabled="pagination.offset + pagination.limit >= pagination.total"
          class="btn-secondary"
        >
          下一页
        </button>
      </div>
    </div>

    <Teleport to="body">
      <div v-if="manualExportText" class="modal-overlay" @click.self="manualExportText = ''">
        <section class="modal-content run-export-fallback" role="dialog" aria-modal="true" aria-labelledby="run-export-fallback-title">
          <header class="modal-header">
            <div>
              <span class="eyebrow">MANUAL COPY</span>
              <h2 id="run-export-fallback-title">手动复制运行记录</h2>
              <p>当前浏览器不支持自动下载或剪贴板，请选中下方文本复制并保存为 .json 文件。</p>
            </div>
            <button class="icon-button modal-close" type="button" aria-label="关闭" @click="manualExportText = ''">
              <AppIcon name="close" :size="19" />
            </button>
          </header>
          <div class="modal-body">
            <textarea
              class="run-export-text"
              :value="manualExportText"
              readonly
              rows="14"
              aria-label="运行记录 JSON"
              @focus="$event.target.select()"
            ></textarea>
          </div>
          <footer class="modal-footer">
            <span class="modal-footnote">仅包含当前筛选的运行记录，不含 API Key。</span>
            <button class="btn btn-secondary" type="button" @click="manualExportText = ''">关闭</button>
          </footer>
        </section>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRunsStore } from '../stores/runs.js'
import { storeToRefs } from 'pinia'
import AppIcon from './AppIcon.vue'
import TraceId from './TraceId.vue'
import { statusLabel, truncateId } from '../utils/runStatus.js'
import {
  RUN_STATUS_FILTERS,
  filterRunsByStatus,
  runAttemptsLabel,
  runErrorInfo,
  runsExportFileName,
  serializeRunsExport,
  statusFilterLabel,
  traceIdOf,
} from '../utils/runDetails.js'
import { saveDefinitionText } from '../utils/definitionTransfer.js'

const props = defineProps({
  workflowId: {
    type: String,
    default: null,
  },
})

const emit = defineEmits(['view-detail', 'compare'])

const runsStore = useRunsStore()
const { runs, loading, error, pagination, formattedRuns, hasRuns } = storeToRefs(runsStore)

const selectedRuns = ref([])
const statusFilters = RUN_STATUS_FILTERS
const statusFilter = ref('all')
const exportNotice = ref('')
const manualExportText = ref('')

// 筛选只作用于已经加载的运行记录；导出与状态筛选共用同一份装饰后的数据。
const visibleRuns = computed(() => filterRunsByStatus(formattedRuns.value, statusFilter.value).map(run => ({
  ...run,
  attemptsLabel: runAttemptsLabel(run),
  errorInfo: runErrorInfo(run),
  traceId: traceIdOf(run),
})))

const allSelected = computed(() => {
  return visibleRuns.value.length > 0 && visibleRuns.value.every(run => selectedRuns.value.includes(run.run_id))
})

onMounted(() => {
  loadRuns()
})

watch(() => props.workflowId, () => {
  selectedRuns.value = []
  statusFilter.value = 'all'
  exportNotice.value = ''
  manualExportText.value = ''
  loadRuns()
})

async function loadRuns() {
  if (props.workflowId) {
    await runsStore.loadWorkflowRuns(props.workflowId)
  } else {
    await runsStore.loadAllRuns()
  }
}

function refresh() {
  selectedRuns.value = []
  exportNotice.value = ''
  loadRuns()
}

function onFilterChange(event) {
  statusFilter.value = event.target.value
  selectedRuns.value = []
  exportNotice.value = ''
}

function clearFilter() {
  statusFilter.value = 'all'
  selectedRuns.value = []
  exportNotice.value = ''
}

async function exportRuns() {
  if (!visibleRuns.value.length) return
  // 导出后端原始记录（不包含界面派生的展示字段），范围与当前筛选一致。
  const filteredRuns = filterRunsByStatus(runs.value, statusFilter.value)
  const text = serializeRunsExport(filteredRuns, {
    workflowId: props.workflowId,
    filter: statusFilter.value,
  })
  exportNotice.value = ''
  try {
    const result = await saveDefinitionText(text, runsExportFileName(statusFilter.value))
    if (result.method === 'download') {
      exportNotice.value = `已下载 ${filteredRuns.length} 条运行记录（${statusFilterLabel(statusFilter.value)}）。`
    } else if (result.method === 'clipboard') {
      exportNotice.value = '当前浏览器不支持自动下载，运行记录 JSON 已复制到剪贴板。'
    } else {
      manualExportText.value = result.text || text
      exportNotice.value = '当前浏览器不支持自动下载或剪贴板，请手动复制。'
    }
  } catch {
    manualExportText.value = text
    exportNotice.value = '导出失败，已降级为手动复制。'
  }
}

// 允许父组件（运行历史面板）在执行结束后重新从 API 拉取。
defineExpose({ refresh })

function toggleSelectAll(event) {
  if (event.target.checked) {
    selectedRuns.value = visibleRuns.value.map(run => run.run_id)
  } else {
    selectedRuns.value = []
  }
}

function viewDetail(runId) {
  emit('view-detail', runId)
}

function compareSelected() {
  if (selectedRuns.value.length < 2 || selectedRuns.value.length > 5) {
    alert('请选择 2-5 个运行进行对比')
    return
  }
  emit('compare', selectedRuns.value)
}

async function confirmDelete(runId) {
  if (!confirm('确定要删除这条运行记录吗？')) {
    return
  }

  try {
    await runsStore.removeRun(runId)
  } catch (error) {
    alert('删除失败：' + error.message)
  }
}

function prevPage() {
  const newOffset = Math.max(0, pagination.value.offset - pagination.value.limit)
  if (props.workflowId) {
    runsStore.loadWorkflowRuns(props.workflowId, pagination.value.limit, newOffset)
  } else {
    runsStore.loadAllRuns(pagination.value.limit, newOffset)
  }
}

function nextPage() {
  const newOffset = pagination.value.offset + pagination.value.limit
  if (newOffset < pagination.value.total) {
    if (props.workflowId) {
      runsStore.loadWorkflowRuns(props.workflowId, pagination.value.limit, newOffset)
    } else {
      runsStore.loadAllRuns(pagination.value.limit, newOffset)
    }
  }
}
</script>

<style scoped>
.run-history {
  padding: 20px;
  background: #ffffff;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.run-history-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 20px;
}

.run-history-header h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
}

.run-history-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.run-filter {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #4b5563;
}

.run-filter select {
  padding: 7px 10px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: #ffffff;
  font-size: 13px;
  color: #374151;
}

.run-count {
  font-size: 12px;
  color: #6b7280;
  white-space: nowrap;
}

.export-notice {
  margin-bottom: 14px;
  padding: 9px 12px;
  border: 1px solid #d8e6d3;
  background: #f3f9f1;
  border-radius: 6px;
  color: #3f6b3a;
  font-size: 13px;
}

.loading-state,
.error-state,
.empty-state {
  text-align: center;
  padding: 40px;
  color: #666;
}

.run-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.run-table th {
  text-align: left;
  padding: 12px 8px;
  border-bottom: 2px solid #e5e7eb;
  font-weight: 600;
  color: #374151;
}

.run-table td {
  padding: 12px 8px;
  border-bottom: 1px solid #e5e7eb;
}

.run-row {
  cursor: pointer;
  transition: background-color 0.15s;
}

.run-row:hover {
  background-color: #f9fafb;
}

.col-checkbox {
  width: 40px;
}

.run-list {
  overflow-x: auto;
}

.run-id {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12px;
  color: #4b5563;
  white-space: nowrap;
}

.col-status {
  width: 150px;
}

.col-run-id {
  width: 100px;
}

.col-trace {
  width: 170px;
}

.col-time {
  width: 170px;
}

.col-duration {
  width: 100px;
}

.col-tokens {
  width: 80px;
}

.col-steps {
  width: 80px;
}

.col-attempts {
  width: 90px;
  white-space: nowrap;
}

.run-error-type,
.run-error-reason {
  display: block;
  margin-top: 4px;
  font-size: 11px;
  line-height: 1.5;
}

.run-error-type {
  color: #991b1b;
}

.run-error-reason {
  color: #6b7280;
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-export-fallback {
  width: 640px;
}

.run-export-text {
  display: block;
  width: 100%;
  min-height: 220px;
  max-height: 340px;
  resize: vertical;
  padding: 12px;
  border: 1px solid #dedede;
  border-radius: 8px;
  background: #ffffff;
  color: #333333;
  font: 12px/1.7 ui-monospace, Consolas, monospace;
}

.run-export-text:focus {
  outline: none;
  border-color: #727272;
  box-shadow: 0 0 0 3px #00000005;
}

.col-actions {
  width: 120px;
}

.status-badge {
  display: inline-block;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.status-success {
  background-color: #d1fae5;
  color: #065f46;
}

.status-running {
  background-color: #dbeafe;
  color: #1e40af;
}

.status-error {
  background-color: #fee2e2;
  color: #991b1b;
}

.status-stopped {
  background-color: #e5e7eb;
  color: #374151;
}

.status-warning {
  background-color: #fef3c7;
  color: #92400e;
}

.status-pending {
  background-color: #f3f4f6;
  color: #6b7280;
}

.btn-link {
  background: none;
  border: none;
  color: #2563eb;
  cursor: pointer;
  padding: 4px 8px;
  font-size: 13px;
}

.btn-link:hover {
  text-decoration: underline;
}

.btn-link.btn-danger {
  color: #dc2626;
}

.btn-secondary {
  padding: 8px 16px;
  background-color: #f3f4f6;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.15s;
}

.btn-secondary:hover:not(:disabled) {
  background-color: #e5e7eb;
}

.btn-secondary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  padding: 8px 16px;
  background-color: #2563eb;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
}

.btn-primary:hover {
  background-color: #1d4ed8;
}

.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 16px;
  margin-top: 20px;
}

.pagination-info {
  font-size: 14px;
  color: #6b7280;
}
</style>
