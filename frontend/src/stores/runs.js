/**
 * 运行历史状态管理
 */
import { defineStore } from 'pinia'
import { getWorkflowRuns, getRunDetail, listAllRuns, deleteRun, compareRuns } from '../services/runs.js'
import { formatDuration, formatTimestamp, pickLatestRun, statusClass } from '../utils/runStatus.js'

export const useRunsStore = defineStore('runs', {
  state: () => ({
    // 当前查看的运行列表
    runs: [],
    // 当前运行详情
    currentRun: null,
    // 当前工作流最近一次运行（来自后端，不依赖内存）
    latestRun: null,
    latestRunError: null,
    // 对比的运行列表
    comparisonRuns: [],
    // 加载状态
    loading: false,
    // 错误信息
    error: null,
    // 分页信息
    pagination: {
      total: 0,
      limit: 20,
      offset: 0,
    },
  }),

  getters: {
    /**
     * 获取格式化的运行列表
     */
    formattedRuns: (state) => {
      return state.runs.map(run => ({
        ...run,
        duration: formatDuration(run.total_duration),
        createdAtFormatted: formatTimestamp(run.created_at),
        statusClass: statusClass(run.status),
      }))
    },

    /**
     * 是否有运行记录
     */
    hasRuns: (state) => state.runs.length > 0,

    /**
     * 是否正在对比
     */
    isComparing: (state) => state.comparisonRuns.length > 0,
  },

  actions: {
    /**
     * 加载工作流运行历史
     */
    async loadWorkflowRuns(workflowId, limit = 20, offset = 0) {
      this.loading = true
      this.error = null

      try {
        const response = await getWorkflowRuns(workflowId, limit, offset)
        this.runs = response.runs || []
        this.pagination = {
          total: response.total || 0,
          limit: response.limit || 20,
          offset: response.offset || 0,
        }
      } catch (error) {
        this.error = error.message || '加载运行历史失败'
        console.error('Failed to load workflow runs:', error)
      } finally {
        this.loading = false
      }
    },

    /**
     * 加载所有运行
     */
    async loadAllRuns(limit = 20, offset = 0) {
      this.loading = true
      this.error = null

      try {
        const response = await listAllRuns(limit, offset)
        this.runs = response.runs || []
        this.pagination = {
          total: response.total || 0,
          limit: response.limit || 20,
          offset: response.offset || 0,
        }
      } catch (error) {
        this.error = error.message || '加载运行列表失败'
        console.error('Failed to load all runs:', error)
      } finally {
        this.loading = false
      }
    },

    /**
     * 从后端读取当前工作流最近一次运行。
     * 刷新页面或断线重连后，状态仍然以服务端记录为准。
     */
    async loadLatestRun(workflowId) {
      this.latestRun = null
      this.latestRunError = null
      if (!workflowId) return null

      try {
        const response = await getWorkflowRuns(workflowId, 1, 0)
        this.latestRun = pickLatestRun(response?.runs)
        return this.latestRun
      } catch (error) {
        this.latestRunError = error.message || '加载最近运行失败'
        console.error('Failed to load latest run:', error)
        return null
      }
    },

    /**
     * 加载运行详情
     */
    async loadRunDetail(runId) {
      this.loading = true
      this.error = null

      try {
        const run = await getRunDetail(runId)
        this.currentRun = run
      } catch (error) {
        this.error = error.message || '加载运行详情失败'
        console.error('Failed to load run detail:', error)
      } finally {
        this.loading = false
      }
    },

    /**
     * 删除运行
     */
    async removeRun(runId) {
      this.loading = true
      this.error = null

      try {
        await deleteRun(runId)
        // 从列表中移除
        this.runs = this.runs.filter(run => run.run_id !== runId)
        this.pagination.total -= 1
      } catch (error) {
        this.error = error.message || '删除运行失败'
        console.error('Failed to delete run:', error)
        throw error
      } finally {
        this.loading = false
      }
    },

    /**
     * 对比运行
     */
    async loadComparison(runIds) {
      this.loading = true
      this.error = null

      try {
        const response = await compareRuns(runIds)
        this.comparisonRuns = response.runs || []
        return response
      } catch (error) {
        this.error = error.message || '加载对比数据失败'
        console.error('Failed to compare runs:', error)
        throw error
      } finally {
        this.loading = false
      }
    },

    /**
     * 清空对比
     */
    clearComparison() {
      this.comparisonRuns = []
    },

    /**
     * 清空当前运行详情
     */
    clearCurrentRun() {
      this.currentRun = null
    },

    /**
     * 清空最近运行（切换工作流时避免显示上一个工作流的记录）
     */
    clearLatestRun() {
      this.latestRun = null
      this.latestRunError = null
    },
  },
})
