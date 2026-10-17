<template>
  <transition-group name="toast" tag="div" class="toast-container" aria-live="polite" aria-relevant="additions text">
    <div
      v-for="toast in toasts"
      :key="toast.id"
      class="toast"
      :class="`toast-${toast.type}`"
      @click="remove(toast.id)"
    >
      <div class="toast-icon">{{ getIcon(toast.type) }}</div>
      <div class="toast-content">
        <div v-if="toast.title" class="toast-title">{{ toast.title }}</div>
        <div class="toast-message">{{ toast.message }}</div>
      </div>
      <button class="toast-close" aria-label="关闭通知" @click.stop="remove(toast.id)">✕</button>
    </div>
  </transition-group>
</template>

<script setup>
import { ref } from 'vue'

const toasts = ref([])
let nextId = 1

function getIcon(type) {
  const icons = {
    success: '✓',
    error: '✕',
    warning: '⚠',
    info: 'ℹ',
  }
  return icons[type] || icons.info
}

function add(message, type = 'info', title = '', duration = 3000) {
  const id = nextId++
  const toast = { id, message, type, title }

  toasts.value.push(toast)

  if (duration > 0) {
    setTimeout(() => {
      remove(id)
    }, duration)
  }

  return id
}

function remove(id) {
  const index = toasts.value.findIndex((t) => t.id === id)
  if (index > -1) {
    toasts.value.splice(index, 1)
  }
}

function clear() {
  toasts.value = []
}

// 导出方法供外部调用
defineExpose({
  add,
  remove,
  clear,
  success: (message, title = '', duration = 3000) => add(message, 'success', title, duration),
  error: (message, title = '', duration = 5000) => add(message, 'error', title, duration),
  warning: (message, title = '', duration = 4000) => add(message, 'warning', title, duration),
  info: (message, title = '', duration = 3000) => add(message, 'info', title, duration),
})
</script>

<style scoped>
.toast-container {
  position: fixed;
  top: 20px;
  right: 16px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 12px;
  pointer-events: none;
}

.toast {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  width: min(380px, calc(100vw - 32px));
  padding: 16px;
  background: white;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  pointer-events: auto;
  cursor: pointer;
  transition: all 0.3s ease;
}

.toast:hover {
  transform: translateX(-4px);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.2);
}

.toast-icon {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  font-weight: 700;
  font-size: 14px;
}

.toast-success {
  border-left: 4px solid #3a3a3a;
}

.toast-success .toast-icon {
  background: #f0f0f0;
  color: #454545;
}

.toast-error {
  border-left: 4px solid #252525;
}

.toast-error .toast-icon {
  background: #eeeeee;
  color: #333333;
}

.toast-warning {
  border-left: 4px solid #666666;
}

.toast-warning .toast-icon {
  background: #f2f2f2;
  color: #555555;
}

.toast-info {
  border-left: 4px solid #252525;
}

.toast-info .toast-icon {
  background: #f0f0f0;
  color: #454545;
}

.toast-content {
  flex: 1;
  min-width: 0;
}

.toast-title {
  font-size: 14px;
  font-weight: 600;
  color: #111827;
  margin-bottom: 4px;
}

.toast-message {
  font-size: 13px;
  color: #6b7280;
  line-height: 1.4;
  word-wrap: break-word;
}

.toast-close {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: none;
  border-radius: 4px;
  color: #9ca3af;
  cursor: pointer;
  font-size: 16px;
  transition: all 0.2s;
}

.toast-close:hover {
  background: #f3f4f6;
  color: #6b7280;
}

/* 动画 */
.toast-enter-active,
.toast-leave-active {
  transition: all 0.3s ease;
}

.toast-enter-from {
  opacity: 0;
  transform: translateX(100%);
}

.toast-leave-to {
  opacity: 0;
  transform: translateX(50px);
}

.toast-move {
  transition: transform 0.3s ease;
}
</style>
