<template>
  <Teleport to="body">
    <Transition name="modal" @after-leave="restoreFocus">
      <div v-if="modelValue" class="modal-overlay creation-overlay" @click.self="close" @keydown.esc.prevent="close" @keydown.tab="trapFocus">
        <section ref="dialog" class="modal-content creation-dialog" role="dialog" aria-modal="true" aria-labelledby="create-dialog-title" tabindex="-1">
          <header class="modal-header creation-header">
            <div class="creation-header-copy"><span class="creation-heading-icon"><AppIcon name="flow" :size="24" /></span><div><span class="eyebrow">NEW WORKFLOW</span><h2 id="create-dialog-title">创建工作流</h2><p>定义协作方式，为你的任务组建一个智能体团队。</p></div></div>
            <button class="icon-button modal-close" type="button" aria-label="关闭创建弹窗" :disabled="creating" @click="close"><AppIcon name="close" :size="19" /></button>
          </header>

          <form id="create-workflow-form" class="modal-body creation-body" @submit.prevent="create">
            <div class="creation-layout">
              <section class="creation-basics" aria-labelledby="workflow-settings-title">
                <div class="creation-section-heading"><span class="creation-section-number">01</span><div><h3 id="workflow-settings-title">工作流设置</h3><p>明确任务，选择团队的协作方式</p></div></div>
                <div class="form-group"><label for="name">工作流名称 <span class="required-mark">*</span></label><input id="name" ref="nameInput" v-model="form.name" type="text" placeholder="例如：内容创作工作流" maxlength="100" required :disabled="creating" /></div>
                <div class="form-group"><label for="description">任务描述<span class="optional-label">可选</span></label><textarea id="description" v-model="form.description" rows="2" placeholder="这个团队将帮你完成什么？" :disabled="creating"></textarea></div>
                <fieldset class="form-group pattern-fieldset" :disabled="creating">
                  <legend>协作模式 <span class="required-mark">*</span></legend>
                  <div class="pattern-options">
                    <label v-for="pattern in patterns" :key="pattern.value" class="pattern-option" :class="{ selected: form.pattern === pattern.value }">
                      <input v-model="form.pattern" type="radio" :value="pattern.value" name="pattern" />
                      <AppIcon :name="pattern.icon" :size="18" /><div class="pattern-details"><span class="pattern-name">{{ pattern.label }}</span><span class="pattern-desc">{{ pattern.description }}</span></div>
                      <span class="radio-indicator"><span></span></span>
                    </label>
                  </div>
                </fieldset>
                <div class="form-group creation-count-row">
                  <div><label for="agentCount">智能体数量</label><p class="hint">按任务分工，配置 1–10 个智能体</p></div>
                  <div class="agent-count-control">
                    <button class="icon-button" type="button" aria-label="减少智能体数量" :disabled="creating || form.agentCount <= 1" @click="adjustAgents(-1)"><AppIcon name="minus" :size="14" /></button>
                    <input id="agentCount" v-model.number="form.agentCount" type="number" min="1" max="10" required :disabled="creating" aria-describedby="count-hint" />
                    <button class="icon-button" type="button" aria-label="增加智能体数量" :disabled="creating || form.agentCount >= 10" @click="adjustAgents(1)"><AppIcon name="plus" :size="14" /></button>
                  </div>
                </div>
                <p v-if="!validCount" id="count-hint" class="creation-inline-error" role="status">请输入 1–10 之间的整数。</p>
                <span v-else id="count-hint" class="sr-only">数量范围为 1 到 10。</span>
              </section>

              <section class="creation-models" aria-labelledby="model-settings-title">
                <div class="creation-section-heading"><span class="creation-section-number">02</span><div><h3 id="model-settings-title">模型连接</h3><p>选择团队使用的模型与服务</p></div></div>
                <div class="form-group">
                  <label for="llmProvider">模型提供商</label>
                  <AppSelect id="llmProvider" v-model="form.llmProvider" label="模型提供商" :options="providerOptions" :disabled="creating" />
                </div>
                <Transition name="field">
                  <div v-if="availableModels.length" class="form-group">
                    <label for="model">选择模型</label>
                    <AppSelect id="model" v-model="form.model" label="选择模型" :options="availableModels" :disabled="creating" />
                    <p v-if="form.llmProvider === 'openrouter'" class="hint creation-model-hint">模型将通过 OpenRouter 接口调用。</p>
                  </div>
                </Transition>
                <Transition name="field">
                  <div v-if="form.llmProvider !== 'local'" class="form-group api-key-field">
                    <label for="apiKey">API Key <span class="required-mark">*</span></label>
                    <div class="creation-key-input"><AppIcon name="key" :size="16" /><input id="apiKey" v-model="form.apiKey" :type="showApiKey ? 'text' : 'password'" placeholder="输入对应服务的 API Key" autocomplete="off" required :disabled="creating" :aria-invalid="Boolean(form.apiKey.trim() && connectionError)" aria-describedby="connection-hint" /><button class="icon-button" type="button" :aria-label="showApiKey ? '隐藏 API Key' : '显示 API Key'" :aria-pressed="showApiKey" :disabled="creating" @click="showApiKey = !showApiKey"><AppIcon :name="showApiKey ? 'eyeOff' : 'eye'" :size="17" /></button></div>
                    <p id="connection-hint" :class="form.apiKey.trim() && connectionError ? 'creation-inline-error' : 'hint'" role="status">{{ form.apiKey.trim() && connectionError ? connectionError : form.llmProvider === 'openrouter' ? '使用 OpenRouter 的密钥，请勿填写其他平台的密钥。' : '请使用所选模型提供商的密钥。' }}</p>
                    <button v-if="form.apiKey.trim().startsWith('sk-or-') && form.llmProvider !== 'openrouter'" class="btn btn-secondary" type="button" :disabled="creating" @click="form.llmProvider = 'openrouter'">切换为 OpenRouter</button>
                  </div>
                </Transition>
                <div v-if="form.llmProvider === 'local'" class="creation-local-note"><AppIcon name="terminal" :size="18" /><p>当前后端尚未支持本地模型，请选择在线模型提供商。</p></div>

                <div class="creation-summary">
                  <h4><AppIcon name="layers" :size="16" />本次工作流</h4>
                  <dl><div><dt>团队规模</dt><dd>{{ validCount ? form.agentCount + ' 个智能体' : '待设置' }}</dd></div><div><dt>协作方式</dt><dd>{{ selectedPattern.label }}</dd></div><div><dt>使用模型</dt><dd>{{ selectedModel?.label || '本地模型' }}</dd></div></dl>
                  <p>创建后，在画布中查看与编排智能体。</p>
                </div>
              </section>
            </div>
            <p v-if="errorMessage" class="form-error creation-error" role="alert">{{ errorMessage }}</p>
          </form>

          <footer class="modal-footer creation-footer">
            <span class="creation-readiness"><span class="status-dot" :class="{ ready: isValid }"></span>{{ isValid ? '配置已就绪' : '填写工作流名称与配置' }}</span>
            <button class="btn btn-secondary" type="button" :disabled="creating" @click="close">取消</button>
            <button class="btn btn-primary" form="create-workflow-form" type="submit" :disabled="!isValid || creating"><span v-if="creating" class="spinner"></span>{{ creating ? '正在创建' : '创建工作流' }}<AppIcon v-if="!creating" name="arrow" :size="16" /></button>
          </footer>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch, nextTick, onBeforeUnmount } from 'vue'
import AppIcon from './AppIcon.vue'
import AppSelect from './AppSelect.vue'
import { providerOptions, modelOptions } from '../utils/workflowOptions'
import { useWorkflowStore } from '../stores/workflow'
import { workflowService } from '../services/workflow'
import { validateConnection, formatExecutionError } from '../utils/connection.js'

const props = defineProps({ modelValue: Boolean, preset: { type: Object, default: null } })
const emit = defineEmits(['update:modelValue', 'created'])
const workflowStore = useWorkflowStore()
const defaults = () => {
  const provider = props.preset?.llmProvider || 'openai'
  return { name: '', description: '', pattern: 'sequential', agentCount: 3, ...props.preset, llmProvider: provider, apiKey: '', model: modelOptions[provider]?.[0]?.value || '' }
}
const form = ref(defaults())
const creating = ref(false)
const errorMessage = ref('')
const showApiKey = ref(false)
const dialog = ref(null)
const nameInput = ref(null)
let previousFocus = null
let previousOverflow = ''
let disposed = false

const availableModels = computed(() => modelOptions[form.value.llmProvider] || [])
const selectedModel = computed(() => availableModels.value.find(model => model.value === form.value.model))
const patterns = [
  { value: 'sequential', label: '顺序执行', icon: 'arrow', description: '依次推进任务' },
  { value: 'parallel', label: '并行执行', icon: 'parallel', description: '同时分工协作' },
  { value: 'hierarchical', label: '层次协作', icon: 'hierarchy', description: '统筹与分层执行' },
  { value: 'debate', label: '辩论模式', icon: 'message', description: '讨论并汇聚共识' },
]
const selectedPattern = computed(() => patterns.find(pattern => pattern.value === form.value.pattern) || patterns[0])
const validCount = computed(() => Number.isInteger(form.value.agentCount) && form.value.agentCount >= 1 && form.value.agentCount <= 10)
const connectionError = computed(() => validateConnection(form.value.llmProvider, form.value.apiKey))
const isValid = computed(() => Boolean(form.value.name.trim() && patterns.some(pattern => pattern.value === form.value.pattern) && validCount.value && selectedModel.value && !connectionError.value))

watch(() => form.value.llmProvider, provider => { form.value.model = modelOptions[provider]?.[0]?.value || '' })
watch(() => props.modelValue, async open => {
  if (open) {
    previousFocus = document.activeElement
    previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    form.value = defaults()
    errorMessage.value = ''
    showApiKey.value = false
    await nextTick()
    nameInput.value?.focus()
  } else {
    document.body.style.overflow = previousOverflow
    form.value.apiKey = ''
    showApiKey.value = false
  }
})
function adjustAgents(delta) {
  const count = Number.isInteger(form.value.agentCount) ? form.value.agentCount : 3
  form.value.agentCount = Math.min(10, Math.max(1, count + delta))
}
function restoreFocus() { if (previousFocus?.isConnected) previousFocus.focus() }
function close() { if (!creating.value) emit('update:modelValue', false) }
function trapFocus(event) {
  const items = [...dialog.value.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]')]
    .filter(el => el.getClientRects().length && (el.type !== 'radio' || el.checked))
  if (!items.length) { event.preventDefault(); dialog.value.focus(); return }
  const first = items[0], last = items.at(-1)
  if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.value)) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
}
async function create() {
  if (!isValid.value || creating.value) return
  creating.value = true
  errorMessage.value = ''
  try {
    const result = await workflowService.createWorkflow({
      name: form.value.name.trim(), description: form.value.description, pattern: form.value.pattern,
      config: { agent_count: form.value.agentCount, llm_provider: form.value.llmProvider, api_key: form.value.apiKey.trim(), model: form.value.model || undefined },
    })
    if (disposed) return
    workflowStore.setWorkflow({ ...result, llm_provider: form.value.llmProvider })
    emit('created', result)
    creating.value = false
    close()
  } catch (error) {
    if (disposed) return
    const detail = error.response?.data?.detail
    errorMessage.value = typeof detail === 'string' ? formatExecutionError(detail) : error.response ? '创建失败，请检查填写内容后重试。' : '暂时无法连接服务，请确认后端已启动后重试。'
  } finally { creating.value = false }
}
onBeforeUnmount(() => { disposed = true; if (props.modelValue) document.body.style.overflow = previousOverflow })
</script>
