import api from './api.js'

/**
 * 工作流相关 API
 */
export const workflowService = {
  /**
   * 获取所有工作流
   */
  async getWorkflows() {
    return api.get('/api/workflows')
  },

  /**
   * 获取工作流详情
   */
  async getWorkflow(workflowId) {
    return api.get(`/api/workflows/${workflowId}`)
  },

  /**
   * 创建工作流
   */
  async createWorkflow(data) {
    return api.post('/api/workflows', data)
  },

  /**
   * 导出工作流定义（版本化 JSON，不含密钥）
   */
  async getWorkflowDefinition(workflowId) {
    return api.get(`/api/workflows/${workflowId}/definition`)
  },

  /**
   * 导入工作流定义（后端分配新 workflow_id，导入后需要重新提供 API Key）
   */
  async importWorkflow(definition) {
    return api.post('/api/workflows/import', definition)
  },

  /**
   * 执行工作流
   */
  async executeWorkflow(workflowId, config) {
    return api.post(`/api/workflows/${workflowId}/execute`, config)
  },

  /**
   * 停止工作流
   */
  async stopWorkflow(workflowId) {
    return api.post(`/api/workflows/${workflowId}/stop`)
  },

  /**
   * 删除工作流
   */
  async deleteWorkflow(workflowId) {
    return api.delete(`/api/workflows/${workflowId}`)
  },

  /**
   * 获取工作流状态
   */
  async getWorkflowStatus(workflowId) {
    return api.get(`/api/workflows/${workflowId}/status`)
  },
}

/**
 * Agent 相关 API
 */
export const agentService = {
  /**
   * 获取所有 agents
   */
  async getAgents() {
    return api.get('/api/agents')
  },

  /**
   * 获取 agent 详情
   */
  async getAgent(agentName) {
    return api.get(`/api/agents/${agentName}`)
  },

  /**
   * 发送消息给 agent
   */
  async sendMessage(agentName, message) {
    return api.post(`/api/agents/${agentName}/message`, { message })
  },
}

/**
 * 消息相关 API
 */
export const messageService = {
  /**
   * 获取消息历史
   */
  async getMessages(workflowId, params = {}) {
    return api.get('/api/messages', { params: { workflow_id: workflowId, ...params } })
  },

  /**
   * 清空消息
   */
  async clearMessages(workflowId) {
    return api.delete(`/api/messages/${workflowId}`)
  },
}
