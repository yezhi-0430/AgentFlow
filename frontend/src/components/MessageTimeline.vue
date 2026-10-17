<template>
  <div ref="timeline" class="message-timeline" @scroll="onScroll">
    <div v-if="!messages.length" class="timeline-empty"><span class="timeline-empty-icon"><AppIcon name="message" :size="20" /></span><div><h3>静待第一条消息</h3><p>工作流开始后，智能体之间的对话将在这里呈现。</p></div><span class="small-caps">NO ACTIVITY YET</span></div>
    <TransitionGroup v-else name="message" tag="div" class="messages" aria-live="polite">
      <article v-for="(msg, index) in messages" :key="msg.id ?? index" class="message-item"><time>{{ formatTime(msg.timestamp) }}</time><div class="message-flow"><span>{{ msg.sender }}</span><AppIcon name="arrow" :size="14" /><span>{{ msg.receiver }}</span></div><p>{{ messageText(msg) }}</p></article>
    </TransitionGroup>
  </div>
</template>
<script setup>
import { computed, ref, watch, nextTick } from 'vue'
import AppIcon from './AppIcon.vue'
import { useMessageStore } from '../stores/messages'
import { formatExecutionError } from '../utils/connection.js'
const store = useMessageStore()
const messages = computed(() => store.messages)
const timeline = ref(null)
const nearBottom = ref(true)
function messageText(message) {
  const text = typeof message.content === 'string' ? message.content : JSON.stringify(message.content)
  return message.metadata?.error || text?.startsWith('Error:') ? formatExecutionError(text) : text
}
function onScroll() { const el = timeline.value; nearBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 48 }
watch(() => messages.value.length, async () => {
  if (!nearBottom.value) return
  await nextTick()
  timeline.value?.scrollTo({ top: timeline.value.scrollHeight, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' })
})
function formatTime(timestamp) {
  if (timestamp == null) return '—'
  const date = new Date(typeof timestamp === 'number' ? timestamp * 1000 : timestamp)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleTimeString('zh-CN', { hour12: false })
}
</script>
