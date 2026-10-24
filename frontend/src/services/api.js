import axios from 'axios'
import { applyAuthHeader } from '../utils/apiAuth.js'

const API_BASE_URL = import.meta.env?.VITE_API_BASE_URL || 'http://localhost:8000'

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器：后端设置 AGENTFLOW_API_TOKEN 时，前端用 VITE_API_TOKEN 附加 Bearer 头。
// token 只进入请求头，不打印、不持久化；未设置时不添加任何 Authorization。
api.interceptors.request.use(
  (config) => applyAuthHeader(config, import.meta.env?.VITE_API_TOKEN),
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
api.interceptors.response.use(
  (response) => {
    return response.data
  },
  (error) => {
    console.error('API request failed:', error.response?.status || error.code || 'NETWORK_ERROR')
    return Promise.reject(error)
  }
)

export default api
