<template>
  <button
    class="rail-button"
    title="群聊协作 · 多 Agent 共享对话"
    aria-label="打开群聊协作"
    @click="$emit('open')"
  >
    <AppIcon name="message" /><span class="nav-label">群聊</span><span class="nav-count">{{ groupWorkflows.length }}</span>
  </button>
</template>

<script setup>
import { computed } from 'vue'
import AppIcon from './AppIcon.vue'
import { useWorkflowStore } from '../stores/workflow'

defineEmits(['open'])
const workflowStore = useWorkflowStore()
const groupWorkflows = computed(() => (workflowStore.workflows || []).filter(workflow => workflow.pattern === 'group_chat'))
</script>
