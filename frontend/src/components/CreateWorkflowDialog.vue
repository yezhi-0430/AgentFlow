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
                    <label v-for="pattern in patterns" :key="pattern.value" class="pattern-option" :class="{ selected: form.pattern === pattern.value }" :title="pattern.description">
                      <input v-model="form.pattern" type="radio" :value="pattern.value" name="pattern" :disabled="creating" />
                      <AppIcon :name="pattern.icon" :size="18" /><div class="pattern-details"><span class="pattern-name">{{ pattern.label }}</span><span class="pattern-desc">{{ pattern.description }} · {{ pattern.roleHint }}</span></div>
                      <span class="radio-indicator"><span></span></span>
                    </label>
                  </div>
                  <p class="hint pattern-support-hint">不同协作模式对团队角色与最少智能体数量有不同要求，切换模式会自动调整数量下限。</p>
                </fieldset>
                <div class="form-group creation-count-row">
                  <div><label for="agentCount">智能体数量</label><p class="hint">按任务分工，配置 {{ minAgentCount }}–{{ maxAgentCount }} 个智能体</p></div>
                  <div class="agent-count-control">
                    <button class="icon-button" type="button" aria-label="减少智能体数量" :disabled="creating || form.agentCount <= minAgentCount" @click="adjustAgents(-1)"><AppIcon name="minus" :size="14" /></button>
                    <input id="agentCount" v-model.number="form.agentCount" type="number" :min="minAgentCount" :max="maxAgentCount" required :disabled="creating" aria-describedby="count-hint" />
                    <button class="icon-button" type="button" aria-label="增加智能体数量" :disabled="creating || form.agentCount >= maxAgentCount" @click="adjustAgents(1)"><AppIcon name="plus" :size="14" /></button>
                  </div>
                </div>
                <p v-if="countError" id="count-hint" class="creation-inline-error" role="status">{{ countError }}</p>
                <span v-else id="count-hint" class="sr-only">{{ selectedPattern.label }}最少需要 {{ minAgentCount }} 个智能体，最多 {{ maxAgentCount }} 个。</span>
                <div v-if="form.pattern === 'group_chat'" class="form-group group-chat-settings">
                  <label class="group-chat-lead"><input v-model="form.enableLead" type="checkbox" :disabled="creating" /> 启用 Lead Agent</label>
                  <p class="hint">开启后由 Lead 规划、分派并总结；关闭后成员轮流发言，可用 @成员名 点名。</p>
                </div>
              </section>

              <section class="creation-models" aria-labelledby="model-settings-title">
                <div class="creation-section-heading"><span class="creation-section-number">02</span><div><h3 id="model-settings-title">模型连接</h3><p>选择团队使用的模型与服务</p></div></div>
                <div class="form-group">
                  <label for="llmProvider">模型提供商</label>
                  <AppSelect id="llmProvider" v-model="form.llmProvider" label="模型提供商" :options="providerOptions" :disabled="creating || form.pattern === 'group_chat'" />
                </div>
                <Transition name="field">
                  <div v-if="availableModels.length && form.pattern !== 'group_chat'" class="form-group">
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

                <div v-if="form.pattern === 'group_chat'" class="form-group group-chat-model-settings">
                  <div class="creation-section-heading group-model-heading"><span class="creation-section-number">03</span><div><h3>群聊模型</h3><p>按特点分类选择模型</p></div></div>
                  <div class="model-recommendation">
                    <div>
                      <strong>推荐主流组合</strong>
                      <p>Lead：GPT-6.1 Sol · 成员：GPT-6 Luna / Claude Sonnet 5.5 / DeepSeek V4.1 Flash / Qwen3.8 Max Prime</p>
                    </div>
                    <button class="btn btn-secondary" type="button" :disabled="creating" @click="applyRecommendedTeam">一键应用</button>
                  </div>
                  <div class="group-model-grid">
                    <div v-for="(member, index) in form.groupMemberModels" :key="index" class="form-group group-model-row">
                      <label :for="`group-model-${index}`">成员 {{ index + 1 }}</label>
                      <input v-model="member.name" type="text" class="group-member-name" :disabled="creating" aria-label="成员名称" />
                      <AppSelect :id="`group-model-${index}`" v-model="member.model" label="成员模型" :options="groupModelOptions" :disabled="creating" />
                      <input v-model="member.customModel" type="text" class="group-member-name" :disabled="creating" placeholder="自定义 model id（可选）" aria-label="自定义成员模型" />
                    </div>
                    <div v-if="form.enableLead" class="form-group group-model-row">
                      <label for="group-lead-model">Lead 模型</label>
                      <AppSelect id="group-lead-model" v-model="form.leadModel" label="Lead 模型" :options="groupModelOptions" :disabled="creating" />
                      <input v-model="form.leadCustomModel" type="text" class="group-member-name" :disabled="creating" placeholder="自定义 Lead model id（可选）" aria-label="自定义 Lead 模型" />
                    </div>
                  </div>
                  <p class="hint">群聊统一使用 OpenRouter；成员与 Lead 可选择不同模型，也可填写自定义 model id。</p>
                  <p v-if="catalogSource === 'fallback'" class="hint">模型目录服务暂不可用，当前显示精选模型；可直接填写自定义 model id。</p>
                </div>

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
import { providerOptions, modelOptions, creationPatterns, isSupportedWorkflowPattern, normalizeCreationPattern, minAgentsForPattern, maxAgentsForPattern, clampAgentCount } from '../utils/workflowOptions'
import { buildGroupChatConfig } from '../utils/groupChatConfig'
import { RECOMMENDED_TEAM, modelProfile, sortModelOptions } from '../utils/modelProfiles'
import { useWorkflowStore } from '../stores/workflow'
import { modelService } from '../services/models'
import { workflowService } from '../services/workflow'
import { validateConnection, formatExecutionError } from '../utils/connection.js'

const props = defineProps({ modelValue: Boolean, preset: { type: Object, default: null } })
const emit = defineEmits(['update:modelValue', 'created'])
const workflowStore = useWorkflowStore()
const defaults = () => {
  const pattern = normalizeCreationPattern(props.preset?.pattern)
  const provider = pattern === 'group_chat' ? 'openrouter' : (props.preset?.llmProvider || 'openai')
  return { name: '', description: '', ...props.preset, pattern, agentCount: clampAgentCount(pattern, props.preset?.agentCount ?? 3), enableLead: true, llmProvider: provider, apiKey: '', model: modelOptions[provider]?.[0]?.value || '', groupMemberModels: [], leadModel: '', leadCustomModel: '' }
}
const form = ref(defaults())
const creating = ref(false)
const errorMessage = ref('')
const showApiKey = ref(false)
const dialog = ref(null)
const nameInput = ref(null)
const modelCatalog = ref([])
const catalogSource = ref('')
let previousFocus = null
let previousOverflow = ''
let disposed = false

const availableModels = computed(() => modelOptions[form.value.llmProvider] || [])
const groupModelOptions = computed(() => {
  if (modelCatalog.value.length) {
    const options = modelCatalog.value
      .filter(model => !model.id.includes(':batch') && !model.id.includes(':free') && !model.id.startsWith('~'))
      .map(model => {
        const profile = modelProfile(model.id)
        const context = model.context_length ? `${Math.round(model.context_length / 1000)}K` : '未知'
        const note = profile.note || `通用对话模型 · ${context} 上下文${model.supports_tools ? ' · 支持工具调用' : ''}`
        return {
          value: model.id,
          label: model.name,
          description: note,
          group: profile.category,
          tag: profile.recommended ? '推荐' : '',
        }
      })
    return sortModelOptions(options)
  }
  return modelOptions.openrouter || []
})
const selectedModel = computed(() => availableModels.value.find(model => model.value === form.value.model))
const patterns = creationPatterns
const selectedPattern = computed(() => patterns.find(pattern => pattern.value === form.value.pattern) || patterns[0])
const minAgentCount = computed(() => minAgentsForPattern(form.value.pattern))
const maxAgentCount = computed(() => maxAgentsForPattern(form.value.pattern))
const validCount = computed(() => Number.isInteger(form.value.agentCount) && form.value.agentCount >= minAgentCount.value && form.value.agentCount <= maxAgentCount.value)
const countError = computed(() => {
  const count = form.value.agentCount
  if (!Number.isInteger(count)) return '请输入整数智能体数量。'
  if (count < minAgentCount.value) return `${selectedPattern.value.label}至少需要 ${minAgentCount.value} 个智能体。`
  if (count > maxAgentCount.value) return `${selectedPattern.value.label}最多支持 ${maxAgentCount.value} 个智能体。`
  return ''
})
const connectionError = computed(() => validateConnection(form.value.llmProvider, form.value.apiKey))
const groupModelsValid = computed(() => {
  if (form.value.pattern !== 'group_chat') return true
  const members = form.value.groupMemberModels || []
  if (!members.length || members.some(member => !(member.customModel || member.model) || !member.name)) return false
  return form.value.enableLead ? Boolean(form.value.leadCustomModel || form.value.leadModel) : true
})
const isValid = computed(() => Boolean(form.value.name.trim() && isSupportedWorkflowPattern(form.value.pattern) && validCount.value && (form.value.pattern === 'group_chat' ? groupModelsValid.value : selectedModel.value) && !connectionError.value))

function syncGroupModels() {
  if (form.value.pattern !== 'group_chat') return
  const count = Math.max(1, form.value.enableLead ? form.value.agentCount - 1 : form.value.agentCount)
  const options = groupModelOptions.value
  const preferred = options.find(option => option.value === 'openai/gpt-6.1-sol')?.value
  const fallback = preferred || options[0]?.value || 'openai/gpt-6.1-sol'
  const valid = new Set(options.map(option => option.value))
  const current = [...(form.value.groupMemberModels || [])]
  form.value.groupMemberModels = Array.from({ length: count }, (_, index) => {
    const candidate = current[index]?.model
    return {
      name: current[index]?.name || `member_${index + 1}`,
      model: valid.has(candidate) ? candidate : fallback,
      customModel: current[index]?.customModel || '',
    }
  })
  if (!valid.has(form.value.leadModel)) form.value.leadModel = fallback
  if (form.value.leadCustomModel == null) form.value.leadCustomModel = ''
}

function applyRecommendedTeam() {
  if (form.value.pattern !== 'group_chat') return
  const options = groupModelOptions.value
  const valid = new Set(options.map(option => option.value))
  const fallback = options[0]?.value || 'openai/gpt-6.1-sol'
  const memberIds = RECOMMENDED_TEAM.members.filter(id => valid.has(id))
  form.value.leadModel = valid.has(RECOMMENDED_TEAM.lead) ? RECOMMENDED_TEAM.lead : fallback
  form.value.leadCustomModel = ''
  form.value.groupMemberModels = form.value.groupMemberModels.map((member, index) => ({
    ...member,
    model: memberIds[index % Math.max(1, memberIds.length)] || fallback,
    customModel: '',
  }))
}

async function loadModelCatalog() {
  try {
    const data = await modelService.getOpenRouterModels()
    modelCatalog.value = data?.models || []
    catalogSource.value = data?.source || ''
  } catch {
    modelCatalog.value = []
    catalogSource.value = 'fallback'
  }
  syncGroupModels()
}

watch(() => form.value.llmProvider, provider => { form.value.model = modelOptions[provider]?.[0]?.value || '' })
watch(() => form.value.pattern, pattern => {
  form.value.agentCount = clampAgentCount(pattern, form.value.agentCount)
  if (pattern === 'group_chat') {
    form.value.llmProvider = 'openrouter'
    if (!form.value.model) form.value.model = groupModelOptions.value[0]?.value || 'openai/gpt-6.1-sol'
  }
  syncGroupModels()
})
watch(() => [form.value.agentCount, form.value.enableLead], syncGroupModels)
watch(() => props.modelValue, async open => {
  if (open) {
    previousFocus = document.activeElement
    previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    form.value = defaults()
    errorMessage.value = ''
    showApiKey.value = false
    await nextTick()
    await loadModelCatalog()
    syncGroupModels()
    nameInput.value?.focus()
  } else {
    document.body.style.overflow = previousOverflow
    form.value.apiKey = ''
    showApiKey.value = false
  }
})
function adjustAgents(delta) {
  const count = Number.isInteger(form.value.agentCount) ? form.value.agentCount : minAgentCount.value
  form.value.agentCount = clampAgentCount(form.value.pattern, count + delta)
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
      name: form.value.name.trim(), description: form.value.description, pattern: normalizeCreationPattern(form.value.pattern),
      config: {
        agent_count: form.value.agentCount,
        llm_provider: form.value.pattern === 'group_chat' ? 'openrouter' : form.value.llmProvider,
        api_key: form.value.apiKey.trim(),
        model: form.value.model || undefined,
        group_chat: form.value.pattern === 'group_chat'
          ? buildGroupChatConfig({
              enableLead: form.value.enableLead,
              leadModel: form.value.leadCustomModel || form.value.leadModel,
              members: form.value.groupMemberModels.map(member => ({
                name: member.name,
                model: member.customModel || member.model,
              })),
            })
          : undefined,
      },
    })
    if (disposed) return
    workflowStore.setWorkflow({ ...result, llm_provider: form.value.pattern === 'group_chat' ? 'openrouter' : form.value.llmProvider })
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

<style scoped>
.model-recommendation { display: flex; gap: 12px; align-items: center; justify-content: space-between; margin: 4px 0 2px; padding: 11px 12px; border: 1px solid #e5e5e5; border-radius: 8px; background: #fafafa; }
.model-recommendation strong { display: block; color: #191919; font-size: 12px; }
.model-recommendation p { margin: 3px 0 0; color: #777; font-size: 11px; line-height: 1.5; }
.model-recommendation .btn { flex-shrink: 0; font-size: 11px; padding: 5px 9px; }
.group-model-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 10px; }
.group-model-row { margin: 0; }
.group-member-name { width: 100%; box-sizing: border-box; margin-top: 6px; padding: 7px 8px; border: 1px solid #d9e2e1; border-radius: 7px; font: inherit; }
@media (max-width: 720px) { .group-model-grid { grid-template-columns: 1fr; } }
</style>

