# Harness²-lite 候选对比报告

> 状态：由 fake 适配器实跑生成（不联网、无付费模型调用）；生成时间 2026-10-24T18:16:26+08:00；报告版本 1.0.0。
> 数字全部来自本次运行，可由文末命令复现；**假模型结果只证明机制，不代表真实模型质量**。

## 1. 实验元数据

| 字段 | 值 |
| --- | --- |
| experiment_id | harness2-c162f77534d2 |
| 实验名称 | Harness²-lite real controlled |
| 创建时间 | 2026-10-24T18:14:41+08:00 |
| 数据集 | agentflow-fixed-v2@2.0.0 |
| 数据文件 / case 数 | experiments/dataset_v2.json（本次 10 / 全量 10） |
| 配置版本 | 1.0.0 |
| 运行器 | run_experiment.py 2.1.0 |
| 适配器 | real / —；network=True，deterministic=False |
| 评分器 | deterministic-rubric-v2@2.0.0（deterministic-rubric-v2） |
| judge | mode=llm；network=True；独立 judge 启用=True；预算={"max_calls": 50, "used": 30, "remaining": 20} |
| tracing | enabled=True；trace_id 缺失记为 null，不伪造 |
| evidence | enabled=True；写入 30 份；清理 0 份；保留 90 天；目录由 AGENTFLOW_EVIDENCE_DIR 控制 |
| 数据库持久化 | persisted=True（experiments/candidates/runs 已关联） |

## 2. 候选对比表（通过率分母 = 全部 case）

| 候选 | candidate_id | 指纹(短) | 指纹(完整) | cases | completed | failed | passed | pass_rate_all_cases | mean_score | total_tokens | total_seconds | trace_id_present | failure_types |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| single | harness2-c162f77534d2-single | 3a59a82b | 3a59a82bcdc02935 | 10 | 10 | 0 | 9 | 90.0% | 0.9417 | 1322 | 23.4105 | 10 | 无 |
| sequential | harness2-c162f77534d2-sequential | 7a3e77f0 | 7a3e77f0c7b69b17 | 10 | 10 | 0 | 7 | 70.0% | 0.8583 | 6442 | 62.4282 | 10 | 无 |
| parallel | harness2-c162f77534d2-parallel | 78d80c61 | 78d80c617ed72ace | 10 | 10 | 0 | 8 | 80.0% | 0.9333 | 3551 | 38.7670 | 10 | 无 |

> `mean_score` 为已评分 case 的平均分；`total_seconds` 为 runner 实测墙钟耗时之和；`failure_types` 统计执行失败/评分失败原因（来自本次运行的 case 记录）。

## 3. case × 候选矩阵

| case_id | single | sequential | parallel |
| --- | --- | --- | --- |
| case-001 | completed / score=1 / status=scored / judge=scored / trace=2e5fb98fb436 / evidence=yes | completed / score=1 / status=scored / judge=scored / trace=3e0f736d9fc8 / evidence=yes | completed / score=1 / status=scored / judge=scored / trace=9973a02a2665 / evidence=yes |
| case-002 | completed / score=1 / status=scored / judge=scored / trace=0101f13b99a2 / evidence=yes | completed / score=1 / status=scored / judge=scored / trace=d031fcf219d4 / evidence=yes | completed / score=1 / status=scored / judge=scored / trace=cf12f9062204 / evidence=yes |
| case-003 | completed / score=1 / status=scored / judge=scored / trace=5db34a175b0c / evidence=yes | completed / score=1 / status=scored / judge=scored / trace=1173a1368760 / evidence=yes | completed / score=1 / status=scored / judge=scored / trace=bb1176d703fe / evidence=yes |
| case-004 | completed / score=0.75 / status=scored / judge=scored / trace=e2a9e858cabd / evidence=yes | completed / score=0.75 / status=scored / judge=scored / trace=920e2328f1e2 / evidence=yes | completed / score=0.6667 / status=scored / judge=scored / trace=b8587a026e4f / evidence=yes |
| case-005 | completed / score=1 / status=scored / judge=scored / trace=35bb730421fa / evidence=yes | completed / score=1 / status=scored / judge=scored / trace=c5722c0d16ce / evidence=yes | completed / score=1 / status=scored / judge=scored / trace=1634996a2f87 / evidence=yes |
| case-006 | completed / score=1 / status=scored / judge=scored / trace=add4115be324 / evidence=yes | completed / score=1 / status=scored / judge=scored / trace=8fc9485f7630 / evidence=yes | completed / score=1 / status=scored / judge=scored / trace=300c111c4ac2 / evidence=yes |
| case-007 | completed / score=1 / status=scored / judge=scored / trace=7c84df5d1e05 / evidence=yes | completed / score=1 / status=scored / judge=scored / trace=574bc1b63bf8 / evidence=yes | completed / score=1 / status=scored / judge=scored / trace=4041f2ea8793 / evidence=yes |
| case-008 | completed / score=1 / status=scored / judge=scored / trace=f3d6e09fc2a8 / evidence=yes | completed / score=0.5 / status=scored / judge=scored / trace=25e5912de956 / evidence=yes | completed / score=1 / status=scored / judge=scored / trace=3c8a2eaf0e67 / evidence=yes |
| case-009 | completed / score=0.6667 / status=scored / judge=scored / trace=30d6f390ea4c / evidence=yes | completed / score=0.333 / status=scored / judge=scored / trace=49b2a68ae5e4 / evidence=yes | completed / score=0.6667 / status=scored / judge=scored / trace=af548b146618 / evidence=yes |
| case-010 | completed / score=1 / status=scored / judge=scored / trace=7be7db276d88 / evidence=yes | completed / score=1 / status=scored / judge=scored / trace=c4a00a54dc9f / evidence=yes | completed / score=1 / status=scored / judge=scored / trace=da22df4da1c1 / evidence=yes |

> 单元格格式：`status / score / score_status / judge / trace / evidence / error`；`score` 为 0-1；`trace` 未开启追踪时为 `null`；`evidence` 默认关闭。

## 4. 评分状态分布（每个候选）

| 候选 | 指纹(完整) | score_status | judge_status | score_source |
| --- | --- | --- | --- | --- |
| single | 3a59a82bcdc02935 | scored×10 | scored×10 | deterministic |
| sequential | 7a3e77f0c7b69b17 | scored×10 | scored×10 | deterministic |
| parallel | 78d80c617ed72ace | scored×10 | scored×10 | deterministic |

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
- deterministic rubric 判为未通过的 case：case-004、case-008、case-009
- 未评分/评分错误/执行失败的 case：无
- 以上只是本次 fake 运行中确定性 rubric 的评分结果（含预先设计的错误回答），用于验证失败可被如实记录；不构成对候选优劣的判断。

## 7. 样本限制与不宣称结论

- 样本量：10 个固定 case × 3 个候选，单轮执行（无重复 seed、无统计显著性检验/置信区间）；结论仅描述本次运行，不外推总体质量。
- 适配器：fake 脚本化确定性假模型，回答是预置脚本文本；通过/失败只证明执行、评分、指纹、证据与报告机制可用，不代表任何真实模型的能力或质量。
- token：假适配器自报的确定性计数，仅用于验证计量链路，不代表真实 token/费用。
- 评分来源：确定性 rubric v2 归一化到 0-1；passed = score >= 阈值且 critical 条目全部命中；分母始终是全部 case（缺失评分、评分错误、执行失败均按未通过计入），不只统计成功案例。
- 独立 judge：本次 judge 模式为 llm；judge 失败/超预算/缺失分别记录，不会被计为通过，也不会改写 deterministic 分数。
- 证据：本报告证据开启状态为 True（默认关闭）；证据文件仅本地保存并按保留期清理。
- 追踪：tracing.enabled=True；未启用时 trace_id 为 null，不伪造。
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

JSON 数据：`docs/harness2_results.json`（`report` 段；源结果 sha256=a1cac92fbefcb2edda7ab839c1900769e636d5c8eb63e2e0677f68661ee6bf11）。
