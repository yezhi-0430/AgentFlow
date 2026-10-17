<template>
  <transition name="fade">
    <div v-if="isLoading" class="loading-overlay" @click.self="onClickOverlay">
      <div class="loading-content">
        <div class="spinner"></div>
        <div v-if="message" class="loading-message">{{ message }}</div>
      </div>
    </div>
  </transition>
</template>

<script setup>
import { ref } from 'vue'

const isLoading = ref(false)
const message = ref('')
const canClose = ref(false)

function show(msg = '', closeable = false) {
  isLoading.value = true
  message.value = msg
  canClose.value = closeable
}

function hide() {
  isLoading.value = false
  message.value = ''
}

function onClickOverlay() {
  if (canClose.value) {
    hide()
  }
}

defineExpose({
  show,
  hide,
})
</script>

<style scoped>
.loading-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9998;
  backdrop-filter: blur(2px);
}

.loading-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  padding: 32px;
  background: white;
  border-radius: 12px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
}

.spinner {
  width: 48px;
  height: 48px;
  border: 4px solid #f3f4f6;
  border-top-color: #252525;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.loading-message {
  font-size: 14px;
  color: #6b7280;
  text-align: center;
  max-width: 300px;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
