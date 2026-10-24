# AgentFlow 基线报告

- 生成时间：2026-10-24T18:18:01+08:00
- 生成命令：`cd backend && python scripts/run_baseline.py`（本报告由脚本基于本次实际运行自动生成）
- 代码版本：commit `08cff608ce6e`，分支 `main`，工作区 dirty=True（改动文件数 104）
- 运行环境：Python 3.13.12 / Windows-11-10.0.22631-SP0 / 解释器 `D:\conda\python.exe`
- 版本冻结：数据集 `agentflow-fixed-v2@2.0.0`，配置 `1.0.0`，评分器 `2.0.0`，judge `deterministic`

> **范围声明**：A、B 两节数字均来自本次实际运行。B 节使用确定性假适配器（不联网、不调用付费模型），其质量数字仅用于证明实验、评分与记录链路可用，**不代表任何真实模型的质量或成本**。

> v2 升级：数据集扩为 10 个固定 case，评分器升级为 rubric v2（阈值 + critical 校准），记录兼容后端 v3（trace_id / attempts / error_type）；本基线只运行 `--judge deterministic`（默认）。

## A. 机制验证（本次实跑）

### A1. 后端测试套件（pytest）

命令：`D:\conda\python.exe -m pytest tests/ -q`（cwd=`backend`）

结果：**196 passed, 0 failed, 0 error, 0 skipped**；退出码 `0`，耗时 19.09s。

摘要行：`196 passed in 19.09s`

本次 pytest 输出尾部（截取）：

```text
........................................................................ [ 36%]
........................................................................ [ 73%]
....................................................                     [100%]
196 passed in 19.09s
```

### A2. 补充确定性断言（独立于 pytest，本轮实跑）

| 检查项 | 结果 | 细节 |
| --- | --- | --- |
| 数据集可加载且版本字段完整 | 通过 | {"dataset_id": "agentflow-fixed-v2", "dataset_version": "2.0.0", "case_count": 10} |
| 至少 10 个固定 case 且 case_id 唯一 | 通过 | {"case_count": 10, "unique": 10, "min_expected": 10, "case_ids": ["case-001", "case-002", "case-003", "case-004", "case-005", "case-006", "case-007", "case-008", "case-009", "case-010"]} |
| 数据集不含预期答案/评分字段（答案隔离） | 通过 | {"leaked_fields": [], "forbidden_keys": ["answer", "answers", "expected", "expected_answer", "labels", "reference_answer", "rubric", "scoring"]} |
| 预期答案覆盖全部固定 case 且评分器版本一致 | 通过 | {"answers_present": true, "scorer_version": "2.0.0", "answer_case_count": 10, "missing_case_ids": [], "unused_case_ids": []} |
| 三种配置（single/sequential/parallel）定义齐全 | 通过 | {"config_version": "1.0.0", "configs": ["parallel", "sequential", "single"], "missing": [], "unexpected": []} |
| 实验配置只使用引擎支持的 sequential/parallel 模式 | 通过 | {"engine_patterns": {"single": "sequential", "sequential": "sequential", "parallel": "parallel"}, "note": "single 是实验层名称，底层为 1 步 sequential；未支持模式不会进入实验配置。"} |
| 引擎冒烟：single 配置可执行、有输出且可评分 | 通过 | {"case_id": "case-001", "status": "completed", "output_chars": 41, "score": 1.0, "elapsed_seconds": 0.0791, "total_tokens": 33, "adapter": "scripted-fake-v1"} |
| 假适配器确定性：同一输入两次运行输出/token/评分一致 | 通过 | {"output_equal": true, "tokens": [33, 33], "scores": [1.0, 1.0]} |
| 运行器默认不启用真实模型（mode=fake、network=false） | 通过 | {"mode": "fake", "network": false, "real_gate_env": "AGENTFLOW_EXPERIMENT_REAL", "real_gate_set": false} |
| 运行记录满足版本化契约（schema_version/run_id/trace_id/attempts/error_type/用量类型） | 通过 | {"backend_record_schema_version": 4, "record_schema_version": 4, "run_id_present": true, "trace_id": null, "tracing_enabled": false, "step_fields": ["agent_name", "attempts", "duration_seconds", "error", "error_type", "finish_reason", "input_chars", "model", "output_excerpt", "status", "step_id", "step_index", "total_tokens", "usage_type", "usage_unknown"], "step_usage_type": "actual", "attempts": 1, "error_type": null} |
| 引擎拒绝未支持的工作流模式（如 debate） | 通过 | {"checked_pattern": "debate", "rejected": true} |

检查通过：**11/11**。
引擎冒烟（single，case=case-001）：状态 `completed`，输出 41 字符，得分 1.0，token=33，耗时 0.0791s，记录 schema_version=4；假适配器确定性复跑一致=True。

## B. 假模型质量实验（本次实跑）

> **仅证明机制，不代表真实模型质量/成本。** 假适配器 `scripted-fake-v1` 返回预先编写的确定性文本，token 计数由确定性规则生成；本节的通过率只说明评分器能区分预设的正确/错误回答，耗时和 token 都不具备外部效度。样本只有 10 个 case，不得外推整体质量。

运行方式（本轮内部执行）：`cd backend && python scripts/run_experiment.py --config all --judge deterministic`

- 数据集：`agentflow-fixed-v2@2.0.0`，固定 case 数 10
- 配置：single / sequential / parallel（`1.0.0`）
- 适配器：`scripted-fake-v1`（mode=fake，network=False，deterministic=True）
- 评分器：v2.0.0（rubric v2 + critical 校准，默认通过阈值 0.75）
- Judge：mode=deterministic，adapter=`deterministic-rubric-v2`，network=False（默认确定性 rubric，不联网）
- trace_id：本次未开启追踪，所有 case 的 `trace_id=null`；字段/映射逻辑已就绪，开启 `--tracing` 且配置 Langfuse 后从 run 记录带入，不伪造。

### B1. 总览（成功率分母始终是全部 case）

| 配置 | 用例数 | 完成 | 部分 | 失败 | 执行成功率 | 已评分 | 缺失评分 | 评分错误 | judge关闭 | 通过 | 通过率(已评分) | 通过率(全部用例) | 平均分(已评分) | 总耗时(s) | 平均耗时(s) | 总token | 平均token/case | 未知用量step数 | trace_id数 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| single | 10 | 10 | 0 | 0 | 100.0% | 10 | 0 | 0 | 0 | 8 | 80.0% | 80.0% | 0.8333 | 0.5678 | 0.0568 | 304 | 30.4 | 0 | 0 |
| sequential | 10 | 10 | 0 | 0 | 100.0% | 10 | 0 | 0 | 0 | 8 | 80.0% | 80.0% | 0.8333 | 0.7077 | 0.0708 | 618 | 61.8 | 0 | 0 |
| parallel | 10 | 10 | 0 | 0 | 100.0% | 10 | 0 | 0 | 0 | 8 | 80.0% | 80.0% | 0.8333 | 0.5945 | 0.0595 | 608 | 60.8 | 0 | 0 |

说明：`通过率(已评分)` 的分母是成功产出且评分的 case；`通过率(全部用例)` 的分母是全部 case，缺失评分、评分错误、执行失败、judge 关闭都按“未通过”计入，不会只统计成功案例。

### B2. 逐 case 结果

| 配置 | case_id | run_id | trace_id | 执行状态 | 工作流状态 | schema | attempts | error_type | 耗时(s) | token | usage_type | 分数 | 通过 | critical缺失 | 评分异常 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| single | case-001 | 360fec41 | — | completed | completed | 4 | 1 | — | 0.0644 | 33 | actual | 1 | 是 |  | — |
| single | case-002 | fa9806fc | — | completed | completed | 4 | 1 | — | 0.0545 | 27 | actual | 1 | 是 |  | — |
| single | case-003 | aaeed38e | — | completed | completed | 4 | 1 | — | 0.0562 | 28 | actual | 0.3333 | 否 | r1,r2 | — |
| single | case-004 | 74388134 | — | completed | completed | 4 | 1 | — | 0.0502 | 29 | actual | 1 | 是 |  | — |
| single | case-005 | f5240432 | — | completed | completed | 4 | 1 | — | 0.0596 | 36 | actual | 1 | 是 |  | — |
| single | case-006 | 8192ea8e | — | completed | completed | 4 | 1 | — | 0.0497 | 38 | actual | 1 | 是 |  | — |
| single | case-007 | 060e3e4d | — | completed | completed | 4 | 1 | — | 0.0585 | 27 | actual | 1 | 是 |  | — |
| single | case-008 | 7b6d724f | — | completed | completed | 4 | 1 | — | 0.0558 | 24 | actual | 1 | 是 |  | — |
| single | case-009 | 846b6915 | — | completed | completed | 4 | 1 | — | 0.0709 | 31 | actual | 0 | 否 | r1 | — |
| single | case-010 | 6c8da5c3 | — | completed | completed | 4 | 1 | — | 0.0480 | 31 | actual | 1 | 是 |  | — |
| sequential | case-001 | 548daaef | — | completed | completed | 4 | 1 | — | 0.0770 | 69 | actual | 1 | 是 |  | — |
| sequential | case-002 | 6ee85dfd | — | completed | completed | 4 | 1 | — | 0.0775 | 57 | actual | 1 | 是 |  | — |
| sequential | case-003 | 6701a600 | — | completed | completed | 4 | 1 | — | 0.0593 | 58 | actual | 0.3333 | 否 | r1,r2 | — |
| sequential | case-004 | e4cf6abc | — | completed | completed | 4 | 1 | — | 0.0729 | 51 | actual | 1 | 是 |  | — |
| sequential | case-005 | 32717209 | — | completed | completed | 4 | 1 | — | 0.0673 | 70 | actual | 1 | 是 |  | — |
| sequential | case-006 | 5670c050 | — | completed | completed | 4 | 1 | — | 0.0584 | 90 | actual | 1 | 是 |  | — |
| sequential | case-007 | 3cdc42cd | — | completed | completed | 4 | 1 | — | 0.0821 | 57 | actual | 1 | 是 |  | — |
| sequential | case-008 | 2d0082ec | — | completed | completed | 4 | 1 | — | 0.0702 | 42 | actual | 1 | 是 |  | — |
| sequential | case-009 | df0c4beb | — | completed | completed | 4 | 1 | — | 0.0692 | 59 | actual | 0 | 否 | r1 | — |
| sequential | case-010 | d56850d7 | — | completed | completed | 4 | 1 | — | 0.0738 | 65 | actual | 1 | 是 |  | — |
| parallel | case-001 | 50262acb | — | completed | completed | 4 | 1 | — | 0.0639 | 66 | actual | 1 | 是 |  | — |
| parallel | case-002 | 9d20dbb5 | — | completed | completed | 4 | 1 | — | 0.0578 | 54 | actual | 1 | 是 |  | — |
| parallel | case-003 | 2832592b | — | completed | completed | 4 | 1 | — | 0.0533 | 56 | actual | 0.3333 | 否 | r1,r2 | — |
| parallel | case-004 | 6adf2677 | — | completed | completed | 4 | 1 | — | 0.0563 | 58 | actual | 1 | 是 |  | — |
| parallel | case-005 | 7dad8fd9 | — | completed | completed | 4 | 1 | — | 0.0561 | 72 | actual | 1 | 是 |  | — |
| parallel | case-006 | f11c85eb | — | completed | completed | 4 | 1 | — | 0.0711 | 76 | actual | 1 | 是 |  | — |
| parallel | case-007 | 16736529 | — | completed | completed | 4 | 1 | — | 0.0662 | 54 | actual | 1 | 是 |  | — |
| parallel | case-008 | 97dfb439 | — | completed | completed | 4 | 1 | — | 0.0633 | 48 | actual | 1 | 是 |  | — |
| parallel | case-009 | 2dd6b11e | — | completed | completed | 4 | 1 | — | 0.0591 | 62 | actual | 0 | 否 | r1 | — |
| parallel | case-010 | 949dd75b | — | completed | completed | 4 | 1 | — | 0.0474 | 62 | actual | 1 | 是 |  | — |

### B3. 评分记录完整性

- 缺失评分（missing_score）记录数：0；评分错误（scoring_error）记录数：0；judge 关闭（judge_disabled）记录数：0。
- 未知用量（usage_type=unknown）步骤数：0；涉及 case：无。未知用量不会被当作 0 真实成本，case 记录中的 usage_type 与 unknown_usage_step_count 会显式体现。
- 本次 trace_id 非空记录数：0（追踪未开启，全部为 null）；`trace_id` 字段始终写入结果，开启 `--tracing` 且配置 Langfuse 后由后端 run 记录带入。

本次假模型实验中每个 case 都产出了评分结果，无缺失评分、无评分错误、无 judge 关闭。

### B4. 如何解读（局限必须连同数字一起阅读）

- 假适配器有 2 条预设回答故意答错（case-003, case-009），因此通过率 <100% 是**评分器识别失败**的证据，不是模型能力结论。
- 质量分数反映“预先编写的回答”与“rubric v2（关键词 + critical）”的匹配程度，无法判断语义等价表达；关键词覆盖不到的正确答案可能被误判。
- 固定数据集只有 10 个 case，不具统计代表性；通过率不可外推为总体质量。
- token 为假适配器按字符长度规则生成的合成值，usage_type 由引擎按“是否返回 usage”判定，均不代表真实模型计费。
- 若步骤用量未知，记录会显式标记 `usage_type=unknown`（并计入“未知用量step数”），不会把 0 当作已统计的真实成本；本次假适配器所有步骤均返回 usage。
- 耗时在毫秒级，受进程调度影响大，仅证明计时字段可用，不可外推到真实模型延迟。

## C. 真实模型实验

**本基线脚本不运行真实模型（避免自动产生费用）。** 真实模型实验已由独立的受控运行完成：

- 数据：`docs\real_experiment_results.json`（生成时间 2026-10-24T17:32:30+08:00，experiment_id `experiment-57426f096f7c`）
- 适配器：mode=`real`，model=`openai/gpt-4o-mini`；评分：mode=`deterministic`（确定性 rubric，未跑真实 LLM judge）

| 配置 | 完成 | 通过 | pass_rate_all_cases | total_tokens | 总耗时(s) | trace_id 数 |
| --- | --- | --- | --- | --- | --- | --- |
| single | 10/10 | 6/10 | 0.6 | 1358 | 23.0369 | 10 |
| sequential | 10/10 | 5/10 | 0.5 | 6454 | 61.3496 | 10 |
| parallel | 10/10 | 8/10 | 0.8 | 3546 | 31.3798 | 10 |

- 逐 case 结果与解读见 `docs/EXPERIMENTS_REPORT.md` C1；样本仅 10 个 case，不能外推总体质量或证明多 Agent 更优。

**基线脚本内状态：未运行（status=`not_run_in_baseline`）。**

原因：本次基线按设计只运行确定性假适配器；真实模型路径需要人工显式开启，基线脚本不会自动调用任何付费模型。

当前开关检查：`AGENTFLOW_EXPERIMENT_REAL` = `未设置（默认关闭）`；`AGENTFLOW_EXPERIMENT_LLM_JUDGE` = `未设置（默认关闭）`。密钥只检查是否存在，不读取、不记录、不打印具体值。

预计样本（仅按固定数据集计算，不代表成本）：10 个 case × 3 个配置 = **30 次执行**；若启用 LLM judge，额外 30 次评审调用。
预计样本仅按固定数据集与配置计算；真实耗时/成本未知，不编造成本数字。

启用条件：
1. 设置 AGENTFLOW_EXPERIMENT_REAL=1
2. 命令行显式加 --real
3. 选择 provider：AGENTFLOW_EXPERIMENT_PROVIDER（默认 openai）
4. 对应 provider 的密钥环境变量存在（只检查是否存在，不打印值）
5. 指定模型：--real-model 或 AGENTFLOW_EXPERIMENT_MODEL
6. 若要 --judge llm：额外设置 AGENTFLOW_EXPERIMENT_LLM_JUDGE=1（额外评审调用会产生费用）
7. 若要记录 trace_id：配置 Langfuse 并显式加 --tracing

启用步骤（示例，密钥请通过环境变量提供，不要写进仓库）：

```bash
export AGENTFLOW_EXPERIMENT_REAL=1  # Windows PowerShell: $env:AGENTFLOW_EXPERIMENT_REAL='1'
export AGENTFLOW_EXPERIMENT_PROVIDER=openai  # 或 deepseek / anthropic / openrouter
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

> C 节当前没有任何数字。真实模型跑完后需人工审阅结果并单独补充本节，禁止用 B 节假模型数字替代真实模型质量/成本结论。

## 复现与相关文件

- 本报告：`docs/BASELINE_REPORT.md`
- 原始结果 JSON：`docs/baseline_results.json`
- 实验数据与配置：`experiments/`（dataset / expected_answers / configs，各自带版本号）
- 重跑基线：`cd backend && python scripts/run_baseline.py`
- 单独跑某配置：`cd backend && python scripts/run_experiment.py --config single|sequential|parallel`

## 未运行 / 未验证项

- 真实模型实验未运行：没有任何真实模型质量、延迟或成本数据；C 节只是受控执行入口。
- 假适配器输出为人工编写的脚本文本，B 节质量数字只能证明评分/执行/记录链路，不能代表真实模型质量。
- 评分器为 rubric v2（关键词/短语 + critical 规则），无法评判语义等价、推理过程正确性等；存在误判可能。
- 固定数据集只有 10 个 case，不具统计代表性；结论不可外推到其他任务。
- 耗时为本机毫秒级调度结果，不能外推为真实模型延迟；token 为假适配器合成值。
- 本次未开启 Langfuse 追踪，trace_id 全为 null；字段与映射逻辑就绪，但尚未产生真实 trace。
- 本轮未覆盖并发/多进程/真实网络故障等场景，成功率不代表生产环境可靠性；后端 v3 的 attempts/error_type 字段已记录，但真实重试/超时未被触发。

