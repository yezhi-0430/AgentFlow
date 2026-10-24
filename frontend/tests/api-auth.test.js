import test from 'node:test'
import assert from 'node:assert/strict'
import { applyAuthHeader, buildAuthHeaders, normalizeApiToken } from '../src/utils/apiAuth.js'
import api from '../src/services/api.js'

test('未配置 token 时不添加 Authorization 头', () => {
  for (const token of [undefined, null, '', '   ', 123, {}]) {
    assert.deepEqual(buildAuthHeaders(token), {}, String(token))
    assert.equal(normalizeApiToken(token), '')
  }
})

test('配置 token 时构造 Bearer 头并去除首尾空白', () => {
  assert.equal(normalizeApiToken(' token '), 'token')
  assert.deepEqual(buildAuthHeaders(' abc '), { Authorization: 'Bearer abc' })
  assert.deepEqual(buildAuthHeaders('abc'), { Authorization: 'Bearer abc' })
})

test('applyAuthHeader 写入普通对象请求头，不覆盖已有头', () => {
  const config = { headers: { 'Content-Type': 'application/json' } }
  const result = applyAuthHeader(config, 'secret')
  assert.equal(result, config)
  assert.equal(config.headers.Authorization, 'Bearer secret')
  assert.equal(config.headers['Content-Type'], 'application/json')
})

test('已有 Authorization 或未配置 token 时保持原样', () => {
  const manual = { headers: { Authorization: 'Bearer manual' } }
  applyAuthHeader(manual, 'env-token')
  assert.equal(manual.headers.Authorization, 'Bearer manual')

  const untouched = { headers: { 'Content-Type': 'application/json' } }
  applyAuthHeader(untouched, undefined)
  assert.deepEqual(untouched.headers, { 'Content-Type': 'application/json' })
})

test('兼容 axios AxiosHeaders 风格的 set/get', () => {
  const values = new Map([['Content-Type', 'application/json']])
  const headers = {
    get: key => values.get(key),
    set: (key, value) => values.set(key, value),
  }
  applyAuthHeader({ headers }, 'abc')
  assert.equal(values.get('Authorization'), 'Bearer abc')
})

test('未配置 VITE_API_TOKEN 时，真实请求拦截器不发送 Authorization', async () => {
  let captured
  const originalAdapter = api.defaults.adapter
  try {
    api.defaults.adapter = async config => {
      captured = config
      return { data: {}, status: 200, statusText: 'OK', headers: {}, config }
    }
    await api.get('/api/health')
  } finally {
    api.defaults.adapter = originalAdapter
  }
  assert.ok(captured)
  assert.equal(captured.headers?.Authorization, undefined)
})
