/**
 * 实验对比状态管理（Harness²-lite）。
 *
 * 只缓存后端返回的只读数据：实验列表、当前实验对比、按 run_id 缓存的脱敏证据。
 * 不写本地存储，不打印密钥。
 */
import { defineStore } from 'pinia'
import { getEvidence, getExperiment, listExperiments } from '../services/experiments.js'
import { normalizeExperimentDetail, normalizeExperimentList, normalizeEvidence } from '../utils/experimentDetails.js'

function readableError(error, fallback) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail.trim()
  if (error?.response?.status === 404) return '实验不存在或已被删除。'
  return fallback
}

export const useExperimentsStore = defineStore('experiments', {
  state: () => ({
    experiments: [],
    listLoading: false,
    listError: '',
    selectedId: '',
    detail: null,
    detailLoading: false,
    detailError: '',
    evidenceByRun: {},
    evidenceRunId: '',
    evidenceLoading: false,
    evidenceError: '',
  }),

  getters: {
    hasExperiments: state => state.experiments.length > 0,
    selectedExperiment: state => state.detail?.experiment || null,
  },

  actions: {
    /** 从后端刷新实验列表；失败时保留旧列表并给出中文错误。 */
    async loadExperiments() {
      this.listLoading = true
      this.listError = ''
      try {
        const payload = await listExperiments()
        this.experiments = normalizeExperimentList(payload)
      } catch (error) {
        this.listError = readableError(error, '实验列表加载失败，请确认后端服务已启动。')
        console.error('Failed to load experiments:', error?.response?.status || error?.code || 'NETWORK_ERROR')
      } finally {
        this.listLoading = false
      }
      return this.experiments
    },

    /** 选择并加载一个实验的候选对比数据。 */
    async selectExperiment(experimentId) {
      const id = typeof experimentId === 'string' ? experimentId.trim() : ''
      if (!id) return null
      this.selectedId = id
      this.detail = null
      this.detailError = ''
      this.detailLoading = true
      try {
        const payload = await getExperiment(id)
        this.detail = normalizeExperimentDetail(payload)
        return this.detail
      } catch (error) {
        this.detail = null
        this.detailError = readableError(error, '实验对比加载失败，请稍后重试。')
        console.error('Failed to load experiment:', error?.response?.status || error?.code || 'NETWORK_ERROR')
        return null
      } finally {
        this.detailLoading = false
      }
    },

    /** 返回实验列表视图，清空当前选中。 */
    clearSelection() {
      this.selectedId = ''
      this.detail = null
      this.detailError = ''
      this.detailLoading = false
    },

    /**
     * 读取运行证据并缓存；404 表示该运行没有保存证据（证据采集默认关闭），
     * 属于正常降级而不是把空内容伪装成证据。
     */
    async loadEvidence(runId) {
      const id = typeof runId === 'string' ? runId.trim() : ''
      if (!id) return null
      if (this.evidenceByRun[id]) return this.evidenceByRun[id]

      this.evidenceRunId = id
      this.evidenceLoading = true
      this.evidenceError = ''
      try {
        const payload = await getEvidence(id)
        const evidence = normalizeEvidence(payload)
        this.evidenceByRun = { ...this.evidenceByRun, [id]: evidence }
        return evidence
      } catch (error) {
        const status = error?.response?.status
        this.evidenceError = status === 404
          ? '该运行没有保存执行证据（证据采集可能未开启）。'
          : readableError(error, '证据加载失败，请确认后端服务已启动后重试。')
        console.error('Failed to load evidence:', status || error?.code || 'NETWORK_ERROR')
        return null
      } finally {
        this.evidenceLoading = false
      }
    },

    clearEvidenceState() {
      this.evidenceRunId = ''
      this.evidenceLoading = false
      this.evidenceError = ''
    },
  },
})
