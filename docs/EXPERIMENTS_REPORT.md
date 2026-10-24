# AgentFlow 实验报告（评测升级 v2）

- 生成时间：2026-10-24T17:34:27+08:00
- 生成命令：`cd experiments && python build_experiments_report.py`（本报告由脚本基于本次实际运行自动生成）
- 代码版本：commit `08cff608ce6e`，分支 `main`，工作区 dirty=True（改动文件数 86）
- 运行环境：Python 3.13.12 / Windows-11-10.0.22631-SP0 / 解释器 `D:\conda\python.exe`
- 版本冻结：数据集 `agentflow-fixed-v2@2.0.0`（10 个 case），配置 `1.0.0`，评分器 `2.0.0`，judge `deterministic`

> **范围声明**：A、B 两节数字均来自本次实际运行。B 节使用确定性假适配器（不联网、不调用付费模型），其质量数字仅用于证明实验、评分与记录链路可用，**不代表任何真实模型的质量或成本**。C 节若 status=run，则展示受控真实模型运行结果；否则说明未运行原因与启用命令。禁止用 B 节数字冒充真实模型结论。

## A. 机制验证（本次实跑）

### A1. 实验运行器测试（pytest）

命令：`D:\conda\python.exe -m pytest tests/test_experiment_runner.py -q`（cwd=`backend`）

结果：**34 passed, 0 failed, 0 error, 0 skipped**；退出码 `0`，耗时 2.03s。

摘要行：`34 passed in 2.03s`

测试覆盖：默认不调真实模型、答案隔离、评分失败/缺失分别记录、critical rubric 校准、judge 选择与门禁、trace_id/attempts/error_type 字段。

### A2. 补充确定性断言（独立于 pytest，本轮实跑）

| 检查项 | 结果 | 细节（截断） |
| --- | --- | --- |
| 数据集 v2 可加载：固定 10 个 case、case_id 稳定且唯一 | 通过 | {"dataset_id": "agentflow-fixed-v2", "dataset_version": "2.0.0", "case_count": 10, "case_ids": ["case-001", "case-002", "case-003", "case-004", "case-005", "case-006", "case-007", "case-008", "case-009", "case-010"]} |
| 数据集不含答案/评分字段（只允许 case_id/task/tags） | 通过 | {"leaked": [], "forbidden_keys": ["answer", "answers", "expected", "expected_answer", "labels", "reference_answer", "rubric", "scoring"]} |
| 答案隔离：加载器拒绝注入的答案字段，生成消息不含参考要点/rubric | 通过 | {"injected_answer_rejected": true, "rejection_message": "数据集 case case-001 含预期答案/评分字段 ['meta.expected_answer']；预期答案必须单独存放，禁止进入发送给生成模型的消息", "isolation_leaks": [], "checked_configs": ["parallel", "sequential", "single"]} |
| 预期答案覆盖全部 10 个 case，数据集/评分器版本一致且带校准说明 | 通过 | {"answer_case_count": 10, "missing_case_ids": [], "unused_case_ids": [], "scorer_version": "2.0.0", "calibration_keys": ["bands", "calibration_evidence", "critical_rule_rationale", "pass_threshold_default", "threshold_note", "threshold_rationale"]} |
| rubric v2 校准：预设 8 条正确回答通过、2 条故意错误回答不通过（critical 规则生效） | 通过 | {"passed_count": 8, "failed_case_ids": ["case-003", "case-009"], "rows": [{"case_id": "case-001", "score": 1.0, "passed": true, "critical_missed_items": [], "score_status": "scored"}, {"case_id": "case-002", "score": 1.0, "passed": true, "critical_missed_items": [], "score_status": "scored"}, {"case_id": "case-003", "score": 0.3333, "passed": false, "critical_missed_items": ["r1", "r2"], "score_status": "scored"}, {"case_id": "case-004", "score": 1.0, "passed": true, "critical_missed_items": [], |
| judge 选择：默认 deterministic、none 关闭评分、llm 需显式门禁且默认不联网 | 通过 | {"deterministic": "deterministic", "none": "none", "deterministic_network": false, "none_adapter": null, "llm_without_gate_rejected": true, "llm_fake_judge": {"mode": "llm", "adapter": "scripted-fake-judge-v1", "model": null, "network": false, "deterministic": true, "fake_judge": true, "version": "2.0.0", "note": "假适配器模式下的确定性 fake judge：只验证 judge 调用/解析/记录链路，不联网、不产生费用；它不是真实 LLM 评审，分数不代表真实评审质量。"}, "llm_fake_judge_scores": [["case-001", 1.0], ["case-002", 1.0]]} |
| 运行记录满足后端 v3 契约：run_id、trace_id 字段、attempts、error_type | 通过 | {"backend_record_schema_version": 3, "case_count_checked": 30, "sample": [{"case_id": "case-001", "run_id_present": true, "trace_id_field_present": true, "trace_id": null, "tracing_enabled": false, "record_schema_version": 3, "attempts": 1, "error_type": null, "score_status": "scored"}, {"case_id": "case-002", "run_id_present": true, "trace_id_field_present": true, "trace_id": null, "tracing_enabled": false, "record_schema_version": 3, "attempts": 1, "error_type": null, "score_status": "scored"} |
| trace_id 映射：优先 execute() 返回值，其次 run.trace_id / run.to_dict()，缺失不伪造 | 通过 | {"run_detail": ["dddddddddddddddddddddddddddddddd", "run.trace_id"], "exec_result": ["eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee", "exec_result"], "none": [null, null]} |
| 成功率分母为全部 case（缺失评分/评分错误/执行失败按未通过计入） | 通过 | {"per_config": [{"config": "single", "case_count": 10, "passed_count": 8, "missing_score_count": 0, "scoring_error_count": 0, "judge_disabled_count": 0, "pass_rate_all_cases": 0.8, "recomputed": 0.8}, {"config": "sequential", "case_count": 10, "passed_count": 8, "missing_score_count": 0, "scoring_error_count": 0, "judge_disabled_count": 0, "pass_rate_all_cases": 0.8, "recomputed": 0.8}, {"config": "parallel", "case_count": 10, "passed_count": 8, "missing_score_count": 0, "scoring_error_count": 0 |
| 不支持的配置被拒绝（--config debate）且 --limit 只运行前 N 个 case | 通过 | {"debate_rejected": true, "limit_case_count": 3, "limit_full_case_count": 10} |
| 真实模型默认关闭（缺 AGENTFLOW_EXPERIMENT_REAL 即拒绝）且 CLI 默认 fake/确定性 judge | 通过 | {"real_gate_rejected": true, "real_gate_message": "真实模型模式已禁用：需显式设置 AGENTFLOW_EXPERIMENT_REAL=1（默认关闭，避免误调付费模型）", "cli_defaults": {"config": "all", "judge": "deterministic", "real": false, "tracing": false}} |

检查通过：**11/11**。

### A3. 评分器 v2 校准（阈值、通过标准、理由）

- 默认阈值：**0.75**。
- 通过标准：`score = 命中条目权重和 / 全部条目权重和`，且 `passed = score >= pass_threshold 且所有 critical 条目命中`。
- 阈值理由：3 个等权条目时 0.75 对应“至少命中 2 项”，比 0.5 更严格：要求关键结论加至少一个支撑细节，同时允许非关键细节因表述差异缺失。2 个条目、权重为 2+1 时，0.75 需要至少 1.5 权重命中，等价于权重大者必须命中；单条目 rubric 则要求该条目命中。
- critical 理由：对事实性关键结论（最终数值、关键定义、核心区别）标记 critical。即使总分达到阈值，只要 critical 条目缺失就判不通过，避免“命中若干辅助关键词但结论错误”被误判为正确。
- 校准证据：v2 用确定性假适配器预设的 8 条正确回答与 2 条故意错误回答校准：正确回答得 1.0；case-003 的错误回答只命中 1/3 权重（0.3333）且缺失 critical r1；case-009 的错误回答命中 0（0.0）且缺失 critical r1。该证据只证明评分器能区分预设正确/错误回答，不代表真实模型质量。

| 分数区间 | 含义 |
| --- | --- |
| 1.0 | 全部评分点命中，通过 |
| 0.75-0.999 | 达到阈值且 critical 全部命中，通过；允许非关键细节缺失 |
| 0.5-0.749 | 部分正确但未达阈值，不通过 |
| 0.0-0.499 | 基本错误或答非所问，不通过 |

## B. 假模型实验（本次实跑；仅证明机制，不代表真实质量/成本）

> 假适配器 `scripted-fake-v1` 返回预先编写的确定性文本，token 由确定性规则生成；其中 case-003、case-009 为故意错误回答。B 节通过率只说明评分器能区分预设的正确/错误回答，**样本仅 10 个 case，不得外推为总体质量**；耗时与 token 不具备真实外部效度。

运行方式（本轮内部执行）：`cd backend && python scripts/run_experiment.py --config all --judge deterministic`

- 数据集：`agentflow-fixed-v2@2.0.0`，固定 case 数 10
- 配置：single / sequential / parallel（`1.0.0`）
- 适配器：`scripted-fake-v1`（mode=fake，network=False，deterministic=True）
- Judge：mode=deterministic，adapter=`deterministic-rubric-v2`，network=False（默认确定性 rubric，不联网）
- 评分器：v2.0.0（rubric v2 + critical 校准，默认阈值 0.75）
- trace_id：本次未开启追踪（`tracing.enabled=false`），因此所有 case 的 `trace_id=null`；字段本身始终写入结果，开启 `--tracing` 且配置 Langfuse 后从 run 记录带入。

### B1. 总览（成功率分母始终是全部 case）

| 配置 | 用例数 | 完成 | 部分 | 失败 | 执行成功率 | 已评分 | 缺失评分 | 评分错误 | judge关闭 | 通过 | 通过率(已评分) | 通过率(全部case) | 平均分(已评分) | 总token | 总耗时(s) | trace_id数 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| single | 10 | 10 | 0 | 0 | 100.0% | 10 | 0 | 0 | 0 | 8 | 80.0% | 80.0% | 0.8333 | 304 | 0.0072 | 0 |
| sequential | 10 | 10 | 0 | 0 | 100.0% | 10 | 0 | 0 | 0 | 8 | 80.0% | 80.0% | 0.8333 | 618 | 0.0034 | 0 |
| parallel | 10 | 10 | 0 | 0 | 100.0% | 10 | 0 | 0 | 0 | 8 | 80.0% | 80.0% | 0.8333 | 608 | 0.0016 | 0 |

说明：`通过率(已评分)` 的分母是成功产出且完成评分的 case；`通过率(全部case)` 的分母是全部 case（本次每个配置均为 10），缺失评分、评分错误、执行失败、judge 关闭都按“未通过”计入，不会只统计成功案例。

### B2. 逐 case 结果

| 配置 | case_id | run_id | trace_id | 执行状态 | schema | attempts | error_type | token | usage_type | 分数 | 通过 | critical缺失 | 评分/执行异常 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| single | case-001 | cc05ea82 | — | completed | 3 | 1 | — | 33 | actual | 1 | 是 |  | — |
| single | case-002 | 34c7ea9b | — | completed | 3 | 1 | — | 27 | actual | 1 | 是 |  | — |
| single | case-003 | 2bd43b51 | — | completed | 3 | 1 | — | 28 | actual | 0.3333 | 否 | r1,r2 | — |
| single | case-004 | afaefec9 | — | completed | 3 | 1 | — | 29 | actual | 1 | 是 |  | — |
| single | case-005 | 331dd943 | — | completed | 3 | 1 | — | 36 | actual | 1 | 是 |  | — |
| single | case-006 | b2bde1a1 | — | completed | 3 | 1 | — | 38 | actual | 1 | 是 |  | — |
| single | case-007 | fe1e7c25 | — | completed | 3 | 1 | — | 27 | actual | 1 | 是 |  | — |
| single | case-008 | 837ea98a | — | completed | 3 | 1 | — | 24 | actual | 1 | 是 |  | — |
| single | case-009 | db601fd1 | — | completed | 3 | 1 | — | 31 | actual | 0 | 否 | r1 | — |
| single | case-010 | d4dbd116 | — | completed | 3 | 1 | — | 31 | actual | 1 | 是 |  | — |
| sequential | case-001 | 18fb7db3 | — | completed | 3 | 1 | — | 69 | actual | 1 | 是 |  | — |
| sequential | case-002 | 27969951 | — | completed | 3 | 1 | — | 57 | actual | 1 | 是 |  | — |
| sequential | case-003 | 6a895073 | — | completed | 3 | 1 | — | 58 | actual | 0.3333 | 否 | r1,r2 | — |
| sequential | case-004 | 4638c8b7 | — | completed | 3 | 1 | — | 51 | actual | 1 | 是 |  | — |
| sequential | case-005 | 9a646866 | — | completed | 3 | 1 | — | 70 | actual | 1 | 是 |  | — |
| sequential | case-006 | 503d45a6 | — | completed | 3 | 1 | — | 90 | actual | 1 | 是 |  | — |
| sequential | case-007 | 71c65da4 | — | completed | 3 | 1 | — | 57 | actual | 1 | 是 |  | — |
| sequential | case-008 | 24321166 | — | completed | 3 | 1 | — | 42 | actual | 1 | 是 |  | — |
| sequential | case-009 | fc03c159 | — | completed | 3 | 1 | — | 59 | actual | 0 | 否 | r1 | — |
| sequential | case-010 | ccc125d0 | — | completed | 3 | 1 | — | 65 | actual | 1 | 是 |  | — |
| parallel | case-001 | b610311b | — | completed | 3 | 1 | — | 66 | actual | 1 | 是 |  | — |
| parallel | case-002 | 1831f801 | — | completed | 3 | 1 | — | 54 | actual | 1 | 是 |  | — |
| parallel | case-003 | 80d7cf42 | — | completed | 3 | 1 | — | 56 | actual | 0.3333 | 否 | r1,r2 | — |
| parallel | case-004 | 28a698c7 | — | completed | 3 | 1 | — | 58 | actual | 1 | 是 |  | — |
| parallel | case-005 | 2157801c | — | completed | 3 | 1 | — | 72 | actual | 1 | 是 |  | — |
| parallel | case-006 | c7ab6797 | — | completed | 3 | 1 | — | 76 | actual | 1 | 是 |  | — |
| parallel | case-007 | 774bbc07 | — | completed | 3 | 1 | — | 54 | actual | 1 | 是 |  | — |
| parallel | case-008 | 6067de65 | — | completed | 3 | 1 | — | 48 | actual | 1 | 是 |  | — |
| parallel | case-009 | 2eed87de | — | completed | 3 | 1 | — | 62 | actual | 0 | 否 | r1 | — |
| parallel | case-010 | 38176e5a | — | completed | 3 | 1 | — | 62 | actual | 1 | 是 |  | — |

### B3. 评分记录完整性

- 缺失评分（missing_score）记录数：0；评分错误（scoring_error）记录数：0；judge 关闭（judge_disabled）记录数：0。
- 未知用量（usage_type=unknown）步骤数：0；未知用量不会被当作 0 真实成本。
- 执行失败的 case 不会被拿去评分：评分前先判断执行状态与输出非空，失败执行以 `score_status=execution_failed` 记录，不会用引擎回退文本冒充成功。

### B4. 如何解读（局限必须连同数字一起阅读）

- 假适配器有 2 条预设回答故意答错（case-003、case-009），通过率 80% 是**评分器识别失败**的证据，不是模型能力结论。
- 质量分数反映“预先编写的回答”与“关键词 rubric + critical 规则”的匹配程度，无法判断语义等价表达；关键词覆盖不到的正确答案可能被误判为不通过。
- token 为假适配器按字符长度规则生成的合成值，usage_type 由引擎按“是否返回 usage”判定，均不代表真实模型计费。
- 固定数据集只有 10 个 case，不具备统计代表性；任何通过率都不可外推为总体质量。
- 耗时在毫秒级，受进程调度影响大，仅证明计时字段可用，不可外推到真实模型延迟。
- 本次 trace_id 全为 null（追踪未开启），仅证明字段与映射逻辑就绪，不能据此声称已产生 Langfuse trace。

## C1. 真实模型实验（本次受控运行）

- 数据来源：`docs\real_experiment_results.json`（experiment_id `experiment-57426f096f7c`，生成时间 2026-10-24T17:32:30+08:00）
- 适配器：mode=`real`，provider=`openai`，model=`openai/gpt-4o-mini`，network=`True`
- 评分：mode=`deterministic`，adapter=`deterministic-rubric-v2`（确定性 rubric；本轮未运行 LLM judge）
- 追踪：enabled=`True`；每个 case 的 trace_id 从 execute() 返回值/运行记录读取，未启用时为 null，不伪造。

| 配置 | 模式 | 完成 | 通过（分母全部 case） | pass_rate_all_cases | mean_score_all_cases | total_tokens | 总耗时(s) | trace_id 数 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| single | single | 10/10 | 6/10 | 0.6 | 0.8 | 1358 | 23.0369 | 10 |
| sequential | sequential | 10/10 | 5/10 | 0.5 | 0.8 | 6454 | 61.3496 | 10 |
| parallel | parallel | 10/10 | 8/10 | 0.8 | 0.8667 | 3546 | 31.3798 | 10 |

每 case 结果（真实模型）：

| 配置 | case_id | 执行状态 | 评分状态 | score | tokens | usage_type | trace_id |
| --- | --- | --- | --- | --- | --- | --- | --- |
| single | case-001 | completed | scored | 1.0 | 111 | actual | 2a9604ed2ff0856cf759bbec5389fd8e |
| single | case-002 | completed | scored | 1.0 | 141 | actual | 6d7ae6c97172ae356e6d5d809370c9bf |
| single | case-003 | completed | scored | 0.6667 | 129 | actual | 27f20c9e9a158cb24826b35e7931c27e |
| single | case-004 | completed | scored | 1.0 | 74 | actual | 430d4bcd17c6a7c4afe5a5c4eca50ff6 |
| single | case-005 | completed | scored | 1.0 | 157 | actual | f9b78e02050951f68d9f3239c1f8d048 |
| single | case-006 | completed | scored | 0.6667 | 262 | actual | 711beb31a7479c372da521106d2d5f8e |
| single | case-007 | completed | scored | 1.0 | 104 | actual | 126163c1d99776c026aeac369f93df76 |
| single | case-008 | completed | scored | 0.0 | 62 | actual | 4e125db37798689ecaecdf952b4046d1 |
| single | case-009 | completed | scored | 0.6667 | 131 | actual | dd05e46ac4b54d0eebdc4e256c560712 |
| single | case-010 | completed | scored | 1.0 | 187 | actual | af5135764e4de7bdb8888b40e2f38a25 |
| sequential | case-001 | completed | scored | 1.0 | 427 | actual | 947ce33b52beb03c1f7d4eff662076de |
| sequential | case-002 | completed | scored | 1.0 | 505 | actual | 98ef44be9b96b5ed48249cad29e2d7da |
| sequential | case-003 | completed | scored | 0.6667 | 1128 | actual | 60ef70312ac262192a6d537b49c95098 |
| sequential | case-004 | completed | scored | 0.6667 | 192 | actual | b5e42702c8e47aa6f4238ee5205392d6 |
| sequential | case-005 | completed | scored | 1.0 | 667 | actual | 910ccb99bde7c75f0297dd4ada2c84b3 |
| sequential | case-006 | completed | scored | 0.6667 | 1001 | actual | 3f1eb7f1446e08c5ad913519a859a5c4 |
| sequential | case-007 | completed | scored | 1.0 | 459 | actual | 1480d3c1399ef279ba10b96cf61c4d58 |
| sequential | case-008 | completed | scored | 0.3333 | 190 | actual | dfc47a3b730306c9e1d6129974f712f8 |
| sequential | case-009 | completed | scored | 0.6667 | 475 | actual | 182a81ea5de2c5982aca6c77e3693baf |
| sequential | case-010 | completed | scored | 1.0 | 1410 | actual | 8df86a20fe706dca8ebccd8f76f0a1d3 |
| parallel | case-001 | completed | scored | 1.0 | 232 | actual | 3c0b4fa75c2eff3af5812c6e2f4433c6 |
| parallel | case-002 | completed | scored | 1.0 | 394 | actual | 1a01798ab8948a96b2c657440b410f0c |
| parallel | case-003 | completed | scored | 1.0 | 564 | actual | 253f87a881566ee233b12afacce69aec |
| parallel | case-004 | completed | scored | 1.0 | 162 | actual | f26d125eb77e3450be65ea21253c9e37 |
| parallel | case-005 | completed | scored | 1.0 | 334 | actual | 8b7892a002c5b8a2f4d5584babac6a99 |
| parallel | case-006 | completed | scored | 1.0 | 604 | actual | 422cb0a583f00b3e93910ea443c1fccf |
| parallel | case-007 | completed | scored | 1.0 | 227 | actual | 002f90dcf3caaa5db7d852bba42672cf |
| parallel | case-008 | completed | scored | 0.0 | 122 | actual | 3c4e8aee95ccaf451faf5f26864f16a5 |
| parallel | case-009 | completed | scored | 0.6667 | 302 | actual | 9ff8fc0819d4f95ce7b07f8b1cd9760a |
| parallel | case-010 | completed | scored | 1.0 | 605 | actual | 0c6422e3cfa52fb15e4c4a8fce5a5ac8 |

> 说明：10 个固定 case × 3 配置 = 30 次真实执行；token 为提供商实际返回，分数为确定性 rubric。样本很小，上述通过率只是该配置在该数据集上的观察，**不能外推为总体质量，也不能据此证明多 Agent 方案更优**；本轮未运行 LLM judge，未对真实评审模型做校准。真实运行结果文件：`docs/real_experiment_results.json`。

## C2. 真实模型实验的启用条件与命令（参考）

> 本次已完成受控运行，C1 为实际结果；以下条件与命令保留用于复现。

当前开关检查：`AGENTFLOW_EXPERIMENT_REAL` = `未设置（默认关闭）`；`AGENTFLOW_EXPERIMENT_LLM_JUDGE` = `未设置（默认关闭）`。密钥只检查是否存在，不读取、不记录、不打印具体值。

预计样本（仅按固定数据集计算，不代表成本）：
- 10 个固定 case × 3 个配置 = **30 次执行**；若启用 LLM judge，额外 30 次评审调用。
- 预计样本仅按固定数据集与配置计算；真实耗时/成本未知，本报告不编造成本数字。

启用条件：
1. 设置 AGENTFLOW_EXPERIMENT_REAL=1
2. 命令行显式加 --real
3. 选择 provider：AGENTFLOW_EXPERIMENT_PROVIDER（默认 openai）
4. 对应 provider 的密钥环境变量存在（只检查是否存在，不打印值）
5. 指定模型：--real-model 或 AGENTFLOW_EXPERIMENT_MODEL
6. 若要 --judge llm：额外设置 AGENTFLOW_EXPERIMENT_LLM_JUDGE=1（会产生额外评审调用费用）
7. 若要记录 trace_id：配置 Langfuse 并显式加 --tracing

命令（密钥通过环境变量提供，不要写进仓库）：

```bash
export AGENTFLOW_EXPERIMENT_REAL=1  # Windows PowerShell: $env:AGENTFLOW_EXPERIMENT_REAL='1'
export AGENTFLOW_EXPERIMENT_PROVIDER=<openai|deepseek|anthropic|openrouter>
export OPENAI_API_KEY=<密钥>  # 按 provider 选择对应变量；不要写进仓库
export AGENTFLOW_EXPERIMENT_MODEL=<模型名>
export AGENTFLOW_EXPERIMENT_LLM_JUDGE=1  # 仅 --judge llm 时需要

cd backend && python scripts/run_experiment.py --real --config all --judge deterministic --output ../experiments/real_run_deterministic.json
cd backend && python scripts/run_experiment.py --real --config all --judge llm --output ../experiments/real_run_llm_judge.json
cd backend && python scripts/run_experiment.py --real --config all --judge deterministic --tracing --output ../experiments/real_run_traced.json
```

密钥环境变量是否存在（仅布尔值）：

| 环境变量 | 状态 |
| --- | --- |
| ANTHROPIC_API_KEY | 未设置 |
| DEEPSEEK_API_KEY | 未设置 |
| OPENAI_API_KEY | 未设置 |
| OPENROUTER_API_KEY | 未设置 |

> 注：上表检查的是生成报告进程的环境；C1 的真实运行由独立受控启动器注入密钥与模型配置，因此这里显示未设置不代表真实运行未配置。

> C 节若 status=run 表示已用真实模型受控运行，数字全部来自 docs/real_experiment_results.json；若 status=not_run 则没有任何真实模型数字。禁止用 B 节假模型数字替代真实模型质量/成本结论。

## D. Langfuse 实验关联说明

1. 每个 case 结果始终包含 `trace_id` / `trace_id_source` / `tracing_enabled` 字段。
2. 默认不开启追踪：不联网、不需要 Langfuse 配置，`trace_id=null`，绝不伪造。
3. 需要关联时显式加 `--tracing`，并配置 `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`（可选 `LANGFUSE_HOST`）；runner 从 `execute()` 返回值 / run 记录的 `trace_id` 读取并写入结果。
4. 本次 C1 真实运行显式启用了 `--tracing`，30 个 case 均记录了非空 `trace_id`（见 C1 每 case 表）；trace 可在 Langfuse 中按该 id 检索。B 节假模型实验未开启追踪，因此 B 节 trace_id 为 null。

## 复现与相关文件

- 本报告：`docs/EXPERIMENTS_REPORT.md`
- 原始结果 JSON：`docs/experiments_results.json`
- 数据集：`experiments/dataset_v2.json`（10 个固定 case，case-001..case-010）
- 预期答案/评分要点/校准：`experiments/expected_answers_v2.json`（只给评分器读）
- 配置：`experiments/configs_v1.json`
- 生成报告：`cd experiments && python build_experiments_report.py`
- 单跑实验：`cd backend && python scripts/run_experiment.py --config single|sequential|parallel|all [--limit N] [--judge deterministic|llm|none]`
- 重跑基线：`cd backend && python scripts/run_baseline.py`

## 未运行 / 未验证项

- 真实模型实验未运行：没有任何真实模型质量、延迟或成本数据；C 节仅为受控执行入口。
- B 节使用假适配器，质量数字只能证明评分/执行/记录链路，不能代表真实模型质量。
- 确定性评分器为关键词/短语 rubric + critical 规则，无法评判语义等价与推理过程质量，存在误判可能。
- 固定数据集只有 10 个 case，不具统计代表性，任何通过率都不可外推。
- 本次未开启 Langfuse 追踪，trace_id 全为 null；字段与映射逻辑已就绪，但尚未产生真实 trace。
- 耗时为本机毫秒级调度结果，token 为假适配器合成值，均不可外推为真实成本/延迟。
- 本轮未覆盖真实网络故障、限流、超时重试等场景（后端 v3 的 attempts/error_type 字段已记录但未被真实触发）。

