<template>
  <div class="agent-inspector">
    <div class="inspector-header"><h2><AppIcon name="sliders" :size="17" />智能体详情</h2><button class="icon-button" aria-label="关闭智能体详情" @click="$emit('close')"><AppIcon name="close" :size="17" /></button></div>
    <Transition name="inspector" mode="out-in">
      <div v-if="selectedAgent" :key="selectedAgent.name" class="inspector-body">
        <div class="agent-profile"><span class="profile-avatar"><AppIcon name="agent" :size="26" /></span><h3>{{ selectedAgent.name }}</h3><p>{{ roleLabels[selectedAgent.role] || selectedAgent.role || '智能体' }}</p><span class="tag"><span class="status-dot"></span>{{ statusLabels[selectedAgent.status] || selectedAgent.status || '就绪' }}</span></div>
        <section class="info-section"><h4>模型配置<span>01</span></h4><dl class="info-grid"><div><dt>模型</dt><dd>{{ selectedAgent.model || '由后端管理' }}</dd></div><div><dt>温度</dt><dd>{{ selectedAgent.temperature ?? '—' }}</dd></div><div><dt>最大令牌</dt><dd>{{ selectedAgent.max_tokens ?? '—' }}</dd></div></dl></section>
        <section v-if="selectedAgent.system_prompt" class="info-section"><h4>系统提示<span>02</span></h4><p class="prompt-box">{{ selectedAgent.system_prompt }}</p></section>
        <section class="info-section"><h4>使用统计<span>03</span></h4><div class="stats-grid"><div><strong>{{ selectedAgent.messages_sent || 0 }}</strong><span>已发送</span></div><div><strong>{{ selectedAgent.messages_received || 0 }}</strong><span>已接收</span></div><div><strong>{{ selectedAgent.tokens_used || 0 }}</strong><span>令牌</span></div></div></section>
        <div class="agent-actions" title="当前版本尚未提供智能体操作接口"><button class="btn btn-secondary" disabled><AppIcon name="reset" :size="14" />重置</button><button class="btn btn-secondary" disabled><AppIcon name="pause" :size="14" />暂停</button><button class="icon-button" disabled aria-label="移除智能体"><AppIcon name="trash" :size="15" /></button></div>
      </div>
      <div v-else class="inspector-body inspector-empty">
        <div class="inspector-empty-content"><div class="empty-inspector-icon"><AppIcon name="sliders" :size="25" /></div><h3>关注每一个细节</h3><p>选择画布中的智能体，<br />查看配置、角色与运行状态。</p><span class="selection-hint"><span class="keycap">↖</span> 点击任意节点</span></div>
        <div class="inspector-summary"><span class="small-caps">WORKSPACE OVERVIEW</span><div><span>智能体</span><strong>{{ workflowStore.agents.length.toString().padStart(2, '0') }}</strong></div><div><span>协作模式</span><strong>{{ patternLabels[workflowStore.currentWorkflow?.pattern] || '—' }}</strong></div></div>
      </div>
    </Transition>
  </div>
</template>
<script setup>
import { computed } from 'vue'
import AppIcon from './AppIcon.vue'
import { useWorkflowStore } from '../stores/workflow'
defineEmits(['close'])
const workflowStore = useWorkflowStore()
const selectedAgent = computed(() => workflowStore.selectedAgent)
const roleLabels = { coordinator: '协调者', worker: '工作者', reviewer: '审核者', specialist: '领域专家' }
const statusLabels = { idle: '就绪', running: '运行中', waiting: '等待中', completed: '已完成', error: '异常', paused: '已暂停', unavailable: '需要 API Key' }
const patternLabels = { sequential: '顺序执行', parallel: '并行执行', hierarchical: '层次协作', debate: '辩论模式' }
</script>
