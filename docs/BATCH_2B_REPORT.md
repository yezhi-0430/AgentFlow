# 第二批剩余事项实施报告（第 2-8 项，Harness² 之前）

本报告记录第二批除"工作流定义持久化"（见 [BATCH_2_REPORT.md](BATCH_2_REPORT.md)）之外的
其余事项：执行控制、评测升级、Langfuse 实验关联、并发与存储工程化、安全隐私、前端体验。
**按用户要求，到 Harness² 之前停止**；Harness² 相关能力（配置指纹、原始请求/响应证据、
独立评分、候选配置对比）尚未实施。

所有数字来自本仓库实际执行；真实模型实验只执行了一次受控运行（30 次调用），未尝试多轮调参。

## 一、完成情况

| # | 事项 | 状态 | 主要产物 |
| --- | --- | --- | --- |
| 2 | 执行控制完善 | 完成 | 单步超时、有限重试、错误分类、尝试次数、多尝试用量聚合、前端停止按钮 |
| 3 | 评测升级 | 完成 | 10 case 数据集 v2、rubric v2、可选 LLM judge 门禁、假模型 + 一次真实模型实验报告 |
| 5 | Langfuse 实验关联 | 完成 | run 记录 `trace_id`、execute 返回 `trace_id`、30 个真实 case 的 trace_id 映射 |
| 6 | 并发与存储工程化 | 完成 | SQLite 写入移出事件循环、进程内写锁、保留/截断策略、CI 更新 |
| 7 | 安全与隐私 | 完成 | 可选 API Token、记录错误脱敏、密钥不落库说明与测试 |
| 8 | 前端体验 | 完成 | 停止按钮、attempts/error_type/trace_id 展示、状态筛选与 JSON 导出、可选 Token 头 |

## 二、执行控制（第 2 项）

- 环境变量：
  - `AGENTFLOW_STEP_TIMEOUT_SECONDS`（默认 0 不启用）
  - `AGENTFLOW_MAX_ATTEMPTS`（默认 1，范围 1-5）
- 仅对 `timeout / rate_limit / network / server` 重试；`auth / validation` 等不重试。
- 步骤记录新增 `attempts`、`error_type`（`timeout/rate_limit/auth/network/server/validation/provider/cancelled/unknown`）。
- 多尝试用量聚合：全部已知为 `actual`；部分尝试未知为 `partial`；全部未知为 `unknown`；未知不填 0。
- 停止语义保持：顺序在步骤边界阻止后续；并行取消未完成；停止期间到达的响应仍记录，但运行终态为 `stopped`。
- 前端：执行中显示「停止运行」，处理 `stopping/stopped/409/404/网络错误`；`stopped` 不显示为成功。

## 三、评测升级（第 3 项）

### 资产

- `experiments/dataset_v2.json`：10 个固定 case（`agentflow-fixed-v2@2.0.0`，case-001..010），只含 `case_id/task/tags`。
- `experiments/expected_answers_v2.json`：rubric v2（权重、critical 条目、阈值 0.75、band 与校准理由），与数据集物理分离；加载器拒绝答案字段注入。
- `backend/scripts/run_experiment.py`：`--config single|sequential|parallel|all`、`--limit`、`--judge deterministic|llm|none`、`--tracing`、`--output`、`--real`；评分状态区分 `scored/judge_disabled/missing_score/scoring_error/execution_failed`。
- `experiments/build_experiments_report.py`：实际运行 pytest + 假模型实验并生成报告；若存在 `docs/real_experiment_results.json`，C 节展示真实运行结果。

### 假模型实验（仅证明机制）

- 三配置各 10 case，全部 completed/scored；passed 8/10，`pass_rate_all_cases=80%`；`missing_score=0`、`scoring_error=0`。
- case-003/case-009 为预设错误回答，被 rubric 识别；该 80% **不代表模型质量**。

### 真实模型实验（本次受控执行一次）

- 模型：`openai/gpt-4o-mini`（通过 OpenRouter 兼容接口），确定性 rubric，显式 `--tracing`，`AUTO_EVALUATE=false` 避免额外评审调用。
- 规模：10 case × 3 配置 = 30 次执行；无失败、无缺失评分。
- 结果（分母均为 10）：

| 配置 | 完成 | 通过 | pass_rate_all_cases | mean_score_all_cases | total_tokens | 总耗时(s) | trace_id 数 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| single | 10/10 | 6/10 | 0.6 | 0.8 | 1358 | 23.04 | 10 |
| sequential | 10/10 | 5/10 | 0.5 | 0.8 | 6454 | 61.35 | 10 |
| parallel | 10/10 | 8/10 | 0.8 | 0.8667 | 3546 | 31.38 | 10 |

- 解读限制：样本仅 10 个 case、单一模型、单轮运行；**不能据此证明并行/串行优于单 Agent，也不能外推总体质量**。
  真实实验 token 合计 11,358，未计算费用（依赖服务商定价）。
- 完整报告：[EXPERIMENTS_REPORT.md](EXPERIMENTS_REPORT.md)；原始数据：[real_experiment_results.json](real_experiment_results.json)。

## 四、Langfuse 实验关联（第 5 项）

- `WorkflowRun` 新增 `trace_id`（schema v3），执行开始时从 tracer 句柄写入；`execute()` 返回值与 `GET /api/runs/{id}` 均包含。
- 实验 runner 每个 case 记录 `trace_id`、`trace_id_source`、`tracing_enabled`；优先取 `execute()` 返回值，其次 run 记录，缺失不伪造。
- 本次真实运行 30 个 case 全部得到非空 trace_id（见 C1 每 case 表），可在 Langfuse 按 trace_id 检索；
  内容采集已按用户确认开启（`LANGFUSE_CAPTURE_CONTENT=true`，上传前脱敏）。
- 假模型实验默认不开启追踪，trace_id 为 null（预期行为，不是失败）。

## 五、并发与存储工程化（第 6 项）

- 运行记录写入改为 `asyncio.to_thread` + `_persist_sync`，不阻塞事件循环；测试断言持久化走 worker 线程。
- 仓储层增加进程内写锁，串行化 SQLite 写入；测试并发 3 个执行器同时持久化无锁错误。
- 保留策略：`AGENTFLOW_MAX_RUNS`（默认 1000）、`AGENTFLOW_RUN_RETENTION_DAYS`（默认 0，不清理）；
  终态保存后自动执行 prune；单测验证"只保留最新 N 条"。
- 单步文本落库截断：`AGENTFLOW_RECORD_TEXT_LIMIT`（默认 20000 字符，0 不截断）。
- CI（`.github/workflows/ci.yml`）：后端安装 `[dev,tracing]`、`pytest`、假模型实验冒烟（single/limit 2）、wheel、仓库检查；前端 lint/test/build 保持。
- 说明：迁移仍采用轻量"启动时补列"方案，未切换到 Alembic（当前 SQLite 本地场景足够；已作为后续工程化事项记录）。

## 六、安全与隐私（第 7 项）

- 可选 API Token：设置 `AGENTFLOW_API_TOKEN` 后所有 `/api/*` 需 `Authorization: Bearer <token>`（`/health`、OPTIONS 除外）；
  每次请求读取环境变量，测试覆盖 401/正确 Token。前端可用 `VITE_API_TOKEN` 注入（会进入浏览器包，仅本地/受信环境）。
- 记录错误文本写入前做保守脱敏（API Key/Bearer/`*_KEY=` 等），测试覆盖。
- API Key 不写入定义、运行记录、Langfuse；重启/导入后的工作流执行时重新提供，密钥只驻留内存。
- 未实现完整本地鉴权/用户体系；Token 只是可选的本地访问门槛，不替代生产鉴权。

## 七、前端体验（第 8 项）

- 停止按钮与 `stopping/stopped/409` 处理；状态绝不把 stopped 显示成 completed。
- 运行历史/详情：`attempts`、`error_type` 中文标签、失败原因、`trace_id`（截断+复制）。
- 运行历史支持状态筛选（全部/已完成/失败/部分完成/已停止）与导出当前筛选为 JSON（下载→剪贴板→手动弹窗降级）。
- `services/api.js` 在存在 `VITE_API_TOKEN` 时统一附加 Authorization 头；未设置不加头、不持久化、不打印。
- 既有功能保持：工作流库、定义恢复、requires_credentials 密钥补充、未支持模式提示、运行历史刷新恢复。

## 八、验证结果（本次实跑）

| 检查 | 结果 |
| --- | --- |
| 后端全量测试 | **168 passed / 0 failed**（新增执行控制/存储/鉴权/脱敏 12 例；实验 runner 34 例） |
| 前端测试 | **106 passed / 0 failed** |
| 前端 lint | exit 0 |
| 前端构建 | ✓ 137 modules transformed |
| 实验机制断言 | 11/11 通过（A 节） |
| 假模型实验 | 三配置各 10 case，80% 通过（仅机制） |
| 真实模型实验 | 30 次执行、0 失败、0 缺失评分；trace_id 30/30；结果见上表 |
| 真实停止冒烟 | 真实模型工作流执行中调用 stop → 终态 `stopped`、1 个步骤 completed、`trace_id` 已记录、schema v3 |
| 基线报告 | `docs/BASELINE_REPORT.md` 已重跑：A 节 168 passed + 11/11 断言 |

## 九、未完成 / 边界（含 Harness² 前停止点）

- **Harness² 未开始**：配置指纹、脱敏后的原始请求/响应证据、独立评分器、候选配置对比报告均未实现。
- 未运行真实 LLM judge（`--judge llm` 仅有假 judge 链路与门禁测试）；rubric 仍为关键词匹配，无法判断语义等价。
- 真实实验只有 10 case × 3 配置、单模型、单轮，无统计显著性；不能据此下"多 Agent 更优"的结论。
- 前端无浏览器点击级 E2E；停止按钮/下载/剪贴板降级仅在构建 + mock 单测下验证。
- 轮询（1s）未改为 SSE；本地场景可接受，已记录为后续。
- 暂停/恢复仍只是状态标记；无自动重放/断点续跑。
- 迁移未切 Alembic；SQLite 仍是本地单机存储。
- 未提交/推送/部署；`backend/.env` 未纳入版本控制，报告中不包含密钥。

## 十、相关文件

- 执行控制：`backend/agentflow/core/workflow.py`、`core/redaction.py`、`core/run.py`
- 存储：`backend/agentflow/storage/{models,database,repository}.py`
- 安全：`backend/agentflow/api/app.py`、`backend/agentflow/core/redaction.py`
- 测试：`backend/tests/test_execution_controls.py`、`tests/test_experiment_runner.py`
- 实验：`experiments/dataset_v2.json`、`expected_answers_v2.json`、`build_experiments_report.py`、`backend/scripts/run_experiment.py`
- 报告：`docs/EXPERIMENTS_REPORT.md`、`docs/experiments_results.json`、`docs/real_experiment_results.json`
- 前端：`frontend/src/components/{DebugPanel,RunHistory,RunDetail,TraceId}.vue`、`utils/{runDetails,stopControl,apiAuth}.js`
- CI：`.github/workflows/ci.yml`
