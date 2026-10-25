# 开发指南

## 运行与配置

优先使用根目录的 `scripts/dev.py`，它检查依赖和端口，并只管理自己启动的两个服务。前端仍有 Vite 热更新；启动器中的后端不自动重载，以避免编辑文件时清空内存工作流。

后端单独开发时，可从 `backend/` 运行：

```bash
python -m uvicorn agentflow.api.app:app --host 127.0.0.1 --port 8000 --reload
```

前端单独运行：

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --strictPort
```

前端默认连接 `http://localhost:8000`。可在 `frontend/.env` 设置 `VITE_API_BASE_URL`，改动后重启 Vite。后端目前从创建请求接收模型密钥，不会自动读取根目录 `.env`。

## 前端组织

- `src/components/`：画布、创建弹窗、执行面板、消息时间线和通用交互。
- `src/stores/`：当前工作流、执行同步、删除与消息状态。
- `src/composables/useTimelineResize.js`：拖拽、键盘与高度持久化。
- `src/utils/`：画布映射、选项导航、连接校验和模型选项。
- `src/services/`：HTTP 请求与原生 WebSocket 服务。
- `tests/`：当前启用的 Node 回归测试。

`npm run lint` 只检查；需要自动修正时使用 `npm run lint:fix`。

## 后端组织

- `agentflow/core/`：Agent、Message、WorkflowExecutor、WorkflowRun/StepResult、WorkflowDefinition。
- `agentflow/storage/`：SQLite 运行记录与工作流定义（模型、仓储、增量列迁移）。
- `agentflow/tracing/`：可选的 Langfuse 适配（默认关闭，默认不采集内容）。
- `agentflow/agents/`：LLM Agent。
- `agentflow/adapters/`：模型接口与工厂。
- `agentflow/api/`：路由和 WebSocket 连接管理。
- `tests/`：假适配器机制回归；`test_api.py` 覆盖无真实密钥的 API 路径。

### 运行记录

- 每次执行生成独立 `run_id`；记录格式 `schema_version=3`（步骤输入输出、模型、状态、错误类型、尝试次数、时间、用量类型；run 含 `trace_id`）。
- 默认数据库 `backend/agentflow_data.db`，可用环境变量 `AGENTFLOW_DB_PATH` 覆盖；旧库启动时自动补齐新列。
- 历史回看接口只读本地库，不调用模型：`GET /api/workflows/{id}/runs`、`GET /api/runs/{run_id}`、`GET /api/runs/compare?run_ids=...`。
- 同一工作流并发执行会被拒绝（409）。
- 写入通过 `asyncio.to_thread` 移出事件循环，并在仓储层串行化；运行结束后按保留策略清理旧记录。

### 执行控制

| 环境变量 | 默认 | 说明 |
| --- | --- | --- |
| `AGENTFLOW_STEP_TIMEOUT_SECONDS` | `0` | 单步超时秒数；0 不启用 |
| `AGENTFLOW_MAX_ATTEMPTS` | `1` | 单步最大尝试次数（1-5）；仅超时/限流/网络/服务端错误重试 |
| `AGENTFLOW_RECORD_TEXT_LIMIT` | `20000` | 单步输入/输出落库截断长度；0 不截断 |
| `AGENTFLOW_MAX_RUNS` | `1000` | 最多保留运行记录条数；0 不限制 |
| `AGENTFLOW_RUN_RETENTION_DAYS` | `0` | 运行记录保留天数；0 不按时间清理 |

- 错误分类写入 `step.error_type`：`timeout/rate_limit/auth/network/server/validation/provider/cancelled/unknown`。
- 多次尝试的用量按已知部分累计：全部已知为 `actual`，部分未知为 `partial`，全未知为 `unknown`；不会把未知当 0。
- 记录中的错误文本会做保守脱敏（API Key/Token 等）。

### 可选 API Token

- 设置 `AGENTFLOW_API_TOKEN` 后，所有 `/api/*` 请求需要 `Authorization: Bearer <token>`；`/health` 与 CORS 预检不受限。
- 前端在 `frontend/.env` 设置 `VITE_API_TOKEN` 时会自动附带该头；**VITE 变量会进入浏览器包**，仅用于本地/受信环境，不建议公网部署。

### 工作流定义持久化与导入导出

- 定义保存在 `workflow_definitions` 表（`definition_json`，`schema_version=1`）；**不保存 API Key/secret/token**。
- 后端启动时自动恢复定义；恢复的工作流 `requires_credentials=true`，Agent 以配置快照展示（status=unavailable）。
- 执行恢复的工作流时在请求体里带 `api_key`（只驻留内存，不落库）：`POST /api/workflows/{id}/execute`。
- 导出：`GET /api/workflows/{id}/definition`；导入：`POST /api/workflows/import`（总会分配新 `workflow_id`）。
- 删除工作流会同时删除定义；历史运行记录保留。
- 定义校验/脱敏逻辑在 `agentflow/core/definition.py`（`WorkflowDefinition.from_dict`），导入和数据库读取都经过它。

### 协作模式（后端执行语义）

`WorkflowPattern` 支持 7 种模式；创建/导入时按模式自动分配角色与智能体数量范围：

| 模式 | 角色分配 | 执行语义 | 智能体范围 |
| --- | --- | --- | --- |
| sequential | 全 worker | 按 steps 依次执行，失败即停 | 1–10 |
| parallel | 全 worker | 所有步骤并发，记录成功/失败/取消 | 1–10 |
| hierarchical | 第 1 个 coordinator + 其余 worker | 协调者规划 → worker 顺序执行 → 协调者汇总 | 2–10 |
| debate | 前 n-1 个 debater + 最后 1 个 judge | 两轮辩论（第二轮互看观点）→ 裁判综合 | 3–10 |
| voting | 前 n-1 个 candidate + 最后 1 个 judge | 候选独立作答 → 裁判比较裁决 | 3–10 |
| dynamic | 第 1 个 coordinator + 其余 worker | 协调者逐轮输出 JSON 选 worker，最多 max_iterations 轮 → 汇总 | 2–10 |
| group_chat | 可选 lead + 其余 member | 共享 transcript：Lead 分派/收尾，或成员 round-robin + @点名；最多 max_iterations 轮 | 2–6 |

- 创建 API 会对数量越界/低于最低值的请求返回 400；定义导入同样校验。
- 新增模式复用 `_execute_recorded_step`：步骤记录、超时/重试、停止、token、trace_id 与现有记录格式一致。
- 动态协调者输出非法 JSON 时回退到第一位 worker，并把运行标记为 partial；群聊 Lead 同样有回退。
- 群聊成员通过 `@name` 或 JSON `{"handoff":"member_2","task":"..."}` 影响下一位发言者（无 Lead 模式）；有 Lead 时由 Lead 决定。
- 群聊消息写入 `workflow_messages` 表（写入前脱敏），按 workflow/run 回放；服务重启后独立群聊面板仍能加载历史。
- 群聊消息的 `content` 保存完整 prompt（模型实际看到的上下文），时间线用 `metadata.display_content` 显示短文案，避免把整段 transcript 刷进聊天气泡。
- 真实模型冒烟见 [GROUP_CHAT_SMOKE.md](GROUP_CHAT_SMOKE.md)。
- 实验脚本的固定配置仍只使用 sequential/parallel，尚未把这些新模式纳入评测数据集。

### Harness²-lite（实验对比）

> 不整体接入 Harness² 框架，只借鉴：配置指纹、执行证据、独立评分、候选对比。设计见
> [HARNESS2_LITE_PLAN.md](HARNESS2_LITE_PLAN.md)。

- **配置指纹** `agentflow/core/fingerprint.py`：由数据集版本、工作流/Agent 配置、执行策略、scorer、provider 计算 16 位 hash；不含密钥/base_url/时间戳。运行记录 `fingerprint` 字段保存。
- **执行证据** `agentflow/core/evidence.py`：每 case 一份脱敏 JSON（请求/响应/用量/错误/评分/trace_id/指纹）；默认关闭，实验用 `--evidence` 或 `AGENTFLOW_EVIDENCE_ENABLED=true` 开启；`AGENTFLOW_EVIDENCE_DIR`、保留期 90 天、单文件上限 200KB。
- **独立评分** `agentflow/core/judge.py`：真实 LLM judge 需 `AGENTFLOW_EXPERIMENT_LLM_JUDGE=1` + 密钥；预算 `AGENTFLOW_JUDGE_MAX_CALLS`（默认 50）；状态区分 scored/judge_disabled/budget_exhausted/scoring_error/missing_score。
- **数据模型（schema v4）**：`workflow_runs` 增加 experiment_id/candidate_id/case_id/fingerprint/evidence_ref/score/passed/score_status/score_source；新增 `experiments`、`experiment_candidates` 表。
- **API（只读）**：
  - `GET /api/experiments`、`GET /api/experiments/{id}`（候选指标 + case×候选矩阵）、`GET /api/experiments/{id}/report`；
  - `GET /api/evidence/{run_id}`（无证据 404）；
  - `GET /api/runs?experiment_id=&candidate_id=&fingerprint=&case_id=` 过滤。
- **报告**：`docs/HARNESS2_COMPARISON.md` + `docs/harness2_results.json`（由 Harness²-lite runner 生成；真实模型需显式门禁，由人工受控执行）。

### 可选的追踪与评估

- `ENABLE_LANGFUSE_TRACING=true` + Langfuse 密钥可开启追踪；默认关闭，导出异常不影响业务。
- `LANGFUSE_CAPTURE_CONTENT` 默认 `false`：只上传元数据；开启后会脱敏后再上传任务/输入输出。
- `AUTO_EVALUATE=true` 会在执行后调用评审模型写入评分；会产生少量模型费用。

### 实验与基线

```bash
cd backend
python scripts/run_experiment.py --config single --limit 3   # 默认假适配器，输出 JSON
python scripts/run_experiment.py --config all
python scripts/run_baseline.py                                # 生成 docs/BASELINE_REPORT.md + baseline_results.json
```

- 数据集、冻结配置、预期答案分别在 `experiments/*.json`，版本号独立；预期答案不会进入生成模型上下文。
- 真实模型实验需要 `AGENTFLOW_EXPERIMENT_REAL=1` + `--real` + 对应密钥；默认拒绝，不会联网。
- 假模型结果只用于验证机制与评分链路，不能代表真实模型质量或成本。

安装为包时会发现所有 `agentflow.*` 子包。可从项目根目录验证 wheel：

```bash
python -m pip wheel --no-deps ./backend -w .artifacts
```

## 检查与提交

运行前端 lint / test / build 和后端 pytest。上传前运行：

```bash
git add .
python scripts/check_repo.py
git diff --cached --stat
```

检查脚本会拒绝已跟踪的环境文件、缓存、依赖目录、明显凭据串和本地用户路径。它是基础检查，不能替代人工审阅暂存内容。

## 示例

`examples/code_review.py` 使用环境变量读取凭据与模型名。先安装 backend 包，然后在自己的终端设置 `OPENAI_API_KEY` 和 `OPENAI_MODEL` 再运行示例。该示例会调用真实模型，产生对应服务商的使用量。
