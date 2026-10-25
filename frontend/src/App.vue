<template>
  <div class="app-shell" :class="{ 'is-focused': focusMode, 'is-resizing-timeline': timelineResizing }">
    <nav class="navigation-rail" aria-label="工作台导航">
      <button class="sidebar-brand" aria-label="返回工作流画布" @click="canvas?.fit()">
        <span class="brand-mark"><AppIcon name="flow" :size="22" /></span>
        <span class="sidebar-brand-text">AgentFlow<span>智能体协作空间</span></span>
      </button>

      <div class="sidebar-section-label">工作空间</div>
      <button class="rail-button active" title="工作流画布" aria-label="工作流编排" @click="canvas?.fit()">
        <AppIcon name="grid" /><span class="nav-label">工作流编排</span><span class="nav-indicator"></span>
      </button>
      <button class="rail-button" :class="{ 'is-on': timelineOpen }" title="消息时间线" aria-label="切换消息时间线" :aria-pressed="timelineOpen" @click="timelineOpen = !timelineOpen">
        <AppIcon name="message" /><span class="nav-label">消息记录</span><span class="nav-count">{{ messageStore.messages.length }}</span>
      </button>
      <button class="rail-button" :class="{ 'is-on': showWorkflowLibrary }" title="工作流库 · 已保存的工作流定义" aria-label="打开工作流库" @click="openWorkflowLibrary">
        <AppIcon name="layers" /><span class="nav-label">工作流库</span><span class="nav-count">{{ workflowStore.workflows.length }}</span>
      </button>
      <RunHistoryPanel ref="historyPanel" :workflow-id="workflowStore.currentWorkflow?.workflow_id || null" />
      <GroupChatPanel ref="groupChatPanel" @create="openCreateWorkflow({ pattern: 'group_chat' })" />
      <ExperimentPanel />
      <button class="rail-button sidebar-create" title="创建工作流 · N" aria-label="创建工作流" @click="openCreateWorkflow()">
        <AppIcon name="plus" /><span class="nav-label">新建工作流</span><kbd>N</kbd>
      </button>

      <div class="sidebar-current">
        <div class="sidebar-section-label">当前工作流</div>
        <button class="current-workflow-card" @click="workflowStore.currentWorkflow ? canvas?.fit() : openCreateWorkflow()">
          <AppIcon name="flow" :size="17" />
          <span><strong>{{ workflowStore.currentWorkflow?.name || '还没有工作流' }}</strong><small>{{ workflowStore.currentWorkflow ? workflowStore.agents.length + ' 个智能体 · ' + patternName : '从第一个想法开始' }}</small></span>
          <AppIcon name="chevron" :size="13" />
        </button>
      </div>
      <div class="rail-spacer"></div>
      <div class="sidebar-bottom"><span class="rail-version">AF</span><span class="sidebar-bottom-copy">我的工作空间<small>本地工作区</small></span><span class="status-dot"></span></div>
    </nav>

    <div class="workspace-shell">
      <header class="topbar">
        <div class="breadcrumb"><span>工作空间</span><AppIcon name="chevron" :size="14" /><span class="breadcrumb-current">工作流编排</span></div>
        <div class="topbar-meta"><span class="local-badge"><span class="status-dot"></span>本地工作区</span><span class="version-tag">v0.1.0</span></div>
      </header>
      <main class="workspace">
        <div class="workspace-heading">
          <div class="workspace-title">
            <h1>
              {{ workflowStore.currentWorkflow?.name || '工作流编排' }}
              <span v-if="workflowStore.currentWorkflow?.isDemo" class="tag">本地示例</span>
              <span v-if="workflowStore.requiresCredentials" class="tag credential-tag" title="连接配置已保留，密钥未保存">需要重新输入 API Key</span>
            </h1>
            <p>{{ workflowStore.currentWorkflow?.description || '让每个智能体各司其职，让好的想法顺畅发生。' }}</p>
          </div>
          <button class="btn btn-primary create-button" title="创建工作流 · N" @click="openCreateWorkflow()"><AppIcon name="plus" :size="17" />创建工作流<kbd>N</kbd></button>
        </div>

        <div class="workspace-tools">
          <div class="workspace-tabs"><span class="workspace-tab selected"><AppIcon name="flow" :size="17" />编排画布</span><span class="count-label">{{ workflowStore.agents.length }} 个智能体</span><span v-if="workflowStore.currentWorkflow" class="pattern-label">{{ patternName }}</span></div>
          <div class="workspace-tool-actions">
            <button v-if="workflowStore.currentWorkflow && !workflowStore.currentWorkflow.isDemo" class="btn btn-quiet export-definition-button" :disabled="workflowStore.exporting" aria-label="导出当前工作流定义" title="导出定义 JSON（不含 API Key）" @click="exportWorkflow"><AppIcon name="download" :size="15" /><span>{{ workflowStore.exporting ? '正在导出…' : '导出定义' }}</span></button>
            <span v-if="workflowStore.currentWorkflow && !workflowStore.currentWorkflow.isDemo" class="tools-divider"></span>
            <button v-if="workflowStore.currentWorkflow" class="btn btn-quiet delete-workflow-button" :disabled="workflowStore.isRunning || workflowStore.deleting" aria-label="删除当前工作流" :title="workflowStore.isRunning ? '运行结束后可删除工作流' : '删除当前工作流'" @click="deleteWorkflow"><AppIcon name="trash" :size="15" /><span>{{ workflowStore.deleting ? '正在删除…' : '删除工作流' }}</span></button>
            <span v-if="workflowStore.currentWorkflow" class="tools-divider"></span>
            <button class="btn btn-quiet layout-button" :disabled="!workflowStore.agents.length" aria-label="自动布局" title="恢复节点布局并适应画布" @click="canvas?.autoLayout()"><AppIcon name="layers" :size="16" /><span>自动布局</span></button>
            <span class="tools-divider"></span>
            <button class="btn btn-quiet focus-toggle" :aria-pressed="focusMode" :aria-label="focusMode ? '退出专注' : '专注模式'" title="专注模式 · F" @click="focusMode = !focusMode"><AppIcon name="fit" :size="16" /><span>{{ focusMode ? '退出专注' : '专注模式' }}</span></button>
            <button class="btn btn-quiet inspector-toggle" :aria-label="inspectorOpen ? '收起详情' : '展开详情'" :aria-pressed="inspectorOpen" @click="inspectorOpen = !inspectorOpen"><AppIcon name="panel" :size="16" /><span>智能体详情</span></button>
          </div>
        </div>

        <div class="workspace-grid" :class="{ 'inspector-closed': !inspectorOpen }">
          <section class="canvas-section" aria-label="工作流画布">
            <WorkflowCanvas ref="canvas" @create="openCreateWorkflow()" @demo="loadDemo" @selected="inspectorOpen = true" />
          </section>
          <aside class="inspector-section" :inert="!inspectorOpen" :aria-hidden="!inspectorOpen"><AgentInspector @close="inspectorOpen = false" /></aside>
        </div>

        <section class="activity-panel" :class="{ collapsed: !timelineOpen, 'timeline-resizing': timelineResizing }" :style="timelineOpen ? { height: timelineHeight + 'px' } : undefined" aria-label="消息时间线">
          <div class="activity-header">
            <button class="activity-title" :aria-expanded="timelineOpen" aria-controls="timeline-content" @click="timelineOpen = !timelineOpen"><AppIcon name="terminal" :size="17" />消息时间线<span class="number-badge">{{ messageStore.messages.length }}</span><AppIcon class="collapse-chevron" :class="{ rotated: !timelineOpen }" name="down" :size="14" /></button>
            <div class="activity-actions"><span class="subtle-label">拖动底边调整阅读区域</span><button v-if="timelineOpen" class="btn btn-quiet timeline-reset" aria-label="恢复时间线默认高度" title="恢复默认高度" @click="resetTimelineHeight"><AppIcon name="reset" :size="14" /></button><button class="btn btn-quiet" :disabled="!messageStore.messages.length" @click="messageStore.clearMessages()"><AppIcon name="trash" :size="14" />清空</button></div>
          </div>
          <div id="timeline-content" class="activity-content" :inert="!timelineOpen" :aria-hidden="!timelineOpen"><MessageTimeline /></div>
          <div v-if="timelineOpen" class="timeline-resize-handle" role="separator" tabindex="0" aria-orientation="horizontal" aria-label="调整消息时间线高度" aria-controls="timeline-content" :aria-valuemin="timelineMinHeight" :aria-valuemax="timelineMaxHeight" :aria-valuenow="timelineHeight" :aria-valuetext="timelineHeight + ' 像素'" title="上下拖动调整高度 · 双击恢复默认 · 方向键微调" @pointerdown="beginTimelineResize" @pointermove="moveTimelineResize" @pointerup="endTimelineResize" @pointercancel="endTimelineResize" @lostpointercapture="endTimelineResize" @keydown="onTimelineResizeKey" @dblclick="resetTimelineHeight"><span></span></div>
        </section>
        <DebugPanel @configure="configureConnection" @history="openRunHistory" />
      </main>
      <footer class="app-footer"><span><span class="status-dot"></span>{{ workflowStore.currentWorkflow ? '工作流已载入' : '工作空间就绪' }}</span><span class="shortcut-hints"><kbd>N</kbd> 新建工作流 <kbd>F</kbd> 专注模式 <kbd>Esc</kbd> 退出专注</span></footer>
    </div>
    <CreateWorkflowDialog v-model="showCreateWorkflow" :preset="creationPreset" @created="onCreated" />
    <WorkflowLibraryDialog v-model="showWorkflowLibrary" @imported="onImported" @selected="onWorkflowSelected" />
  </div>
  <Toast ref="toast" />
  <LoadingOverlay ref="loading" />
  <ConfirmDialog ref="confirm" />
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="manualExportText" class="modal-overlay" @click.self="manualExportText = ''">
        <section class="modal-content export-fallback" role="dialog" aria-modal="true" aria-labelledby="export-fallback-title">
          <header class="modal-header"><div><span class="eyebrow">MANUAL COPY</span><h2 id="export-fallback-title">手动复制工作流定义</h2><p>当前浏览器不支持自动下载或剪贴板，请选中下方文本复制并保存为 .json 文件。</p></div><button class="icon-button modal-close" type="button" aria-label="关闭" @click="manualExportText = ''"><AppIcon name="close" :size="19" /></button></header>
          <div class="modal-body"><textarea class="export-fallback-text" :value="manualExportText" readonly rows="14" aria-label="工作流定义 JSON" @focus="$event.target.select()"></textarea></div>
          <footer class="modal-footer"><span class="modal-footnote">定义中包含工作流结构，不含 API Key。</span><button class="btn btn-secondary" type="button" @click="manualExportText = ''">关闭</button></footer>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, ref, onMounted, onBeforeUnmount, watch } from 'vue'
import AppIcon from './components/AppIcon.vue'
import WorkflowCanvas from './components/WorkflowCanvas.vue'
import AgentInspector from './components/AgentInspector.vue'
import MessageTimeline from './components/MessageTimeline.vue'
import DebugPanel from './components/DebugPanel.vue'
import CreateWorkflowDialog from './components/CreateWorkflowDialog.vue'
import WorkflowLibraryDialog from './components/WorkflowLibraryDialog.vue'
import RunHistoryPanel from './components/RunHistoryPanel.vue'
import GroupChatPanel from './components/GroupChatPanel.vue'
import ExperimentPanel from './components/ExperimentPanel.vue'
import Toast from './components/Toast.vue'
import LoadingOverlay from './components/LoadingOverlay.vue'
import ConfirmDialog from './components/ConfirmDialog.vue'
import { useWorkflowStore } from './stores/workflow'
import { useMessageStore } from './stores/messages'
import { useTimelineResize } from './composables/useTimelineResize.js'
import { isTerminalExecutionStatus } from './utils/runStatus.js'
import { definitionFileName, serializeDefinition } from './utils/workflowDefinition.js'
import { saveDefinitionText } from './utils/definitionTransfer.js'
import { workflowPatternLabels } from './utils/workflowOptions.js'

const workflowStore = useWorkflowStore()
const messageStore = useMessageStore()
const showCreateWorkflow = ref(false)
const showWorkflowLibrary = ref(false)
const manualExportText = ref('')
const creationPreset = ref(null)
const timelineOpen = ref(true)
const inspectorOpen = ref(false)
const focusMode = ref(false)
const canvas = ref(null)
const toast = ref(null)
const confirm = ref(null)
const historyPanel = ref(null)
const groupChatPanel = ref(null)
const { height: timelineHeight, minHeight: timelineMinHeight, maxHeight: timelineMaxHeight, resizing: timelineResizing, beginResize: beginTimelineResize, moveResize: moveTimelineResize, endResize: endTimelineResize, onResizeKey: onTimelineResizeKey, resetHeight: resetTimelineHeight, fitViewport: fitTimelineViewport } = useTimelineResize()
const patternName = computed(() => workflowPatternLabels[workflowStore.currentWorkflow?.pattern] || '未设置模式')

function handleShortcut(event) {
  if (event.defaultPrevented || event.isComposing || event.ctrlKey || event.metaKey || event.altKey) return
  if (showCreateWorkflow.value || showWorkflowLibrary.value || manualExportText.value || document.querySelector('[role="dialog"], [role="alertdialog"]')) return
  if (event.key === 'Escape') { focusMode.value = false; return }
  if (event.target?.closest?.('input, textarea, select, [contenteditable="true"]')) return
  if (event.key.toLowerCase() === 'n') { event.preventDefault(); openCreateWorkflow() }
  if (event.key.toLowerCase() === 'f') { event.preventDefault(); focusMode.value = !focusMode.value }
}
function openCreateWorkflow(preset = null) {
  creationPreset.value = preset
  showCreateWorkflow.value = true
}
function openWorkflowLibrary() {
  showWorkflowLibrary.value = true
}
async function exportWorkflow() {
  if (!workflowStore.currentWorkflow || workflowStore.currentWorkflow.isDemo || workflowStore.exporting) return
  try {
    const definition = await workflowStore.exportCurrentDefinition()
    if (!definition) return
    // 序列化前再次清洗疑似密钥字段，导出的 JSON 永远不会包含 API Key。
    const text = serializeDefinition(definition)
    const result = await saveDefinitionText(text, definitionFileName(definition))
    if (result.method === 'download') toast.value?.success('工作流定义已下载，不包含 API Key。', '导出成功')
    else if (result.method === 'clipboard') toast.value?.success('工作流定义已复制到剪贴板，不包含 API Key。', '导出成功')
    else manualExportText.value = result.text || text
  } catch (error) {
    const detail = error.response?.data?.detail
    if (error.response?.status === 404) toast.value?.error('工作流已不存在，无法导出。', '导出失败')
    else toast.value?.error(typeof detail === 'string' ? '导出失败：' + detail : '导出失败，请确认后端服务已启动后重试。', '导出失败')
  }
}
async function deleteWorkflow() {
  const workflow = workflowStore.currentWorkflow
  if (!workflow || workflowStore.isRunning || workflowStore.deleting) return
  try {
    const approved = await confirm.value.show({
      title: '删除工作流？',
      message: `确定删除「${workflow.name}」吗？`,
      details: workflow.isDemo ? '移除当前示例，返回空白画布。' : '工作流、智能体配置和消息记录将一并删除，此操作无法撤销。',
      type: 'danger',
      confirmText: '删除工作流',
    })
    if (!approved || workflowStore.currentWorkflow !== workflow) return
  } catch { return }
  if (await workflowStore.deleteCurrentWorkflow()) {
    inspectorOpen.value = false
    focusMode.value = false
    toast.value?.success('工作流及相关记录已删除。', '删除成功')
  } else {
    toast.value?.error(workflowStore.deletionError || '工作流暂时无法删除，请稍后重试。', '删除失败')
  }
}
function configureConnection(task) {
  const workflow = workflowStore.currentWorkflow
  openCreateWorkflow({
    name: workflow?.name || '',
    description: task || workflow?.description || '',
    pattern: workflow?.pattern || 'sequential',
    agentCount: workflowStore.agents.length || 3,
    llmProvider: workflowStore.executionError.includes('OpenRouter') ? 'openrouter' : workflow?.llm_provider || 'openai',
  })
}
function onCreated(workflow) {
  messageStore.clearMessages()
  inspectorOpen.value = false
  workflowStore.refreshExecution()
  workflowStore.loadWorkflows()
  if (workflow?.pattern === 'group_chat') groupChatPanel.value?.selectWorkflow?.(workflow.workflow_id)
  toast.value?.success('确认下方任务后，点击「开始运行」。', '创建成功')
}
function onImported(workflow) {
  messageStore.clearMessages()
  inspectorOpen.value = false
  showWorkflowLibrary.value = false
  toast.value?.success(`已导入「${workflow?.name || '工作流'}」，请重新输入 API Key 后再执行。`, '导入成功')
}
function onWorkflowSelected(workflow) {
  inspectorOpen.value = false
  if (workflow?.requires_credentials) {
    toast.value?.warning('连接配置已保留，但 API Key 未保存。请在执行前重新输入 API Key。', '工作流已载入')
  } else {
    toast.value?.success('工作流已载入。', '工作流已恢复')
  }
}
function openRunHistory() {
  historyPanel.value?.open()
}
// 执行结束（完成/失败/部分完成/停止）后让已打开的历史面板重新从 API 取数。
watch(() => workflowStore.status, status => {
  if (isTerminalExecutionStatus(status)) historyPanel.value?.refresh?.()
})
function loadDemo() {
  messageStore.clearMessages()
  workflowStore.setWorkflow({
    name: '内容创作工作流', description: '研究、创作、审阅，让三个智能体完成一次清晰的协作。', pattern: 'sequential', isDemo: true,
    agents: [
      { name: '研究员', role: 'specialist', model: '本地示例', system_prompt: '收集与整理资料，为内容创作提供可靠的研究依据。', status: 'idle' },
      { name: '创作者', role: 'worker', model: '本地示例', system_prompt: '根据研究结果组织结构，完成清晰、自然的初稿。', status: 'idle' },
      { name: '审阅者', role: 'reviewer', model: '本地示例', system_prompt: '检查内容的逻辑与表达，提出具体的修改建议。', status: 'idle' },
    ],
    steps: [{ agent_name: '研究员' }, { agent_name: '创作者' }, { agent_name: '审阅者' }],
  })
  inspectorOpen.value = false
}
onMounted(() => {
  window.addEventListener('keydown', handleShortcut)
  window.addEventListener('resize', fitTimelineViewport)
  workflowStore.restoreWorkflow()
  // 同步一次列表，让"工作流库"入口即使当前工作区为空也能看到已保存的定义。
  workflowStore.loadWorkflows()
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleShortcut)
  window.removeEventListener('resize', fitTimelineViewport)
  endTimelineResize()
  workflowStore.disposeExecution()
})
</script>

<style scoped>
.credential-tag { margin-left: 10px; vertical-align: middle; background: #faf5e9; border-color: #e3d9c2; color: #6f5520; }
.export-fallback { width: 720px; }
.export-fallback-text { display: block; width: 100%; min-height: 210px; max-height: 320px; resize: vertical; padding: 12px; border: 1px solid #dedede; border-radius: 8px; background: #fff; color: #333; font: 12px/1.7 ui-monospace, Consolas, monospace; }
.export-fallback-text:focus { outline: none; border-color: #727272; box-shadow: 0 0 0 3px #00000005; }
</style>
