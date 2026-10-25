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
            <div v-if="!timeline.length" class="gc-empty-chat">
              <div class="gc-avatar-stack">
                <div v-for="member in members.slice(0, 4)" :key="member.name" class="gc-avatar" :style="{ background: avatarFor(member.name, member.model).color }">
                  {{ avatarFor(member.name, member.model).initials }}
                </div>
              </div>
              <h2>开始一场多模型讨论</h2>
              <p>每个成员使用不同模型，Lead 负责分派与总结。输入任务后，他们的讨论会显示在这里。</p>
              <div class="gc-empty-chips">
                <span v-for="member in members" :key="member.name">{{ modelLabel(member.model) }}</span>
              </div>
            </div>
            <template v-for="item in timeline" :key="item.id">
              <div v-if="item.type === 'divider'" class="gc-run-divider">
                <span>第 {{ runIndex(item.runId) }} 次运行</span>
              </div>
              <article v-else class="gc-message" :class="[item.kind, { 'is-lead': item.sender === leadName, 'is-internal': item.kind === 'internal' }]">
                <div class="gc-avatar" :style="{ background: avatarFor(item.sender, item.model).color }">
                  {{ avatarFor(item.sender, item.model).initials }}
                </div>
                <div class="gc-bubble-wrap">
                  <header class="gc-bubble-meta">
                    <strong>{{ item.sender }}</strong>
                    <span v-if="item.model" class="gc-model">{{ modelLabel(item.sender === leadName ? leadModel : item.model) }}</span>
                    <span v-if="item.kind !== 'system'" class="gc-role">{{ item.sender === leadName ? 'coordinator' : item.role }}</span>
                    <time>{{ formatTime(item.timestamp) }}</time>
                  </header>
                  <div class="gc-bubble" :style="item.kind === 'system' ? {} : bubbleStyleFor(item.model, item.sender)">
                    <details v-if="item.kind === 'internal'" class="gc-internal-details">
                      <summary>内部规划 · 点击展开</summary>
                      <pre>{{ item.rawContent || item.content }}</pre>
                    </details>
                    <details v-else-if="item.kind === 'tool' && item.rawContent" class="gc-tool-details">
                      <summary>{{ item.content }}</summary>
                      <pre>{{ item.rawContent }}</pre>
                    </details>
                    <p v-else>{{ item.content }}</p>
                  </div>
                </div>
              </article>
            </template>
            <article v-if="typing" class="gc-message chat typing" :class="{ 'is-lead': activeAgent === leadName }">
              <div class="gc-avatar" :style="{ background: avatarFor(activeAgent, activeModel).color }">
                {{ avatarFor(activeAgent, activeModel).initials }}
              </div>
              <div class="gc-bubble-wrap">
                <header class="gc-bubble-meta"><strong>{{ activeAgent }}</strong><span class="gc-model">{{ modelLabel(activeModel) }}</span></header>
                <div class="gc-bubble" :style="bubbleStyleFor(activeModel, activeAgent)"><p>正在发言<span class="gc-dots">…</span></p></div>
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
              :placeholder="`重新输入 ${keyLabel} API Key`"
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
import { bubbleStyleFor, formatChatTime, isGroupChatTerminal, normalizeGroupChatMessages } from '../utils/groupChat'
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
let requestToken = 0

const groupWorkflows = computed(() => (workflowStore.workflows || []).filter(workflow => workflow.pattern === 'group_chat'))
const selected = computed(() => groupWorkflows.value.find(workflow => workflow.workflow_id === selectedId.value) || null)
const members = computed(() => selected.value?.agents || [])
const leadName = computed(() => members.value.find(member => member.role === 'coordinator')?.name || 'lead')
const leadModel = computed(() => members.value.find(member => member.name === leadName.value)?.model || '')
const membersText = computed(() => members.value.length ? members.value.map(member => member.name).join('、') : '共享群聊')
const keyLabel = computed(() => {
  const provider = selected.value?.connection?.provider || 'openrouter'
  return { openrouter: 'OpenRouter', openai: 'OpenAI', anthropic: 'Anthropic', deepseek: 'DeepSeek' }[provider] || provider
})
const messages = computed(() => rawMessages.value.filter(message => message.kind))
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
  return formatChatTime(value)
}

function clearPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function nearBottom() {
  const box = scrollBox.value
  return !box || box.scrollHeight - box.scrollTop - box.clientHeight < 120
}

async function scrollToBottom() {
  await nextTick()
  if (scrollBox.value) scrollBox.value.scrollTop = scrollBox.value.scrollHeight
}

async function loadMessages({ before, silent = false } = {}) {
  const workflowId = selectedId.value
  const token = requestToken
  if (!workflowId) return
  try {
    const data = await messageService.getMessages(workflowId, before ? { before, limit: 50, include_internal: true } : { limit: 50, include_internal: true })
    if (token !== requestToken || workflowId !== selectedId.value) return
    const incoming = normalizeGroupChatMessages(data?.messages || []).filter(message => message.kind)
    const shouldScroll = !silent && nearBottom()
    if (before) {
      const known = new Set(rawMessages.value.map(message => message.id))
      rawMessages.value = [...incoming.filter(message => !known.has(message.id)), ...rawMessages.value]
      hasEarlier.value = (data?.messages || []).length >= 50
    } else {
      const merged = new Map(rawMessages.value.map(message => [message.id, message]))
      incoming.forEach(message => merged.set(message.id, message))
      rawMessages.value = [...merged.values()].sort((a, b) => Number(a.timestamp || 0) - Number(b.timestamp || 0))
      if (incoming.length >= 50) hasEarlier.value = true
      if (!silent && shouldScroll) await scrollToBottom()
    }
  } catch {
    if (token === requestToken && workflowId === selectedId.value && !before && !silent) error.value = '消息加载失败'
  }
}

async function loadEarlier() {
  const first = rawMessages.value.find(message => message.timestamp)
  if (first?.timestamp) await loadMessages({ before: first.timestamp })
}

async function syncStatus() {
  const workflowId = selectedId.value
  const token = requestToken
  if (!workflowId) return
  try {
    const data = await workflowService.getWorkflowStatus(workflowId)
    if (token !== requestToken || workflowId !== selectedId.value) return
    statusText.value = data.status || 'idle'
    running.value = ['executing', 'running', 'stopping', 'paused'].includes(String(statusText.value).toLowerCase())
    activeAgent.value = data.active_agent || ''
    activeModel.value = data.active_model || ''
    if (data.status === 'failed') error.value = String(data.current_run?.error || '群聊执行失败')
    if (isGroupChatTerminal(statusText.value)) {
      await loadMessages({ silent: true })
      activeAgent.value = ''
      activeModel.value = ''
      clearPoll()
    } else if (running.value) {
      startPoll()
    }
  } catch {
    // 状态读取失败时保留当前页面，下一次轮询继续。
  }
}

function startPoll() {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    await loadMessages({ silent: true })
    await syncStatus()
  }, 1200)
}

async function selectWorkflow(workflowId) {
  requestToken += 1
  selectedId.value = workflowId
  emit('select', workflowId)
  error.value = ''
  rawMessages.value = []
  hasEarlier.value = false
  running.value = false
  statusText.value = 'idle'
  activeAgent.value = ''
  activeModel.value = ''
  task.value = ''
  apiKey.value = ''
  clearPoll()
  await loadMessages()
  await syncStatus()
  if (running.value) startPoll()
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

watch(() => props.workflowId, async workflowId => {
  if (workflowId && workflowId !== selectedId.value) {
    await workflowStore.loadWorkflows()
    await selectWorkflow(workflowId)
  }
})

onMounted(async () => {
  await workflowStore.loadWorkflows()
  if (!selectedId.value) selectedId.value = groupWorkflows.value[0]?.workflow_id || ''
  if (selectedId.value) {
    requestToken += 1
    emit('select', selectedId.value)
    await loadMessages()
    await syncStatus()
    if (running.value) startPoll()
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
.gc-message.system { max-width: 100%; justify-content: flex-start; }
.gc-message.system .gc-avatar { display: none; }
.gc-message.system .gc-bubble { background: transparent; color: #6b7777; font-size: 12px; text-align: left; }
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

/* Align the full-screen page with AgentFlow's white/black workbench theme. */
.gc-page { background: #fff; color: #191919; }
.gc-header { background: #fff; border-bottom-color: #e8e8e8; }
.gc-back { color: #191919; }
.gc-title p, .gc-status, .gc-sidebar-heading, .gc-member small { color: #838383; }
.gc-body { background: #fff; }
.gc-sidebar { background: #fff; border-right-color: #e8e8e8; }
.gc-members { background: #fff; border-left-color: #e8e8e8; }
.gc-room { background: #f6f6f6; }
.gc-group { border: 1px solid transparent; }
.gc-group:hover { background: #f6f6f6; }
.gc-group.selected { background: #191919; color: #fff; border-color: #191919; }
.gc-group.selected small { color: #c9c9c9; }
.gc-group-avatar { background: #191919; border-radius: 7px; }
.gc-group.selected .gc-group-avatar { background: #fff; color: #191919; }
.gc-messages { scrollbar-width: thin; scrollbar-color: #c9c9c9 transparent; overscroll-behavior: contain; scroll-behavior: smooth; }
.gc-messages::-webkit-scrollbar { width: 8px; }
.gc-messages::-webkit-scrollbar-thumb { background: #d2d2d2; border-radius: 999px; }
.gc-bubble { background: #fff; border: 1px solid #ededed; box-shadow: 0 1px 2px #00000008; }
.gc-model { background: #f0f0f0; color: #444; }
.gc-message.system .gc-bubble { background: transparent; border: 0; box-shadow: none; color: #838383; }
.gc-message.tool .gc-bubble { background: #fff; border: 1px dashed #cfcfcf; }
.gc-tool-details summary { cursor: pointer; color: #191919; font-weight: 600; }
.gc-tool-details pre { margin: 8px 0 0; max-height: 220px; overflow: auto; white-space: pre-wrap; color: #666; font: 11px/1.5 ui-monospace, Consolas, monospace; }
.gc-run-divider { color: #9a9a9a; }
.gc-run-divider::before, .gc-run-divider::after { background: #e2e2e2; }
.gc-earlier { border-color: #dedede; color: #191919; background: #fff; }
.gc-composer { background: #fff; border-top-color: #e8e8e8; }
.gc-composer textarea, .gc-key { border-color: #dedede; background: #fff; }
.gc-composer textarea:focus, .gc-key:focus { outline: none; border-color: #191919; box-shadow: 0 0 0 3px #1919190d; }
.gc-composer-actions .btn-primary { background: #191919; border-color: #191919; color: #fff; }
.gc-header-actions .btn-secondary { background: #191919; border-color: #191919; color: #fff; }
.gc-header-actions .btn-secondary:hover { background: #333; }
.gc-lead { background: #191919; }
.gc-empty-chat { margin: auto; max-width: 430px; padding: 36px 22px; text-align: center; color: #666; }
.gc-empty-chat h2 { margin: 16px 0 6px; color: #191919; font-size: 17px; }
.gc-empty-chat p { margin: 0; line-height: 1.8; font-size: 12px; }
.gc-avatar-stack { display: flex; justify-content: center; }
.gc-avatar-stack .gc-avatar { margin: 0 -5px; border: 3px solid #f6f6f6; }
.gc-empty-chips { display: flex; flex-wrap: wrap; justify-content: center; gap: 6px; margin-top: 16px; }
.gc-empty-chips span { padding: 3px 8px; border: 1px solid #e2e2e2; border-radius: 999px; background: #fff; color: #666; font-size: 10px; }
.gc-message { animation: gc-message-in 260ms cubic-bezier(.22, 1, .36, 1); }
.gc-message.is-lead { margin-left: auto; flex-direction: row-reverse; width: fit-content; max-width: 78%; }
.gc-message.is-lead .gc-bubble-wrap { align-items: flex-end; }
.gc-message.is-lead .gc-bubble-meta { justify-content: flex-end; }
.gc-message.is-lead .gc-bubble { border-bottom-left-radius: 14px; border-bottom-right-radius: 4px; }
.gc-message.is-lead .gc-bubble p, .gc-message.is-lead .gc-bubble summary { color: #fff; }
.gc-message.is-lead .gc-bubble pre { color: #d6d6d6; }
.gc-message.is-lead.system { width: fit-content; max-width: 88%; justify-content: flex-end; margin-left: auto; }
.gc-message.is-lead.system .gc-bubble { background: #191919; border: 1px solid #191919; color: #fff; text-align: right; }
.gc-message.is-lead.system .gc-bubble p { color: #fff; }
.gc-message.is-internal { max-width: 92%; }
.gc-internal-details summary { cursor: pointer; color: #666; font-weight: 600; }
.gc-internal-details pre { margin: 8px 0 0; max-height: 260px; overflow: auto; white-space: pre-wrap; color: #666; font: 11px/1.5 ui-monospace, Consolas, monospace; }
.gc-message.is-lead .gc-internal-details summary, .gc-message.is-lead .gc-internal-details pre { color: #d6d6d6; }
@keyframes gc-message-in { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
</style>
