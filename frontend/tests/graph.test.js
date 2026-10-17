import test from 'node:test'
import assert from 'node:assert/strict'
import { buildGraph } from '../src/utils/graph.js'

test('empty or summary-only workflow produces an empty canvas', () => {
  assert.deepEqual(buildGraph(null), { nodes: [], edges: [] })
  assert.deepEqual(buildGraph({ agents: 3 }), { nodes: [], edges: [] })
})

test('nodes preserve agent data and have distinct layout positions', () => {
  const agents = Array.from({ length: 5 }, (_, i) => ({ name: `agent-${i}`, role: 'worker', temperature: 0 }))
  const { nodes } = buildGraph({ agents })
  assert.equal(nodes.length, 5)
  assert.equal(new Set(nodes.map(n => `${n.position.x},${n.position.y}`)).size, 5)
  assert.equal(nodes[0].data.temperature, 0)
  assert.equal(nodes[0].data.status, 'idle')
})

test('sequential connectors follow execution steps rather than the agent list', () => {
  const { nodes, edges } = buildGraph({
    pattern: 'sequential', agents: [{ name: 'A' }, { name: 'B' }, { name: 'C' }],
    steps: [{ agent_name: 'C' }, { agent_name: 'A' }],
  })
  assert.equal(edges.length, 1)
  assert.equal(nodes.find(n => n.id === edges[0].source).data.name, 'C')
  assert.equal(nodes.find(n => n.id === edges[0].target).data.name, 'A')
})

test('parallel workflows do not imply sequential dependencies', () => {
  assert.equal(buildGraph({ pattern: 'parallel', agents: [{ name: 'A' }, { name: 'B' }] }).edges.length, 0)
})
