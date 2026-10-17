<template>
  <section class="execution-console" aria-label="执行控制">
    <div v-if="store.currentWorkflow" class="execution-task">
      <label for="execution-task">本次任务<span>{{ store.currentWorkflow.isDemo ? '示例仅用于查看编排，请创建工作流后运行' : '确认任务后开始运行，结果将在消息时间线显示' }}</span></label>
      <textarea id="execution-task" v-model="task" rows="2" :disabled="store.isRunning || store.currentWorkflow.isDemo" placeholder="输入要交给智能体完成的任务…" />
    </div>
    <div v-if="store.executionError" class="execution-notice" role="alert"><AppIcon name="message" :size="16" /><span>{{ store.executionError }}</span><button class="btn btn-secondary" :disabled="store.isRunning" @click="emit('configure', task)">重新配置模型</button></div>
    <div v-if="store.connectionError" class="execution-notice" role="status"><span>{{ store.connectionError }}</span><button class="btn btn-quiet" @click="store.refreshExecution()">重新同步</button></div>
    <div class="execution-bar">
      <div class="execution-controls">
        <span class="execution-label"><AppIcon name="play" :size="15" />执行控制</span>
        <div class="execution-buttons">
          <button class="btn btn-primary" :disabled="!canRun" @click="store.startExecution(task)"><AppIcon name="play" :size="13" />{{ store.submitting ? '正在提交…' : store.isRunning ? '运行中…' : store.status === 'completed' || store.status === 'error' ? '重新运行' : '开始运行' }}</button>
          <span v-if="store.isRunning" class="execution-hint" role="status">正在等待模型响应…</span>
        </div>
      </div>
      <div class="execution-status" aria-live="polite"><span><span class="status-dot" :class="{ pulsing: store.isRunning }"></span>{{ statusLabels[store.status] || store.status }}</span><span class="execution-separator"></span><span>步骤 <strong>{{ store.currentStep }}<span class="muted"> / {{ store.totalSteps }}</span></strong></span><span>消息 <strong>{{ messageStore.messages.length }}</strong></span></div>
    </div>
  </section>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import { useWorkflowStore } from '../stores/workflow'
import { useMessageStore } from '../stores/messages'
const store = useWorkflowStore()
const emit = defineEmits(['configure'])
const messageStore = useMessageStore()
const task = ref('')
const canRun = computed(() => Boolean(store.currentWorkflow?.workflow_id && !store.currentWorkflow.isDemo && task.value.trim() && !store.isRunning && !store.deleting))
const statusLabels = { idle: '等待运行', created: '等待运行', executing: '正在启动', running: '运行中', completed: '已完成', error: '运行异常', paused: '已暂停', stopped: '已停止' }
watch(() => store.currentWorkflow, workflow => { task.value = workflow?.description?.trim() || workflow?.name || '' }, { immediate: true })
</script>
