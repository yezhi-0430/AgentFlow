import api from './api.js'

export const modelService = {
  async getOpenRouterModels() {
    return api.get('/api/models/openrouter')
  },
}
