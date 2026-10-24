<template>
  <div class="run-detail">
    <div v-if="loading" class="loading-state">
      加载中...
    </div>

    <div v-else-if="error" class="error-state">
      <p>{{ error }}</p>
      <button @click="$emit('close')" class="btn-primary">返回</button>
    </div>

    <div v-else-if="run" class="run-content">
      <!-- 头部 -->
      <div class="run-header">
        <div class="run-title">
          <h2>运行详情</h2>
          <span :class="['status-badge', statusClass(run.status)]">
            {{ statusLabel(run.status) }}
          </span>
          <span v-if="run.stop_requested" class="status-badge status-stopped">已请求停止</span>
        </div>
        <button @click="$emit('close')" class="btn-secondary">关闭</button>
      </div>

      <!-- 基本信息 -->
      <div class="run-info-grid">
        <div class="info-item">
          <span class="info-label">运行 ID</span>
          <span class="info-value">{{ run.run_id }}</span>
        </div>
        <div class="info-item">
          <span class="info-label">Trace ID</span>
          <span class="info-value"><TraceId :trace-id="traceId" :length="16" /></span>
        </div>
        <div v-if="run.workflow_name" class="info-item">
          <span class="info-label">工作流名称</span>
          <span class="info-value">{{ run.workflow_name }}</span>
        </div>
        <div class="info-item">
          <span class="info-label">工作流 ID</span>
          <span class="info-value">{{ run.workflow_id }}</span>
        </div>
        <div class="info-item">
          <span class="info-label">创建时间</span>
          <span class="info-value">{{ formatTimestamp(run.created_at) }}</span>
        </div>
        <div class="info-item">
          <span class="info-label">开始时间</span>
          <span class="info-value">{{ formatTimestamp(run.started_at) }}</span>
        </div>
        <div class="info-item">
          <span class="info-label">完成时间</span>
          <span class="info-value">{{ formatTimestamp(run.completed_at) }}</span>
        </div>
        <div class="info-item">
          <span class="info-label">总耗时</span>
          <span class="info-value">{{ formatDuration(run.total_duration) }} 秒</span>
        </div>
        <div class="info-item">
          <span class="info-label">总 Token</span>
          <span class="info-value">{{ run.total_tokens }}</span>
        </div>
        <div v-if="attemptsLabel" class="info-item">
          <span class="info-label">步骤尝试</span>
          <span class="info-value">{{ attemptsLabel }}</span>
        </div>
        <div v-if="run.stop_requested" class="info-item">
          <span class="info-label">停止请求</span>
          <span class="info-value">已请求停止</span>
        </div>
      </div>

      <!-- 任务输入 -->
      <div class="section">
        <h3>任务输入</h3>
        <div class="code-block">{{ run.task_input }}</div>
      </div>

      <!-- 最终结果 -->
      <div v-if="run.final_result" class="section">
        <h3>最终结果</h3>
        <div class="code-block">{{ run.final_result }}</div>
      </div>

      <!-- 错误信息：失败/超时展示 error_type 中文标签与具体原因 -->
      <div v-if="run.error || errorInfo.typeLabel" class="section">
        <h3>错误信息 <span v-if="errorInfo.typeLabel" class="error-type-badge">{{ errorInfo.typeLabel }}</span></h3>
        <div class="code-block error-block">{{ run.error || errorInfo.reason || errorInfo.typeLabel }}</div>
      </div>

      <!-- 步骤详情 -->
      <div v-if="run.step_results && run.step_results.length > 0" class="section">
        <h3>步骤详情 ({{ run.step_results.length }})</h3>
        <div class="steps-list">
          <div
            v-for="(step, index) in run.step_results"
            :key="step.step_id || step.step_index || index"
            class="step-card"
          >
            <div class="step-header">
              <div class="step-title">
                <span class="step-number">{{ index + 1 }}</span>
                <span class="step-agent">{{ step.agent_name }}</span>
                <span :class="['status-badge', 'small', statusClass(step.status)]">
                  {{ statusLabel(step.status) }}
                </span>
                <span v-if="step.error_type" class="status-badge small error-type-badge">
                  {{ errorTypeLabel(step.error_type) }}
                </span>
              </div>
              <div class="step-meta">
                <span v-if="stepAttemptsLabel(step)" class="meta-item attempts">
                  {{ stepAttemptsLabel(step) }}
                </span>
                <span v-if="step.duration" class="meta-item">
                  耗时: {{ formatDuration(step.duration) }}s
                </span>
                <span v-if="step.usage && step.usage.total_tokens" class="meta-item">
                  Token: {{ step.usage.total_tokens }}
                </span>
                <span v-if="step.usage_type" class="meta-item usage-type">
                  {{ getUsageTypeText(step.usage_type) }}
                </span>
                <span v-if="step.model" class="meta-item">模型: {{ step.model }}</span>
                <span v-if="step.finish_reason" class="meta-item">结束原因: {{ step.finish_reason }}</span>
              </div>
            </div>

            <div v-if="step.error || step.error_type" class="step-error">
              <strong>{{ step.error_type ? errorTypeLabel(step.error_type) + '：' : '错误：' }}</strong>
              {{ step.error || '该步骤执行失败。' }}
            </div>

            <div v-if="step.input_text" class="step-output">
              <details>
                <summary>输入</summary>
                <div class="code-block small">{{ step.input_text }}</div>
              </details>
            </div>

            <div v-if="step.output_text || step.output" class="step-output">
              <strong>输出:</strong>
              <div class="code-block small">{{ step.output_text || step.output }}</div>
            </div>

            <div v-if="step.usage" class="step-usage">
              <details>
                <summary>详细用量</summary>
                <pre>{{ JSON.stringify(step.usage, null, 2) }}</pre>
              </details>
            </div>
          </div>
        </div>
      </div>

      <!-- 配置快照 -->
      <div v-if="run.config_snapshot" class="section">
        <details>
          <summary><h3>配置快照</h3></summary>
          <pre class="config-json">{{ JSON.stringify(run.config_snapshot, null, 2) }}</pre>
        </details>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, watch } from 'vue'
import { useRunsStore } from '../stores/runs.js'
import { storeToRefs } from 'pinia'
import TraceId from './TraceId.vue'
import { formatDuration, formatTimestamp, statusClass, statusLabel } from '../utils/runStatus.js'
import {
  errorTypeLabel,
  formatAttempts,
  runAttemptsLabel,
  runErrorInfo,
  traceIdOf,
} from '../utils/runDetails.js'

const props = defineProps({
  runId: {
    type: String,
    required: true,
  },
})

defineEmits(['close'])

const runsStore = useRunsStore()
const { currentRun: run, loading, error } = storeToRefs(runsStore)

// 详情页展示：Trace ID、运行级尝试次数与失败原因（均来自后端记录）。
const traceId = computed(() => traceIdOf(run.value))
const attemptsLabel = computed(() => runAttemptsLabel(run.value))
const errorInfo = computed(() => runErrorInfo(run.value))

onMounted(() => {
  loadDetail()
})

watch(() => props.runId, () => {
  loadDetail()
})

async function loadDetail() {
  if (props.runId) {
    await runsStore.loadRunDetail(props.runId)
  }
}

function getUsageTypeText(usageType) {
  const typeMap = {
    actual: '实际',
    estimated: '估算',
    partial: '部分',
    unknown: '未知',
  }
  return typeMap[usageType] || usageType
}

function stepAttemptsLabel(step) {
  return formatAttempts(step?.attempts)
}
</script>

<style scoped>
.run-detail {
  padding: 20px;
  background: #ffffff;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  max-width: 1200px;
  margin: 0 auto;
}

.loading-state,
.error-state {
  text-align: center;
  padding: 40px;
  color: #666;
}

.run-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 2px solid #e5e7eb;
}

.run-title {
  display: flex;
  align-items: center;
  gap: 12px;
}

.run-title h2 {
  margin: 0;
  font-size: 24px;
  font-weight: 600;
}

.run-info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.info-label {
  font-size: 13px;
  color: #6b7280;
  font-weight: 500;
}

.info-value {
  font-size: 15px;
  color: #111827;
  font-family: monospace;
}

.section {
  margin-bottom: 24px;
}

.section h3 {
  margin: 0 0 12px 0;
  font-size: 18px;
  font-weight: 600;
  color: #111827;
}

.code-block {
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 12px;
  font-family: monospace;
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-word;
}

.code-block.small {
  font-size: 12px;
  padding: 8px;
}

.error-block {
  border-color: #f0c7c7;
  background: #fdf3f3;
  color: #991b1b;
}

.steps-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.step-card {
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 16px;
}

.step-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.step-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.step-number {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  background: #e5e7eb;
  border-radius: 50%;
  font-size: 12px;
  font-weight: 600;
}

.step-agent {
  font-weight: 600;
  color: #111827;
}

.step-meta {
  display: flex;
  gap: 12px;
  font-size: 13px;
  color: #6b7280;
}

.meta-item {
  display: flex;
  align-items: center;
}

.usage-type {
  padding: 2px 8px;
  background: #dbeafe;
  color: #1e40af;
  border-radius: 4px;
  font-size: 11px;
}

.error-type-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  background: #fee2e2;
  color: #991b1b;
  font-size: 11px;
  font-weight: 500;
  vertical-align: middle;
}

.meta-item.attempts {
  padding: 2px 8px;
  background: #fef3c7;
  color: #92400e;
  border-radius: 4px;
  font-size: 11px;
}

.step-error {
  padding: 12px;
  background: #fee2e2;
  border-left: 3px solid #dc2626;
  border-radius: 4px;
  margin-bottom: 12px;
  font-size: 14px;
  color: #991b1b;
}

.step-output {
  margin-top: 8px;
}

.step-usage {
  margin-top: 8px;
  font-size: 13px;
}

.step-usage details summary {
  cursor: pointer;
  color: #2563eb;
  user-select: none;
}

.step-usage pre {
  margin-top: 8px;
  padding: 8px;
  background: #f3f4f6;
  border-radius: 4px;
  font-size: 12px;
  overflow-x: auto;
}

.config-json {
  margin-top: 12px;
  padding: 12px;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  font-size: 12px;
  overflow-x: auto;
}

details summary {
  cursor: pointer;
  user-select: none;
}

details summary h3 {
  display: inline;
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
