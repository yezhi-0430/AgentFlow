<template>
  <transition name="modal">
    <div v-if="isVisible" class="confirm-overlay" @click.self="cancel" @keydown.esc.stop.prevent="cancel" @keydown.tab="trapFocus">
      <div ref="dialog" class="confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-message confirm-details">
        <div class="confirm-header">
          <div class="confirm-icon" :class="`icon-${type}`">
            <AppIcon :name="getIcon(type)" :size="23" />
          </div>
          <h3 id="confirm-title">{{ title }}</h3>
        </div>

        <div class="confirm-body">
          <p id="confirm-message">{{ message }}</p>
          <div v-if="details" id="confirm-details" class="confirm-details">
            {{ details }}
          </div>
        </div>

        <div class="confirm-footer">
          <button
            class="btn btn-secondary"
            ref="cancelButton"
            @click="cancel"
            :disabled="loading"
          >
            {{ cancelText }}
          </button>
          <button
            class="btn"
            :class="confirmClass"
            @click="confirm"
            :disabled="loading"
          >
            <span v-if="loading" class="spinner"></span>
            {{ loading ? '处理中...' : confirmText }}
          </button>
        </div>
      </div>
    </div>
  </transition>
</template>

<script setup>
import { ref, computed, nextTick } from 'vue'
import AppIcon from './AppIcon.vue'

const isVisible = ref(false)
const title = ref('')
const message = ref('')
const details = ref('')
const type = ref('warning') // warning, danger, info, success
const confirmText = ref('确认')
const cancelText = ref('取消')
const loading = ref(false)
const dialog = ref(null)
const cancelButton = ref(null)
let previousFocus = null

let resolvePromise = null
let rejectPromise = null

const confirmClass = computed(() => {
  const classes = {
    warning: 'btn-warning',
    danger: 'btn-danger',
    info: 'btn-primary',
    success: 'btn-success',
  }
  return classes[type.value] || 'btn-primary'
})

function getIcon(iconType) {
  const icons = {
    warning: 'message',
    danger: 'trash',
    info: 'message',
    success: 'check',
  }
  return icons[iconType] || 'message'
}

function show(options = {}) {
  previousFocus = document.activeElement
  title.value = options.title || '确认操作'
  message.value = options.message || '你确定要执行此操作吗？'
  details.value = options.details || ''
  type.value = options.type || 'warning'
  confirmText.value = options.confirmText || '确认'
  cancelText.value = options.cancelText || '取消'
  loading.value = false
  isVisible.value = true
  nextTick(() => cancelButton.value?.focus())

  return new Promise((resolve, reject) => {
    resolvePromise = resolve
    rejectPromise = reject
  })
}

function confirm() {
  if (loading.value) return

  if (resolvePromise) {
    resolvePromise(true)
    resolvePromise = null
  }
  close()
}

function cancel() {
  if (loading.value) return

  if (rejectPromise) {
    rejectPromise(false)
    rejectPromise = null
  }
  close()
}

function close() {
  isVisible.value = false
  loading.value = false
  nextTick(() => { if (previousFocus?.isConnected) previousFocus.focus() })
}

function trapFocus(event) {
  const buttons = [...dialog.value.querySelectorAll('button:not(:disabled)')]
  if (!buttons.length) { event.preventDefault(); return }
  const first = buttons[0], last = buttons.at(-1)
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
}

function setLoading(value) {
  loading.value = value
}

defineExpose({
  show,
  close,
  setLoading,
})
</script>

<style scoped>
.confirm-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  backdrop-filter: blur(2px);
}

.confirm-dialog {
  background: white;
  border-radius: 12px;
  width: 90%;
  max-width: 450px;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1),
              0 10px 10px -5px rgba(0, 0, 0, 0.04);
  overflow: hidden;
}

.confirm-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 24px 24px 16px 24px;
}

.confirm-icon {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  flex-shrink: 0;
}

.icon-warning {
  background: #f2f2f2;
}

.icon-danger {
  background: #eeeeee;
}

.icon-info {
  background: #f0f0f0;
}

.icon-success {
  background: #f0f0f0;
}

.confirm-header h3 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: #111827;
}

.confirm-body {
  padding: 0 24px 24px 24px;
}

.confirm-body p {
  margin: 0;
  font-size: 15px;
  color: #6b7280;
  line-height: 1.6;
}

.confirm-details {
  margin-top: 12px;
  padding: 12px;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  font-size: 13px;
  color: #374151;
  line-height: 1.5;
}

.confirm-footer {
  display: flex;
  gap: 12px;
  padding: 16px 24px;
  background: #f9fafb;
  border-top: 1px solid #e5e7eb;
  justify-content: flex-end;
}

.btn {
  padding: 10px 20px;
  border: none;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-secondary {
  background: white;
  color: #374151;
  border: 1px solid #d1d5db;
}

.btn-secondary:hover:not(:disabled) {
  background: #f9fafb;
  border-color: #9ca3af;
}

.btn-primary {
  background: #252525;
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: #444444;
}

.btn-warning {
  background: #666666;
  color: white;
}

.btn-warning:hover:not(:disabled) {
  background: #555555;
}

.btn-danger {
  background: #252525;
  color: white;
}

.btn-danger:hover:not(:disabled) {
  background: #444444;
}

.btn-success {
  background: #3a3a3a;
  color: white;
}

.btn-success:hover:not(:disabled) {
  background: #555555;
}

.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.3s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-active .confirm-dialog,
.modal-leave-active .confirm-dialog {
  transition: transform 0.3s ease;
}

.modal-enter-from .confirm-dialog {
  transform: scale(0.9);
}

.modal-leave-to .confirm-dialog {
  transform: scale(0.9);
}
</style>
