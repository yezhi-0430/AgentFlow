<template>
  <div class="workflow-canvas">
    <VueFlow id="agent-workspace" v-model:nodes="nodes" :edges="edges" :min-zoom="0.25" :max-zoom="2" :nodes-connectable="false" :edges-updatable="false" :delete-key-code="null" :zoom-on-double-click="false" @node-click="selectNode" @pane-click="workflowStore.selectAgent(null)" @nodes-initialized="fit">
      <Background :gap="22" :size="1" pattern-color="#d9d9d9" />
      <template #node-agent="{ data }">
        <div class="agent-node" :class="{ selected: workflowStore.selectedAgent?.name === data.name }" role="button" tabindex="0" :aria-label="'查看智能体：' + data.name" @keydown.enter.prevent.stop="selectName(data.name)" @keydown.space.prevent.stop="selectName(data.name)">
          <Handle type="target" :position="Position.Left" />
          <div class="node-topline"><span class="node-symbol"><AppIcon name="agent" :size="21" /></span><span class="node-order">AGENT {{ String(data.order).padStart(2, '0') }}</span><AppIcon class="node-detail-icon" name="chevron" :size="14" /></div>
          <div class="node-name">{{ data.name }}</div>
          <div class="node-role">{{ roleLabels[data.role] || data.role || '智能体' }}</div>
          <div class="node-bottomline"><span class="node-status"><span class="status-dot" :class="{ pulsing: data.status === 'running' }"></span>{{ statusLabels[data.status] || data.status }}</span><span class="node-model">{{ data.model || '后端模型' }}</span></div>
          <Handle type="source" :position="Position.Right" />
        </div>
      </template>
    </VueFlow>
    <div class="canvas-caption"><span class="status-dot"></span>{{ nodes.length ? '工作流视图' : '空白画布' }}<span class="canvas-caption-line"></span><span class="canvas-caption-description">{{ nodes.length ? '拖动节点调整位置，点击查看详情' : '准备好，让协作开始' }}</span></div>
    <Transition name="fade">
      <CanvasWelcome v-if="!nodes.length" @create="emit('create')" @demo="emit('demo')" />
    </Transition>
    <div class="canvas-toolbar" aria-label="画布控制">
      <button class="icon-button" aria-label="缩小" title="缩小" @click="zoomOut(motion())"><AppIcon name="minus" :size="16" /></button>
      <button class="zoom-label" title="重置为 100%" aria-label="重置缩放" @click="zoomTo(1, motion())">{{ Math.round(viewport.zoom * 100) }}%</button>
      <button class="icon-button" aria-label="放大" title="放大" @click="zoomIn(motion())"><AppIcon name="plus" :size="16" /></button>
      <span class="toolbar-divider"></span>
      <button class="icon-button" aria-label="适应画布" title="适应画布" @click="fit"><AppIcon name="fit" :size="16" /></button>
    </div>
    <span class="canvas-hint">拖动画布平移 <span>·</span> 滚轮缩放</span>
  </div>
</template>
<script setup>
import { ref, watch, nextTick, onBeforeUnmount } from 'vue'
import { VueFlow, Handle, Position, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import AppIcon from './AppIcon.vue'
import CanvasWelcome from './CanvasWelcome.vue'
import { useWorkflowStore } from '../stores/workflow'
import { buildGraph } from '../utils/graph'
const emit = defineEmits(['create', 'demo', 'selected'])
const workflowStore = useWorkflowStore()
const nodes = ref([])
const edges = ref([])
const { zoomIn, zoomOut, zoomTo, fitView, viewport, dimensions } = useVueFlow('agent-workspace')
let resizeTimer
const roleLabels = { coordinator: '协调者', worker: '创作执行', reviewer: '质量审核', specialist: '领域专家' }
const statusLabels = { idle: '就绪', running: '运行中', waiting: '等待中', completed: '已完成', error: '异常', paused: '已暂停' }
const motion = () => ({ duration: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 260 })
function fit() { return fitView({ padding: 0.18, maxZoom: 1, ...motion() }) }
// Fit only after Vue Flow has measured the final container size.
watch(() => [dimensions.value.width, dimensions.value.height], () => {
  clearTimeout(resizeTimer)
  if (nodes.value.length) resizeTimer = setTimeout(fit, 120)
})
onBeforeUnmount(() => clearTimeout(resizeTimer))
function selectNode({ node }) {
  selectName(node.data.name)
}
function selectName(name) {
  workflowStore.selectAgent(name)
  emit('selected')
}
async function autoLayout() {
  const graph = buildGraph({ ...workflowStore.currentWorkflow, agents: workflowStore.agents })
  nodes.value = graph.nodes
  edges.value = graph.edges
  await nextTick()
  await fit()
}
watch(() => workflowStore.currentWorkflow, workflow => {
  const graph = buildGraph(workflow)
  nodes.value = graph.nodes
  edges.value = graph.edges
}, { immediate: true })
watch(() => workflowStore.agents.map(a => a.status), () => {
  nodes.value.forEach(node => {
    const agent = workflowStore.agents.find(a => a.name === node.data.name)
    if (agent) node.data = { ...node.data, ...agent, status: agent.status || 'idle' }
  })
})
defineExpose({ fit, autoLayout })
</script>
