<template>
  <section class="execution-console" aria-label="执行控制">
    <div v-if="store.currentWorkflow" class="execution-task">
      <label for="execution-task">本次任务<span>{{ store.currentWorkflow.isDemo ? '示例仅用于查看编排，请创建工作流后运行' : '确认任务后开始运行，结果将在消息时间线显示' }}</span></label>
      <textarea id="execution-task" v-model="task" rows="2" :disabled="store.isRunning || store.currentWorkflow.isDemo" placeholder="输入要交给智能体完成的任务…" />
    </div>
    <div v-if="store.requiresCredentials && !store.currentWorkflow?.isDemo" class="execution-credential" role="group" aria-labelledby="execution-credential-title">
      <div class="execution-credential-heading">
        <AppIcon name="key" :size="15" />
        <strong id="execution-credential-title">需要重新输入 API Key</strong>
        <span>连接配置已保留，密钥未保存</span>
      </div>
      <div class="execution-key-input">
        <input
          id="execution-api-key"
          ref="keyInput"
          v-model="apiKey"
          :type="showApiKey ? 'text' : 'password'"
          placeholder="输入 API Key（只在本次执行时提交，不会保存）"
          autocomplete="off"
          autocapitalize="off"
          spellcheck="false"
          :disabled="store.isRunning || store.submitting"
          :aria-invalid="isMissingKeyError"
          aria-describedby="execution-key-hint"
          @keydown.enter.prevent="run"
        />
        <button class="icon-button" type="button" :aria-label="showApiKey ? '隐藏 API Key' : '显示 API Key'" :aria-pressed="showApiKey" :disabled="store.isRunning || store.submitting" @click="showApiKey = !showApiKey">
          <AppIcon :name="showApiKey ? 'eyeOff' : 'eye'" :size="16" />
        </button>
      </div>
      <p id="execution-key-hint" class="execution-key-hint">该工作流由服务重启恢复或由定义导入，连接配置已保留，但 API Key 不会随工作流保存。密钥仅在本次执行请求中提交，请求结束后输入框会自动清空，也不会写入本地存储。</p>
    </div>
    <div v-if="store.executionError" class="execution-notice" role="alert"><AppIcon name="message" :size="16" /><span>{{ store.executionError }}</span><button v-if="!isMissingKeyError" class="btn btn-secondary" :disabled="store.isRunning" @click="emit('configure', task)">重新配置模型</button></div>
    <div v-if="store.stopError" class="execution-notice execution-stop-notice" role="status"><AppIcon name="stop" :size="16" /><span>{{ store.stopError }}</span><button class="btn btn-quiet" type="button" :disabled="store.stopping" @click="refreshStopState">重新同步</button></div>
    <div v-if="store.connectionError" class="execution-notice" role="status"><span>{{ store.connectionError }}</span><button class="btn btn-quiet" @click="store.refreshExecution()">重新同步</button></div>
    <div v-if="latestRun" class="latest-run" aria-label="最近一次运行">
      <span class="latest-run-label"><AppIcon name="history" :size="14" />最近运行</span>
      <code class="latest-run-id" :title="latestRun.run_id">{{ truncateId(latestRun.run_id) }}</code>
      <span class="latest-run-status" :class="'is-' + statusTone(latestRun.status)" :title="latestRun.error || ''">{{ statusLabel(latestRun.status) }}</span>
      <span v-if="latestRun.created_at" class="latest-run-time">{{ formatTimestamp(latestRun.created_at) }}</span>
      <button class="btn btn-quiet latest-run-refresh" type="button" title="从后端刷新最近运行状态" @click="refreshLatestRun"><AppIcon name="refresh" :size="13" />刷新</button>
      <button class="btn btn-quiet" type="button" @click="emit('history')"><AppIcon name="history" :size="13" />运行历史</button>
    </div>
    <div class="execution-bar">
      <div class="execution-controls">
        <span class="execution-label"><AppIcon name="play" :size="15" />执行控制</span>
        <div class="execution-buttons">
          <button class="btn btn-primary" :disabled="!canRun" @click="run"><AppIcon name="play" :size="13" />{{ store.submitting ? '正在提交…' : store.isStopping ? '停止中…' : store.isRunning ? '运行中…' : isTerminalExecutionStatus(store.status) ? '重新运行' : '开始运行' }}</button>
          <button
            v-if="store.isRunning && !store.currentWorkflow?.isDemo"
            class="btn btn-secondary stop-button"
            type="button"
            :disabled="store.stopping || store.submitting || store.status === 'stopping'"
            :title="store.status === 'stopping' ? '已请求停止，正在等待当前调用结束' : '停止当前运行（已完成的步骤会保留）'"
            @click="stopRun"
          >
            <AppIcon name="stop" :size="13" />{{ store.isStopping ? '正在停止…' : '停止运行' }}
          </button>
          <span v-if="store.isRunning" class="execution-hint" role="status">{{ store.isStopping ? '正在停止，等待当前调用结束…' : '正在等待模型响应…' }}</span>
        </div>
      </div>
      <div class="execution-status" aria-live="polite"><span><span class="status-dot" :class="{ pulsing: store.isRunning }"></span>{{ statusLabels[store.status] || store.status }}</span><span class="execution-separator"></span><span>步骤 <strong>{{ store.currentStep }}<span class="muted"> / {{ store.totalSteps }}</span></strong></span><span>消息 <strong>{{ messageStore.messages.length }}</strong></span></div>
    </div>
  </section>
</template>
<script setup>
import { computed, ref, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import AppIcon from './AppIcon.vue'
import { useWorkflowStore } from '../stores/workflow'
import { useMessageStore } from '../stores/messages'
import { useRunsStore } from '../stores/runs'
import { formatTimestamp, isTerminalExecutionStatus, statusLabel, statusTone, truncateId } from '../utils/runStatus.js'
import { MISSING_KEY_MESSAGE } from '../utils/credentialState.js'
const store = useWorkflowStore()
const runsStore = useRunsStore()
const emit = defineEmits(['configure', 'history'])
const messageStore = useMessageStore()
const task = ref('')
// 只存在于组件内存中的临时密钥输入，执行结束立即清空，绝不进入 store / localStorage。
const apiKey = ref('')
const showApiKey = ref(false)
const keyInput = ref(null)
let retryTimer
const canRun = computed(() => Boolean(store.currentWorkflow?.workflow_id && !store.currentWorkflow.isDemo && task.value.trim() && !store.isRunning && !store.deleting))
const isMissingKeyError = computed(() => store.executionError === MISSING_KEY_MESSAGE)
const statusLabels = { idle: '等待运行', created: '等待运行', executing: '正在启动', running: '运行中', stopping: '停止中', completed: '已完成', partial: '部分完成', failed: '失败', cancelled: '已取消', error: '运行异常', paused: '已暂停', stopped: '已停止' }
// 后端因缺少密钥拒绝执行时，把焦点放回密钥输入框，方便立即补填。
watch(() => store.executionError, error => {
  if (error === MISSING_KEY_MESSAGE) nextTick(() => keyInput.value?.focus())
})
// 最近运行优先展示后端运行记录；刚提交、尚未落库时退回执行接口返回的 run_id。
const latestRun = computed(() => {
  const stored = runsStore.latestRun
  const runId = store.currentRunId
  if (runId && (!stored || stored.run_id !== runId)) {
    return { run_id: runId, status: store.runStatus || 'running', created_at: null }
  }
  return stored || null
})
watch(() => store.currentWorkflow, workflow => { task.value = workflow?.description?.trim() || workflow?.name || '' }, { immediate: true })
watch(() => store.currentWorkflow?.workflow_id, (id, previous) => {
  // 切换工作流时清空上一份密钥输入，避免误提交到另一个工作流。
  apiKey.value = ''
  showApiKey.value = false
  if (id !== previous) loadLatestRun()
})
// 执行进入终态后重新从后端取一次运行记录，刷新页面后同样以服务端为准。
watch(() => store.status, status => { if (isTerminalExecutionStatus(status)) loadLatestRun() })
onMounted(() => loadLatestRun())
onBeforeUnmount(() => clearTimeout(retryTimer))
async function run() {
  const submittedKey = apiKey.value
  try {
    await store.startExecution(task.value, submittedKey)
  } finally {
    // 无论成功、失败还是被后端拒绝，请求结束后都不在界面保留密钥。
    apiKey.value = ''
    showApiKey.value = false
  }
}
async function loadLatestRun(retry = true) {
  clearTimeout(retryTimer)
  const workflow = store.currentWorkflow
  if (!workflow?.workflow_id || workflow.isDemo) {
    runsStore.clearLatestRun()
    return
  }
  const workflowId = workflow.workflow_id
  const run = await runsStore.loadLatestRun(workflowId)
  // 运行记录可能在状态变为终态后才落库，缺失时短暂重试一次。
  if (!run && retry && isTerminalExecutionStatus(store.status) && store.currentWorkflow?.workflow_id === workflowId) {
    retryTimer = setTimeout(() => loadLatestRun(false), 1200)
  }
}
function refreshLatestRun() {
  loadLatestRun()
}
// 停止运行：状态归一化与终态轮询都在 store 内完成，这里只触发一次请求。
async function stopRun() {
  await store.stopExecution()
}
function refreshStopState() {
  store.refreshExecution()
}
</script>
<style scoped>
.execution-credential { margin-top: 12px; padding: 13px 16px; background: #fff; border: 1px solid #dedee0; border-radius: 9px; }
.execution-credential-heading { display: flex; align-items: center; gap: 8px; color: #444; font-size: 12px; line-height: 1.6; }
.execution-credential-heading > svg { color: #7d7d7d; flex-shrink: 0; }
.execution-credential-heading strong { font-weight: 550; }
.execution-credential-heading span { color: #969696; font-size: 11px; }
.execution-key-input { display: flex; align-items: center; gap: 8px; margin-top: 10px; padding: 0 8px 0 12px; border: 1px solid #dedede; border-radius: 7px; background: #fff; transition: border-color 160ms, box-shadow 160ms; }
.execution-key-input:focus-within { border-color: #727272; box-shadow: 0 0 0 3px #00000005; }
.execution-key-input > svg { color: #999; flex-shrink: 0; }
.execution-key-input input { flex: 1; min-width: 0; border: 0; padding: 10px 0; background: transparent; font: inherit; font-size: 13px; color: #222; }
.execution-key-input input:focus { outline: none; }
.execution-key-input .icon-button { width: 28px; height: 28px; flex-shrink: 0; }
.execution-key-hint { margin-top: 8px; color: #969696; font-size: 11px; line-height: 1.7; }
.execution-stop-notice { border-color: #d9c9a3; background: #f8f4ea; }
</style>
