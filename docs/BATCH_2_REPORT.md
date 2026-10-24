# 第二批第 1 项：工作流定义持久化与导入导出

本报告记录实际实现、验证方式与边界。所有数字均来自本仓库本次实跑；未运行真实模型实验，
也未提交/推送代码。

## 一、目标与完成情况

| 目标 | 状态 | 说明 |
| --- | --- | --- |
| 工作流定义持久化 | 完成 | 定义写入本地 SQLite（`workflow_definitions`，schema v1），后端启动时自动恢复 |
| 密钥不落库 | 完成 | 定义导出/导入/持久化前统一清洗 `api_key`/`secret`/`token` 等字段；执行密钥只驻留内存 |
| 重启后可用 | 完成 | 恢复的工作流以 `requires_credentials=true` 出现在列表/详情/状态；提供密钥后可执行 |
| 定义导入/导出 | 完成 | `GET /api/workflows/{id}/definition`、`POST /api/workflows/import`；导入总是分配新 `workflow_id` |
| 前端支持 | 完成 | 刷新恢复、需密钥徽标与密码输入、工作流库、导入/导出入口、密钥不写入浏览器存储 |
| 回归测试 | 完成 | 后端新增 8 例（总计 140 passed）；前端新增 28 例（总计 81 passed） |

## 二、设计与实现

### 1. 定义格式（schema v1）

`agentflow/core/definition.py` 中的 `WorkflowDefinition`：

- 字段：`schema_version`、`workflow_id`、`name`、`description`、`pattern`（仅 sequential/parallel）、
  `agents`（名称/角色/系统提示词/模型/温度/最大 token）、`steps`（id/agent_name/input_from）、
  `max_iterations`、`connection`（仅 provider/base_url/site_url/app_name）、`metadata`、时间戳。
- 校验：模式必须受支持；agents/steps 非空且引用一致；id 唯一；数量上限；版本必须为 1。
- 脱敏：递归剔除 `api_key`、`secret`、`token`、`password`、`authorization` 及 `*_key/*_secret/*_token` 字段；
  连接信息只保留白名单字段。导入、导出、落库、读取都经过同一套清洗。

### 2. 持久化

- 新表 `workflow_definitions`（`workflow_id` 唯一、`definition_json`、`schema_version`、时间戳）；
  由 SQLAlchemy `create_all` 自动创建，旧数据库启动时自动补表。
- `WorkflowDefinitionRepository` 提供 upsert/get/list_all/delete。
- 创建/导入/删除工作流时同步写/删定义；历史运行记录不受删除影响。

### 3. 启动恢复与执行

- 应用 lifespan 中调用 `restore_workflows()`，把定义恢复成执行器（不注册 Agent/适配器）。
- 恢复的工作流：
  - 列表/详情/状态带 `requires_credentials=true`；详情 Agent 使用配置快照，状态为 `unavailable`；
  - 执行时若未提供 `api_key` → **400**，detail 说明需要密钥；
  - 提供 `api_key` 时按定义中的 provider/base_url 构建适配器并注册 Agent（仅内存），随后执行。
- 删除工作流同时删除定义；重新执行仍会创建新 run，费用与历史记录策略与第一批一致。

### 4. 导入/导出

- 导出：`GET /api/workflows/{workflow_id}/definition` → 版本化 JSON（无密钥）。
- 导入：`POST /api/workflows/import`，body 为定义 JSON（必须含 `schema_version`/`workflow_id`/`name`/`agents`/`steps`）；
  校验后分配新 `workflow_id`，`requires_credentials=true`。
- 前端：工具栏“导出定义”支持下载（浏览器 API 不可用时降级剪贴板/手动复制）；
  “工作流库”→“导入”支持选择 JSON 文件或粘贴并实时校验；导入成功后自动选中新工作流并提示需重新输入 API Key。

### 5. 前端（最小改动）

- 刷新后按 localStorage 中记录的 `workflow_id` 从 `GET /api/workflows` 恢复；失效则回退最近一个；主动清空保持空白。
- `requires_credentials` 时显示“需要重新输入 API Key”徽标与密码输入框；密钥仅随本次执行请求提交，
  结束时清空，不写 localStorage/sessionStorage/Pinia 持久化/日志；400 显示中文提示。
- 新增“工作流库”面板（列表/切换/导入）、导出入口、定义解析与密钥清洗工具。

## 三、实际验证结果

### 后端

```bash
cd backend && python -m pytest tests/ -q
```

**140 passed, 0 failed**（新增 `tests/test_workflow_definition.py` 8 例，覆盖：定义持久化无密钥、
导出/导入 roundtrip、删除、重启恢复与密钥门禁、损坏定义跳过、导入校验、导入脱敏、from_dict 校验）。

### 前端

```bash
cd frontend && npm run test && npm run lint && npm run build
```

- `npm run test`：**81 passed / 0 failed**（新增 28 例：定义解析/脱敏、credential 状态、工作流库/恢复）
- `npm run lint`：exit 0
- `npm run build`：✓ 131 modules transformed

### 真实进程重启冒烟（不调用模型）

为验证定义确实跨进程恢复，本次实际执行：

1. 启动后端 → 通过 API 创建 2 Agent 的顺序工作流（仅创建，不执行模型）→ 导出定义，确认导出无密钥；
2. **终止后端进程并重启**；
3. 重启后：
   - `GET /api/workflows` 包含该工作流，`requires_credentials=true`、名称/描述一致；
   - 详情 Agent 来自配置快照（status=unavailable），`connection.provider=openrouter`；
   - 未提供密钥执行 → 400（detail 含 needs an API key），未触发模型调用；
   - 导出定义与重启前一致；
   - `POST /api/workflows/import` 生成新 workflow_id（requires_credentials=true）；
   - 删除两个工作流后列表为空，定义表中记录为 0。
4. 清理冒烟数据，临时脚本已删除。

### 前后端联调 + 浏览器渲染检查

- 启动后端（`AUTO_EVALUATE=false`，避免评审费用）与前端（Vite 5173），页面与新增模块均 200；
- 使用本机 Chrome headless `--dump-dom` 渲染页面，DOM 中出现 “AgentFlow / 工作流 / 画布 / 工作流库 / 运行历史”等界面文本，应用可渲染；
- 通过 API 完成创建 → 导出 → 导入 → 缺密钥 400 → 删除的联调，结果正常；
- 说明：未做真实浏览器点击级 E2E（无 Playwright/jsdom），上述为渲染与契约级验证。

### 基线

`docs/BASELINE_REPORT.md` 已重新生成（A 节：140 passed + 11/11 确定性断言；B 节假模型机制结果不变；
C 节真实模型未运行）。本次改动不改变实验结论。

## 四、开关状态（按用户确认开启）

`backend/.env`（未提交、未打印密钥）中：

```text
ENABLE_LANGFUSE_TRACING=true
LANGFUSE_CAPTURE_CONTENT=true
AUTO_EVALUATE=true
```

含义：追踪开启并允许在脱敏后上传任务/输入输出；执行结束自动评估并写入 Langfuse 评分（会产生少量评审模型费用）。

## 五、边界与未完成

- 浏览器点击级 E2E 未自动化；前端验证为 Node 单测 + lint + build + headless DOM 渲染。
- 定义版本目前只有 v1；没有旧格式迁移逻辑（旧库首次升级会建表，无历史定义）。
- 没有“编辑/重命名定义”的 API；重新导入会生成新 workflow_id。
- 导入 body 必须包含 `workflow_id`（当前版本要求）；前端已提示。
- 恢复的工作流需要重新输入密钥；密钥不在服务端持久化，浏览器也不保存。
- 消息时间线仍是内存态；已完成运行的步骤输入输出可从运行记录回看，未运行的任务输入不持久化。
- 真实模型质量/成本实验仍未运行；本项未新增任何付费调用。

## 六、相关文件

- `backend/agentflow/core/definition.py`（定义模型/校验/脱敏）
- `backend/agentflow/storage/models.py`、`repository.py`、`database.py`（定义表与仓储）
- `backend/agentflow/core/workflow.py`（`workflow_id` 注入、`to_definition`、`requires_credentials`）
- `backend/agentflow/api/routes/workflow.py`（创建/恢复/导出/导入/删除/执行密钥）
- `backend/agentflow/api/app.py`（启动恢复）
- `backend/tests/test_workflow_definition.py`
- `frontend/src/components/WorkflowLibraryDialog.vue`、`DebugPanel.vue`、`App.vue`
- `frontend/src/stores/workflow.js`、`services/workflow.js`
- `frontend/src/utils/workflowDefinition.js`、`credentialState.js`、`workflowStorage.js`、`definitionTransfer.js`
- `frontend/tests/workflow-definition.test.js`、`credential-state.test.js`、`workflow-library.test.js`
