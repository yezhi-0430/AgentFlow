<template>
  <span class="trace-id">
    <template v-if="value">
      <code class="trace-value" :title="value">{{ display }}</code>
      <button
        type="button"
        class="trace-copy"
        title="复制完整 Trace ID"
        :aria-label="'复制 Trace ID：' + value"
        @click.stop="copy"
      >
        复制
      </button>
      <span v-if="copyMessage" class="trace-copy-state" role="status">{{ copyMessage }}</span>
    </template>
    <span v-else class="trace-empty">-</span>

    <Teleport to="body">
      <div v-if="manualText" class="trace-modal-overlay" @click.self="closeManual">
        <section class="trace-modal" role="dialog" aria-modal="true" aria-labelledby="trace-modal-title">
          <header class="trace-modal-header">
            <h3 id="trace-modal-title">手动复制 Trace ID</h3>
            <button type="button" class="trace-modal-close" aria-label="关闭" @click="closeManual">✕</button>
          </header>
          <p class="trace-modal-hint">当前浏览器无法自动写入剪贴板，请选中下方文本复制。</p>
          <textarea
            class="trace-modal-text"
            readonly
            rows="3"
            aria-label="Trace ID"
            :value="manualText"
            @focus="$event.target.select()"
          ></textarea>
          <footer class="trace-modal-footer">
            <button type="button" class="trace-modal-button" @click="closeManual">关闭</button>
          </footer>
        </section>
      </div>
    </Teleport>
  </span>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { copyText } from '../utils/clipboard.js'
import { truncateTraceId } from '../utils/runDetails.js'

const props = defineProps({
  traceId: {
    type: String,
    default: '',
  },
  length: {
    type: Number,
    default: 12,
  },
})

const value = computed(() => (typeof props.traceId === 'string' ? props.traceId.trim() : ''))
const display = computed(() => truncateTraceId(value.value, props.length))
const copyMessage = ref('')
const manualText = ref('')
let timer

watch(() => props.traceId, () => {
  copyMessage.value = ''
  manualText.value = ''
  clearTimeout(timer)
})

onBeforeUnmount(() => clearTimeout(timer))

async function copy() {
  if (!value.value) return
  const result = await copyText(value.value)
  if (result.method === 'clipboard') {
    copyMessage.value = '已复制'
    clearTimeout(timer)
    timer = setTimeout(() => { copyMessage.value = '' }, 2000)
  } else {
    manualText.value = result.text || value.value
  }
}

function closeManual() {
  manualText.value = ''
}
</script>

<style scoped>
.trace-id {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.trace-value {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12px;
  color: #4b5563;
  white-space: nowrap;
}

.trace-copy {
  padding: 2px 7px;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  background: #ffffff;
  color: #2563eb;
  font-size: 11px;
  line-height: 1.6;
  cursor: pointer;
}

.trace-copy:hover {
  background: #f3f4f6;
}

.trace-copy-state {
  font-size: 11px;
  color: #059669;
  white-space: nowrap;
}

.trace-empty {
  color: #9ca3af;
}

.trace-modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(17, 24, 39, 0.45);
}

.trace-modal {
  width: min(560px, 100%);
  padding: 20px;
  background: #ffffff;
  border-radius: 10px;
  box-shadow: 0 20px 45px rgba(0, 0, 0, 0.2);
}

.trace-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.trace-modal-header h3 {
  margin: 0;
  font-size: 16px;
  color: #111827;
}

.trace-modal-close {
  border: 0;
  background: none;
  color: #6b7280;
  font-size: 16px;
  cursor: pointer;
}

.trace-modal-hint {
  margin: 10px 0;
  font-size: 12px;
  color: #6b7280;
}

.trace-modal-text {
  display: block;
  width: 100%;
  padding: 10px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font: 12px/1.7 ui-monospace, Consolas, monospace;
  resize: vertical;
}

.trace-modal-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.trace-modal-button {
  padding: 7px 14px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: #f3f4f6;
  font-size: 13px;
  cursor: pointer;
}
</style>
