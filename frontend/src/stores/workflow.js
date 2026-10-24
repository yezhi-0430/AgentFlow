import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { workflowService, messageService, agentService } from '../services/workflow.js'
import { useMessageStore } from './messages.js'
import { formatExecutionError } from '../utils/connection.js'
import {
  mergeWorkflowDisplay,
  missingCredentialMessage,
  normalizeExecutionStatus,
  pickRestoredWorkflow,
  requiresCredentials as workflowRequiresCredentials,
} from '../utils/credentialState.js'
import { readStoredWorkflow, writeStoredWorkflow } from '../utils/workflowStorage.js'
import { resolveStopOutcome } from '../utils/stopControl.js'

const activeStatuses = new Set(['executing', 'running', 'stopping', 'paused'])
const errorText = error => {
  const detail = error.response?.data?.detail
  return typeof detail === 'string' ? detail : error.message || '请求失败，请检查后端服务是否启动。'
}

export const useWorkflowStore = defineStore('workflow', () => {
  const currentWorkflow = ref(null)
  const agents = ref([])
  const selectedAgentName = ref(null)
  const status = ref('idle')
  const currentRunId = ref(null)
  const runStatus = ref('')
  const currentStep = ref(0)
  const totalSteps = ref(0)
  const messageCount = ref(0)
  const executionError = ref('')
  const connectionError = ref('')
  const submitting = ref(false)
  // 停止请求是否正在提交（与后端已经进入 stopping 区分开）。
  const stopping = ref(false)
  // 用户是否已经请求停止；后端落定终态前保持“停止中”，避免界面闪回“运行中”。
  const stopRequested = ref(false)
  const stopError = ref('')
  const deleting = ref(false)
  const deletionError = ref('')
  // 后端已保存的工作流列表（含服务重启后恢复的定义）
  const workflows = ref([])
  const workflowsLoading = ref(false)
  const workflowListError = ref('')
  const importing = ref(false)
  const exporting = ref(false)
  const isRunning = computed(() => submitting.value || activeStatuses.has(status.value))
  const isStopping = computed(() => stopping.value || status.value === 'stopping')
  const selectedAgent = computed(() => agents.value.find(a => a.name === selectedAgentName.value))
  // 恢复/导入的工作流只有执行时拿到内存密钥，界面据此提示重新输入。
  const needsCredentials = computed(() => Boolean(currentWorkflow.value?.requires_credentials))
  let timer
  let generation = 0
  let runMessageOffset = 0
  let waitingForStart = false
  let workflowsRequest = null

  function disposeExecution() {
    clearTimeout(timer)
    generation++
  }
  function resetStopState() {
    stopping.value = false
    stopRequested.value = false
    stopError.value = ''
  }
  function selectAgent(name) { selectedAgentName.value = name }
  function updateStatus(newStatus) { status.value = newStatus }

  function syncWorkflowSummary(workflowId, patch) {
    if (!workflowId || !workflows.value.length) return
    workflows.value = workflows.value.map(item => (
      item?.workflow_id === workflowId ? { ...item, ...patch } : item
    ))
  }
  function removeWorkflowSummary(workflowId) {
    if (!workflowId) return
    workflows.value = workflows.value.filter(item => item?.workflow_id !== workflowId)
  }
  function persistCurrentWorkflow(workflow) {
    if (workflow && !workflow.isDemo && workflow.workflow_id) writeStoredWorkflow(workflow)
    else if (!workflow) writeStoredWorkflow(null)
  }

  function setWorkflow(workflow) {
    disposeExecution()
    const messages = useMessageStore()
    messages.clearMessages()
    const next = workflow ? { ...workflow } : null
    if (next) {
      next.requires_credentials = workflowRequiresCredentials(next)
      next.status = normalizeExecutionStatus(next.status, next)
    }
    currentWorkflow.value = next
    agents.value = Array.isArray(next?.agents) ? next.agents : []
    totalSteps.value = Array.isArray(next?.steps) ? next.steps.length : (Number(next?.steps) || agents.value.length)
    selectedAgentName.value = null
    currentStep.value = 0
    status.value = next?.status || 'idle'
    currentRunId.value = null
    runStatus.value = ''
    messageCount.value = 0
    executionError.value = ''
    deletionError.value = ''
    connectionError.value = ''
    submitting.value = false
    resetStopState()
    runMessageOffset = 0
    waitingForStart = false
    persistCurrentWorkflow(next)
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
      // 恢复/导入的工作流在首次执行成功后不再需要密钥；同步到界面与本地列表。
      if (currentWorkflow.value?.workflow_id === id) {
        const requires = workflowRequiresCredentials(snapshot)
        currentWorkflow.value.requires_credentials = requires
        if (typeof snapshot.description === 'string' && snapshot.description !== currentWorkflow.value.description) {
          currentWorkflow.value.description = snapshot.description
        }
        syncWorkflowSummary(id, {
          requires_credentials: requires,
          ...(typeof snapshot.description === 'string' ? { description: snapshot.description } : {}),
        })
      }
      const messages = history.messages || []
      useMessageStore().messages = messages
      messageCount.value = messages.length
      currentStep.value = snapshot.current_step || 0
      totalSteps.value = snapshot.total_steps ?? totalSteps.value
      // 后端状态里带有真实运行记录时，优先使用它，避免 partial/stopped 被展示成成功。
      const latestRun = snapshot.current_run || {}
      const runId = latestRun.run_id || snapshot.run_id
      if (runId) currentRunId.value = runId
      if (latestRun.status) runStatus.value = latestRun.status
      // 后端运行记录里的 stop_requested 用来保持“停止中”，缺失时保留本地请求标记。
      if (latestRun && Object.prototype.hasOwnProperty.call(latestRun, 'stop_requested')) {
        stopRequested.value = Boolean(latestRun.stop_requested)
      } else if (snapshot && Object.prototype.hasOwnProperty.call(snapshot, 'stop_requested')) {
        stopRequested.value = Boolean(snapshot.stop_requested)
      }
      const lastRunStart = messages.findLastIndex(message => message.message_type === 'task' && message.metadata?.step_index === 0)
      const failures = messages.slice(Math.max(runMessageOffset, lastRunStart, 0)).filter(message => message.metadata?.error)
      executionError.value = failures.length ? formatExecutionError(failures[0].content) : formatExecutionError(snapshot.error || latestRun.error || '')
      if (snapshot.status !== 'idle' && snapshot.status !== 'created') waitingForStart = false
      let resolvedStatus = snapshot.status
      if (latestRun.status === 'failed' || snapshot.status === 'failed') resolvedStatus = 'failed'
      else if (latestRun.status === 'partial' || snapshot.status === 'partial') resolvedStatus = 'partial'
      else if (latestRun.status === 'stopped' || snapshot.status === 'stopped') resolvedStatus = 'stopped'
      else if (latestRun.status === 'cancelled' || snapshot.status === 'cancelled') resolvedStatus = 'cancelled'
      else if (failures.length && !activeStatuses.has(snapshot.status)) resolvedStatus = 'error'
      else if (latestRun.status === 'completed' || snapshot.status === 'completed') resolvedStatus = 'completed'
      else resolvedStatus = waitingForStart ? 'executing' : snapshot.status
      // 已请求停止但后端尚未落定终态时保持“停止中”，不闪回运行中，也不显示成功。
      if (stopRequested.value && (resolvedStatus === 'running' || resolvedStatus === 'executing')) resolvedStatus = 'stopping'
      status.value = normalizeExecutionStatus(resolvedStatus, currentWorkflow.value)
      // 后端状态里没有 current_run 时，用归一化后的终态补全最近运行标签。
      if (!latestRun.status && ['completed', 'failed', 'partial', 'stopped', 'cancelled'].includes(status.value)) {
        runStatus.value = status.value
      }
      if ((status.value === 'error' || status.value === 'failed') && !executionError.value) executionError.value = '工作流执行失败，请检查模型配置或后端日志。'
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
      if (error.response?.status === 404) {
        removeWorkflowSummary(id)
        connectionError.value = '该工作流已不存在（可能已被删除）。'
        waitingForStart = false
        status.value = 'error'
      } else {
        connectionError.value = '状态同步失败：' + errorText(error)
        if (isRunning.value) scheduleRefresh(token)
      }
    }
  }

  /**
   * 执行工作流。apiKey 只作为本次请求参数传入后端内存，绝不写入 store、日志或本地存储。
   */
  async function startExecution(task, apiKey = '') {
    const id = currentWorkflow.value?.workflow_id
    if (!id || currentWorkflow.value.isDemo || !task?.trim() || isRunning.value || deleting.value) return false
    const token = generation
    submitting.value = true
    executionError.value = ''
    connectionError.value = ''
    resetStopState()
    try {
      // Exclude previous attempts when detecting model errors in cumulative history.
      const history = await messageService.getMessages(id)
      if (token !== generation) return false
      runMessageOffset = history.messages?.length || 0
      const payload = { task: task.trim() }
      const key = typeof apiKey === 'string' ? apiKey.trim() : ''
      if (key) payload.api_key = key
      const response = await workflowService.executeWorkflow(id, payload)
      if (token !== generation) return false
      // 后端在收到密钥后已在内存中重建适配器，后续不必再要求密钥。
      if (currentWorkflow.value?.workflow_id === id) {
        currentWorkflow.value.requires_credentials = false
        syncWorkflowSummary(id, { requires_credentials: false })
      }
      // 新后端会在执行响应里返回 run_id；旧响应缺少该字段时保持兼容。
      const runId = response?.run_id || response?.run?.run_id
      if (runId) {
        currentRunId.value = runId
        runStatus.value = 'running'
      }
      status.value = 'executing'
      currentStep.value = 0
      waitingForStart = true
      await refreshExecution()
      return true
    } catch (error) {
      if (token === generation) {
        const httpStatus = error.response?.status
        const detail = error.response?.data?.detail
        const needsKey = missingCredentialMessage(error)
        if (httpStatus === 409) {
          // 同一工作流并发执行会被后端拒绝：同步真实状态，而不是伪造一次失败。
          executionError.value = '当前工作流已有运行中的任务，请等待结束或停止后再试。'
          status.value = 'running'
          scheduleRefresh(token)
        } else if (needsKey) {
          // 恢复/导入的工作流缺少密钥：保持可重试的等待状态并给出中文说明。
          executionError.value = needsKey
          if (currentWorkflow.value?.workflow_id === id) currentWorkflow.value.requires_credentials = true
          status.value = 'idle'
          waitingForStart = false
        } else if (httpStatus === 400 && typeof detail === 'string' && /not supported/i.test(detail)) {
          executionError.value = '该协作模式暂不支持，请重新创建顺序执行或并行执行的工作流。'
          status.value = 'error'
        } else {
          executionError.value = formatExecutionError(errorText(error))
          status.value = 'error'
        }
      }
      return false
    } finally {
      if (token === generation) submitting.value = false
    }
  }

  /**
   * 请求停止当前运行。
   * - 200 {"status":"stopping"}：进入停止中，继续轮询到 stopped；
   * - 200 {"status":"stopped"}：直接落到 stopped（绝不当作成功）；
   * - 409：后端没有活动运行，只同步真实状态，不伪造失败或成功；
   * - 网络/鉴权错误：保留停止中并继续轮询，同时给出中文提示。
   */
  async function stopExecution() {
    const workflow = currentWorkflow.value
    const id = workflow?.workflow_id
    if (!id || workflow.isDemo || stopping.value) return false
    if (!isRunning.value && !activeStatuses.has(status.value)) return false
    const token = generation
    stopping.value = true
    stopError.value = ''
    stopRequested.value = true
    status.value = 'stopping'
    runStatus.value = 'stopping'
    try {
      const response = await workflowService.stopWorkflow(id)
      if (token !== generation) return false
      const outcome = resolveStopOutcome({ status: response?.status })
      if (outcome.kind === 'stopped' || outcome.kind === 'terminal') {
        status.value = outcome.status
        runStatus.value = outcome.status
        stopRequested.value = false
      } else {
        status.value = 'stopping'
      }
      // 不论后端返回 stopping 还是已停止，都以状态接口/运行记录为最终依据。
      await refreshExecution()
      return true
    } catch (error) {
      if (token !== generation) return false
      const detail = error.response?.data?.detail
      const outcome = resolveStopOutcome({
        httpStatus: error.response?.status ?? null,
        status: error.response?.data?.status,
        detail: typeof detail === 'string' ? detail : '',
        networkError: !error.response,
      })
      stopError.value = outcome.message
      if (outcome.kind === 'no-active-run') {
        // 409 表示已经没有活动运行：以状态接口为准，避免把“停止请求无效”当成运行失败。
        stopRequested.value = false
      } else if (outcome.kind === 'network') {
        status.value = 'stopping'
        runStatus.value = 'stopping'
      }
      await refreshExecution()
      return false
    } finally {
      if (token === generation) stopping.value = false
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
        removeWorkflowSummary(workflow.workflow_id)
      }
      if (token === generation) setWorkflow(null)
      return true
    } catch (error) {
      if (error.response?.status === 404) {
        removeWorkflowSummary(workflow.workflow_id)
        if (token === generation) setWorkflow(null)
        return true
      }
      deletionError.value = formatExecutionError(errorText(error))
      return false
    } finally {
      deleting.value = false
    }
  }

  /** 从后端拉取已保存的工作流列表（服务重启后仍能看到历史定义）。 */
  async function loadWorkflows() {
    if (workflowsRequest) return workflowsRequest
    workflowListError.value = ''
    workflowsLoading.value = true
    workflowsRequest = (async () => {
      try {
        const data = await workflowService.getWorkflows()
        workflows.value = Array.isArray(data?.workflows) ? data.workflows : []
        return workflows.value
      } catch (error) {
        workflowListError.value = '工作流列表加载失败：' + errorText(error)
        return []
      } finally {
        workflowsLoading.value = false
      }
    })()
    try { return await workflowsRequest } finally { workflowsRequest = null }
  }

  async function activateWorkflow(workflowId, saved = null, token = generation) {
    try {
      const detail = await workflowService.getWorkflow(workflowId)
      if (token !== generation) return null
      setWorkflow(mergeWorkflowDisplay(saved, detail))
      await refreshExecution()
      return currentWorkflow.value
    } catch (error) {
      if (token !== generation) return null
      if (error.response?.status === 404) {
        removeWorkflowSummary(workflowId)
        connectionError.value = '该工作流已不存在（可能已被删除）。'
        return null
      }
      const summary = workflows.value.find(item => item?.workflow_id === workflowId)
      if (summary) {
        // 详情接口失败时仍可用列表摘要展示，至少让用户看到已恢复的定义。
        setWorkflow(mergeWorkflowDisplay(saved, summary))
        connectionError.value = '工作流详情暂时无法加载：' + errorText(error)
        return currentWorkflow.value
      }
      connectionError.value = '工作流载入失败：' + errorText(error)
      return null
    }
  }

  /** 切换到某个已保存的工作流（工作流库列表）。 */
  async function openWorkflow(workflowId) {
    if (!workflowId || isRunning.value || deleting.value) return false
    const token = generation
    const stored = readStoredWorkflow()
    const saved = stored.workflow?.workflow_id === workflowId ? stored.workflow : null
    const opened = await activateWorkflow(workflowId, saved, token)
    return Boolean(opened)
  }

  async function restoreWorkflow() {
    const token = generation
    const stored = readStoredWorkflow()
    // 用户主动清空的工作区：刷新后保持空白，不自动打开别的工作流。
    if (stored.empty) return
    try {
      await loadWorkflows()
      if (token !== generation || currentWorkflow.value) return
      const target = pickRestoredWorkflow(stored.workflow?.workflow_id, workflows.value)
      if (!target?.workflow_id) return
      const saved = stored.workflow?.workflow_id === target.workflow_id ? stored.workflow : null
      await activateWorkflow(target.workflow_id, saved, token)
    } catch {
      // 后端尚未启动时保留空白工作区。
    }
  }

  /** 导出当前工作流定义（后端返回已清洗密钥的版本化 JSON）。 */
  async function exportCurrentDefinition() {
    const workflow = currentWorkflow.value
    if (!workflow?.workflow_id || workflow.isDemo || exporting.value) return null
    exporting.value = true
    try {
      return await workflowService.getWorkflowDefinition(workflow.workflow_id)
    } finally {
      exporting.value = false
    }
  }

  /** 导入定义：后端分配新 workflow_id，导入后必须重新提供 API Key 才能执行。 */
  async function importDefinition(definition) {
    if (!definition || importing.value) return null
    const token = generation
    importing.value = true
    try {
      const created = await workflowService.importWorkflow(definition)
      if (token !== generation) return null
      if (!created?.workflow_id) throw new Error('导入接口没有返回 workflow_id。')
      let detail = null
      try { detail = await workflowService.getWorkflow(created.workflow_id) } catch { detail = null }
      setWorkflow({
        ...created,
        ...(detail || {}),
        requires_credentials: true,
        status: 'idle',
      })
      await loadWorkflows()
      return currentWorkflow.value
    } finally {
      importing.value = false
    }
  }

  return {
    currentWorkflow, agents, selectedAgent, status, currentRunId, runStatus, currentStep, totalSteps, messageCount,
    executionError, connectionError, submitting, isRunning, deleting, deletionError, requiresCredentials: needsCredentials,
    stopping, stopRequested, stopError, isStopping,
    workflows, workflowsLoading, workflowListError, importing, exporting,
    selectAgent, updateStatus, setWorkflow, startExecution, stopExecution, refreshExecution, restoreWorkflow, disposeExecution, deleteCurrentWorkflow,
    loadWorkflows, openWorkflow, exportCurrentDefinition, importDefinition,
  }
})
