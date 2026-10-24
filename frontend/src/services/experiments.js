/**
 * Harness²-lite 实验对比 / 证据只读 API。
 *
 * 这些接口只读，不会修改后端数据；证据内容由后端脱敏后返回。
 */
import api from './api.js'

/**
 * 列出实验。
 * @returns {Promise<{experiments: Array<Object>}>}
 */
export async function listExperiments() {
  return api.get('/api/experiments')
}

/**
 * 获取单个实验的候选与 case × 候选对比数据。
 * @param {string} experimentId
 * @returns {Promise<{experiment: Object, candidates: Array<Object>, cases: Array<Object>}>}
 */
export async function getExperiment(experimentId) {
  return api.get(`/api/experiments/${encodeURIComponent(experimentId)}`)
}

/**
 * 获取同一对比结构的报告（可用于刷新/导出）；后端未实现时调用方应降级。
 * @param {string} experimentId
 */
export async function getExperimentReport(experimentId) {
  return api.get(`/api/experiments/${encodeURIComponent(experimentId)}/report`)
}

/**
 * 读取一次运行的脱敏证据；没有证据时后端返回 404。
 * @param {string} runId
 */
export async function getEvidence(runId) {
  return api.get(`/api/evidence/${encodeURIComponent(runId)}`)
}

/**
 * 按实验/候选/指纹过滤运行记录（沿用运行列表返回结构）。
 * @param {{experiment_id?: string, candidate_id?: string, fingerprint?: string, limit?: number, offset?: number}} params
 */
export async function listExperimentRuns(params = {}) {
  return api.get('/api/runs', { params })
}
