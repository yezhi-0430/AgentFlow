import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { workflowService, messageService, agentService } from '../services/workflow.js'
import { useMessageStore } from './messages.js'
import { formatExecutionError } from '../utils/connection.js'

const activeStatuses = new Set(['executing', 'running', 'paused'])
const errorText = error => {
  const detail = error.response?.data?.detail
  return typeof detail === 'string' ? detail : error.message || '请求失败，请检查后端服务是否启动。'
}
const storageKey = 'agentflow.current-workflow'

export const useWorkflowStore = defineStore('workflow', () => {
  const currentWorkflow = ref(null)
  const agents = ref([])
  const selectedAgentName = ref(null)
  const status = ref('idle')
  const currentStep = ref(0)
  const totalSteps = ref(0)
  const messageCount = ref(0)
  const executionError = ref('')
  const connectionError = ref('')
  const submitting = ref(false)
  const deleting = ref(false)
  const deletionError = ref('')
  const isRunning = computed(() => submitting.value || activeStatuses.has(status.value))
  const selectedAgent = computed(() => agents.value.find(a => a.name === selectedAgentName.value))
  let timer
  let generation = 0
  let runMessageOffset = 0
  let waitingForStart = false

  function disposeExecution() {
    clearTimeout(timer)
    generation++
  }
  function selectAgent(name) { selectedAgentName.value = name }
  function updateStatus(newStatus) { status.value = newStatus }

  function setWorkflow(workflow) {
    disposeExecution()
    const messages = useMessageStore()
    messages.clearMessages()
    currentWorkflow.value = workflow
    agents.value = Array.isArray(workflow?.agents) ? workflow.agents : []
    totalSteps.value = Array.isArray(workflow?.steps) ? workflow.steps.length : (Number(workflow?.steps) || agents.value.length)
    selectedAgentName.value = null
    currentStep.value = 0
    status.value = workflow?.status || 'idle'
    messageCount.value = 0
    executionError.value = ''
    deletionError.value = ''
    connectionError.value = ''
    submitting.value = false
    runMessageOffset = 0
    waitingForStart = false
    try {
      if (workflow?.workflow_id && !workflow.isDemo) {
        // Save only display data; never persist API keys or adapter configuration.
        const { workflow_id, name, description, pattern, agents: displayAgents, steps } = workflow
        sessionStorage.setItem(storageKey, JSON.stringify({ workflow_id, name, description, pattern, agents: displayAgents, steps }))
      } else if (!workflow) {
        // Remember an intentionally empty workspace rather than auto-opening another workflow.
        sessionStorage.setItem(storageKey, 'null')
      }
    } catch { /* Storage can be unavailable in private browsing. */ }
  }

  function scheduleRefresh(token) {
    clearTimeout(timer)
    if (token === generation) timer = setTimeout(() => refreshExecution(), 1000)
  }

  async function refreshExecution() {
    const id = currentWorkflow.value?.workflow_id
    if (!id || currentWorkflow.value.isDemo) return
    const token = generation
    clearTimeout(timer)
    try {
      // Fetch history after status so a terminal snapshot includes the final response.
      const snapshot = await workflowService.getWorkflowStatus(id)
      const [history, agentData] = await Promise.all([
        messageService.getMessages(id),
        agentService.getAgents().catch(() => null),
      ])
      if (token !== generation) return
      connectionError.value = ''
      const messages = history.messages || []
      useMessageStore().messages = messages
      messageCount.value = messages.length
      currentStep.value = snapshot.current_step || 0
      totalSteps.value = snapshot.total_steps ?? totalSteps.value
      const lastRunStart = messages.findLastIndex(message => message.message_type === 'task' && message.metadata?.step_index === 0)
      const failures = messages.slice(Math.max(runMessageOffset, lastRunStart, 0)).filter(message => message.metadata?.error)
      executionError.value = failures.length ? formatExecutionError(failures[0].content) : formatExecutionError(snapshot.error || '')
      if (snapshot.status !== 'idle' && snapshot.status !== 'created') waitingForStart = false
      status.value = failures.length && !activeStatuses.has(snapshot.status) ? 'error' : (waitingForStart ? 'executing' : snapshot.status)
      if (status.value === 'error' && !executionError.value) executionError.value = '工作流执行失败，请检查模型配置或后端日志。'
      if (agentData) {
        agents.value = agents.value.map(agent => {
          const latest = agentData.agents?.find(item => item.workflow_id === id && item.name === agent.name)
          const model = messages.findLast(message => message.sender === agent.name && message.metadata?.model)?.metadata.model
          return latest ? { ...agent, ...latest, model: model || agent.model, messages_sent: messages.filter(message => message.sender === agent.name).length, messages_received: messages.filter(message => message.receiver === agent.name).length, tokens_used: latest.total_tokens } : agent
        })
      }
      if (activeStatuses.has(status.value)) scheduleRefresh(token)
    } catch (error) {
      if (token !== generation) return
      connectionError.value = error.response?.status === 404 ? '工作流已不存在，后端重启后需重新创建。' : '状态同步失败：' + errorText(error)
      if (error.response?.status === 404) {
        waitingForStart = false
        status.value = 'error'
      } else if (isRunning.value) scheduleRefresh(token)
    }
  }

  async function startExecution(task) {
    const id = currentWorkflow.value?.workflow_id
    if (!id || currentWorkflow.value.isDemo || !task?.trim() || isRunning.value || deleting.value) return false
    const token = generation
    submitting.value = true
    executionError.value = ''
    connectionError.value = ''
    try {
      // Exclude previous attempts when detecting model errors in cumulative history.
      const history = await messageService.getMessages(id)
      if (token !== generation) return false
      runMessageOffset = history.messages?.length || 0
      await workflowService.executeWorkflow(id, { task: task.trim() })
      if (token !== generation) return false
      status.value = 'executing'
      currentStep.value = 0
      waitingForStart = true
      await refreshExecution()
      return true
    } catch (error) {
      if (token === generation) {
        executionError.value = formatExecutionError(errorText(error))
        status.value = 'error'
      }
      return false
    } finally {
      if (token === generation) submitting.value = false
    }
  }

  async function deleteCurrentWorkflow() {
    const workflow = currentWorkflow.value
    if (!workflow || isRunning.value || deleting.value) return false
    const token = generation
    deleting.value = true
    deletionError.value = ''
    try {
      if (workflow.workflow_id && !workflow.isDemo) {
        const latest = await workflowService.getWorkflowStatus(workflow.workflow_id)
        if (activeStatuses.has(latest.status)) {
          deletionError.value = '工作流正在运行，请等待运行结束后再删除。'
          return false
        }
        await workflowService.deleteWorkflow(workflow.workflow_id)
      }
      if (token === generation) setWorkflow(null)
      return true
    } catch (error) {
      if (error.response?.status === 404) {
        if (token === generation) setWorkflow(null)
        return true
      }
      deletionError.value = formatExecutionError(errorText(error))
      return false
    } finally {
      deleting.value = false
    }
  }

  async function restoreWorkflow() {
    const token = generation
    try {
      let saved
      try {
        const stored = sessionStorage.getItem(storageKey)
        if (stored === 'null') return
        saved = JSON.parse(stored || 'null')
      } catch { /* No saved workflow. */ }
      const data = await workflowService.getWorkflows()
      if (token !== generation || currentWorkflow.value) return
      const existing = saved ? data.workflows?.find(workflow => workflow.workflow_id === saved.workflow_id) : data.workflows?.at(-1)
      if (existing) {
        setWorkflow({ ...saved, ...existing, agents: existing.agents.map(agent => ({ ...saved?.agents?.find(item => item.name === agent.name), ...agent })) })
        await refreshExecution()
      }
    } catch {
      // An empty workspace remains available if the backend is not started yet.
    }
  }

  return {
    currentWorkflow, agents, selectedAgent, status, currentStep, totalSteps, messageCount,
    executionError, connectionError, submitting, isRunning, deleting, deletionError,
    selectAgent, updateStatus, setWorkflow, startExecution, refreshExecution, restoreWorkflow, disposeExecution, deleteCurrentWorkflow,
  }
})
