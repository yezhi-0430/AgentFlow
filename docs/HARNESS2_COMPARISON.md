# Harness²-lite 候选对比报告

> 状态：由 fake 适配器实跑生成（不联网、无付费模型调用）；生成时间 2026-10-24T18:10:23+08:00；报告版本 1.0.0。
> 数字全部来自本次运行，可由文末命令复现；**假模型结果只证明机制，不代表真实模型质量**。

## 1. 实验元数据

| 字段 | 值 |
| --- | --- |
| experiment_id | harness2-3e4f4da4332a |
| 实验名称 | Harness²-lite fake baseline |
| 创建时间 | 2026-10-24T18:10:16+08:00 |
| 数据集 | agentflow-fixed-v2@2.0.0 |
| 数据文件 / case 数 | experiments/dataset_v2.json（本次 10 / 全量 10） |
| 配置版本 | 1.0.0 |
| 运行器 | run_experiment.py 2.1.0 |
| 适配器 | fake / scripted-fake-v1；network=False，deterministic=True |
| 评分器 | deterministic-rubric-v2@2.0.0（deterministic-rubric-v2） |
| judge | mode=deterministic；network=False；独立 judge 启用=False；预算={"max_calls": 50, "used": 0, "remaining": 50} |
| tracing | enabled=False；trace_id 缺失记为 null，不伪造 |
| evidence | enabled=True；写入 30 份；清理 0 份；保留 90 天；目录由 AGENTFLOW_EVIDENCE_DIR 控制 |
| 数据库持久化 | persisted=True（experiments/candidates/runs 已关联） |

## 2. 候选对比表（通过率分母 = 全部 case）

| 候选 | candidate_id | 指纹(短) | 指纹(完整) | cases | completed | failed | passed | pass_rate_all_cases | mean_score | total_tokens | total_seconds | trace_id_present | failure_types |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| single | harness2-3e4f4da4332a-single | 3141640d | 3141640de8c5b3ae | 10 | 10 | 0 | 8 | 80.0% | 0.8333 | 304 | 0.9359 | 0 | 无 |
| sequential | harness2-3e4f4da4332a-sequential | e58ce8db | e58ce8dbbeac385c | 10 | 10 | 0 | 8 | 80.0% | 0.8333 | 618 | 0.8579 | 0 | 无 |
| parallel | harness2-3e4f4da4332a-parallel | 07296a8c | 07296a8c12c7533a | 10 | 10 | 0 | 8 | 80.0% | 0.8333 | 608 | 0.6234 | 0 | 无 |

> `mean_score` 为已评分 case 的平均分；`total_seconds` 为 runner 实测墙钟耗时之和；`failure_types` 统计执行失败/评分失败原因（来自本次运行的 case 记录）。

## 3. case × 候选矩阵

| case_id | single | sequential | parallel |
| --- | --- | --- | --- |
| case-001 | completed / score=1 / status=scored / trace=null / evidence=yes | completed / score=1 / status=scored / trace=null / evidence=yes | completed / score=1 / status=scored / trace=null / evidence=yes |
| case-002 | completed / score=1 / status=scored / trace=null / evidence=yes | completed / score=1 / status=scored / trace=null / evidence=yes | completed / score=1 / status=scored / trace=null / evidence=yes |
| case-003 | completed / score=0.3333 / status=scored / trace=null / evidence=yes | completed / score=0.3333 / status=scored / trace=null / evidence=yes | completed / score=0.3333 / status=scored / trace=null / evidence=yes |
| case-004 | completed / score=1 / status=scored / trace=null / evidence=yes | completed / score=1 / status=scored / trace=null / evidence=yes | completed / score=1 / status=scored / trace=null / evidence=yes |
| case-005 | completed / score=1 / status=scored / trace=null / evidence=yes | completed / score=1 / status=scored / trace=null / evidence=yes | completed / score=1 / status=scored / trace=null / evidence=yes |
| case-006 | completed / score=1 / status=scored / trace=null / evidence=yes | completed / score=1 / status=scored / trace=null / evidence=yes | completed / score=1 / status=scored / trace=null / evidence=yes |
| case-007 | completed / score=1 / status=scored / trace=null / evidence=yes | completed / score=1 / status=scored / trace=null / evidence=yes | completed / score=1 / status=scored / trace=null / evidence=yes |
| case-008 | completed / score=1 / status=scored / trace=null / evidence=yes | completed / score=1 / status=scored / trace=null / evidence=yes | completed / score=1 / status=scored / trace=null / evidence=yes |
| case-009 | completed / score=0 / status=scored / trace=null / evidence=yes | completed / score=0 / status=scored / trace=null / evidence=yes | completed / score=0 / status=scored / trace=null / evidence=yes |
| case-010 | completed / score=1 / status=scored / trace=null / evidence=yes | completed / score=1 / status=scored / trace=null / evidence=yes | completed / score=1 / status=scored / trace=null / evidence=yes |

> 单元格格式：`status / score / score_status / judge / trace / evidence / error`；`score` 为 0-1；`trace` 未开启追踪时为 `null`；`evidence` 默认关闭。

## 4. 评分状态分布（每个候选）

| 候选 | 指纹(完整) | score_status | judge_status | score_source |
| --- | --- | --- | --- | --- |
| single | 3141640de8c5b3ae | scored×10 | — | deterministic |
| sequential | e58ce8dbbeac385c | scored×10 | — | deterministic |
| parallel | 07296a8c12c7533a | scored×10 | — | deterministic |

## 5. 评分口径

- 主评分来源：deterministic-rubric-v2（0-1 归一化）
- 通过规则：score >= pass_threshold（默认 0.75）且所有 critical 条目命中
- 通过率分母：全部 case（len(case_matrix)）
- 累计通过率：passed / 全部 case
- 平均分：已评分 case 的平均分；全 case 平均分：已评分 case 分数之和 / 全部 case（未评分为 0）
- 耗时：runner 实测每个 case 的 elapsed_seconds 之和（墙钟时间）
- 独立 judge 是否用于 passed：False（否；judge 失败/超预算/缺失不会冒充通过）

## 6. 本次运行观察（仅机制验证）

- 所有候选是否全部完成全部 case：True
- deterministic rubric 判为未通过的 case：case-003、case-009
- 未评分/评分错误/执行失败的 case：无
- 以上只是本次 fake 运行中确定性 rubric 的评分结果（含预先设计的错误回答），用于验证失败可被如实记录；不构成对候选优劣的判断。

## 7. 样本限制与不宣称结论

- 样本量：10 个固定 case × 3 个候选，单轮执行（无重复 seed、无统计显著性检验/置信区间）；结论仅描述本次运行，不外推总体质量。
- 适配器：fake 脚本化确定性假模型，回答是预置脚本文本；通过/失败只证明执行、评分、指纹、证据与报告机制可用，不代表任何真实模型的能力或质量。
- token：假适配器自报的确定性计数，仅用于验证计量链路，不代表真实 token/费用。
- 评分来源：确定性 rubric v2 归一化到 0-1；passed = score >= 阈值且 critical 条目全部命中；分母始终是全部 case（缺失评分、评分错误、执行失败均按未通过计入），不只统计成功案例。
- 独立 judge：本次 judge 模式为 deterministic；judge 失败/超预算/缺失分别记录，不会被计为通过，也不会改写 deterministic 分数。
- 证据：本报告证据开启状态为 True（默认关闭）；证据文件仅本地保存并按保留期清理。
- 追踪：tracing.enabled=False；未启用时 trace_id 为 null，不伪造。
- 不宣称某个候选最优；真实模型对比必须 --real + 环境门禁 + 受控预算单独执行，本报告不含真实模型数据。

## 8. 复现命令

```powershell
# fake 全量运行 + 生成报告（离线、无费用）：
cd backend
python scripts/run_experiment.py --config all --experiment-name "Harness²-lite fake baseline" --evidence --output ../docs/harness2_results.json
cd ..
python experiments/build_harness2_report.py

# 真实模型（未执行；仅命令模板，需门禁/预算，由 Lead 受控执行）：
cd backend
python scripts/run_experiment.py --config all --real --real-model <model> --judge llm --judge-budget 50 --evidence --output ../docs/real_harness2_results.json
# 需 AGENTFLOW_EXPERIMENT_REAL=1（以及 --judge llm 时的 judge 门禁/密钥）；
# 由 Lead 受控执行并复核预算；本报告不含真实模型数据。
```

JSON 数据：`docs/harness2_results.json`（`report` 段；源结果 sha256=b7b0830ccd8714855c36abd5c7db64d0dcd3272825d2d209a0fc034612ad95d1）。
