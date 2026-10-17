export function buildGraph(workflow) {
  if (!Array.isArray(workflow?.agents)) return { nodes: [], edges: [] }
  const nodes = workflow.agents.map((agent, index) => ({
    id: `agent-${index}`, type: 'agent',
    position: { x: (index % 3) * 310, y: Math.floor(index / 3) * 220 },
    data: { ...agent, status: agent.status || 'idle', order: index + 1 },
  }))
  const edges = []
  if (workflow.pattern === 'sequential') {
    const order = Array.isArray(workflow.steps) && workflow.steps.length
      ? workflow.steps.map(step => nodes.find(n => n.data.name === step.agent_name)?.id)
      : nodes.map(n => n.id)
    for (let i = 1; i < order.length; i++) {
      if (order[i - 1] && order[i] && order[i - 1] !== order[i]) {
        edges.push({ id: `edge-${i}`, source: order[i - 1], target: order[i], type: 'smoothstep' })
      }
    }
  }
  return { nodes, edges }
}
