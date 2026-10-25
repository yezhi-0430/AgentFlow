<template>
  <div ref="root" class="app-select">
    <button :id="id" ref="trigger" type="button" class="select-trigger" :class="{ 'select-open': open }"
      role="combobox" aria-haspopup="listbox" :aria-label="label" :aria-expanded="open"
      :aria-controls="open ? listId : undefined" :aria-activedescendant="open && active >= 0 ? optionId(active) : undefined"
      :disabled="disabled || !options.length" @click="toggle" @keydown="onKeydown">
      <span v-if="selected?.symbol" class="select-symbol">{{ selected.symbol }}</span>
      <span class="select-value">{{ selected?.label || placeholder }}</span>
      <AppIcon class="select-chevron" name="down" :size="15" />
    </button>
    <Teleport to="body">
      <Transition name="select-menu">
        <div v-if="open" :id="listId" ref="panel" class="select-popover" :class="{ 'opens-above': above }"
          :style="position" role="listbox" :aria-label="label">
          <div class="select-menu-caption">{{ label }}</div>
          <input
            ref="searchInput"
            v-model="filter"
            class="select-search"
            type="search"
            :placeholder="`搜索${label}`"
            aria-label="搜索选项"
            @click.stop
            @keydown.stop
          />
          <template v-for="group in groupedOptions" :key="group.name">
            <div v-if="group.name" class="select-group-title">{{ group.name }}</div>
            <div v-for="option in group.options" :id="optionId(option._index)" :key="option.value" role="option"
              class="select-option" :class="{ 'is-active': active === option._index, 'is-selected': option.value === modelValue }"
              :aria-selected="option.value === modelValue" @pointermove="active = option._index" @pointerdown.prevent @click="choose(option._index)">
              <span v-if="option.symbol" class="select-symbol">{{ option.symbol }}</span>
              <span class="select-option-copy"><span class="select-option-title">{{ option.label }}<span v-if="option.tag" class="select-option-tag">{{ option.tag }}</span></span><small v-if="option.description">{{ option.description }}</small></span>
              <AppIcon v-if="option.value === modelValue" class="select-check" name="check" :size="16" />
            </div>
          </template>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, ref, watch, nextTick, onBeforeUnmount } from 'vue'
import AppIcon from './AppIcon.vue'
import { moveOptionIndex, findOptionMatch } from '../utils/selection'

const props = defineProps({
  id: { type: String, required: true },
  label: { type: String, required: true },
  modelValue: { type: String, default: '' },
  options: { type: Array, default: () => [] },
  placeholder: { type: String, default: '请选择' },
  disabled: Boolean,
})
const emit = defineEmits(['update:modelValue'])
const root = ref(null)
const trigger = ref(null)
const panel = ref(null)
const open = ref(false)
const active = ref(-1)
const above = ref(false)
const position = ref({})
const filter = ref('')
const searchInput = ref(null)
const listId = computed(() => props.id + '-listbox')
const selected = computed(() => props.options.find(option => option.value === props.modelValue))
const filteredOptions = computed(() => {
  const query = filter.value.trim().toLowerCase()
  if (!query) return props.options
  return props.options.filter(option =>
    String(option.label || '').toLowerCase().includes(query)
    || String(option.value || '').toLowerCase().includes(query)
    || String(option.description || '').toLowerCase().includes(query)
  )
})
const groupedOptions = computed(() => {
  const groups = new Map()
  filteredOptions.value.forEach((option, index) => {
    const name = option.group || ''
    if (!groups.has(name)) groups.set(name, [])
    groups.get(name).push({ ...option, _index: index })
  })
  return [...groups.entries()].map(([name, options]) => ({ name, options }))
})
let search = ''
let searchTimer
const optionId = index => props.id + '-option-' + index

function updatePosition() {
  if (!open.value || !trigger.value) return
  const bounds = trigger.value.getBoundingClientRect()
  if (bounds.bottom < 0 || bounds.top > window.innerHeight) { open.value = false; return }
  const below = window.innerHeight - bounds.bottom - 12
  const upper = bounds.top - 12
  const desired = Math.min(340, filteredOptions.value.length * 59 + 40)
  above.value = below < desired && upper > below
  const width = Math.min(bounds.width, window.innerWidth - 24)
  position.value = {
    position: 'fixed',
    width: width + 'px',
    left: Math.max(12, Math.min(bounds.left, window.innerWidth - width - 12)) + 'px',
    maxHeight: Math.max(40, Math.min(340, (above.value ? upper : below) - 6)) + 'px',
    ...(above.value ? { bottom: window.innerHeight - bounds.top + 6 + 'px' } : { top: bounds.bottom + 6 + 'px' }),
  }
}
function outside(event) {
  if (!root.value?.contains(event.target) && !panel.value?.contains(event.target)) open.value = false
}
function onScroll(event) {
  if (panel.value?.contains(event.target)) return
  updatePosition()
}
async function scrollActive() {
  await nextTick()
  document.getElementById(optionId(active.value))?.scrollIntoView({ block: 'nearest' })
}
function show() {
  if (props.disabled || !props.options.length) return
  filter.value = ''
  active.value = Math.max(0, filteredOptions.value.findIndex(option => option.value === props.modelValue))
  open.value = true
  updatePosition()
  scrollActive()
  nextTick(() => searchInput.value?.focus({ preventScroll: true }))
}
function toggle() { if (open.value) open.value = false; else show() }
function choose(index) {
  const option = filteredOptions.value[index]
  if (!option) return
  emit('update:modelValue', option.value)
  open.value = false
  trigger.value?.focus({ preventScroll: true })
}
function onKeydown(event) {
  if (event.key === 'Escape' && open.value) {
    event.preventDefault()
    event.stopPropagation()
    open.value = false
    return
  }
  if (event.key === 'Tab') { open.value = false; return }
  if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
    event.preventDefault()
    if (!open.value) {
      show()
      if (event.key === 'Home' || event.key === 'End') active.value = moveOptionIndex(active.value, filteredOptions.value.length, event.key)
    } else active.value = moveOptionIndex(active.value, filteredOptions.value.length, event.key)
    scrollActive()
    return
  }
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    if (open.value) choose(active.value); else show()
    return
  }
  if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
    event.preventDefault()
    if (!open.value) show()
    clearTimeout(searchTimer)
    search += event.key
    let match = findOptionMatch(filteredOptions.value, search, active.value)
    if (match < 0) { search = event.key; match = findOptionMatch(filteredOptions.value, search, active.value) }
    if (match >= 0) { active.value = match; scrollActive() }
    searchTimer = setTimeout(() => { search = '' }, 550)
  }
}
function removeListeners() {
  document.removeEventListener('pointerdown', outside, true)
  document.removeEventListener('scroll', onScroll, true)
  window.removeEventListener('resize', updatePosition)
}
watch(open, isOpen => {
  if (isOpen) {
    document.addEventListener('pointerdown', outside, true)
    document.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', updatePosition)
  } else {
    removeListeners()
    clearTimeout(searchTimer)
    search = ''
    filter.value = ''
  }
})
watch(filter, () => { active.value = 0; scrollActive() })
watch(() => props.disabled, disabled => { if (disabled) open.value = false })
watch(() => props.options, () => { if (open.value) { active.value = Math.max(0, filteredOptions.value.findIndex(option => option.value === props.modelValue)); updatePosition(); scrollActive() } })
onBeforeUnmount(() => { removeListeners(); clearTimeout(searchTimer) })
</script>

<style scoped>
.select-search { width: calc(100% - 20px); margin: 0 10px 8px; padding: 7px 9px; border: 1px solid #d9d9d9; border-radius: 6px; font: inherit; font-size: 12px; outline: none; }
.select-search:focus { border-color: #191919; }
.select-group-title { padding: 7px 12px 4px; color: #999; font-size: 10px; font-weight: 600; letter-spacing: .04em; }
</style>
