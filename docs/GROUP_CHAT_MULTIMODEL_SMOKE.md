# 群聊多模型与全屏页冒烟（2026-10-26）

## 范围

- 群聊成员各自选择 OpenRouter 模型；
- Lead 独立选择模型；
- 全屏微信式群聊页面、头像、模型徽章、跨 run 历史；
- 每轮发言完成后追加消息，显示“正在发言”，不做逐 token 流式输出。

## 已验证

| 项目 | 结果 |
| --- | --- |
| 后端多模型创建 | 通过：Lead / 成员模型分别落库并返回 |
| 后端消息可见性 | 通过：默认隐藏 `visibility=internal`，`include_internal=true` 可见 |
| 跨 run 历史 | 通过：两次执行的消息均保留，按时间排序 |
| 状态字段 | 通过：`active_agent` / `active_model` 存在 |
| 前端构建 | 通过：lint、test、build |
| 全屏页面 | 通过：群列表、消息气泡、头像、模型徽章、成员面板可用 |
| 真实模型（DeepSeek） | 通过：`deepseek/deepseek-chat-v3.1`，max_turns=1，completed，1,193 tokens |
| 真实多厂商模型 | 未完成：`openai/gpt-4o-mini` 返回 403 “This model is not available in your region.” |

## 真实模型记录

- 模型：`deepseek/deepseek-chat-v3.1`（Lead + 1 个成员）
- 任务：用一句话说明 list 和 tuple 的区别
- 结果：`completed`，1,193 tokens
- 页面：消息按运行分隔，显示成员头像、模型徽章、自然语言回复与系统总结
- 说明：OpenAI 模型在当前网络区域被 OpenRouter 拒绝，属于 provider 区域限制，不是 AgentFlow 代码错误。

## 截图

![多模型群聊全屏页](images/group-chat-multimodel.png)

## 限制

- 未完成 GPT/Claude/Gemini 多厂商同时调用的真实冒烟；
- 头像为生成式首字母 + 品牌色，不是厂商 Logo；
- 不做 token 级流式输出；
- 群聊只支持 OpenRouter；其他模式保持原 provider 选择。
