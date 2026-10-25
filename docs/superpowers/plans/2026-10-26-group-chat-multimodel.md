# 群聊多模型与全屏群聊页实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让群聊按成员/Lead 选择不同 OpenRouter 模型，并提供带头像、模型徽章和正在发言状态的全屏微信式群聊页。

**Architecture:** 一个群聊工作流只创建一个 OpenRouterAdapter；每个 Agent 使用自己的 `AgentConfig.model`。前端在现有 SPA 内用 `#group-chat` hash 切换到全屏 `GroupChatPage`，复用现有消息轮询与运行状态接口；不引入逐 token 流式协议。

**Tech Stack:** Python 3.13、FastAPI、Pydantic、SQLite、pytest；Vue 3、Pinia、node:test、Vite、OpenRouter。

**Spec:** `docs/superpowers/specs/2026-10-26-group-chat-multimodel-design.md`

## Global Constraints

- 群聊统一使用 `llm_provider="openrouter"`；其他模式保持现有 provider 选择。
- 群聊成员 2–6 个；有 Lead 时总数最多 6。
- 所有 Agent 共享一个 OpenRouter Key/Adapter；Key 不写入定义、消息、日志或导出。
- 不做逐 token SSE/WebSocket；消息在每轮完成后追加，当前发言人显示“正在发言”。
- 全屏页用 `#group-chat` hash；不引入 Vue Router。
- 头像使用生成式首字母 + 品牌色 + 角色徽章，不依赖外部图片服务。
- 旧群聊（`agent_count` + 全局 `model`）必须继续可创建/恢复。
- 所有新增行为先写失败测试，再实现；每个任务结束提交一次。

## Review Focus

- 旧群聊没有 `members` 字段时仍能被创建、恢复并执行。
- 成员重名、成员数为 1/7、Lead 模型缺失时返回 400，而不是运行中失败。
- OpenRouter 模型目录不可用时，前端仍可通过 fallback/自定义 id 创建群聊。
- 浏览器刷新 `#group-chat`、点击返回、运行中切换群聊时，页面状态不丢失或串群。
- 消息回放时即使没有实时运行状态，也能显示模型/角色并保持正确顺序。

---

### Task 1: 后端群聊成员模型配置

**Files:**
- Modify: `backend/agentflow/api/routes/workflow.py:202-404`
- Create: `backend/tests/test_group_chat_models.py`

**Interfaces:**
- Consumes: `WorkflowCreateRequest.config` dict、`AdapterFactory.create_adapter`、`AgentConfig`。
- Produces:
  - `_group_chat_specs(config: dict, agent_count: int, default_model: str) -> tuple[Optional[str], list[dict]]`
    - 返回 `(lead_model, members)`；
    - `members` 元素为 `{"name": str, "model": str}`；
    - 无 `group_chat.members` 时返回 `(None, [])`，交给旧逻辑。
  - `_build_pattern_agents(..., group_chat_config: Optional[dict] = None)`，群聊分支使用 `lead_model`/`members`。

- [ ] **Step 1: 写失败测试**

```python
def test_group_chat_accepts_per_member_models(client):
    response = client.post("/api/workflows", json={
        "name": "multi-model",
        "pattern": "group_chat",
        "config": {
            "llm_provider": "openrouter",
            "api_key": "sk-or-test",
            "model": "openai/gpt-5",
            "group_chat": {
                "enable_lead": True,
                "lead_model": "anthropic/claude-sonnet-4.5",
                "members": [
                    {"name": "member_1", "model": "openai/gpt-5"},
                    {"name": "member_2", "model": "google/gemini-2.5-pro"},
                ],
            },
        },
    })
    assert response.status_code == 200
    agents = {a["name"]: a["model"] for a in response.json()["agents"]}
    assert agents == {
        "lead": "anthropic/claude-sonnet-4.5",
        "member_1": "openai/gpt-5",
        "member_2": "google/gemini-2.5-pro",
    }

def test_group_chat_old_config_still_works(client):
    response = client.post("/api/workflows", json={
        "name": "old", "pattern": "group_chat",
        "config": {"agent_count": 3, "llm_provider": "openai",
                   "api_key": "test-only-not-a-real-key", "model": "test-model"},
    })
    assert response.status_code == 200
    assert [a["model"] for a in response.json()["agents"]] == ["test-model"] * 3

def test_group_chat_rejects_non_openrouter(client):
    response = client.post("/api/workflows", json={
        "name": "bad", "pattern": "group_chat",
        "config": {"llm_provider": "openai", "api_key": "x", "model": "gpt-4",
                   "group_chat": {"members": [
                       {"name": "member_1", "model": "openai/gpt-5"},
                       {"name": "member_2", "model": "google/gemini-2.5-pro"},
                   ]}},
    })
    assert response.status_code == 400
    assert "OpenRouter" in response.json()["detail"]

@pytest.mark.parametrize("members", [
    [],
    [{"name": "member_1", "model": "a"}, {"name": "member_1", "model": "b"}],
])
def test_group_chat_rejects_invalid_members(client, members):
    response = client.post("/api/workflows", json={
        "name": "bad", "pattern": "group_chat",
        "config": {"llm_provider": "openrouter", "api_key": "sk-or-test",
                   "model": "openai/gpt-5",
                   "group_chat": {"members": members}},
    })
    assert response.status_code == 400

def test_group_chat_allows_lead_plus_one_member(client):
    response = client.post("/api/workflows", json={
        "name": "lead-one", "pattern": "group_chat",
        "config": {"llm_provider": "openrouter", "api_key": "sk-or-test",
                   "model": "openai/gpt-5",
                   "group_chat": {"enable_lead": True,
                                  "lead_model": "anthropic/claude-sonnet-4.5",
                                  "members": [{"name": "member_1", "model": "openai/gpt-5"}]}},
    })
    assert response.status_code == 200
    assert len(response.json()["agents"]) == 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest backend/tests/test_group_chat_models.py -q`
Expected: FAIL（`group_chat.members` 未被读取，或模型断言不符）

- [ ] **Step 3: 实现配置解析与构建**

在 `workflow.py` 中新增 `_group_chat_specs`：

- 若 `group_chat.members` 存在：
  - 校验 list；有 Lead 时长度 1–5，无 Lead 时长度 2–6；总数不得超过 6；
  - 每个元素有非空 `name`/`model`，名字唯一且不能是 `lead`；
  - 若 `llm_provider != "openrouter"`，抛 `HTTPException(400, "group_chat requires OpenRouter")`；
  - `enable_lead` 为真时 `lead_model` 必填；Lead 模型独立，可与成员模型重复。
- 若无 `members`，返回 `(None, [])`，保持旧 `agent_count` 路径。
- `_build_pattern_agents` 群聊分支：使用 lead_model / members 生成 `AgentConfig`；无 members 时沿用当前循环。
- 创建时若群聊带 members，Adapter 只允许 `openrouter`；`group_chat_config` 传入 `_build_pattern_agents`。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest backend/tests/test_group_chat_models.py -q`
Expected: PASS

- [ ] **Step 5: 回归旧群聊测试**

Run: `python -m pytest backend/tests/test_group_chat.py backend/tests/test_run_semantics.py -q`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/agentflow/api/routes/workflow.py backend/tests/test_group_chat_models.py
git commit -m "feat(group-chat): support per-member OpenRouter models"
```

---

### Task 2: 消息可见性、跨 run 历史与正在发言状态

**Files:**
- Modify: `backend/agentflow/core/workflow.py`（`_execute_recorded_step`、group chat calls、`get_status`、初始化字段）
- Modify: `backend/agentflow/api/routes/message.py`
- Modify: `backend/tests/test_group_chat_models.py`
- Modify: `backend/tests/test_run_semantics.py`

**Interfaces:**
- Consumes: `LLMAgent.config.model`、`Agent.role`、`MessageRepository`、`WorkflowExecutor.message_history`。
- Produces:
  - `_execute_recorded_step(..., visibility: str = "chat")`，metadata 含 `visibility`。
  - `Message.metadata` 增加 `model`、`role`、`visibility`。
  - `WorkflowExecutor.active_agent`、`active_model`；`get_status()` 返回二者。
  - `GET /api/messages?workflow_id&limit&before&include_internal` 返回跨 run 可见历史。

- [ ] **Step 1: 写失败测试**

```python
def test_messages_hide_internal_by_default(client):
    # 执行一个带 Lead 的群聊
    visible = client.get("/api/messages", params={"workflow_id": workflow_id}).json()["messages"]
    assert all(m["metadata"].get("visibility") != "internal" for m in visible)
    hidden = client.get("/api/messages", params={"workflow_id": workflow_id, "include_internal": True}).json()["messages"]
    assert any(m["metadata"].get("visibility") == "internal" for m in hidden)

def test_messages_keep_history_across_runs(client):
    execute_workflow(client, workflow_id, "first")
    execute_workflow(client, workflow_id, "second")
    messages = client.get("/api/messages", params={"workflow_id": workflow_id, "limit": 200}).json()["messages"]
    assert len({m["run_id"] for m in messages}) >= 2
    assert [m["timestamp"] for m in messages] == sorted(m["timestamp"] for m in messages)

def test_status_exposes_active_agent(client):
    assert "active_agent" in client.get(status_url).json()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest backend/tests/test_group_chat_models.py -q`
Expected: FAIL（无 visibility 过滤、跨 run 历史被内存消息覆盖、status 缺 active_agent）

- [ ] **Step 3: 实现消息可见性与历史**

- `_execute_recorded_step` 增加 `visibility` 参数（默认 `chat`），写入 TASK metadata；响应消息 metadata 也补 `model/role/visibility`。
- 群聊调用点：
  - Lead 规划调用：`visibility="internal"`；
  - Lead 总结、run 分隔：`visibility="system"`；
  - 普通成员发言：`chat`；
  - `ask_agent/handoff_to` 的目标调用与工具结果：`tool`。
- `message.py`：
  - 读取 DB `list_by_workflow`（全部历史）+ 内存当前 run；
  - 按 `id` 去重，按 `timestamp` 升序；
  - 默认过滤 `visibility=internal`；
  - 支持 `limit`（默认 50，最大 200）与 `before`；
  - 每条消息保留 `run_id`。
- `get_status()` 返回 `active_agent`、`active_model`。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest backend/tests/test_group_chat_models.py backend/tests/test_group_chat.py backend/tests/test_run_semantics.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/agentflow/core/workflow.py backend/agentflow/api/routes/message.py backend/tests/test_group_chat_models.py backend/tests/test_run_semantics.py
git commit -m "feat(group-chat): filter messages and keep cross-run history"
```

---

### Task 3: OpenRouter 模型目录接口

**Files:**
- Create: `backend/agentflow/api/routes/models.py`
- Modify: `backend/agentflow/api/app.py`
- Create: `backend/tests/test_models_api.py`

**Interfaces:**
- Produces:
  - `GET /api/models/openrouter`
  - 响应：`{"models": [{"id","name","provider","context_length","pricing","supports_tools"}], "source": "remote"|"fallback"}`
  - 模块级缓存 `(expires_at, payload)`，TTL 600 秒。
  - `FALLBACK_MODELS: list[dict]` 覆盖 OpenAI/Anthropic/Google/DeepSeek/Qwen/xAI/Mistral 的代表模型。

- [ ] **Step 1: 写失败测试**

```python
def test_openrouter_models_remote(client, monkeypatch):
    async def fake_fetch():
        return [{"id": "openai/gpt-5", "name": "GPT-5", "provider": "OpenAI",
                 "context_length": 128000, "pricing": {}, "supports_tools": True}]
    monkeypatch.setattr(models_route, "_fetch_openrouter_models", fake_fetch)
    data = client.get("/api/models/openrouter").json()
    assert data["source"] == "remote"
    assert data["models"][0]["id"] == "openai/gpt-5"

def test_openrouter_models_fallback(client, monkeypatch):
    async def fail():
        raise RuntimeError("offline")
    monkeypatch.setattr(models_route, "_fetch_openrouter_models", fail)
    data = client.get("/api/models/openrouter").json()
    assert data["source"] == "fallback"
    assert len(data["models"]) >= 6
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest backend/tests/test_models_api.py -q`
Expected: FAIL（404）

- [ ] **Step 3: 实现接口**

- 使用 `httpx.AsyncClient(timeout=10)` 请求 `https://openrouter.ai/api/v1/models`；不发送 Key。
- 将 `data` 映射为前端字段；`supported_parameters` 包含 `tools` 时 `supports_tools=True`。
- 缓存成功结果 600 秒；异常/超时返回 `FALLBACK_MODELS`，`source="fallback"`。
- 在 `app.py` 注册 `models.router`，prefix `/api/models`。
- 不把远程响应中的无关字段透传。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest backend/tests/test_models_api.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/agentflow/api/routes/models.py backend/agentflow/api/app.py backend/tests/test_models_api.py
git commit -m "feat(models): add cached OpenRouter model catalog"
```

---

### Task 4: 全屏群聊页与 hash 视图

**Files:**
- Create: `frontend/src/components/GroupChatPage.vue`
- Create: `frontend/src/utils/avatars.js`
- Modify: `frontend/src/utils/groupChat.js`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/components/GroupChatPanel.vue`（仅保留 rail 按钮，点击 emit 打开页面）
- Create: `frontend/tests/avatars.test.js`
- Create: `frontend/tests/group-chat-page.test.js`

**Interfaces:**
- Consumes: `workflowService.loadWorkflows/getWorkflowStatus`、`messageService.getMessages(workflowId, {limit,before,include_internal})`、`normalizeGroupChatMessages`。
- Produces:
  - `avatarFor(name: string, model: string) -> { initials: string, color: string }`（稳定、同名同色）。
  - `classifyGroupMessage(message) -> "chat"|"system"|"tool"`；`internal` 不进入气泡。
  - `GroupChatPage` emit `close`；props `workflowId?: string`。
  - `App.vue` 的 `groupChatOpen = ref(false)` + `openGroupChat()/closeGroupChat()`，hash `#group-chat` 同步。

- [ ] **Step 1: 写失败测试**

```javascript
test('avatarFor is stable and uses initials', () => {
  const first = avatarFor('member_1', 'openai/gpt-5')
  assert.deepEqual(first, avatarFor('member_1', 'openai/gpt-5'))
  assert.equal(first.initials.length >= 1, true)
  assert.match(first.color, /^#[0-9a-f]{6}$/i)
})

test('internal lead planning messages are not bubbles', () => {
  assert.equal(classifyGroupMessage({ metadata: { visibility: 'internal' } }), null)
  assert.equal(classifyGroupMessage({ metadata: { visibility: 'tool' } }), 'tool')
  assert.equal(classifyGroupMessage({ sender: 'member_1', content: 'hi' }), 'chat')
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm --prefix frontend run test -- tests/avatars.test.js tests/group-chat-page.test.js`
Expected: FAIL（模块/函数不存在）

- [ ] **Step 3: 实现头像、消息分类与全屏页骨架**

- `avatars.js`：用 name+model 做稳定 hash，从 8 个品牌色选一个；initials 取 name 首字母/数字，Lead 用 `L`。
- `groupChat.js`：
  - `classifyGroupMessage`：`internal` 返回 null；`tool` 返回 tool；`system` 返回 system；其余返回 chat；
  - 旧数据无 `visibility` 时按 chat；明显是 Lead 规划 JSON 的消息降级为 system 或隐藏。
- `GroupChatPage.vue`：
  - 左侧群聊列表；
  - 中间消息气泡（头像、sender、model 徽章、role、content、time、正在发言占位）；
  - `tool` 渲染成可展开的系统卡片；`system` 使用分隔/居中样式；
  - 跨 run 历史按 `run_id` 插入分隔线，顶部“加载更早消息”分页；
  - 右侧成员面板（模型/角色/Lead 标识）；
  - 顶部返回/状态/模型数，底部任务输入；
  - `requires_credentials` 时显示“重新输入 API Key”输入框，密钥只驻页面内存。
- 从 `GroupChatPanel.vue` 移除 overlay 逻辑，仅保留 rail 按钮，emit `open`。
- `App.vue` 用 `v-if="groupChatOpen"` 渲染 `GroupChatPage`，否则原工作台；监听 `hashchange`/`popstate`，`#group-chat` 进入，返回时清 hash。

- [ ] **Step 4: 运行前端测试**

Run: `npm --prefix frontend run test -- tests/avatars.test.js tests/group-chat-page.test.js`
Expected: PASS

- [ ] **Step 5: 构建与回归**

Run: `npm --prefix frontend run test && npm --prefix frontend run lint && npm --prefix frontend run build`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add frontend/src/components/GroupChatPage.vue frontend/src/components/GroupChatPanel.vue frontend/src/utils/avatars.js frontend/src/utils/groupChat.js frontend/src/App.vue frontend/tests/avatars.test.js frontend/tests/group-chat-page.test.js
git commit -m "feat(group-chat): add full-screen hashed chat page"
```

---

### Task 5: 创建群聊的多模型选择

**Files:**
- Modify: `frontend/src/components/CreateWorkflowDialog.vue`
- Modify: `frontend/src/utils/workflowOptions.js`
- Create: `frontend/src/services/models.js`
- Create: `frontend/tests/group-chat-models.test.js`

**Interfaces:**
- Consumes: `GET /api/models/openrouter`。
- Produces:
  - `modelService.getOpenRouterModels() -> Promise<{models, source}>`。
  - 创建请求：
    - `group_chat.members: [{name, model}]`
    - `group_chat.lead_model?: string`
    - `group_chat.enable_lead: boolean`
- 校验：OpenRouter 群聊时有 Lead 时成员 1–5，无 Lead 时成员 2–6；每个成员有 model；Lead 开启时 `lead_model` 必填；Lead 模型独立，可不在成员中。

- [ ] **Step 1: 写失败测试**

```javascript
test('buildGroupChatConfig carries member and lead models', () => {
  const config = buildGroupChatConfig({
    members: [{ name: 'member_1', model: 'openai/gpt-5' }, { name: 'member_2', model: 'google/gemini-2.5-pro' }],
    enableLead: true,
    leadModel: 'anthropic/claude-sonnet-4.5',
  })
  assert.deepEqual(config.members.map(m => m.model), ['openai/gpt-5', 'google/gemini-2.5-pro'])
  assert.equal(config.lead_model, 'anthropic/claude-sonnet-4.5')
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm --prefix frontend run test -- tests/group-chat-models.test.js`
Expected: FAIL（buildGroupChatConfig 不存在）

- [ ] **Step 3: 实现创建 UI 与 payload**

- 群聊模式下显示成员行：名字输入 + 模型下拉；成员数量控制（有 Lead 1–5，无 Lead 2–6）。
- Lead 开关 + Lead 模型下拉（独立模型，可不在成员中）。
- 模型目录加载失败时展示 fallback 列表 + 自定义 model id 输入。
- 群聊请求强制 `llm_provider="openrouter"`。
- 保持非群聊路径不变。

- [ ] **Step 4: 运行测试**

Run: `npm --prefix frontend run test -- tests/group-chat-models.test.js`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/CreateWorkflowDialog.vue frontend/src/utils/workflowOptions.js frontend/src/services/models.js frontend/tests/group-chat-models.test.js
git commit -m "feat(group-chat): choose per-member and lead models"
```

---

### Task 6: 回归、文档与真实冒烟

**Files:**
- Modify: `README.md`
- Modify: `docs/development.md`
- Modify: `docs/limitations.md`
- Create: `docs/GROUP_CHAT_MULTIMODEL_SMOKE.md`

- [ ] **Step 1: 后端全量测试**

Run: `python -m pytest backend/tests -q`
Expected: PASS

- [ ] **Step 2: 前端全量测试、lint、build**

Run: `npm --prefix frontend run test && npm --prefix frontend run lint && npm --prefix frontend run build`
Expected: PASS

- [ ] **Step 3: 真实 OpenRouter 冒烟**

用 2 个不同模型 + Lead，OpenRouter Key，`max_turns=2`；连续执行两次，验证：
- 创建响应中每个 Agent 的 model 正确；
- 运行完成后消息 sender/model 正确；
- 默认不返回 Lead 原始规划 JSON，`include_internal=true` 才可见；
- 两次运行的消息都保留，前端出现运行分隔线；
- 全屏页能看到头像、模型徽章和对话；
- 失败时 run.error 可读。
记录 token 和结果到 `docs/GROUP_CHAT_MULTIMODEL_SMOKE.md`，不写 Key。

- [ ] **Step 4: 更新文档**

README 增加“群聊多模型 / 全屏群聊页 / OpenRouter 模型目录”；限制说明写清楚：不做逐 token 流式、头像为生成式、群聊只支持 OpenRouter。

- [ ] **Step 5: 提交**

```bash
git add README.md docs/development.md docs/limitations.md docs/GROUP_CHAT_MULTIMODEL_SMOKE.md
git commit -m "docs(group-chat): document multi-model full-screen chat"
```
