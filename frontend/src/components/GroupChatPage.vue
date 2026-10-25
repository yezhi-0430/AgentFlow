<template>
  <section class="gc-page" aria-label="群聊协作页面">
    <header class="gc-header">
      <button class="gc-back" type="button" @click="$emit('close')">
        <AppIcon name="arrow" :size="16" /> 返回画布
      </button>
      <div class="gc-title">
        <span class="eyebrow">GROUP CHAT</span>
        <h1>{{ selected?.name || '群聊协作' }}</h1>
        <p>{{ membersText }}<span v-if="selected?.requires_credentials"> · 需要重新输入 API Key</span></p>
      </div>
      <div class="gc-header-actions">
        <span class="gc-status"><span class="status-dot" :class="{ pulsing: running }"></span>{{ statusText }}</span>
        <button class="btn btn-secondary" type="button" @click="$emit('create')"><AppIcon name="plus" :size="14" />新建群聊</button>
      </div>
    </header>

    <div class="gc-body">
      <aside class="gc-sidebar" aria-label="群聊列表">
        <div class="gc-sidebar-heading">群聊</div>
        <button
          v-for="group in groupWorkflows"
          :key="group.workflow_id"
          type="button"
          class="gc-group"
          :class="{ selected: group.workflow_id === selectedId }"
          @click="selectWorkflow(group.workflow_id)"
        >
          <span class="gc-group-avatar">{{ (group.name || '群').slice(0, 1) }}</span>
          <span class="gc-group-copy">
            <strong>{{ group.name }}</strong>
            <small>{{ groupModelSummary(group) }}</small>
          </span>
          <span class="status-dot" :class="{ ready: !group.requires_credentials }"></span>
        </button>
        <p v-if="!groupWorkflows.length" class="gc-empty">还没有群聊工作流。</p>
      </aside>

      <main class="gc-room">
        <div v-if="!selected" class="gc-room-empty">
          <AppIcon name="message" :size="28" />
          <h2>选择一个群聊</h2>
          <p>从左侧选择，或新建一个群聊。</p>
        </div>
        <template v-else>
          <div ref="scrollBox" class="gc-messages" aria-live="polite">
            <button v-if="hasEarlier" class="gc-earlier" type="button" @click="loadEarlier">
              加载更早消息
            </button>
            <div v-if="!timeline.length" class="gc-messages-empty">
              <p>输入任务后开始群聊；每轮发言会显示在这里。</p>
            </div>
            <template v-for="item in timeline" :key="item.id">
              <div v-if="item.type === 'divider'" class="gc-run-divider">
                <span>第 {{ runIndex(item.runId) }} 次运行</span>
              </div>
              <article v-else class="gc-message" :class="item.kind">
                <div class="gc-avatar" :style="{ background: avatarFor(item.sender, item.model).color }">
                  {{ avatarFor(item.sender, item.model).initials }}
                </div>
                <div class="gc-bubble-wrap">
                  <header class="gc-bubble-meta">
                    <strong>{{ item.sender }}</strong>
                    <span v-if="item.model" class="gc-model">{{ modelLabel(item.model) }}</span>
                    <span v-if="item.role" class="gc-role">{{ item.role }}</span>
                    <time>{{ formatTime(item.timestamp) }}</time>
                  </header>
                  <div class="gc-bubble">
                    <p>{{ item.content }}</p>
                  </div>
                </div>
              </article>
            </template>
            <article v-if="typing" class="gc-message chat typing">
              <div class="gc-avatar" :style="{ background: avatarFor(activeAgent, activeModel).color }">
                {{ avatarFor(activeAgent, activeModel).initials }}
              </div>
              <div class="gc-bubble-wrap">
                <header class="gc-bubble-meta"><strong>{{ activeAgent }}</strong><span class="gc-model">{{ modelLabel(activeModel) }}</span></header>
                <div class="gc-bubble"><p>正在发言<span class="gc-dots">…</span></p></div>
              </div>
            </article>
          </div>

          <p v-if="error" class="gc-error" role="alert">{{ error }}</p>
          <form class="gc-composer" @submit.prevent="run">
            <input
              v-if="selected.requires_credentials"
              v-model="apiKey"
              type="password"
              class="gc-key"
              placeholder="重新输入 OpenRouter API Key"
              autocomplete="off"
            />
            <textarea v-model="task" rows="2" placeholder="输入群聊任务，例如：讨论并给出这个功能的设计方案" :disabled="running"></textarea>
            <div class="gc-composer-actions">
              <span class="hint">Lead 会决定下一位发言者；无 Lead 时成员轮流发言。</span>
              <button v-if="running" class="btn btn-secondary" type="button" @click="stop">停止</button>
              <button v-else class="btn btn-primary" type="submit" :disabled="!task.trim()">开始群聊<AppIcon name="arrow" :size="15" /></button>
            </div>
          </form>
        </template>
      </main>

      <aside class="gc-members" aria-label="群聊成员">
        <div class="gc-sidebar-heading">成员</div>
        <div v-for="member in members" :key="member.name" class="gc-member">
          <div class="gc-avatar small" :style="{ background: avatarFor(member.name, member.model).color }">
            {{ avatarFor(member.name, member.model).initials }}
          </div>
          <div>
            <strong>{{ member.name }}<span v-if="member.role === 'coordinator'" class="gc-lead">Lead</span></strong>
            <small>{{ modelLabel(member.model) }}</small>
          </div>
        </div>
        <p v-if="!members.length" class="gc-empty">暂无成员信息。</p>
      </aside>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import { useWorkflowStore } from '../stores/workflow'
import { messageService, workflowService } from '../services/workflow'
import { isGroupChatTerminal, normalizeGroupChatMessages } from '../utils/groupChat'
import { avatarFor } from '../utils/avatars'

const props = defineProps({ workflowId: { type: String, default: '' } })
const emit = defineEmits(['close', 'create', 'select'])

const workflowStore = useWorkflowStore()
const selectedId = ref(props.workflowId || '')
const rawMessages = ref([])
const task = ref('')
const apiKey = ref('')
const running = ref(false)
const statusText = ref('idle')
const activeAgent = ref('')
const activeModel = ref('')
const error = ref('')
const scrollBox = ref(null)
const hasEarlier = ref(false)
let pollTimer = null

const groupWorkflows = computed(() => (workflowStore.workflows || []).filter(workflow => workflow.pattern === 'group_chat'))
const selected = computed(() => groupWorkflows.value.find(workflow => workflow.workflow_id === selectedId.value) || null)
const members = computed(() => selected.value?.agents || [])
const membersText = computed(() => members.value.length ? members.value.map(member => member.name).join('、') : '共享群聊')
const messages = computed(() => normalizeGroupChatMessages(rawMessages.value).filter(message => message.kind))
const timeline = computed(() => {
  const items = []
  let lastRun = ''
  for (const message of messages.value) {
    if (message.runId && message.runId !== lastRun) {
      items.push({ type: 'divider', id: `run-${message.runId}`, runId: message.runId })
      lastRun = message.runId
    }
    items.push({ ...message, type: 'message' })
  }
  return items
})
const typing = computed(() => running.value && Boolean(activeAgent.value))

function modelLabel(model) {
  if (!model) return ''
  return String(model).split('/').pop()
}

function runIndex(runId) {
  const ids = [...new Set(messages.value.map(message => message.runId).filter(Boolean))]
  return Math.max(1, ids.indexOf(runId) + 1)
}

function groupModelSummary(group) {
  const models = [...new Set((group.agents || []).map(agent => modelLabel(agent.model)).filter(Boolean))]
  return models.join(' · ') || `${(group.agents || []).length} 个成员`
}

function formatTime(value) {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function clearPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function scrollToBottom() {
  await nextTick()
  if (scrollBox.value) scrollBox.value.scrollTop = scrollBox.value.scrollHeight
}

async function loadMessages({ before } = {}) {
  if (!selectedId.value) return
  try {
    const data = await messageService.getMessages(selectedId.value, before ? { before, limit: 50 } : { limit: 50 })
    const incoming = normalizeGroupChatMessages(data?.messages || []).filter(message => message.kind)
    if (before) {
      const known = new Set(rawMessages.value.map(message => message.id))
      rawMessages.value = [...incoming.filter(message => !known.has(message.id)), ...rawMessages.value]
    } else {
      rawMessages.value = incoming
      hasEarlier.value = (data?.messages || []).length >= 50
      scrollToBottom()
    }
  } catch {
    rawMessages.value = before ? rawMessages.value : []
  }
}

async function loadEarlier() {
  const first = rawMessages.value.find(message => message.timestamp)
  if (first?.timestamp) await loadMessages({ before: first.timestamp })
}

async function syncStatus() {
  if (!selectedId.value) return
  try {
    const data = await workflowService.getWorkflowStatus(selectedId.value)
    statusText.value = data.status || 'idle'
    running.value = ['executing', 'running', 'stopping', 'paused'].includes(String(statusText.value).toLowerCase())
    activeAgent.value = data.active_agent || ''
    activeModel.value = data.active_model || ''
    if (isGroupChatTerminal(statusText.value)) {
      activeAgent.value = ''
      activeModel.value = ''
      clearPoll()
    }
  } catch {
    // 状态读取失败时保留当前页面，下一次轮询继续。
  }
}

function startPoll() {
  clearPoll()
  pollTimer = setInterval(async () => {
    await loadMessages()
    await syncStatus()
  }, 1200)
}

async function selectWorkflow(workflowId) {
  selectedId.value = workflowId
  emit('select', workflowId)
  error.value = ''
  rawMessages.value = []
  clearPoll()
  await loadMessages()
  await syncStatus()
  startPoll()
}

async function run() {
  if (!selectedId.value || !task.value.trim() || running.value) return
  if (selected.value?.requires_credentials && !apiKey.value.trim()) {
    error.value = '请先输入 OpenRouter API Key'
    return
  }
  error.value = ''
  try {
    await workflowService.executeWorkflow(selectedId.value, {
      task: task.value.trim(),
      ...(apiKey.value.trim() ? { api_key: apiKey.value.trim() } : {}),
    })
    task.value = ''
    running.value = true
    startPoll()
    await loadMessages()
  } catch (requestError) {
    error.value = requestError.response?.data?.detail || '群聊启动失败'
  }
}

async function stop() {
  if (!selectedId.value) return
  try {
    await workflowService.stopWorkflow(selectedId.value)
    await syncStatus()
  } catch {
    error.value = '停止失败，请稍后重试'
  }
}

watch(() => props.workflowId, workflowId => {
  if (workflowId && workflowId !== selectedId.value) selectWorkflow(workflowId)
})

onMounted(async () => {
  await workflowStore.loadWorkflows()
  if (!selectedId.value) selectedId.value = groupWorkflows.value[0]?.workflow_id || ''
  if (selectedId.value) {
    await loadMessages()
    await syncStatus()
    startPoll()
  }
})

onBeforeUnmount(clearPoll)
</script>

<style scoped>
.gc-page { position: fixed; inset: 0; z-index: 30; display: flex; flex-direction: column; background: #f4f6f5; color: #172121; }
.gc-header { display: flex; align-items: center; gap: 18px; padding: 14px 22px; border-bottom: 1px solid #d9e2e1; background: #fff; }
.gc-back { display: inline-flex; align-items: center; gap: 6px; border: 0; background: transparent; color: #2f6f78; cursor: pointer; font: inherit; }
.gc-title { flex: 1; min-width: 0; }
.gc-title h1 { margin: 2px 0; font-size: 18px; }
.gc-title p { margin: 0; color: #5f6b6b; font-size: 12px; }
.gc-header-actions { display: flex; align-items: center; gap: 12px; }
.gc-status { display: inline-flex; align-items: center; gap: 6px; color: #5f6b6b; font-size: 12px; }
.gc-body { flex: 1; min-height: 0; display: grid; grid-template-columns: 230px minmax(0, 1fr) 220px; }
.gc-sidebar, .gc-members { padding: 18px 12px; background: #fff; overflow-y: auto; }
.gc-sidebar { border-right: 1px solid #d9e2e1; }
.gc-members { border-left: 1px solid #d9e2e1; }
.gc-sidebar-heading { margin: 0 8px 10px; color: #5f6b6b; font-size: 11px; font-weight: 700; letter-spacing: .08em; }
.gc-group { display: flex; align-items: center; gap: 9px; width: 100%; padding: 9px; border: 0; border-radius: 10px; background: transparent; text-align: left; cursor: pointer; }
.gc-group:hover, .gc-group.selected { background: #eef4f3; }
.gc-group-avatar { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 9px; background: #2f6f78; color: #fff; font-weight: 700; }
.gc-group-copy { flex: 1; min-width: 0; }
.gc-group-copy strong, .gc-group-copy small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gc-group-copy small { color: #5f6b6b; font-size: 11px; }
.gc-room { min-width: 0; display: flex; flex-direction: column; }
.gc-messages { flex: 1; overflow-y: auto; padding: 22px 28px 12px; }
.gc-room-empty, .gc-messages-empty { margin: auto; text-align: center; color: #5f6b6b; }
.gc-earlier { display: block; margin: 0 auto 16px; border: 1px solid #d9e2e1; border-radius: 999px; background: #fff; color: #2f6f78; padding: 4px 12px; cursor: pointer; }
.gc-run-divider { display: flex; align-items: center; gap: 10px; margin: 18px 0; color: #8a9696; font-size: 11px; }
.gc-run-divider::before, .gc-run-divider::after { content: ''; height: 1px; flex: 1; background: #d9e2e1; }
.gc-message { display: flex; gap: 10px; margin: 0 0 16px; max-width: 78%; }
.gc-message.system { max-width: 100%; justify-content: center; }
.gc-message.system .gc-avatar { display: none; }
.gc-message.system .gc-bubble { background: transparent; color: #6b7777; font-size: 12px; text-align: center; }
.gc-message.tool { max-width: 88%; }
.gc-message.tool .gc-bubble { background: #f1f5f4; border: 1px dashed #b9c8c6; }

@keyframes gc-dots { 0%, 100% { opacity: .25; } 50% { opacity: 1; } }
.gc-avatar { flex: 0 0 auto; display: grid; place-items: center; width: 34px; height: 34px; border-radius: 10px; color: #fff; font-weight: 700; font-size: 13px; margin-top: 2px; }
.gc-avatar.small { width: 30px; height: 30px; border-radius: 9px; margin: 0; font-size: 12px; }
.gc-bubble-wrap { min-width: 0; }
.gc-bubble-meta { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; color: #5f6b6b; font-size: 11px; }
.gc-bubble-meta strong { color: #172121; font-size: 12px; }
.gc-model { padding: 1px 6px; border-radius: 999px; background: #e6efee; color: #2f6f78; font-size: 10px; }
.gc-role { color: #8a9696; }
.gc-bubble-meta time { margin-left: auto; color: #9aa5a5; }
.gc-bubble { padding: 9px 12px; border-radius: 4px 14px 14px 14px; background: #fff; box-shadow: 0 1px 2px rgba(23,33,33,.06); line-height: 1.65; white-space: pre-wrap; word-break: break-word; }
.gc-bubble p { margin: 0; }
.typing .gc-bubble { color: #5f6b6b; }
.gc-dots { animation: gc-dots 1.1s infinite; }
.gc-composer { padding: 12px 22px 18px; border-top: 1px solid #d9e2e1; background: #fff; }
.gc-key { width: 100%; margin-bottom: 8px; padding: 8px 10px; border: 1px solid #d9e2e1; border-radius: 8px; font: inherit; }
.gc-composer textarea { width: 100%; resize: vertical; border: 1px solid #d9e2e1; border-radius: 10px; padding: 10px; font: inherit; box-sizing: border-box; }
.gc-composer-actions { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 8px; }
.gc-error { margin: 0 22px 8px; color: #b42318; font-size: 12px; }
.gc-member { display: flex; align-items: center; gap: 8px; padding: 8px 6px; }
.gc-member strong, .gc-member small { display: block; }
.gc-member small { color: #5f6b6b; font-size: 11px; }
.gc-lead { margin-left: 5px; padding: 1px 5px; border-radius: 999px; background: #2f6f78; color: #fff; font-size: 9px; }
.gc-empty { padding: 10px; color: #8a9696; font-size: 12px; }
@media (max-width: 900px) {
  .gc-body { grid-template-columns: 180px minmax(0, 1fr); }
  .gc-members { display: none; }
}
</style>
