/**
 * 可选 API Token 支持。
 *
 * 后端只有在设置 AGENTFLOW_API_TOKEN 时才要求所有 /api 请求携带
 * `Authorization: Bearer <token>`；前端从构建期环境变量 VITE_API_TOKEN 读取。
 *
 * 安全约束：
 * - 未设置（undefined / 空字符串 / 纯空白）时不添加任何请求头；
 * - token 只用于构造 Authorization 请求头，不持久化、不打印、不写入 localStorage；
 * - VITE_ 前缀意味着该值会打包进浏览器资源，只适用于本地或受信环境。
 */

const AUTH_HEADER = 'Authorization'

/** 归一化 token：只接受字符串，去掉首尾空白；其余情况视为未配置。 */
export function normalizeApiToken(token) {
  if (typeof token !== 'string') return ''
  return token.trim()
}

/** 纯函数：根据 token 构造请求头；没有 token 时返回空对象。 */
export function buildAuthHeaders(token) {
  const value = normalizeApiToken(token)
  return value ? { [AUTH_HEADER]: `Bearer ${value}` } : {}
}

/**
 * 纯函数：把可选 Authorization 写入 axios 请求配置。
 * 显式设置过 Authorization 的请求不覆盖；没有 token 时原样返回配置。
 */
export function applyAuthHeader(config, token) {
  if (!config || typeof config !== 'object') return config
  const authorization = buildAuthHeaders(token)[AUTH_HEADER]
  if (!authorization) return config

  const headers = config.headers
  const current = typeof headers?.get === 'function' ? headers.get(AUTH_HEADER) : headers?.[AUTH_HEADER]
  if (current) return config

  if (typeof headers?.set === 'function') headers.set(AUTH_HEADER, authorization)
  else config.headers = { ...(headers || {}), [AUTH_HEADER]: authorization }
  return config
}
