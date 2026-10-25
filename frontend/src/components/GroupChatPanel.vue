<template>
  <button
    class="rail-button"
    :class="{ 'is-on': isOpen }"
    title="群聊协作 · 多 Agent 共享对话"
    aria-label="打开群聊协作"
    @click="toggle"
  >
    <AppIcon name="message" /><span class="nav-label">群聊</span><span class="nav-count">{{ groupWorkflows.length }}</span>
  </button>

  <Teleport to="body">
    <Transition name="group-chat-fade">
      <section v-if="isOpen" class="group-chat-overlay" aria-label="群聊协作面板" @click.self="close">
        <div class="group-chat-panel" role="dialog" aria-modal="true" aria-labelledby="group-chat-title">
          <header class="group-chat-header">
            <div>
              <span class="eyebrow">GROUP CHAT</span>
              <h2 id="group-chat-title">群聊协作</h2>
              <p>多个 Agent 共享一份对话记录；可选 Lead 分派与总结。</p>
            </div>
            <div class="group-chat-header-actions">
              <button class="btn btn-secondary" type="button" @click="createGroup"><AppIcon name="plus" :size="14" />新建群聊</button>
              <button class="icon-button" type="button" aria-label="关闭群聊面板" @click="close"><AppIcon name="close" :size="19" /></button>
            </div>
          </header>

          <div class="group-chat-body">
            <aside class="group-chat-list" aria-label="群聊列表">
              <div v-if="!groupWorkflows.length" class="group-chat-list-empty">
                <p>还没有群聊工作流。</p>
                <button class="btn btn-primary" type="button" @click="createGroup"><AppIcon name="plus" :size="14" />创建一个群聊</button>
              </div>
              <button
                v-for="workflow in groupWorkflows"
                :key="workflow.workflow_id"
                class="group-chat-list-item"
                :class="{ selected: workflow.workflow_id === selectedId }"
                type="button"
                @click="selectWorkflow(workflow.workflow_id)"
              >
                <span class="group-chat-avatar">{{ (workflow.name || '群').slice(0, 1) }}</span>
                <span class="group-chat-list-copy">
                  <strong>{{ workflow.name }}</strong>
                  <small>{{ (workflow.agents || []).length }} 个成员</small>
                </span>
                <span class="status-dot" :class="{ ready: !workflow.requires_credentials }"></span>
              </button>
            </aside>

            <main class="group-chat-room" aria-label="群聊内容">
              <div v-if="!selected" class="group-chat-room-empty">
                <AppIcon name="message" :size="24" />
                <h3>选择一个群聊</h3>
                <p>从左侧选择，或创建一个新的群聊工作流。</p>
              </div>
              <template v-else>
                <div class="group-chat-room-header">
                  <div>
                    <h3>{{ selected.name }}</h3>
                    <p>{{ membersText }}<span v-if="selected.requires_credentials"> · 需要重新输入 API Key</span></p>
                  </div>
                  <div class="group-chat-status">
                    <span class="status-dot" :class="{ pulsing: running }"></span>
                    <span>{{ statusText }}</span>
                  </div>
                </div>

                <div class="group-chat-messages" aria-live="polite">
                  <div v-if="!messages.length" class="group-chat-messages-empty">
                    <p>输入任务后开始群聊；Agent 的发言会显示在这里。</p>
                  </div>
                  <article v-for="message in messages" :key="message.id" class="group-chat-message">
                    <header>
                      <strong>{{ message.sender }}</strong>
                      <AppIcon name="arrow" :size="12" />
                      <span>{{ message.receiver }}</span>
                      <time v-if="message.timestamp">{{ formatTime(message.timestamp) }}</time>
                    </header>
                    <p>{{ message.content }}</p>
                  </article>
                </div>

                <p v-if="error" class="group-chat-error" role="alert">{{ error }}</p>

                <form class="group-chat-composer" @submit.prevent="run">
                  <input
                    v-if="selected.requires_credentials"
                    v-model="apiKey"
                    type="password"
                    class="group-chat-api-key"
                    placeholder="重新输入 API Key"
                    autocomplete="off"
                  />
                  <textarea
                    v-model="task"
                    rows="2"
                    placeholder="输入群聊任务，例如：讨论并给出这个功能的设计方案"
                    :disabled="running"
                    aria-label="群聊任务"
                  ></textarea>
                  <div class="group-chat-composer-actions">
                    <span class="hint">Lead 会决定下一位发言者；无 Lead 时成员轮流发言。</span>
                    <button v-if="running" class="btn btn-secondary" type="button" @click="stop">停止</button>
                    <button v-else class="btn btn-primary" type="submit" :disabled="!task.trim()">开始群聊<AppIcon name="arrow" :size="15" /></button>
                  </div>
                </form>
              </template>
            </main>
          </div>
        </div>
      </section>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import { useWorkflowStore } from '../stores/workflow'
import { messageService, workflowService } from '../services/workflow'
import { isGroupChatTerminal, normalizeGroupChatMessages } from '../utils/groupChat'

const emit = defineEmits(['create'])
const workflowStore = useWorkflowStore()

const isOpen = ref(false)
const selectedId = ref(null)
const messages = ref([])
const task = ref('')
const apiKey = ref('')
const running = ref(false)
const statusText = ref('idle')
const error = ref('')
let pollTimer = null

const groupWorkflows = computed(() => (workflowStore.workflows || []).filter(workflow => workflow.pattern === 'group_chat'))
const selected = computed(() => groupWorkflows.value.find(workflow => workflow.workflow_id === selectedId.value) || null)
const membersText = computed(() => {
  const agents = selected.value?.agents || []
  if (!agents.length) return '共享群聊'
  return agents.map(agent => agent.name).join('、')
})

function clearPoll() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function toggle() {
  isOpen.value = !isOpen.value
  if (isOpen.value) {
    workflowStore.loadWorkflows()
    if (selectedId.value) loadMessages()
  } else {
    clearPoll()
  }
}

function close() {
  isOpen.value = false
  clearPoll()
}

function createGroup() {
  emit('create')
}

function formatTime(value) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

async function loadMessages() {
  if (!selectedId.value) {
    messages.value = []
    return
  }
  try {
    const data = await messageService.getMessages(selectedId.value)
    messages.value = normalizeGroupChatMessages(data?.messages || [])
  } catch {
    messages.value = []
  }
}

async function syncStatus() {
  if (!selectedId.value) return
  try {
    const data = await workflowService.getWorkflowStatus(selectedId.value)
    statusText.value = data.status || 'idle'
    running.value = ['executing', 'running', 'stopping', 'paused'].includes(String(statusText.value).toLowerCase())
    if (isGroupChatTerminal(statusText.value)) clearPoll()
  } catch {
    // 状态读取失败不打断聊天视图，下一次轮询继续。
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
  error.value = ''
  statusText.value = 'idle'
  running.value = false
  clearPoll()
  await loadMessages()
  await syncStatus()
}

async function run() {
  if (!selectedId.value || !task.value.trim() || running.value) return
  error.value = ''
  running.value = true
  statusText.value = 'running'
  try {
    await workflowService.executeWorkflow(selectedId.value, {
      task: task.value.trim(),
      ...(apiKey.value.trim() ? { api_key: apiKey.value.trim() } : {}),
    })
    await loadMessages()
    startPoll()
  } catch (err) {
    running.value = false
    statusText.value = 'failed'
    const detail = err.response?.data?.detail
    error.value = typeof detail === 'string' ? detail : '无法开始群聊，请检查模型连接或后端服务。'
  }
}

async function stop() {
  if (!selectedId.value) return
  try {
    await workflowService.stopWorkflow(selectedId.value)
    statusText.value = 'stopping'
  } catch (err) {
    const detail = err.response?.data?.detail
    error.value = typeof detail === 'string' ? detail : '停止请求失败。'
  }
}

onBeforeUnmount(clearPoll)

defineExpose({
  selectWorkflow,
  refresh: loadMessages,
  open: () => { isOpen.value = true; workflowStore.loadWorkflows() },
})
</script>

<style scoped>
.group-chat-overlay { position: fixed; inset: 0; z-index: 1300; background: #18181855; backdrop-filter: blur(4px); display: flex; align-items: stretch; justify-content: flex-end; }
.group-chat-panel { width: min(940px, 100vw); height: 100%; background: #fff; display: flex; flex-direction: column; box-shadow: -20px 0 70px #00000018; }
.group-chat-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; padding: 24px 28px 18px; border-bottom: 1px solid #ececec; }
.group-chat-header h2 { margin-top: 7px; font-size: 24px; letter-spacing: -.4px; }
.group-chat-header p { margin-top: 6px; color: #8a8a8a; font-size: 12px; }
.group-chat-header-actions { display: flex; align-items: center; gap: 8px; }
.group-chat-body { flex: 1; min-height: 0; display: grid; grid-template-columns: 220px 1fr; }
.group-chat-list { border-right: 1px solid #ececec; padding: 14px 10px; overflow-y: auto; background: #fafafa; }
.group-chat-list-empty { padding: 14px 10px; color: #888; font-size: 12px; display: grid; gap: 12px; }
.group-chat-list-item { width: 100%; display: flex; align-items: center; gap: 9px; padding: 10px 9px; border: 0; border-radius: 9px; background: transparent; cursor: pointer; text-align: left; }
.group-chat-list-item:hover, .group-chat-list-item.selected { background: #f0f0f0; }
.group-chat-avatar { width: 28px; height: 28px; border-radius: 8px; background: #262626; color: #fff; display: grid; place-items: center; font-size: 12px; flex-shrink: 0; }
.group-chat-list-copy { display: grid; gap: 2px; min-width: 0; flex: 1; }
.group-chat-list-copy strong { font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.group-chat-list-copy small { color: #999; font-size: 10px; }
.group-chat-room { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.group-chat-room-empty { flex: 1; display: grid; place-content: center; justify-items: center; gap: 8px; color: #999; text-align: center; padding: 30px; }
.group-chat-room-empty h3 { color: #555; font-size: 16px; }
.group-chat-room-empty p { font-size: 12px; }
.group-chat-room-header { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 15px 20px; border-bottom: 1px solid #f0f0f0; }
.group-chat-room-header h3 { font-size: 16px; }
.group-chat-room-header p { margin-top: 4px; color: #999; font-size: 11px; }
.group-chat-status { display: flex; align-items: center; gap: 7px; color: #777; font-size: 12px; }
.group-chat-messages { flex: 1; overflow-y: auto; padding: 16px 20px; display: grid; align-content: start; gap: 10px; }
.group-chat-messages-empty { color: #999; font-size: 12px; padding: 8px 0; }
.group-chat-message { background: #f7f7f7; border: 1px solid #eee; border-radius: 10px; padding: 10px 12px; }
.group-chat-message header { display: flex; align-items: center; gap: 6px; color: #777; font-size: 11px; }
.group-chat-message header strong { color: #333; font-size: 12px; }
.group-chat-message header time { margin-left: auto; color: #aaa; font-family: ui-monospace, Consolas, monospace; }
.group-chat-message p { margin-top: 6px; color: #444; font-size: 12px; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.group-chat-error { margin: 0 20px 8px; padding: 8px 10px; border-radius: 8px; background: #fff1f0; color: #b42318; font-size: 12px; }
.group-chat-composer { padding: 12px 20px 18px; border-top: 1px solid #ececec; display: grid; gap: 8px; }
.group-chat-composer textarea { width: 100%; resize: vertical; min-height: 58px; border: 1px solid #ddd; border-radius: 9px; padding: 10px 11px; font: inherit; font-size: 13px; outline: none; }
.group-chat-composer textarea:focus { border-color: #999; }
.group-chat-api-key { border: 1px solid #ddd; border-radius: 8px; padding: 8px 10px; font: inherit; font-size: 12px; }
.group-chat-composer-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.group-chat-composer-actions .hint { color: #999; font-size: 10px; }
.group-chat-fade-enter-active, .group-chat-fade-leave-active { transition: opacity 180ms ease; }
.group-chat-fade-enter-from, .group-chat-fade-leave-to { opacity: 0; }
@media (max-width: 720px) {
  .group-chat-body { grid-template-columns: 1fr; }
  .group-chat-list { max-height: 160px; border-right: 0; border-bottom: 1px solid #ececec; }
}
</style>
