# 群聊真实模型冒烟（2026-10-25）

## 范围

- 模式：`group_chat`，`enable_lead=true`
- 模型：`openai/gpt-4o-mini`（OpenAI 兼容接口，provider=`openai`）
- 智能体：`lead` + `member_1`（2 个）
- `max_turns=2`
- 任务：用两句话说明 Python list 与 tuple 的核心区别，并分别给出一个适用场景
- 开关：`AUTO_EVALUATE=false`，`ENABLE_LANGFUSE_TRACING=false`（冒烟不写外部 trace）
- 数据库：临时 SQLite（不污染本地开发数据）

## 结果

| 项目 | 结果 |
| --- | --- |
| 执行状态 | `completed` |
| 消息数 | 6 |
| 总 token | 1,247 |
| Lead 行为 | 输出合法 JSON，选择 `member_1` 并给出子任务 |
| 成员行为 | 围绕原始任务回答 list/tuple 区别与场景 |
| Lead 收尾 | 输出 `{"done": true, "summary": "..."}`，与成员回答一致 |
| 失败/重试 | 0 次执行失败；本脚本未启用追踪 |

## 结论

受控群聊的真实模型链路已跑通：Lead 能输出 JSON 分派、成员能围绕原始任务回答、Lead 能收尾。
样本只有 2 个 Agent、1 轮任务，不能说明群聊质量稳定；多轮/多人/不同模型仍需重复验证。

> 本次冒烟只验证“Lead 分派 + 成员回答 + Lead 收尾”。
> 执行器中介的 `ask_agent` / `handoff_to` 工具协议已用假 Agent 单测覆盖，并另做了一次真实模型工具冒烟（见下）。

## 真实模型工具冒烟（ask_agent）

- 模式：`group_chat`，`enable_lead=false`（纯成员群聊）
- 模型：`openai/gpt-4o-mini`
- 智能体：`member_1`、`member_2`
- `max_turns=2`
- 任务：要求 member_1 先用 `ask_agent` 请 member_2 核对 list/tuple 事实，再基于结果回答
- 结果：

| 项目 | 结果 |
| --- | --- |
| 执行状态 | `completed` |
| 消息数 | 6 |
| 总 token | 990 |
| 工具步骤 | `tool_1_member_1_member_2`、`tool_followup_1_member_1` |
| 结果 | member_1 输出合法 ask_agent JSON → member_2 返回 tuple 不可变 → member_1 基于结果给出最终回答 |

这说明工具协议不仅是假 Agent 单测，真实模型也能按 JSON 协议触发并被执行器正确路由。
仍未做多轮/多工具/非法工具参数的真实模型验证。

## 冒烟中发现并修复的问题

1. **初始 prompt 被短文案替换**：为了让时间线显示简洁，曾把发给模型的完整 prompt 换成短文案，导致 Lead 看不到原始任务，输出与任务无关。现已分离：
   - 模型收到完整 `input_text`；
   - 时间线通过 `metadata.display_content` 显示短文案。
2. **Lead 返回非 JSON 时把闲聊当子任务**：已改为回退到原始任务，并把运行标记为 `partial`。
3. **Lead 可能选择不存在的成员**：执行器会回退到合法成员并标记 `partial`；创建时的 Lead system prompt 已强调“next 必须来自成员列表”。

## 限制

- 仅一次冒烟，未做多轮重复/多人/不同模型对比；
- 未启用 Langfuse（避免外部写入），trace_id 为空；
- 未做自动 RSI；
- 真实模型费用很小但不为零（约千级 token）。
