/**
 * 运行历史相关 API
 */
import api from './api.js'

/**
 * 获取工作流的运行历史
 * @param {string} workflowId - 工作流 ID
 * @param {number} limit - 返回数量限制
 * @param {number} offset - 偏移量
 * @returns {Promise<Object>}
 */
export async function getWorkflowRuns(workflowId, limit = 20, offset = 0) {
  return api.get(`/api/workflows/${workflowId}/runs`, {
    params: { limit, offset }
  })
}

/**
 * 获取运行详情
 * @param {string} runId - 运行 ID
 * @returns {Promise<Object>}
 */
export async function getRunDetail(runId) {
  return api.get(`/api/runs/${runId}`)
}

/**
 * 列出所有运行
 * @param {number} limit - 返回数量限制
 * @param {number} offset - 偏移量
 * @returns {Promise<Object>}
 */
export async function listAllRuns(limit = 20, offset = 0) {
  return api.get('/api/runs', {
    params: { limit, offset }
  })
}

/**
 * 删除运行记录
 * @param {string} runId - 运行 ID
 * @returns {Promise<Object>}
 */
export async function deleteRun(runId) {
  return api.delete(`/api/runs/${runId}`)
}

/**
 * 对比多个运行
 * @param {string[]} runIds - 运行 ID 数组
 * @returns {Promise<Object>}
 */
export async function compareRuns(runIds) {
  const runIdsStr = runIds.join(',')
  return api.get('/api/runs/compare', {
    params: { run_ids: runIdsStr }
  })
}
