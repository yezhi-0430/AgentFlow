# Harness²-lite 实施报告（配置指纹 / 证据 / 独立评分 / 候选对比）

> 状态：已实施并验证。**不整体接入 Harness² 框架，不做 Propose–Probe–Compose 自动改工作流。**
> 设计见 [HARNESS2_LITE_PLAN.md](HARNESS2_LITE_PLAN.md)；实验数据见
> [HARNESS2_COMPARISON.md](HARNESS2_COMPARISON.md)（假模型）与
> [HARNESS2_REAL_COMPARISON.md](HARNESS2_REAL_COMPARISON.md)（真实模型受控运行）。

## 一、已交付能力

| 能力 | 实现 | 关键点 |
| --- | --- | --- |
| 配置指纹 | `agentflow/core/fingerprint.py` | 数据集@版本 + 工作流/Agent 配置（含 system_prompt）+ 执行策略 + scorer + provider → 16 位 hash；排除密钥/base_url/时间戳/名称 |
| 执行证据 | `agentflow/core/evidence.py` | 每 case 脱敏 JSON（run 记录、指纹、trace_id、评分、judge）；默认关闭，`--evidence`/env 开启；90 天保留、200KB 上限、路径越界保护 |
| 独立评分 | `agentflow/core/judge.py` | 真实 LLM judge 显式门禁 + 预算（默认 50）；状态 scored/judge_disabled/budget_exhausted/scoring_error/missing_score；**不覆盖主分数**，只做增量记录 |
| 候选对比数据 | schema v4 + `experiments`/`experiment_candidates` 表 | `workflow_runs` 增加 experiment/candidate/case/fingerprint/evidence_ref/score/passed/score_status/score_source |
| 对比 API | `agentflow/api/routes/experiments.py` | 实验列表/详情（候选指标 + case×候选矩阵）/report/证据读取；`/api/runs` 支持 experiment/candidate/fingerprint/case 过滤 |
| 实验 runner | `backend/scripts/run_experiment.py` | 创建实验与候选、传关联字段、写 deterministic 评分、可选 judge/证据、报告数据 |
| 报告生成 | `experiments/build_harness2_report.py` | 候选表/case 矩阵/口径/限制/复现命令；默认拒绝真实数据，`--allow-real` 才生成真实报告；写盘前密钥扫描 |
| 前端 | `ExperimentPanel.vue` + stores/services/utils | 侧栏「实验对比」、候选表、矩阵、证据抽屉、trace/运行详情、导出 JSON、空状态 |

## 二、口径与安全

- **主分数**：始终为 deterministic rubric（0-1）与 `passed`；通过率分母固定为**全部 case**。
- **独立 judge**：只作为增量字段 `independent_judge`/`judge_status`；judge 失败/超预算/缺失**不会**把 case 标为通过，也不会改写 deterministic 分数。
- **证据**：默认关闭；开启后只写本地目录，写入前脱敏（Key/Bearer/连接配置），单文件大小受限，读取校验路径不越界，按 90 天保留期清理。
- **密钥**：不写入定义、运行记录、证据、报告、实验候选配置；报告与证据生成后做过密钥扫描。
- **候选 ID**：`experiment_candidates.candidate_id` 有全局唯一约束，采用 `<experiment_id>-<config>`；展示名仍是 single/sequential/parallel。

## 三、验证结果（本次实跑）

### 1. 测试与构建

| 检查 | 结果 |
| --- | --- |
| 后端全量 | **196 passed / 0 failed**（新增 Harness 核心 10 例 + runner 18 例） |
| 前端测试 | **118 passed / 0 failed**（新增实验面板 12 例） |
| 前端 lint / build | exit 0 / ✓ 142 modules |
| 基线 | `docs/BASELINE_REPORT.md` 重跑：A 节 196 passed + 11/11 断言 |

### 2. 假模型实验（仅证明机制）

- experiment_id `harness2-3e4f4da4332a`，3 候选 × 10 case = 30 次执行；30 条运行落库、30 份证据。
- 三候选均 10/10 completed、passed 8/10（80%）、mean_score 0.8333；tokens 304/618/608；trace_id 0（未开 tracing，null 不伪造）。
- 指纹：single `3141640de8c5b3ae`、sequential `e58ce8dbbeac385c`、parallel `07296a8c12c7533a`（多次运行一致）。
- 失败仅 case-003/case-009（预置错误回答，证明失败可记录）。
- 前端集成验证：临时种子数据下实验列表/详情/report/证据/过滤 API 均正常；空状态与 404 降级可用。

### 3. 真实模型受控实验（一次）

- experiment_id `harness2-c162f77534d2`，模型 `openai/gpt-4o-mini`（OpenRouter 兼容），judge=llm，evidence=on，tracing=on；30 次执行 + 30 次 judge 调用。
- 结果（分母 10）：

| 候选 | 指纹(短) | 完成 | deterministic 通过 | pass_rate_all_cases | mean_score | tokens | 总耗时(s) | trace_id | 证据 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| single | `3a59a82b` | 10/10 | 9 | 0.9 | 0.9417 | 1322 | 23.41 | 10 | 10 |
| sequential | `7a3e77f0` | 10/10 | 7 | 0.7 | 0.8583 | 6442 | 62.43 | 10 | 10 |
| parallel | `78d80c61` | 10/10 | 8 | 0.8 | 0.9333 | 3551 | 38.77 | 10 | 10 |

- 独立 judge：30/30 `scored`；judge 通过 vs deterministic 通过的一致率：single 9/10、sequential 8/10、parallel 9/10；judge 平均分 0.91/0.875/0.90。
- 运行 token 合计 11,315；judge 调用 token 未在 runner 中计量（费用以服务商账单为准，量级为几美分到十几美分）。
- 已用 Langfuse API 抽查 trace `2e5fb98f…`：存在 `experiment-single` 根 span + `solver` generation。
- API 复核：`GET /api/experiments/harness2-c162f77534d2` → 3 候选 / 30 run / 10 行矩阵；`GET /api/evidence/{run_id}` 200；按 experiment+candidate 过滤 runs 正常。

### 4. 浏览器走查（headless Chrome，真实数据）

启动真实后端 + Vite，用 Chrome DevTools Protocol 打开工作台并模拟点击：

- 点击侧栏「实验对比」→ 实验行 `Harness²-lite real controlled` → 候选表显示 single/sequential/parallel、通过率 90%/70%/80%、指纹、Trace 10/10；
- 点击矩阵单元格 → 证据抽屉显示 case-001、运行 ID、Trace ID、配置指纹、请求/响应、prompt/completion/total token、attempts；
- 无运行时异常；截图：
  - [实验面板](images/harness2-experiment-panel.png)
  - [证据抽屉](images/harness2-evidence-drawer.png)

> 说明：前端候选表的「耗时」是后端运行记录中步骤耗时之和，报告中的 `total_seconds` 是 runner 墙钟耗时，
> 两者口径不同。假模型报告 `HARNESS2_COMPARISON.md` 中引用的证据文件在验证后已清理（本地证据按保留策略管理）；
> 真实实验的 30 份证据保留在 `backend/evidence/`（已 gitignore）。

### 5. 结论与限制

- 在本数据集上 single 90% > parallel 80% > sequential 70%；**样本仅 10 个 case、单一模型、单轮运行**，不能外推为总体质量，也不能证明"多 Agent 更优/更差"。
- judge 与 deterministic 在 2-3 个 case 上不一致，说明单一评分器不足；报告保留两个来源，不互相覆盖。
- 真实实验只做了一次；未做多轮重复/置信区间；关键词 rubric 无法判断语义等价。
- 前端未做浏览器点击级 E2E（Node 单测 + lint + build + 真实 API 数据链路验证）。
- Harness² 的递归自动改进（Propose–Probe–Compose）与自动发布**未实现**，也不在本轮范围。

## 四、复现命令

```bash
# 假模型（默认，不联网）
cd backend
python scripts/run_experiment.py --config all --judge deterministic \
  --experiment-name "Harness²-lite fake baseline" --evidence --output ../docs/harness2_results.json
cd ..
python experiments/build_harness2_report.py

# 真实模型（显式门禁 + 受控预算；不要回显密钥）
# 设置 AGENTFLOW_EXPERIMENT_REAL=1、provider 密钥、AGENTFLOW_EXPERIMENT_LLM_JUDGE=1
cd backend
python scripts/run_experiment.py --config all --real --real-model openai/gpt-4o-mini \
  --judge llm --judge-budget 50 --experiment-name "Harness²-lite real controlled" \
  --evidence --tracing --output ../docs/real_harness2_results.json
cd ..
python experiments/build_harness2_report.py --results docs/real_harness2_results.json \
  --markdown docs/HARNESS2_REAL_COMPARISON.md --allow-real
```

## 五、相关文件

- 后端：`agentflow/core/{fingerprint,evidence,judge}.py`、`core/run.py`（schema v4）、`core/workflow.py`（execution metadata/config snapshot）、`storage/{models,database,repository}.py`、`api/routes/experiments.py`、`api/routes/runs.py`
- 前端：`frontend/src/components/ExperimentPanel.vue`、`stores/experiments.js`、`services/experiments.js`、`utils/experimentDetails.js`
- runner/报告：`backend/scripts/run_experiment.py`、`experiments/build_harness2_report.py`、`docs/HARNESS2_COMPARISON.md`、`docs/HARNESS2_REAL_COMPARISON.md`、`docs/harness2_results.json`、`docs/real_harness2_results.json`
- 测试：`backend/tests/test_harness2_core.py`、`tests/test_harness2_runner.py`、`tests/test_experiment_runner.py`、`frontend/tests/experiment-details.test.js`
