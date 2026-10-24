# AgentFlow 实验资产（experiments/）

本目录冻结 AgentFlow 的质量实验输入、配置与报告生成脚本，供 `backend/scripts/run_experiment.py`、
`backend/scripts/run_baseline.py`、`experiments/build_experiments_report.py` 与
`experiments/build_harness2_report.py` 读取。
所有实验默认使用**确定性假适配器**，不联网、不调用付费模型。

## 文件

| 文件 | 作用 | 版本字段 |
| --- | --- | --- |
| `dataset_v2.json` | 固定任务集（10 个 case，case-001..case-010），含稳定 `case_id` 与发送给模型的 `task` | `dataset_version` = `2.0.0` |
| `expected_answers_v2.json` | 预期答案、评分要点（rubric）与校准说明，**只给评分器/judge 读** | `dataset_version` = `2.0.0`，`scorer_version` = `2.0.0` |
| `configs_v1.json` | 三种冻结配置 `single` / `sequential` / `parallel`（配置结构未变，版本保持 1.0.0） | `config_version` = `1.0.0` |
| `dataset_v1.json` / `expected_answers_v1.json` | 第一批的 5 case 版本，保留用于对比/复现历史基线 | `1.0.0` |
| `build_experiments_report.py` | 生成 `docs/EXPERIMENTS_REPORT.md` 与 `docs/experiments_results.json`（实际运行） | `REPORT_VERSION` |
| `build_harness2_report.py` | 读取 runner 结果，生成 `docs/HARNESS2_COMPARISON.md` 与 `docs/harness2_results.json` 的 `report` 段（候选对比） | `REPORT_VERSION` |

## 隔离规则（防止答案泄漏）

1. `dataset_v2.json` 的 case 只允许 `case_id`、`task`、`tags`；**禁止**出现
   `reference_answer` / `rubric` / `expected*` / `answer*` / `scoring` / `labels` 等字段，
   嵌套对象里的疑似答案字段也会被递归拒绝。
2. 运行器 `run_experiment.py` 在加载数据集时执行校验：发现上述字段会直接报错退出；
   发送给生成模型的消息只由配置中的 system prompt 与 case 的 `task` 拼成。
3. `expected_answers_v2.json` 只在执行结束后交给评分器；LLM judge 的提示词也只在评分阶段使用。
4. 数据集 case 不允许任何未声明的额外输入字段，避免答案以自定义键名夹带。

## 评分器 v2（确定性 rubric + 校准）

- 规则：命中条目的权重和 / 全部条目权重和 = `score`；
  `passed = score >= pass_threshold 且所有 critical 条目命中`。
- 默认阈值 `0.75`；阈值理由、分数 band、critical 规则理由都写在
  `expected_answers_v2.json` 的 `calibration` 字段中，报告 A3 节会原样引用。
- 评分失败（`scoring_error`）与缺失评分（`missing_score`）分别记录；
  执行失败的任务不会被评分，也不会用引擎回退文本冒充成功。

## Judge 选择

| `--judge` | 行为 | 联网/费用 |
| --- | --- | --- |
| `deterministic`（默认） | 确定性 rubric v2 | 不联网、无费用 |
| `none` | 显式关闭评分，case 记录 `score_status=judge_disabled` | 不联网、无费用 |
| `llm` | 需额外设置 `AGENTFLOW_EXPERIMENT_LLM_JUDGE=1`；假适配器模式下使用确定性 fake judge 验证链路 | 默认不联网；真实 LLM judge 仅在 `--real` 门禁下调用，会产生费用 |

## 配置

- `single`：1 个 Agent、1 步，直接作答；实验层名称为 `single`，`engine_pattern=sequential`（底层为 1 步串行）。
- `sequential`：2 个 Agent 串行（`drafter` → `reviewer`），`engine_pattern=sequential`，最终输出为复核后的答案。
- `parallel`：2 个 Agent 并行独立作答，`engine_pattern=parallel`，聚合文本（`aggregated`）用于评分。

配置中只出现引擎实际支持的模式（`sequential` / `parallel`）；debate/voting 等未实现模式不会进入实验配置。

## 使用

```bash
cd backend
# 默认假适配器 + 确定性 judge，跑全部配置，JSON 输出到 stdout
python scripts/run_experiment.py --config all

# 单个配置 / 限制 case 数 / 关闭评分 / 写入文件
python scripts/run_experiment.py --config single --limit 2 --output ../experiments/results_single.json
python scripts/run_experiment.py --config all --judge none

# LLM judge 假链路（离线，需显式门禁）
export AGENTFLOW_EXPERIMENT_LLM_JUDGE=1   # Windows PowerShell: $env:AGENTFLOW_EXPERIMENT_LLM_JUDGE='1'
python scripts/run_experiment.py --config single --judge llm

# 机制验证 + 假模型实验，生成 docs/BASELINE_REPORT.md 与 docs/baseline_results.json
python scripts/run_baseline.py

# 生成 docs/EXPERIMENTS_REPORT.md 与 docs/experiments_results.json
cd ../experiments && python build_experiments_report.py

# Harness²-lite：fake 全量候选对比（实验/候选/指纹/评分落库 + 证据 + 报告）
cd ../backend
python scripts/run_experiment.py --config all \
    --experiment-name "Harness²-lite fake baseline" \
    --evidence --output ../docs/harness2_results.json
cd ..
python experiments/build_harness2_report.py
```

## Harness²-lite（实验 / 候选 / 指纹 / 证据 / 独立 judge）

当前 `run_experiment.py`（v2.1）在保留原有 v2 行为的基础上，复用后端
`agentflow.core.fingerprint / evidence / judge` 与 `agentflow.storage`：

1. **实验与候选落库**：每次运行生成 `experiment_id = harness2-<hex>`，并写入
   `experiments` 表（名称、dataset/scorer id/version、notes JSON 元数据，不含密钥）；
   三个候选写入 `experiment_candidates` 表。数据库 `candidate_id` 全局唯一，因此候选 ID
   使用 `<experiment_id>-<config>`（如 `harness2-1a2b3c4d5e6f-single`），显示名仍为
   `single` / `sequential` / `parallel`，避免重复运行相互覆盖历史实验。
2. **配置指纹**：`fingerprint` 由 `agentflow.core.fingerprint.compute_fingerprint` 计算，
   输入为 dataset(id/version) + 配置快照（pattern/steps/agents 含 system prompt/模型参数/
   执行策略）+ scorer + 模型连接 provider；密钥、base_url、时间戳不参与。同配置重跑指纹稳定，
   改提示词/参数/模型会变化。
3. **运行关联**：每个 case 执行时把 `experiment_id / candidate_id / case_id / fingerprint`
   传给 `WorkflowExecutor.execute()`，并持久化评分：
   `score`（0-1）、`passed`、`score_status`、`score_source="deterministic"`。
   失败执行不会拿引擎回退文本评分；缺失答案记 `missing_score`，评分失败记 `scoring_error`。
4. **独立 judge（可选）**：`--judge llm` 且 `AGENTFLOW_EXPERIMENT_LLM_JUDGE=1` 时，在确定性
   评分之外调用 `agentflow.core.judge.judge_case` 记录独立评审结果（`independent_judge` /
   `judge_status`），预算 `--judge-budget`（默认 50，或 `AGENTFLOW_JUDGE_MAX_CALLS`）。
   假适配器模式下注入离线确定性 judge client（不联网、无费用，只验证链路）；
   judge 禁用/失败/超预算/缺失分别记录，**不会**把 judge 失败当作通过，也不改写 deterministic 分数。
5. **执行证据（默认关闭）**：`--evidence` 或 `AGENTFLOW_EVIDENCE_ENABLED=true` 开启；
   每 case 通过 `build_evidence` + `write_evidence` 写脱敏证据到
   `AGENTFLOW_EVIDENCE_DIR`（默认 `backend/evidence/<experiment>/<candidate>/<case>.json`），
   并回填 `run.evidence_ref`；每个实验结束按 `AGENTFLOW_EVIDENCE_RETENTION_DAYS`
   （默认 90 天）调用一次 `prune_evidence`。证据只存本地、写入前脱敏、单文件限 200KB。
6. **候选对比报告**：`build_harness2_report.py` 读取 runner 结果（默认
   `docs/harness2_results.json`），生成候选表（fingerprint/cases/completed/failed/passed/
   pass_rate_all_cases/mean_score/total_tokens/total_seconds/trace_id_present/failure_types）、
   case×候选矩阵（status/score/score_status/trace_id/evidence_ref）、评分口径与样本限制，
   并把 `report` 段写回 JSON。脚本默认只接受 **fake** 适配器结果（真实模型需 `--allow-real`
   并在报告中标注），写盘前扫描敏感键与密钥形态字符串。

新增 CLI 参数：`--experiment-name`、`--evidence`、`--judge-budget`（原有
`--config/--limit/--judge/--real/--tracing/--output` 保持不变）。

环境变量（证据/预算）：

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `AGENTFLOW_EVIDENCE_ENABLED` | `false` | 是否写证据包（`--evidence` 也可显式开启） |
| `AGENTFLOW_EVIDENCE_DIR` | `backend/evidence` | 证据根目录 |
| `AGENTFLOW_EVIDENCE_RETENTION_DAYS` | `90` | 证据保留天数（实验结束时清理一次） |
| `AGENTFLOW_JUDGE_MAX_CALLS` | `50` | 独立 judge 单实验调用预算（`--judge-budget` 优先） |
| `AGENTFLOW_DB_PATH` | `./agentflow_data.db` | SQLite 路径（实验/候选/运行记录） |

报告工件：`docs/HARNESS2_COMPARISON.md`（人读）与 `docs/harness2_results.json`
（runner 原始数据 + `report` 段；数字全部来自本次实跑，不含密钥/base_url）。

## trace_id / Langfuse 关联

每个 case 结果都包含 `trace_id`、`trace_id_source`、`tracing_enabled` 字段。
默认不开启追踪，`trace_id=null`；只有显式加 `--tracing` 且配置 Langfuse
（`LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`，可选 `LANGFUSE_HOST`）后，
runner 才会从 `execute()` 返回值 / run 记录读取 `trace_id` 写入结果。缺失时绝不伪造。

## 真实模型（默认关闭）

真实模型路径**只**在同时满足以下条件时才会被创建：

1. 环境变量 `AGENTFLOW_EXPERIMENT_REAL=1`；
2. 命令行显式加 `--real`；
3. 对应 provider 的密钥环境变量存在（`OPENAI_API_KEY` / `DEEPSEEK_API_KEY` /
   `ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY`）；
4. 通过 `AGENTFLOW_EXPERIMENT_PROVIDER`（默认 `openai`）与 `AGENTFLOW_EXPERIMENT_MODEL`
   （或 `--real-model`）指定 provider 与模型；
5. 若使用 `--judge llm`，还需 `AGENTFLOW_EXPERIMENT_LLM_JUDGE=1`。

脚本不会打印密钥。报告 C 节在未实际运行真实模型前必须保持"未运行"，
不得用假模型数字替代真实模型质量/成本结论。
