# 群聊多模型与全屏群聊页设计

- 日期：2026-10-26
- 状态：待确认
- 目标仓库：AgentFlow

## 1. 背景与目标

当前群聊工作流只能为整个群聊选择一个模型，所有 Agent 共用一个 Adapter；群聊 UI 是工作台内的弹层，消息只显示 sender / receiver / content，没有模型标识和头像。

本次要把它升级为：

1. 创建群聊时，逐个选择加入群聊的模型；
2. 单独选择 Lead 模型，或从成员模型中指定 Lead；
3. 点击「群聊」进入全屏群聊页面，而不是弹层；
4. 消息以微信式气泡呈现，带头像、成员名、模型徽章、角色和时间；
5. 每一轮 Agent 发言完成后显示消息，并显示「正在发言」状态；
6. 群聊调用统一走 OpenRouter，一个 OpenRouter Key 支持多个模型。

已确认：**不做逐 token 流式输出**，采用轮次完成后的消息追加 + 正在发言状态。

## 2. 非目标

- 不做逐 token SSE / WebSocket 流式输出；
- 不在本次接入 MCP、Skills 或通用外部工具；
- 不改变顺序、并行、层次、辩论、投票、动态等其他模式的模型配置；
- 不做多用户实时协作、语音、文件传输；
- 不把 API Key 写入数据库、导出定义或消息记录；
- 不做自动 RSI / 自迭代。

## 3. 现状约束

- `create_workflow` 只创建一个 Adapter，并把同一个 `model` 传给所有 `AgentConfig`；
- `AgentConfig.model` 字段已存在，但 `_build_pattern_agents` 只接收一个全局 model；
- 群聊 Agent 数量规则：有 Lead 时 `agent_count` 是总数（Lead + members），无 Lead 时全部为 members；最多 6 个；
- 群聊消息已持久化到 `workflow_messages`，`metadata` 可保存模型、角色、轮次等扩展信息；
- 群聊面板通过 1.2s 轮询刷新消息和状态，没有流式协议；
- 前端没有 Vue Router，当前群聊是 `GroupChatPanel.vue` 弹层；
- 前端 `modelOptions` 是硬编码列表，且包含过时/不准确的模型标识；
- OpenRouter 已有 `OpenRouterAdapter`，支持 OpenAI 兼容的 tools / tool_calls。

## 4. 已选择的实现方向

### 4.0 已确认的产品决策（2026-10-26）

1. **气泡可见性**：默认隐藏 Lead 的原始规划 JSON；成员自然语言发言显示为微信气泡；工具调用显示为简洁系统卡片（可展开详情）；Lead 分派/总结使用系统消息样式。
2. **历史范围**：一个群聊保留跨多次运行的历史；每次运行用分隔线/时间标记；消息 API 返回全部历史并支持分页，不再只返回当前 run。
3. **Lead 选择**：Lead 是独立协调者，单独选择模型，可以不是成员之一；有 Lead 时总数仍最多 6（Lead + 最多 5 个成员）。
4. **Key 重新输入**：全屏群聊页保留“重新输入 API Key”输入；密钥只驻留内存，不落库。
5. **旧群聊兼容**：旧 `agent_count + 全局 model` 配置继续可创建/恢复/执行；只有新的 `members` 配置强制 OpenRouter。
6. **tools 能力**：不硬性拦截不支持 tools 的模型；目录显示能力徽章，群聊仍可用 JSON 协议兜底。

### 4.1 模型架构：单 OpenRouter Adapter + 每 Agent 独立 model

一个群聊工作流只创建一个 `OpenRouterAdapter`，所有 Agent 共享它；每个 `AgentConfig.model` 保存自己的 OpenRouter model id。Lead 也是普通 LLM Agent，只是角色为 coordinator，使用独立的 `lead_model`。

未选择方案：

- 每个 Agent 独立 Adapter：支持混用 provider，但与「统一 OpenRouter」冲突，密钥与配置复杂度高；
- 保持全局单模型：不满足需求。

### 4.2 全屏页面：SPA 内全屏视图 + hash

不引入 Vue Router；在 `App.vue` 增加页面状态，URL 使用 `#group-chat`（可带 workflow id），点击「群聊」进入全屏页，返回按钮/浏览器后退回到画布。

未选择方案：

- 引入 vue-router：URL 更规范，但需要重构现有导航；
- 独立 HTML 页面：重复外壳和状态，不划算。

### 4.3 头像：生成式首字母 + 品牌色

每个 Agent 根据名字/模型生成稳定头像：首字母或模型短名 + 品牌色 + 角色徽章；Lead 加皇冠标识。后续可以替换为厂商 Logo，不影响数据结构。

未选择方案：

- 直接使用厂商 Logo：识别度高，但要处理图标资源与版权；
- 外部头像服务：依赖网络，不适合本地优先。

## 5. 数据模型与 API

### 5.1 创建请求

群聊配置新增以下结构，同时保留旧字段兼容：

```json
{
  "name": "多模型产品评审",
  "pattern": "group_chat",
  "config": {
    "llm_provider": "openrouter",
    "api_key": "sk-or-...",
    "model": "openai/gpt-5",
    "group_chat": {
      "enable_lead": true,
      "lead_model": "anthropic/claude-sonnet-4.5",
      "members": [
        { "name": "member_1", "model": "openai/gpt-5" },
        { "name": "member_2", "model": "google/gemini-2.5-pro" },
        { "name": "member_3", "model": "deepseek/deepseek-chat" }
      ],
      "max_turns": 12
    }
  }
}
```

规则：

- 群聊只允许 `llm_provider="openrouter"`（其他 provider 返回 400）；
- 有 Lead 时 `members` 至少 1 个、总数不超过 6；无 Lead 时 `members` 至少 2 个、最多 6；
- `members[].name` 唯一，不能叫 `lead`；
- `members[].model` 必填，允许自定义 OpenRouter model id；
- `enable_lead=false` 时忽略 `lead_model`；
- 未传 `members` 时，回退到旧的 `agent_count` + 全局 `model`，生成 `member_1..N`；
- `max_turns` 仍限制在 1–20。
- Lead 模型与成员模型可以重复，不做唯一性限制。

### 5.2 Agent 构建

- `_build_pattern_agents` 增加群聊专用入口，接收 `lead_model` 和 `members`；
- `AgentConfig.model` 使用各自的 model；
- 全部 Agent 共用一个 OpenRouter Adapter；
- 持久化定义只保存 agents 的 model/role/prompt，不保存 api_key。

### 5.3 消息、可见性与历史

消息 metadata 增加：

```json
{
  "model": "openai/gpt-5",
  "provider": "openrouter",
  "role": "member",
  "turn": 3,
  "visibility": "chat",
  "display_content": "..."
}
```

`visibility` 取值：

- `chat`：成员自然语言发言，渲染为微信气泡；
- `system`：Lead 分派/总结、轮次分隔，渲染为系统消息；
- `tool`：`ask_agent` / `handoff_to` 调用，渲染为可展开的工具卡片；
- `internal`：Lead 原始规划 JSON、内部提示，默认不返回给聊天视图。

消息 API 调整：

```text
GET /api/messages?workflow_id=<id>&limit=50&before=<timestamp>&include_internal=false
```

- 默认返回跨 run 的全部可见历史（`chat/system/tool`），按时间升序；
- 分页使用 `before`（时间戳）和 `limit`，默认 50，最大 200；
- 每条消息保留 `run_id`；前端按 `run_id` 变化插入“本次运行”分隔线；
- 旧消息没有 `visibility` 时按 `chat` 处理；无法解析的 Lead JSON 由前端识别并隐藏；
- 当前运行的内存消息与 DB 消息按 `id` 去重。

运行状态增加当前发言者：

```json
{
  "active_agent": "member_2",
  "active_model": "google/gemini-2.5-pro"
}
```

前端据此显示「member_2 正在发言…」；轮次结束后消息通过现有轮询追加，不引入流式协议。

### 5.4 OpenRouter 模型目录

新增后端接口：

```text
GET /api/models/openrouter
```

- 代理 OpenRouter `/api/v1/models`；
- 内存缓存 10 分钟；
- 返回 id、名称、厂商、上下文长度、价格、是否支持 tools；
- 失败时返回精选 fallback 列表；
- 前端按厂商分组、支持搜索，并允许输入自定义 model id。

不再依赖前端的虚假/过期模型名作为唯一来源。

## 6. 全屏群聊页面

新增 `GroupChatPage.vue`，布局：

```text
┌──────────────────────────────────────────────────────┐
│ ← 返回画布   群聊名称 / 状态 / 模型数     运行 · 停止 │
├──────────────┬───────────────────────────┬───────────┤
│ 群聊列表      │ 微信式消息流               │ 成员面板   │
│ + 新建群聊    │ 头像 名字 模型徽章 角色     │ Lead/成员  │
│              │ 气泡内容 / 时间             │ 模型       │
│              │ 正在发言状态                │            │
├──────────────┴───────────────────────────┴───────────┤
│ 任务输入框                                   开始群聊 │
└──────────────────────────────────────────────────────┘
```

消息样式：

- 每个成员有稳定的生成头像；
- 每条消息显示：头像、名字、模型徽章、Lead/成员角色、时间；
- Lead 的消息带协调者标识；
- 系统消息（分派、总结、run 分隔）单独样式；
- `visibility=tool` 显示为「member_1 → member_2：核对事实」的系统卡片，可展开原始结果；
- `visibility=internal` 的 Lead 原始规划 JSON 不显示；
- 当前发言者显示「正在思考 / 正在发言」占位气泡；
- 轮次完成后消息追加，自动滚动到底部；
- 跨 run 历史加载后，按运行插入“本次运行”分隔线；
- 顶部提供滚动加载更早消息（分页）。

全屏页还需要：

- 当 `selected.requires_credentials` 为真时，显示“重新输入 API Key”输入框；密钥只驻留页面内存；
- 支持停止当前运行、切换群聊、刷新后恢复 hash；
- 群聊列表显示每个群的成员模型摘要。

创建群聊弹窗改造：

- 成员数量 1–5（有 Lead）/ 2–6（无 Lead）；
- 每个成员一行：名字 + 模型选择；
- Lead 开关 + Lead 模型选择（独立模型，可不在成员中）；
- 统一 OpenRouter Key 输入；
- 模型目录支持搜索与自定义 id；
- 创建成功后直接进入全屏群聊页。

## 7. 分阶段计划

### Phase 1：后端模型配置

- 群聊配置 schema 与校验；
- 每 Agent model；
- 单 OpenRouter Adapter；
- 消息 metadata 与 active_agent 状态；
- 单元/API 测试。

### Phase 2：OpenRouter 模型目录

- 模型列表代理接口 + 缓存；
- fallback 精选列表；
- 前端模型选择数据源改造；
- 错误与空状态。

### Phase 3：全屏群聊页

- `GroupChatPage.vue`；
- App 视图切换 + hash/返回；
- 微信式消息气泡、头像、模型徽章、角色、时间；
- 正在发言状态；
- 成员面板和输入区；
- 前端组件测试。

### Phase 4：创建流程

- 创建弹窗多模型选择；
- Lead 模型选择；
- 兼容旧群聊配置；
- 创建后进入全屏页。

### Phase 5：验证

- 后端 2/3/6 成员与非法配置测试；
- 前端消息/状态/头像测试；
- 真实 OpenRouter 冒烟：至少 2 个不同厂商模型 + Lead，确认模型标识和消息顺序；
- 更新 README、开发文档和限制说明。

## 8. 风险与边界

- 模型 id 会变化：用动态目录 + 自定义 id，不把硬编码列表当唯一来源；
- 多模型成本更高：保留 max_turns、工具预算、token 统计和停止能力；
- 全屏页面仍是单机本地应用：hash 只是视图状态，不是服务端路由；
- 不做逐 token 流式输出，发送中的「正在发言」来自运行状态，不是 token 流；
- 现有群聊定义需要兼容：旧 `agent_count` + 全局 model 仍可创建和恢复。

## 9. 待确认

- 是否接受头像先用「生成式首字母 + 品牌色」，后续再换厂商 Logo；
- 是否接受全屏页先用 `#group-chat` hash，不引入 Vue Router；
- 是否接受群聊只允许 OpenRouter，其他模式保持现状。

以上确认后，再进入实现计划和分阶段开发。
