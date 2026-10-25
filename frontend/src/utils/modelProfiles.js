// 群聊模型精选：分类、推荐顺序与中文特点。
export const MODEL_CATEGORY_ORDER = ['综合旗舰', '代码与 Agent', '深度推理', '多模态', '中文优化', '高性价比', '实时观点', '长文档', '更多模型']

export const MODEL_PROFILES = {
  'openai/gpt-6.1-sol': {
    category: '综合旗舰', order: 1, recommended: true,
    note: '旗舰综合 · 1.05M 上下文 · 规划/总结质量最高，适合 Lead',
  },
  'anthropic/claude-sonnet-5.5': {
    category: '代码与 Agent', order: 2, recommended: true,
    note: '推理与代码均衡 · 1M 上下文 · 适合评审、实现和工具协作',
  },
  'deepseek/deepseek-v4.1-flash-1017': {
    category: '高性价比', order: 3, recommended: true,
    note: '极低成本高速度 · 1M 上下文 · 适合并行成员与长讨论',
  },
  'google/gemini-4-argon': {
    category: '多模态', order: 4, recommended: true,
    note: '原生多模态 · 1M 上下文 · 支持图像/音频/搜索',
  },
  'qwen/qwen3.8-max-prime': {
    category: '中文优化', order: 5, recommended: true,
    note: '中文/多语言强 · 1M 上下文 · 适合中文产品讨论',
  },
  'openai/gpt-6-luna': {
    category: '高性价比', order: 6, recommended: true,
    note: '低成本高吞吐 · 1.05M 上下文 · 适合大量成员发言',
  },
  'anthropic/claude-opus-5.5': {
    category: '深度推理', order: 7, recommended: false,
    note: '深度推理与长文写作 · 1M 上下文 · 质量优先、成本较高',
  },
  'x-ai/grok-4.7': {
    category: '实时观点', order: 8, recommended: true,
    note: '实时风格与搜索增强 · 500K 上下文 · 适合观点碰撞',
  },
  'moonshotai/kimi-k3.1-pro': {
    category: '长文档', order: 9, recommended: false,
    note: '中文长文档与资料整理 · 1M 上下文',
  },
  'mistralai/mistral-large-4-0': {
    category: '综合旗舰', order: 10, recommended: false,
    note: '推理效率高 · 1M 上下文 · 结构化输出稳定',
  },
  'minimax/minimax-m3.1-flash': {
    category: '高性价比', order: 11, recommended: false,
    note: '低价快速 · 1M 上下文 · 适合草稿与多轮',
  },
  'z-ai/glm-5.3-prime': {
    category: '代码与 Agent', order: 12, recommended: false,
    note: '中文 Agent 与代码 · 1M 上下文 · 适合工具型成员',
  },
  'cohere/command-a-plus': {
    category: '长文档', order: 13, recommended: false,
    note: '企业 RAG/检索 · 192K 上下文 · 适合知识库问答',
  },
  'xiaomi/mimo-v2.6-pro': {
    category: '中文优化', order: 14, recommended: false,
    note: '高性价比中文 · 1.05M 上下文 · 成本敏感场景',
  },
  'meta/muse-wonder': {
    category: '多模态', order: 15, recommended: false,
    note: '创意与多模态 · 1M 上下文 · 适合头脑风暴',
  },
  'nvidia/nemotron-3.5-super-vl': {
    category: '多模态', order: 16, recommended: false,
    note: '开源多模态 · 1M 上下文 · 适合视觉资料',
  },
}

export const RECOMMENDED_TEAM = {
  lead: 'openai/gpt-6.1-sol',
  members: [
    'openai/gpt-6-luna',
    'anthropic/claude-sonnet-5.5',
    'deepseek/deepseek-v4.1-flash-1017',
    'qwen/qwen3.8-max-prime',
    'google/gemini-4-argon',
  ],
}

export function modelProfile(modelId) {
  const base = String(modelId || '').split(':')[0]
  return MODEL_PROFILES[base] || {
    category: '更多模型', order: 999, recommended: false, note: '',
  }
}

export function sortModelOptions(options) {
  return [...options].sort((a, b) => {
    const profileA = modelProfile(a.value)
    const profileB = modelProfile(b.value)
    if (profileA.recommended !== profileB.recommended) return profileA.recommended ? -1 : 1
    const groupOrder = MODEL_CATEGORY_ORDER.indexOf(profileA.category) - MODEL_CATEGORY_ORDER.indexOf(profileB.category)
    if (groupOrder !== 0) return groupOrder
    if (profileA.order !== profileB.order) return profileA.order - profileB.order
    return String(a.label || '').localeCompare(String(b.label || ''), 'zh-CN')
  })
}
