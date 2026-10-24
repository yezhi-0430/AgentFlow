<template>
  <div class="run-comparison">
    <div class="comparison-header">
      <h2>运行对比</h2>
      <button @click="$emit('close')" class="btn-secondary">关闭</button>
    </div>

    <div v-if="loading" class="loading-state">
      加载中...
    </div>

    <div v-else-if="error" class="error-state">
      <p>{{ error }}</p>
      <button @click="$emit('close')" class="btn-primary">返回</button>
    </div>

    <div v-else-if="comparison" class="comparison-content">
      <!-- 摘要统计 -->
      <div class="summary-section">
        <h3>对比摘要</h3>
        <div class="summary-grid">
          <div class="summary-card">
            <div class="summary-label">对比数量</div>
            <div class="summary-value">{{ comparison.summary.total_runs }}</div>
          </div>
          <div class="summary-card">
            <div class="summary-label">平均 Token</div>
            <div class="summary-value">{{ comparison.summary.avg_tokens.toFixed(0) }}</div>
          </div>
          <div class="summary-card">
            <div class="summary-label">平均耗时</div>
            <div class="summary-value">{{ comparison.summary.avg_duration.toFixed(2) }}s</div>
          </div>
        </div>

        <!-- 状态分布 -->
        <div class="status-distribution">
          <h4>状态分布</h4>
          <div class="status-chart">
            <div
              v-for="(count, status) in comparison.summary.status_distribution"
              :key="status"
              class="status-bar"
              :style="{ width: (count / comparison.summary.total_runs * 100) + '%' }"
            >
              <span :class="['status-label', statusClass(status)]">
                {{ statusLabel(status) }}: {{ count }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- 详细对比表 -->
      <div class="comparison-table-section">
        <h3>详细对比</h3>
        <div class="table-wrapper">
          <table class="comparison-table">
            <thead>
              <tr>
                <th class="col-metric">指标</th>
                <th
                  v-for="(run, index) in comparison.runs"
                  :key="run.run_id"
                  class="col-run"
                >
                  运行 {{ index + 1 }}
                </th>
              </tr>
            </thead>
            <tbody>
              <!-- Run ID -->
              <tr>
                <td class="metric-name">Run ID</td>
                <td
                  v-for="run in comparison.runs"
                  :key="run.run_id"
                  class="metric-value mono"
                >
                  {{ run.run_id.substring(0, 8) }}...
                </td>
              </tr>

              <!-- 状态 -->
              <tr>
                <td class="metric-name">状态</td>
                <td v-for="run in comparison.runs" :key="run.run_id" class="metric-value">
                  <span :class="['status-badge', 'small', statusClass(run.status)]">
                    {{ statusLabel(run.status) }}
                  </span>
                </td>
              </tr>

              <!-- 创建时间 -->
              <tr>
                <td class="metric-name">创建时间</td>
                <td
                  v-for="run in comparison.runs"
                  :key="run.run_id"
                  class="metric-value small-text"
                >
                  {{ formatTimestamp(run.created_at) }}
                </td>
              </tr>

              <!-- 总耗时 -->
              <tr>
                <td class="metric-name">总耗时 (秒)</td>
                <td
                  v-for="run in comparison.runs"
                  :key="run.run_id"
                  class="metric-value"
                  :class="getDurationClass(run.total_duration, comparison.runs)"
                >
                  {{ run.total_duration?.toFixed(2) || '-' }}
                </td>
              </tr>

              <!-- 总 Token -->
              <tr>
                <td class="metric-name">总 Token</td>
                <td
                  v-for="run in comparison.runs"
                  :key="run.run_id"
                  class="metric-value"
                  :class="getTokenClass(run.total_tokens, comparison.runs)"
                >
                  {{ run.total_tokens }}
                </td>
              </tr>

              <!-- 步骤数 -->
              <tr>
                <td class="metric-name">步骤数</td>
                <td v-for="run in comparison.runs" :key="run.run_id" class="metric-value">
                  {{ run.step_results?.length || 0 }}
                </td>
              </tr>

              <!-- 任务输入 -->
              <tr>
                <td class="metric-name">任务输入</td>
                <td
                  v-for="run in comparison.runs"
                  :key="run.run_id"
                  class="metric-value small-text"
                >
                  {{ truncate(run.task_input, 50) }}
                </td>
              </tr>

              <!-- 最终结果 -->
              <tr>
                <td class="metric-name">最终结果</td>
                <td
                  v-for="run in comparison.runs"
                  :key="run.run_id"
                  class="metric-value small-text"
                >
                  {{ truncate(run.final_result, 50) || '-' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 步骤对比 -->
      <div class="steps-comparison-section">
        <h3>步骤对比</h3>
        <div class="steps-grid">
          <div
            v-for="(run, index) in comparison.runs"
            :key="run.run_id"
            class="run-steps-card"
          >
            <h4>运行 {{ index + 1 }}</h4>
            <div class="steps-list-compact">
              <div
                v-for="(step, stepIndex) in run.step_results"
                :key="step.step_id"
                class="step-compact"
              >
                <span class="step-index">{{ stepIndex + 1 }}</span>
                <span class="step-agent">{{ step.agent_name }}</span>
                <span :class="['status-badge', 'mini', statusClass(step.status)]">
                  {{ statusLabel(step.status) }}
                </span>
                <span class="step-duration">{{ step.duration?.toFixed(2) || '-' }}s</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 可视化图表 -->
      <div class="charts-section">
        <h3>可视化对比</h3>
        <div class="charts-grid">
          <!-- Token 对比条形图 -->
          <div class="chart-card">
            <h4>Token 用量对比</h4>
            <div class="bar-chart">
              <div
                v-for="(run, index) in comparison.runs"
                :key="run.run_id"
                class="bar-item"
              >
                <span class="bar-label">运行 {{ index + 1 }}</span>
                <div class="bar-container">
                  <div
                    class="bar-fill"
                    :style="{
                      width: (run.total_tokens / maxTokens * 100) + '%',
                      backgroundColor: getChartColor(index)
                    }"
                  >
                    <span class="bar-value">{{ run.total_tokens }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 耗时对比条形图 -->
          <div class="chart-card">
            <h4>耗时对比</h4>
            <div class="bar-chart">
              <div
                v-for="(run, index) in comparison.runs"
                :key="run.run_id"
                class="bar-item"
              >
                <span class="bar-label">运行 {{ index + 1 }}</span>
                <div class="bar-container">
                  <div
                    class="bar-fill"
                    :style="{
                      width: (run.total_duration / maxDuration * 100) + '%',
                      backgroundColor: getChartColor(index)
                    }"
                  >
                    <span class="bar-value">{{ run.total_duration?.toFixed(2) }}s</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRunsStore } from '../stores/runs.js'
import { storeToRefs } from 'pinia'
import { statusClass, statusLabel } from '../utils/runStatus.js'

const props = defineProps({
  runIds: {
    type: Array,
    required: true,
  },
})

defineEmits(['close'])

const runsStore = useRunsStore()
const { loading, error } = storeToRefs(runsStore)

const comparison = ref(null)

const maxTokens = computed(() => {
  if (!comparison.value?.runs) return 1
  return Math.max(...comparison.value.runs.map(r => r.total_tokens || 0))
})

const maxDuration = computed(() => {
  if (!comparison.value?.runs) return 1
  return Math.max(...comparison.value.runs.map(r => r.total_duration || 0))
})

onMounted(async () => {
  await loadComparison()
})

async function loadComparison() {
  try {
    comparison.value = await runsStore.loadComparison(props.runIds)
  } catch (error) {
    console.error('Failed to load comparison:', error)
  }
}

function formatTimestamp(timestamp) {
  if (!timestamp) return '-'
  return new Date(timestamp * 1000).toLocaleString()
}

function truncate(text, length) {
  if (!text) return ''
  return text.length > length ? text.substring(0, length) + '...' : text
}

function getDurationClass(duration, runs) {
  if (!duration) return ''
  const durations = runs.map(r => r.total_duration).filter(Boolean)
  const min = Math.min(...durations)
  const max = Math.max(...durations)
  if (duration === min) return 'metric-best'
  if (duration === max) return 'metric-worst'
  return ''
}

function getTokenClass(tokens, runs) {
  if (!tokens) return ''
  const tokensList = runs.map(r => r.total_tokens).filter(Boolean)
  const min = Math.min(...tokensList)
  const max = Math.max(...tokensList)
  if (tokens === min) return 'metric-best'
  if (tokens === max) return 'metric-worst'
  return ''
}

function getChartColor(index) {
  const colors = [
    '#3b82f6', // blue
    '#10b981', // green
    '#f59e0b', // amber
    '#ef4444', // red
    '#8b5cf6', // purple
  ]
  return colors[index % colors.length]
}
</script>

<style scoped>
.run-comparison {
  padding: 20px;
  background: #ffffff;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  max-width: 1400px;
  margin: 0 auto;
}

.comparison-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 2px solid #e5e7eb;
}

.comparison-header h2 {
  margin: 0;
  font-size: 24px;
  font-weight: 600;
}

.loading-state,
.error-state {
  text-align: center;
  padding: 40px;
  color: #666;
}

.summary-section {
  margin-bottom: 32px;
}

.summary-section h3 {
  margin: 0 0 16px 0;
  font-size: 18px;
  font-weight: 600;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}

.summary-card {
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px;
  text-align: center;
}

.summary-label {
  font-size: 13px;
  color: #6b7280;
  margin-bottom: 8px;
}

.summary-value {
  font-size: 28px;
  font-weight: 700;
  color: #111827;
}

.status-distribution h4 {
  font-size: 16px;
  font-weight: 600;
  margin: 0 0 12px 0;
}

.status-chart {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.status-bar {
  background: #e5e7eb;
  border-radius: 4px;
  padding: 8px;
  min-width: 80px;
}

.status-label {
  font-size: 13px;
  font-weight: 500;
}

.comparison-table-section,
.steps-comparison-section,
.charts-section {
  margin-bottom: 32px;
}

.comparison-table-section h3,
.steps-comparison-section h3,
.charts-section h3 {
  margin: 0 0 16px 0;
  font-size: 18px;
  font-weight: 600;
}

.table-wrapper {
  overflow-x: auto;
}

.comparison-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.comparison-table th,
.comparison-table td {
  padding: 12px;
  border: 1px solid #e5e7eb;
  text-align: left;
}

.comparison-table th {
  background: #f9fafb;
  font-weight: 600;
}

.col-metric {
  min-width: 120px;
  background: #f3f4f6;
  font-weight: 600;
}

.col-run {
  min-width: 150px;
}

.metric-name {
  background: #f9fafb;
  font-weight: 500;
}

.metric-value {
  font-size: 14px;
}

.metric-value.mono {
  font-family: monospace;
}

.metric-value.small-text {
  font-size: 12px;
  color: #6b7280;
}

.metric-best {
  background: #d1fae5;
}

.metric-worst {
  background: #fee2e2;
}

.steps-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 16px;
}

.run-steps-card {
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px;
}

.run-steps-card h4 {
  margin: 0 0 12px 0;
  font-size: 16px;
  font-weight: 600;
}

.steps-list-compact {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.step-compact {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  background: #ffffff;
  border-radius: 4px;
  font-size: 13px;
}

.step-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  background: #e5e7eb;
  border-radius: 50%;
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
}

.step-agent {
  flex: 1;
  font-weight: 500;
}

.step-duration {
  color: #6b7280;
  font-size: 12px;
}

.charts-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
  gap: 20px;
}

.chart-card {
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 20px;
}

.chart-card h4 {
  margin: 0 0 16px 0;
  font-size: 16px;
  font-weight: 600;
}

.bar-chart {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.bar-item {
  display: flex;
  align-items: center;
  gap: 12px;
}

.bar-label {
  width: 60px;
  font-size: 13px;
  font-weight: 500;
  flex-shrink: 0;
}

.bar-container {
  flex: 1;
  height: 32px;
  background: #e5e7eb;
  border-radius: 4px;
  position: relative;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  display: flex;
  align-items: center;
  padding: 0 8px;
  transition: width 0.3s ease;
}

.bar-value {
  font-size: 12px;
  font-weight: 600;
  color: white;
}

.status-badge {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 4px;
  font-size: 13px;
  font-weight: 500;
}

.status-badge.small {
  padding: 2px 8px;
  font-size: 11px;
}

.status-badge.mini {
  padding: 2px 6px;
  font-size: 10px;
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

.btn-secondary,
.btn-primary {
  padding: 8px 16px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.15s;
}

.btn-secondary {
  background-color: #f3f4f6;
  border: 1px solid #d1d5db;
}

.btn-secondary:hover {
  background-color: #e5e7eb;
}

.btn-primary {
  background-color: #2563eb;
  color: white;
  border: none;
}

.btn-primary:hover {
  background-color: #1d4ed8;
}
</style>
