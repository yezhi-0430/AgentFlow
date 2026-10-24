<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="modelValue" class="modal-overlay library-overlay" @click.self="close" @keydown.esc.prevent="close">
        <section ref="dialog" class="modal-content library-dialog" role="dialog" aria-modal="true" aria-labelledby="library-title" tabindex="-1">
          <header class="modal-header library-header">
            <div class="library-header-copy">
              <span class="eyebrow">WORKFLOW LIBRARY</span>
              <h2 id="library-title">工作流库</h2>
              <p>刷新或重启后，这里列出已保存到本机的工作流定义。API Key 不会保存，恢复或导入后执行时需要重新输入。</p>
            </div>
            <button class="icon-button modal-close" type="button" aria-label="关闭工作流库" :disabled="store.importing" @click="close"><AppIcon name="close" :size="19" /></button>
          </header>

          <div v-if="mode === 'list'" class="modal-body library-body">
            <div class="library-toolbar">
              <span class="library-count">{{ store.workflows.length }} 个已保存工作流</span>
              <div class="library-toolbar-actions">
                <button class="btn btn-quiet" type="button" :disabled="store.workflowsLoading" @click="refresh"><AppIcon name="refresh" :size="14" />刷新列表</button>
                <button class="btn btn-secondary" type="button" :disabled="isBusy" @click="startImport"><AppIcon name="plus" :size="14" />导入工作流</button>
              </div>
            </div>
            <p v-if="listError" class="library-error" role="alert">{{ listError }}</p>
            <p v-if="store.workflowListError" class="library-error" role="alert">{{ store.workflowListError }}</p>
            <div v-if="store.workflowsLoading && !store.workflows.length" class="library-empty" role="status">正在读取工作流列表…</div>
            <ul v-else-if="store.workflows.length" class="library-list">
              <li v-for="workflow in store.workflows" :key="workflow.workflow_id" class="library-item">
                <button class="library-item-main" type="button" :disabled="isBusy" @click="selectWorkflow(workflow)">
                  <span class="library-item-name">{{ workflow.name || '未命名工作流' }}</span>
                  <span class="library-item-meta">{{ patternLabel(workflow.pattern) }} · {{ (workflow.agents || []).length }} 个智能体</span>
                </button>
                <span v-if="workflow.workflow_id === store.currentWorkflow?.workflow_id" class="library-tag is-current">当前</span>
                <span v-if="workflow.requires_credentials" class="library-tag is-credential" title="连接配置已保留，密钥未保存">需要 API Key</span>
                <span v-else class="library-tag">连接已就绪</span>
                <button class="btn btn-quiet library-open" type="button" :disabled="isBusy" @click="selectWorkflow(workflow)">打开<AppIcon name="arrow" :size="13" /></button>
              </li>
            </ul>
            <div v-else class="library-empty">还没有保存的工作流。创建工作流或导入定义后会出现在这里。</div>
          </div>

          <div v-else class="modal-body library-body">
            <div class="library-import-toolbar">
              <label class="btn btn-secondary library-file-button">
                <AppIcon name="upload" :size="14" />选择 JSON 文件
                <input class="sr-only" type="file" accept=".json,application/json" :disabled="store.importing" @change="onFileSelected" />
              </label>
              <span>或把导出的定义 JSON 直接粘贴到下方。</span>
            </div>
            <textarea v-model="importText" class="library-import-text" rows="11" spellcheck="false" placeholder="粘贴工作流定义 JSON，例如：{ &quot;schema_version&quot;: 1, &quot;name&quot;: ... }" :disabled="store.importing" aria-label="工作流定义 JSON" />
            <p v-if="importError" class="library-error" role="alert">{{ importError }}</p>
            <p v-else-if="parsed.ok && parsed.warnings.length" class="library-warning" role="status">{{ parsed.warnings[0] }}</p>
            <p v-if="!parsed.ok && importText.trim()" class="library-error" role="status">{{ parsed.error }}</p>
            <div v-if="parsed.ok" class="library-preview">
              <span class="library-preview-label">即将导入</span>
              <strong>{{ summary.name || '未命名工作流' }}</strong>
              <span>{{ summary.patternLabel }} · {{ summary.agentCount }} 个智能体 · {{ summary.stepCount }} 个步骤</span>
              <span class="library-tag is-credential">导入后需要重新输入 API Key</span>
            </div>
            <p class="library-hint">导入会分配新的 workflow_id，不会覆盖现有工作流；定义中的疑似密钥字段会被自动移除。</p>
          </div>

          <footer class="modal-footer library-footer">
            <template v-if="mode === 'list'">
              <span class="library-footnote">工作流定义保存在本机数据库，API Key 不落库。</span>
              <button class="btn btn-secondary" type="button" @click="close">关闭</button>
            </template>
            <template v-else>
              <span class="library-footnote">{{ store.importing ? '正在导入工作流…' : '导入后需要重新输入 API Key 才能执行。' }}</span>
              <button class="btn btn-secondary" type="button" :disabled="store.importing" @click="backToList">返回列表</button>
              <button class="btn btn-primary" type="button" :disabled="!parsed.ok || store.importing" @click="submitImport"><span v-if="store.importing" class="spinner"></span>{{ store.importing ? '正在导入' : '导入工作流' }}</button>
            </template>
          </footer>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>
<script setup>
import { computed, nextTick, ref, watch, onBeforeUnmount } from 'vue'
import AppIcon from './AppIcon.vue'
import { useWorkflowStore } from '../stores/workflow'
import { parseWorkflowDefinition, workflowDefinitionSummary } from '../utils/workflowDefinition.js'
import { readDefinitionFile } from '../utils/definitionTransfer.js'
import { workflowPatternLabels } from '../utils/workflowOptions.js'
import { formatExecutionError } from '../utils/connection.js'

const props = defineProps({ modelValue: Boolean })
const emit = defineEmits(['update:modelValue', 'imported', 'selected'])
const store = useWorkflowStore()
const dialog = ref(null)
const mode = ref('list')
const importText = ref('')
const importError = ref('')
const listError = ref('')
let previousOverflow = ''
let disposed = false

const isBusy = computed(() => store.isRunning || store.deleting || store.importing)
const parsed = computed(() => parseWorkflowDefinition(importText.value))
const summary = computed(() => workflowDefinitionSummary(parsed.value.ok ? parsed.value.value : {}))
const patternLabel = pattern => workflowPatternLabels[pattern] || pattern || '未设置模式'

watch(() => props.modelValue, async open => {
  if (open) {
    previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    mode.value = 'list'
    importText.value = ''
    importError.value = ''
    listError.value = ''
    store.loadWorkflows()
    await nextTick()
    dialog.value?.focus()
  } else {
    document.body.style.overflow = previousOverflow
  }
})
function close() {
  if (store.importing) return
  emit('update:modelValue', false)
}
function backToList() {
  if (store.importing) return
  mode.value = 'list'
  importError.value = ''
}
function startImport() {
  importError.value = ''
  mode.value = 'import'
}
async function refresh() {
  listError.value = ''
  await store.loadWorkflows()
}
async function selectWorkflow(workflow) {
  if (isBusy.value) return
  listError.value = ''
  const opened = await store.openWorkflow(workflow.workflow_id)
  if (!opened) {
    listError.value = store.connectionError || '该工作流暂时无法打开，请稍后重试。'
    return
  }
  emit('selected', store.currentWorkflow)
  close()
}
async function onFileSelected(event) {
  const file = event.target?.files?.[0]
  event.target.value = ''
  if (!file) return
  importError.value = ''
  try {
    importText.value = await readDefinitionFile(file)
  } catch (error) {
    importError.value = error.message || '读取文件失败，请直接粘贴 JSON 文本。'
  }
}
async function submitImport() {
  if (!parsed.value.ok || store.importing) return
  importError.value = ''
  try {
    const imported = await store.importDefinition(parsed.value.value)
    if (disposed) return
    if (!imported) {
      importError.value = '导入失败，请检查定义内容后重试。'
      return
    }
    emit('imported', imported)
    close()
  } catch (error) {
    if (disposed) return
    const detail = error.response?.data?.detail
    importError.value = typeof detail === 'string'
      ? `导入失败：${formatExecutionError(detail)}`
      : error.response ? '导入失败，请检查定义内容后重试。' : '暂时无法连接后端服务，请确认服务已启动后重试。'
  }
}
onBeforeUnmount(() => {
  disposed = true
  if (props.modelValue) document.body.style.overflow = previousOverflow
})
</script>
<style scoped>
.library-overlay { padding: 28px; }
.library-dialog { width: 700px; }
.library-header { align-items: flex-start; }
.library-header-copy { min-width: 0; }
.library-header h2 { font-size: 22px; }
.library-header p { max-width: 520px; line-height: 1.7; }
.library-body { padding: 20px 28px; }
.library-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
.library-count { font-size: 12px; color: #8a8a8a; }
.library-toolbar-actions { display: flex; align-items: center; gap: 6px; }
.library-list { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.library-item { display: flex; align-items: center; gap: 9px; padding: 11px 12px; border: 1px solid #e7e7e7; border-radius: 9px; background: #fafafa; }
.library-item-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 5px; padding: 0; border: 0; background: transparent; text-align: left; cursor: pointer; color: inherit; }
.library-item-main:disabled { cursor: default; opacity: .7; }
.library-item-name { font-size: 13px; font-weight: 550; color: #333; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.library-item-meta { font-size: 11px; color: #969696; }
.library-tag { flex-shrink: 0; padding: 3px 8px; border: 1px solid #e5e5e5; border-radius: 999px; background: #fff; color: #7d7d7d; font-size: 10px; line-height: 1.6; white-space: nowrap; }
.library-tag.is-current { border-color: #d5d5d5; background: #f0f0f0; color: #4b4b4b; }
.library-tag.is-credential { border-color: #ddd3bd; background: #faf5e9; color: #7d5f22; }
.library-open { flex-shrink: 0; }
.library-empty { padding: 34px 16px; border: 1px dashed #e0e0e0; border-radius: 9px; text-align: center; color: #969696; font-size: 12px; line-height: 1.8; }
.library-error { margin: 10px 0 0; padding: 10px 12px; border: 1px solid #e4d3d3; border-radius: 7px; background: #fbf3f3; color: #7d3a3a; font-size: 12px; line-height: 1.7; overflow-wrap: anywhere; }
.library-warning { margin: 10px 0 0; padding: 10px 12px; border: 1px solid #e8dfc9; border-radius: 7px; background: #fbf7ec; color: #7d6322; font-size: 12px; line-height: 1.7; }
.library-import-toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; font-size: 11px; color: #969696; }
.library-file-button { position: relative; display: inline-flex; align-items: center; gap: 7px; cursor: pointer; }
.library-import-text { display: block; width: 100%; min-height: 190px; max-height: 320px; resize: vertical; padding: 12px; border: 1px solid #dedede; border-radius: 8px; background: #fff; color: #333; font: 12px/1.7 ui-monospace, Consolas, monospace; }
.library-import-text:focus { outline: none; border-color: #727272; box-shadow: 0 0 0 3px #00000005; }
.library-preview { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-top: 12px; padding: 11px 13px; border: 1px solid #ededed; border-radius: 8px; background: #fafafa; font-size: 11px; color: #8a8a8a; }
.library-preview-label { color: #969696; }
.library-preview strong { color: #454545; font-size: 12px; font-weight: 550; }
.library-hint { margin-top: 12px; color: #9a9a9a; font-size: 11px; line-height: 1.7; }
.library-footer { padding: 16px 28px; }
.library-footnote { margin-right: auto; color: #9a9a9a; font-size: 11px; line-height: 1.6; }
</style>
