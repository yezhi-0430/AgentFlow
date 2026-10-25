# 群聊模型目录（2026-10-26）

群聊统一通过 OpenRouter 调用。下面的精选模型用于模型目录接口不可用时的回退列表，也是创建群聊时的推荐组合；OpenRouter 在线目录恢复后会自动显示更多模型。

## 推荐组合

- **Lead**：`openai/gpt-6.1-sol` 或 `anthropic/claude-opus-5.5`
- **成员**：`openai/gpt-6-luna`、`deepseek/deepseek-v4.1-flash-1017`、`qwen/qwen3.8-max-prime`
- **低成本**：`deepseek/deepseek-v4.1-flash-1017`、`minimax/minimax-m3.1-flash`、`xiaomi/mimo-v2.6-pro`

## 模型特点

| 模型 | OpenRouter ID | 厂商 | 上下文 | 特点 | 适合角色 |
| --- | --- | --- | --- | --- | --- |
| GPT-6.1 Sol | `openai/gpt-6.1-sol` | OpenAI | 1.05M | 旗舰综合能力，规划与最终总结质量最高，成本较高 | Lead / 复杂任务 |
| GPT-6 Luna | `openai/gpt-6-luna` | OpenAI | 1.05M | 低成本高吞吐，响应快，适合大量成员发言 | 普通成员 |
| Claude Sonnet 5.5 | `anthropic/claude-sonnet-5.5` | Anthropic | 1M | 推理与代码均衡，长上下文稳定，适合评审和实现 | 评审 / 开发 |
| Claude Opus 5.5 | `anthropic/claude-opus-5.5` | Anthropic | 1M | 深度推理与长文写作，质量优先，价格高 | Lead / 写作 |
| Gemini 4 Argon | `google/gemini-4-argon` | Google | 1M | 原生多模态，支持图像、音频和搜索，适合资料分析 | 研究 / 多模态 |
| DeepSeek V4.1 Flash | `deepseek/deepseek-v4.1-flash-1017` | DeepSeek | 1M | 极低成本、速度快，适合并行成员和长讨论 | 普通成员 |
| Qwen3.8 Max Prime | `qwen/qwen3.8-max-prime` | Qwen | 1M | 中文与多语言强，适合中文产品和运营讨论 | 中文成员 |
| Grok 4.7 | `x-ai/grok-4.7` | xAI | 500K | 实时风格、搜索增强，观点鲜明，适合趋势判断 | 观点碰撞 |
| Mistral Large 4 | `mistralai/mistral-large-4-0` | Mistral | 1M | 推理效率高，结构化输出稳定，欧洲模型生态 | 分析 / 结构化 |
| Kimi K3.1 Pro | `moonshotai/kimi-k3.1-pro` | Moonshot | 1M | 中文长文档和资料整理能力强 | 研究 / 资料 |
| MiniMax M3.1 Flash | `minimax/minimax-m3.1-flash` | MiniMax | 1M | 低价快速，适合草稿、多轮和轻量成员 | 草稿 / 多轮 |
| GLM 5.3 Prime | `z-ai/glm-5.3-prime` | Zhipu | 1M | 中文 Agent 和代码优化，工具调用表现好 | 工具型成员 |
| Command A+ | `cohere/command-a-plus` | Cohere | 192K | 企业 RAG 和检索增强，适合知识库问答 | 知识库 / RAG |
| MiMo-V2.6-Pro | `xiaomi/mimo-v2.6-pro` | Xiaomi | 1.05M | 高性价比中文模型，成本敏感场景友好 | 成本优先 |
| Meta Muse Wonder | `meta/muse-wonder` | Meta | 1M | 创意和多模态，适合头脑风暴和内容创作 | 创意成员 |
| Nemotron 3.5 Super VL | `nvidia/nemotron-3.5-super-vl` | NVIDIA | 1M | 开源多模态，适合视觉资料和开放模型实验 | 视觉 / 实验 |

## 说明

- 模型目录接口每 10 分钟缓存一次；在线目录不可用时使用上表回退。
- 所有模型都走同一个 `OpenRouterAdapter`，按 `model` 参数区分，不需要为每个模型写单独调用方法。
- 支持原生 `tool_calls` 的模型会使用 OpenRouter 原生工具调用；不支持时回退到 JSON 工具协议。
- 模型是否可用、价格和上下文以 OpenRouter 账户与区域实际返回为准。
