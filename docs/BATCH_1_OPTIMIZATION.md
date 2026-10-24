# AgentFlow 第一批优化实施报告

本报告记录第一批"可信运行与可比较记录"优化的实际完成情况、验证方式和仍未完成的部分。
所有数字都来自本仓库实际执行结果；假模型实验只证明机制，不代表真实模型质量或成本。

## 一、本批目标与实际完成情况

| 目标 | 状态 | 说明 |
| --- | --- | --- |
| 工作流定义与运行实例分离 | 完成 | `workflow_id` 标识定义，`run_id` 标识一次执行；每次运行记录任务输入、配置快照、起止时间、终态、步骤结果与用量 |
| 错误传播与终止语义真实一致 | 完成 | 顺序失败停止下游；并行区分全部成功/部分失败/全部失败/取消；失败不把"失败前输入"当最终结果；停止接入真实执行控制 |
| 记忆、状态、消息、统计隔离 | 完成 | 每次运行独立重置 Agent 记忆与统计；消息按 run 隔离；当前输入不重复发送 |
| 顺序与并行执行记录统一 | 完成 | 统一 `StepResult`（schema v2）：step_index/输入输出/模型/finish_reason/状态/错误/时间/用量类型，增量写入 SQLite |
| 确定性回归案例与基线报告 | 完成 | 假适配器测试矩阵 + 冻结数据集/配置/评分器 + `docs/BASELINE_REPORT.md` |
| 可关闭的 Langfuse 追踪 | 完成 | 关闭/缺配置/异常均不影响业务；默认不上传任务与输入输出内容，开启时脱敏 |

## 二、核心机制

### 1. 运行实例与并发策略

- `WorkflowExecutor.execute(task, run_id=None)` 每次创建独立 `WorkflowRun`；API 提前生成 `run_id` 并返回，前端可立即查询。
- 同一执行器同一时刻只允许一个活动运行：并发请求抛 `RunAlreadyRunningError`，`POST /execute` 返回 **409**。
- 运行开始时重置 Agent 记忆与统计（`Agent.reset_for_run()`）；第二次运行不累积第一次的 messages/token 统计。
- 延续会话当前**显式不支持**：不会因为复用对象而隐式带上下文。
- 消息历史按运行隔离：`executor.run_messages[run_id]`，`GET /api/messages?run_id=...` 可回看；不带 run_id 时返回当前/最近运行。

### 2. 错误与终止语义

- 顺序模式：必需步骤失败（adapter 异常或 `metadata.error=True`）立即停止，后续步骤不调用；失败步骤记录 error，不把 `Error: ...` 内容交给下游。
- 并行模式：全部成功 → `completed`；部分成功 → `partial`；全部失败 → `failed`；收到停止 → 取消未完成调用，步骤标记 `cancelled`，运行标记 `stopped`。
- 停止：`POST /api/workflows/{id}/stop` → 设置停止标志；顺序模式在步骤边界阻止后续调用，并行模式取消未完成任务。无活动运行时返回 409。
- 失败/停止的 `execute()` 返回值里 `result.final_result = None` 且带 `error`，调用方必须看 `status`。
- 远端推理是否真正取消无法确认：被取消步骤的用量记为 `unknown`，不填 0。

### 3. 统一记录格式（schema_version = 2）

`WorkflowRun`：run_id、workflow_id、workflow_name、task_input、status、schema_version、created_at/started_at/completed_at、final_result、error、stop_requested、config_snapshot（不含密钥/连接配置）、total_tokens、total_duration、step_results。

`StepResult`：step_id、step_index、agent_name、status、input/output_message_id、input_text、output_text、error、model、finish_reason、started_at/completed_at/duration、usage、usage_type。

- 持久化：本地 SQLite（`backend/agentflow_data.db`，可用 `AGENTFLOW_DB_PATH` 覆盖），运行开始、每个步骤后、终态各保存一次，刷新页面/中断后仍能看到已保存的"运行中"记录。
- 旧数据库自动迁移（补齐新列），旧记录 `schema_version=1`，新记录为 2。
- 历史回看只读本地数据库，不调用任何模型；重新执行会创建新 run_id，可能产生新费用。
- 记录中不含 API Key、base_url 等连接配置。

### 4. 用量语义

- `actual`：提供商返回 total_tokens，或同时返回 prompt/completion（可精确求和）；
- `partial`：只返回部分字段，保留原值但不补造 total；
- `unknown`：缺失或非法值；`total_tokens` 统计保持 0，不把 `max_tokens` 当实际消耗；
- 假适配器的合成 usage 也会按 `actual` 记录：这只说明引擎如实记录"适配器声称的用量"，不代表真实成本。

### 5. 模式范围

仅支持 `sequential` / `parallel`。`hierarchical`、`debate`、`voting`、`dynamic` 在 API 创建阶段返回 **400**、引擎构造时抛 `UnsupportedPatternError`，不再半执行。

### 6. Langfuse 追踪（可选）

- `ENABLE_LANGFUSE_TRACING=false`（默认）时完全本地运行；缺依赖/缺密钥/导出异常都不影响业务结果。
- `LANGFUSE_CAPTURE_CONTENT=false`（默认）：不上传任务、输入、输出、错误正文、评分理由；只上传 id、pattern、step_index、model、token 用量、耗时、level、脱敏后的错误摘要。
- 开启内容采集后会先脱敏：API Key、Bearer/Authorization、`*_KEY/*_SECRET/*_TOKEN`、连接配置（host/base_url）、长十六进制/字母数字串。
- `AUTO_EVALUATE=true` 时执行结束调用评审模型打分写入 Langfuse 评分；评分数值与 trace 关联始终写入，评审理由仅在内容采集开启时写入。
- 追踪父子关系在异步/并行下均挂到同一个 trace（由 `create_trace_id(seed=run_id)` 稳定推导 run_id → trace_id）。

## 三、验证结果（本次实跑）

### A. 机制回归（假适配器，不联网）

```bash
cd backend && python -m pytest tests/ -q
```

结果：**132 passed / 0 failed / 0 error / 0 skipped**。

覆盖矩阵（新增 `tests/test_run_semantics.py`、`tests/test_tracing_hardening.py`、`tests/test_experiment_runner.py` 等）：

- 顺序输入交接、统一记录字段；
- 必需步骤失败后下游未被调用，`Error:` 不作为正常输入；
- 并行全部成功 / 部分失败 / 全部失败 / 停止取消；
- 并发 execute 拒绝、重复执行 run_id 与统计隔离；
- 每次运行前记忆/统计重置，当前输入不重复进入请求；
- 用量缺失→`unknown`、部分用量→`partial`；
- 追踪关闭、追踪全链路抛异常时业务结果不变；
- 历史回看不触发模型调用（adapter 调用次数不变）；
- API 状态与记录一致（execute 返回 run_id、409、stop 409、unsupported pattern 400、分页 total、compare 路由）。

### B. 假模型质量实验（仅证明机制）

```bash
cd backend && python scripts/run_experiment.py --config all
```

- 数据集：`experiments/dataset_v1.json`（5 个固定 case，case-001..005，版本 1.0.0）
- 评分答案分离在 `experiments/expected_answers_v1.json`（不进入生成上下文）
- 冻结配置：`experiments/configs_v1.json`（single/sequential/parallel）
- 结果（假适配器，确定性）：三配置各 5 cases，全部 completed/scored，passed 12/15，
  `pass_rate_scored = pass_rate_all_cases = 80%`；`missing_score=0`、`scoring_error=0`；
  case-003 的预设错误回答被评分器识别（0.3333）；token 153/305/306 为合成值。

### C. 真实模型实验

**未运行**。没有配置真实模型密钥，也未设置 `AGENTFLOW_EXPERIMENT_REAL=1`；本批不产生付费调用。
因此本批**没有任何真实模型的质量、延迟、成本结论**，也不能用假模型结果宣称多 Agent 提升了准确率。

### D. 前端

```bash
cd frontend && npm run test && npm run lint && npm run build
```

- `npm run test`：**53 passed / 0 failed**
- `npm run lint`：exit 0
- `npm run build`：成功（123 modules transformed）

前端改动：创建弹窗仅允许 sequential/parallel，其余模式可见但禁用并标注"暂不支持"；导航栏接入运行历史面板（RunHistory/RunDetail/RunComparison）；DebugPanel 显示最近运行 run_id 与真实状态；刷新后从 API 重新获取记录；failed/partial/stopped/cancelling 不会显示成成功。

## 四、如何本地查看

```bash
# 启动后端 + 前端（只管理本项目进程）
python scripts/dev.py
# 前端 http://localhost:5173 ，后端文档 http://localhost:8000/docs
```

1. 创建工作流（仅 sequential/parallel）→ 填写任务并执行；
2. 点击左侧「运行历史」查看每次运行的状态、run_id、步骤输入输出、模型与 token；
3. 刷新页面后，运行历史与"最近运行"从 `/api/workflows/{id}/runs`、`/api/runs/{run_id}` 重新读取；
4. 后端记录保存在 `backend/agentflow_data.db`；删除数据库文件可清空历史（工作流定义本身仍在内存，需重建）。

实验入口：

```bash
cd backend
python scripts/run_experiment.py --config single --limit 3     # 默认假适配器，输出 JSON
python scripts/run_baseline.py                                  # 重新生成 docs/BASELINE_REPORT.md
```

## 五、明确未完成 / 仍需注意

- **未完成模式**：hierarchical、debate、voting、dynamic 被显式拒绝；没有实现。
- **停止按钮**：后端 stop 语义已接通，但前端本批未新增停止按钮（只能看到 stopping/stopped 状态）。
- **暂停/单步/重试**：未实现；`pause/resume` 仅状态标记，不中断进行中的模型调用。
- **真实模型基线**：未运行；质量与成本结论需要用户自行配置密钥后运行真实实验。
- **实验评分器**：关键词 rubric、5 条样本，不具统计代表性；评分失败与缺失评分分别记录，不作平均掩盖。
- **中断粒度**：运行记录在步骤边界增量保存；进程在单步调用中途被杀时，该步骤可能停留在 running 状态，需要通过 run 状态与错误字段判断。
- **工作流定义与 API Key**：仍在后端内存中，重启后需要重新创建工作流；本批只持久化运行记录。
- **并发**：单执行器拒绝并发运行；多浏览器标签同时操作同一工作流会收到 409，而不是排队。
- **Langfuse 云 API 兼容**：使用 SDK 5.x + OTLP 写入与 v2 读接口；Langfuse Cloud 的 v3 旧接口将于 2026-11-16 下线（本项目未使用）。
