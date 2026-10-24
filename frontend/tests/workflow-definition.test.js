import test from 'node:test'
import assert from 'node:assert/strict'
import {
  DEFINITION_SCHEMA_VERSION,
  definitionFileName,
  detectSecretFields,
  parseWorkflowDefinition,
  serializeDefinition,
  stripSecretFields,
  workflowDefinitionSummary,
} from '../src/utils/workflowDefinition.js'
import { readDefinitionFile, saveDefinitionText } from '../src/utils/definitionTransfer.js'

const validDefinition = () => ({
  schema_version: 1,
  workflow_id: 'wf-export-1',
  name: '内容创作 工作流',
  description: '研究、创作、审阅',
  pattern: 'sequential',
  agents: [
    { name: 'worker_1', role: 'worker', model: 'gpt-4', system_prompt: '写' },
    { name: 'worker_2', role: 'reviewer', model: 'gpt-4' },
  ],
  steps: [
    { id: 'step_1', agent_name: 'worker_1' },
    { id: 'step_2', agent_name: 'worker_2', input_from: 'step_1' },
  ],
  connection: { provider: 'openai' },
})

test('导出的定义可以完整解析并通过校验', () => {
  const result = parseWorkflowDefinition(JSON.stringify(validDefinition()))
  assert.equal(result.ok, true)
  assert.deepEqual(result.warnings, [])
  assert.equal(result.value.schema_version, DEFINITION_SCHEMA_VERSION)
  assert.equal(result.value.name, '内容创作 工作流')
  assert.equal(result.value.pattern, 'sequential')
})

test('兼容 { definition: ... } 包装与缺省 schema_version', () => {
  const wrapped = { definition: validDefinition() }
  assert.equal(parseWorkflowDefinition(JSON.stringify(wrapped)).ok, true)
  const noVersion = validDefinition()
  delete noVersion.schema_version
  assert.equal(parseWorkflowDefinition(JSON.stringify(noVersion)).ok, true)
  assert.equal(parseWorkflowDefinition(JSON.stringify(validDefinition())).value.schema_version, 1)
})

test('格式与字段错误给出中文提示且不抛异常', () => {
  assert.match(parseWorkflowDefinition('').error, /粘贴/)
  assert.match(parseWorkflowDefinition('   ').error, /粘贴/)
  assert.match(parseWorkflowDefinition('{ not json').error, /JSON/)
  assert.match(parseWorkflowDefinition('[1, 2]').error, /JSON 对象/)

  const tooNew = validDefinition()
  tooNew.schema_version = 99
  assert.match(parseWorkflowDefinition(JSON.stringify(tooNew)).error, /schema_version=99/)

  const noId = validDefinition()
  delete noId.workflow_id
  assert.match(parseWorkflowDefinition(JSON.stringify(noId)).error, /workflow_id/)

  const noName = validDefinition()
  noName.name = '  '
  assert.match(parseWorkflowDefinition(JSON.stringify(noName)).error, /name/)

  const unsupported = validDefinition()
  unsupported.pattern = 'debate'
  assert.match(parseWorkflowDefinition(JSON.stringify(unsupported)).error, /暂不支持/)

  const noAgents = validDefinition()
  noAgents.agents = []
  assert.match(parseWorkflowDefinition(JSON.stringify(noAgents)).error, /agents/)

  const noSteps = validDefinition()
  noSteps.steps = []
  assert.match(parseWorkflowDefinition(JSON.stringify(noSteps)).error, /steps/)
})

test('agent / step 引用关系按后端规则校验', () => {
  const duplicateAgent = validDefinition()
  duplicateAgent.agents.push({ name: 'worker_1', role: 'worker' })
  assert.match(parseWorkflowDefinition(JSON.stringify(duplicateAgent)).error, /重复/)

  const unknownAgent = validDefinition()
  unknownAgent.steps[0].agent_name = 'ghost'
  assert.match(parseWorkflowDefinition(JSON.stringify(unknownAgent)).error, /不存在的 agent/)

  const duplicateStep = validDefinition()
  duplicateStep.steps[1].id = 'step_1'
  assert.match(parseWorkflowDefinition(JSON.stringify(duplicateStep)).error, /step id 重复/)

  const unknownInput = validDefinition()
  unknownInput.steps[1].input_from = 'step_9'
  assert.match(parseWorkflowDefinition(JSON.stringify(unknownInput)).error, /input_from/)

  // 前向引用合法：按后端规则先收集全部 step id 再校验。
  const forward = validDefinition()
  forward.steps[0].input_from = 'step_2'
  assert.equal(parseWorkflowDefinition(JSON.stringify(forward)).ok, true)
})

test('定义中的疑似密钥字段会被识别并清洗，且提示不会回显密钥值', () => {
  const secret = 'sk-or-v1-super-secret-value'
  const payload = validDefinition()
  payload.api_key = secret
  payload.connection.api_key = secret
  payload.agents[0].api_key = secret
  payload.agents[0].metadata = { access_token: secret }

  const result = parseWorkflowDefinition(JSON.stringify(payload))
  assert.equal(result.ok, true)
  const serialized = JSON.stringify(result.value)
  assert.doesNotMatch(serialized, /super-secret-value/)
  assert.equal(result.value.api_key, undefined)
  assert.equal(result.value.connection.api_key, undefined)
  assert.equal(result.value.agents[0].api_key, undefined)

  assert.equal(result.warnings.length, 1)
  assert.match(result.warnings[0], /api_key/)
  assert.doesNotMatch(result.warnings[0], /super-secret-value/)

  const paths = detectSecretFields(payload)
  assert.ok(paths.includes('api_key'))
  assert.ok(paths.includes('connection.api_key'))
  assert.ok(paths.includes('agents[0].metadata.access_token'))
})

test('导出文本经过清洗与格式化，文件名安全', () => {
  const payload = validDefinition()
  payload.api_key = 'sk-should-not-be-exported'
  const text = serializeDefinition(payload)
  assert.match(text, /\n {2}"schema_version": 1/)
  assert.doesNotMatch(text, /sk-should-not-be-exported/)
  assert.doesNotMatch(JSON.stringify(stripSecretFields({ token: 'x', keep: 1 })), /"token"/)
  assert.deepEqual(JSON.parse(text).steps.length, 2)

  const file = definitionFileName(payload)
  assert.match(file, /^agentflow-.*\.json$/)
  assert.doesNotMatch(file, /[\\/:*?"<>|]/)

  const reserved = definitionFileName({ name: 'a/b:c*?"<>|', workflow_id: 'wf-123456789' })
  assert.match(reserved, /^agentflow-a-b-c-/)
  assert.match(reserved, /wf-12345\.json$/)
  assert.match(definitionFileName({}), /^agentflow-workflow\.json$/)
})

test('导入预览摘要展示可读信息', () => {
  const summary = workflowDefinitionSummary(validDefinition())
  assert.equal(summary.name, '内容创作 工作流')
  assert.equal(summary.patternLabel, '顺序执行')
  assert.equal(summary.agentCount, 2)
  assert.equal(summary.stepCount, 2)
})

test('导出在浏览器 API 可用时下载文件', async () => {
  const clicked = []
  const revoked = []
  const link = { href: '', download: '', rel: '', click: () => clicked.push('click'), remove: () => clicked.push('remove') }
  const env = {
    Blob: class { constructor(parts) { this.parts = parts } },
    URL: { createObjectURL: () => 'blob:mock', revokeObjectURL: url => revoked.push(url) },
    document: { createElement: () => link, body: { appendChild: () => {} } },
  }
  const result = await saveDefinitionText('{"ok":true}', 'wf.json', env)
  assert.equal(result.method, 'download')
  assert.equal(link.download, 'wf.json')
  assert.equal(link.href, 'blob:mock')
  assert.deepEqual(clicked, ['click', 'remove'])
  assert.deepEqual(revoked, ['blob:mock'])
})

test('下载不可用时降级到剪贴板，再降级到手动复制', async () => {
  let copied = ''
  const clipboardEnv = { navigator: { clipboard: { writeText: async text => { copied = text } } } }
  const clipboard = await saveDefinitionText('{"ok":true}', 'wf.json', clipboardEnv)
  assert.equal(clipboard.method, 'clipboard')
  assert.equal(copied, '{"ok":true}')

  const manual = await saveDefinitionText('{"ok":true}', 'wf.json', {})
  assert.equal(manual.method, 'manual')
  assert.equal(manual.text, '{"ok":true}')

  const denied = await saveDefinitionText('{"ok":true}', 'wf.json', { navigator: { clipboard: { writeText: async () => { throw new Error('denied') } } } })
  assert.equal(denied.method, 'manual')
})

test('读取本地 JSON 文件支持 file.text 与失败提示', async () => {
  assert.equal(await readDefinitionFile({ text: async () => '{"a":1}' }), '{"a":1}')
})
