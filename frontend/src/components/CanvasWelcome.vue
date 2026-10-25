<template>
  <div class="canvas-empty">
    <div class="welcome-content">
      <div class="empty-flow-art" aria-hidden="true">
        <span class="welcome-mini-node"><AppIcon name="agent" :size="24" /><small>研究</small></span>
        <span class="welcome-connector"><i></i><AppIcon name="chevron" :size="13" /></span>
        <span class="welcome-mini-node welcome-node-dark"><AppIcon name="flow" :size="25" /><small>创作</small></span>
        <span class="welcome-connector"><i></i><AppIcon name="chevron" :size="13" /></span>
        <span class="welcome-mini-node"><AppIcon name="check" :size="24" /><small>审阅</small></span>
      </div>
      <span class="eyebrow">FROM AN IDEA TO A WORKFLOW</span>
      <h2>把想法，交给一个好团队。</h2>
      <p>连接不同角色的智能体，让复杂任务一步步完成。<br />从空白画布开始，或先体验一次完整编排。</p>
      <div class="starter-options">
        <button class="starter-card" @click="$emit('create')">
          <span class="starter-icon"><AppIcon name="plus" :size="21" /></span>
          <span class="starter-copy"><strong>从空白开始</strong><small>自由定义你的协作流程</small></span>
          <AppIcon class="starter-arrow" name="arrow" :size="17" />
        </button>
        <button class="starter-card" @click="$emit('demo')">
          <span class="starter-icon"><AppIcon name="flow" :size="21" /></span>
          <span class="starter-copy"><strong>体验内容创作示例</strong><small>研究 → 创作 → 审阅</small></span>
          <AppIcon class="starter-arrow" name="arrow" :size="17" />
        </button>
      </div>
      <div class="welcome-footnote"><AppIcon name="check" :size="13" /><span>支持顺序、并行、层次、辩论、投票、动态与群聊协作</span><span class="welcome-footnote-divider"></span><span>示例无需连接模型</span></div>
    </div>
  </div>
</template>
<script setup>
import AppIcon from './AppIcon.vue'
defineEmits(['create', 'demo'])
</script>
