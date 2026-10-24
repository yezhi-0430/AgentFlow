<template>
  <div class="run-history-panel">
    <!-- 运行历史按钮 - 添加到导航栏 -->
    <button
      class="rail-button"
      :class="{ 'is-on': showHistory }"
      title="运行历史"
      aria-label="查看运行历史"
      @click="toggleHistory"
    >
      <AppIcon name="history" />
      <span class="nav-label">运行历史</span>
    </button>

    <!-- 运行历史侧边栏 -->
    <div v-if="showHistory" class="history-sidebar">
      <div class="history-tabs">
        <button
          :class="{ active: activeTab === 'list' }"
          @click="activeTab = 'list'"
        >
          历史列表
        </button>
        <button
          v-if="selectedRunId"
          :class="{ active: activeTab === 'detail' }"
          @click="activeTab = 'detail'"
        >
          运行详情
        </button>
        <button
          v-if="comparisonRunIds.length > 0"
          :class="{ active: activeTab === 'comparison' }"
          @click="activeTab = 'comparison'"
        >
          运行对比
        </button>
      </div>

      <div class="history-content">
        <RunHistory
          v-if="activeTab === 'list'"
          ref="historyList"
          :workflow-id="workflowId"
          @view-detail="viewDetail"
          @compare="compareRuns"
        />
        <RunDetail
          v-if="activeTab === 'detail' && selectedRunId"
          :run-id="selectedRunId"
          @close="closeDetail"
        />
        <RunComparison
          v-if="activeTab === 'comparison' && comparisonRunIds.length > 0"
          :run-ids="comparisonRunIds"
          @close="closeComparison"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import AppIcon from './AppIcon.vue'
import RunHistory from './RunHistory.vue'
import RunDetail from './RunDetail.vue'
import RunComparison from './RunComparison.vue'

const props = defineProps({
  workflowId: {
    type: String,
    default: null,
  },
})

const showHistory = ref(false)
const activeTab = ref('list')
const selectedRunId = ref(null)
const comparisonRunIds = ref([])
const historyList = ref(null)

function open() {
  showHistory.value = true
}

function close() {
  showHistory.value = false
  activeTab.value = 'list'
  selectedRunId.value = null
  comparisonRunIds.value = []
}

function toggleHistory() {
  if (showHistory.value) close()
  else open()
}

// 执行结束或切换工作流后由父组件调用：回到列表并重新从 API 拉取。
async function refresh() {
  if (!showHistory.value) return
  activeTab.value = 'list'
  await nextTick()
  historyList.value?.refresh?.()
}

// 切换工作流时清空选中状态，避免把上一个工作流的运行详情当成当前的。
watch(() => props.workflowId, () => {
  selectedRunId.value = null
  comparisonRunIds.value = []
  activeTab.value = 'list'
})

defineExpose({ open, close, refresh })

function viewDetail(runId) {
  selectedRunId.value = runId
  activeTab.value = 'detail'
}

function closeDetail() {
  selectedRunId.value = null
  activeTab.value = 'list'
}

function compareRuns(runIds) {
  comparisonRunIds.value = runIds
  activeTab.value = 'comparison'
}

function closeComparison() {
  comparisonRunIds.value = []
  activeTab.value = 'list'
}
</script>

<style scoped>
.run-history-panel {
  display: contents;
}

.history-sidebar {
  position: fixed;
  right: 0;
  top: 0;
  bottom: 0;
  width: min(800px, 100vw);
  background: white;
  box-shadow: -2px 0 8px rgba(0, 0, 0, 0.1);
  z-index: 100;
  display: flex;
  flex-direction: column;
}

.history-tabs {
  display: flex;
  gap: 8px;
  padding: 16px;
  border-bottom: 1px solid #e5e7eb;
  background: #f9fafb;
}

.history-tabs button {
  padding: 8px 16px;
  background: white;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.15s;
}

.history-tabs button:hover {
  background: #f3f4f6;
}

.history-tabs button.active {
  background: #2563eb;
  color: white;
  border-color: #2563eb;
}

.history-content {
  flex: 1;
  overflow-y: auto;
}
</style>
