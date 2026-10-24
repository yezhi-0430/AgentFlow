# Harness²-lite 设计与预估清单

> 状态：已实施并验证（2026-10-24）。实际结果见
> [HARNESS2_LITE_REPORT.md](HARNESS2_LITE_REPORT.md)、[HARNESS2_COMPARISON.md](HARNESS2_COMPARISON.md)、
> [HARNESS2_REAL_COMPARISON.md](HARNESS2_REAL_COMPARISON.md)。
> **不整体接入 Harness² 框架，不实现自动修改并发布工作流。**
> 参考：[google-research/harness2](https://github.com/google-research/harness2)、[arXiv:2610.14224](https://arxiv.org/abs/2610.14224)。

## 已确认决策

1. 证据包**默认关闭**，实验用 `--evidence` 或环境变量显式开启；
2. 证据保留期 **90 天**（可配），仅本地存储；
3. 独立 judge 使用与实验相同的 OpenAI 兼容模型配置，**单轮预算 50 次调用**；
4. **本轮包含前端**实验对比面板与证据查看；
5. Phase A/B 验收后允许**一次**受控真实模型对比实验（预算受控）。


## 1. 要解决的问题

当前 AgentFlow 能回答"一次运行发生了什么"（run_id、步骤输入输出、错误、用量、trace_id），
但不能可靠回答"同一任务下哪套配置更好、凭什么"：

- 配置靠版本号和人工记录，无法快速确认两次运行是否真的同一配置；
- 只有最终分数，缺少可回查的脱敏请求/响应证据；
- 评分是确定性关键词 rubric，没有独立评分与一致率；
- 候选对比只存在于一次性 JSON/Markdown 报告，没有可查询、可复现的数据结构。

Harness²-lite 只做四件事：**指纹、证据、独立评分、候选对比**。不做递归自动改进。

## 2. 非目标

- 不接入 Harness² 的基准执行器（OpenCode/Codex、JobBench/LAB/WorkBuddy-Bench）；
- 不实现 Propose–Probe–Compose 自动改工作流，不自动发布；
- 不训练模型权重；
- 不重建 UI，只在现有运行历史/详情上增加最小实验视图。

## 3. 交付物设计

### D1. 配置指纹（Config Fingerprint）

为"候选配置"生成稳定、可复现的 ID：

```
fingerprint = sha256(canonical_json({
  dataset: {id, version},
  config: {pattern, agents:[{name, role, system_prompt, model, temperature, max_tokens}],
           steps:[{id, agent_name, input_from}], max_iterations},
  execution_policy: {step_timeout_seconds, max_attempts},
  scorer: {id, version},
  model_connection: {provider, model},   # 不含 base_url/密钥
}))[:16]
```

规则：

- 排序键后序列化，字典/列表顺序不影响结果；
- 密钥、base_url、host、时间戳、run_id 不参与；
- 修改提示词/模型参数/步骤会改变指纹；仅换密钥不改变；
- 展示完整 hash + 短码，报告与 UI 均显示。

验收：同配置重复生成稳定；提示词改 1 字变化；换密钥不变；reorder 不变。

### D2. 执行证据包（Evidence Bundle）

每个 case 落一份脱敏证据包（本地文件 + 索引）：

```
evidence/<experiment_id>/<candidate_id>/<case_id>.json
{
  "fingerprint", "experiment_id", "candidate_id", "case_id",
  "run_id", "trace_id", "dataset": {...}, "scorer": {...},
  "request": {"messages": [...], "model", "temperature", "max_tokens"},
  "response": {"content", "model", "finish_reason"},
  "usage": {"prompt_tokens","completion_tokens","total_tokens"}, "usage_type",
  "attempts", "error", "error_type", "started_at", "completed_at", "duration",
  "score": {...}, "judge": {...}
}
```

- 写入前复用/扩展 `redact_text` 脱敏：Key、Bearer、`*_KEY=`、连接配置；
- 单包上限（如 100KB）与文本截断；默认只存本地，不外发；
- 默认关闭，实验显式 `--evidence` 开启；`AGENTFLOW_EVIDENCE_DIR`、`AGENTFLOW_EVIDENCE_RETENTION_DAYS` 可配；
- 运行记录增加 `evidence_ref` 指针，UI 可按 run 打开。

验收：证据中无密钥；超限截断；保留期清理；关闭时零额外写入；缺失证据不影响运行。

### D3. 独立评分（Independent Judge）

- 在现有 `--judge deterministic|llm` 基础上，把 LLM judge 做成**独立评分器**：
  - 自己的模型、提示词、rubric 版本，不参与生成；
  - 显式门禁（`AGENTFLOW_EXPERIMENT_LLM_JUDGE=1` + CLI `--judge llm`）；
  - 预算上限（最大调用次数/失败即停），失败/缺失分别记录；
  - 与确定性 rubric 交叉校验，输出一致率（agreement）；
  - 人工抽查入口：对少量 case 记录人工评分，报告与 judge/rubric 的差异。
- 成本控制：默认不跑；真实 judge 只允许在受控实验中开启。

验收：judge 未开启时零调用；超预算停止并标记；失败/缺失分别统计；一致率计算可复现。

### D4. 候选对比（Candidate Comparison）

- 数据模型（推荐，避免大量改 UI）：
  - 新表 `experiment_candidates`：`candidate_id`、`experiment_id`、`name`、`fingerprint`、
    `config_json`（无密钥）、`created_at`；
  - `workflow_runs` 增加可空列：`experiment_id`、`candidate_id`、`case_id`、`fingerprint`、`evidence_ref`（schema v4）；
  - 实验元数据表或复用定义表：`experiments`（id、name、dataset_id/version、scorer_version、notes）。
- 实验运行器写出候选与每次运行关联；报告生成：
  - 候选总表：完成率、通过率（分母=全部 case）、平均分、token、耗时、失败类型分布；
  - case × 候选矩阵；证据/`trace_id` 链接；样本量与不确定性（如 Wilson 区间），明确不宣称总体质量；
  - 决策备注（adopt/reject）与复现命令。
- API（只读为主，避免重写调度）：`GET /api/experiments`、`GET /api/experiments/{id}`、
  `GET /api/experiments/{id}/report`、`GET /api/evidence/{run_id}`；
  `GET /api/runs?experiment_id=...&fingerprint=...` 过滤。
- 前端：新增“实验对比”面板（候选表/矩阵/证据抽屉/评分来源），运行详情增加指纹、trace、证据入口；保留现有布局。

验收：同一实验可按候选/指纹筛选；报告分母正确；证据与 trace 可跳转；重复运行结果可对账。

## 4. 技术改动清单

| 模块 | 改动 | 风险 |
| --- | --- | --- |
| `core/run.py` + `storage/*` | schema v4：runs 增加 experiment/candidate/case/fingerprint/evidence_ref；新表 candidates/experiments；迁移 | 中（迁移需可回退） |
| 新 `core/fingerprint.py` | 指纹生成/校验 | 低 |
| 新 `core/evidence.py` | 证据构造/脱敏/落盘/保留策略 | 中（隐私） |
| `core/auto_evaluate.py` + 新 judge 模块 | 独立 judge、预算、一致率 | 中（成本/偏差） |
| `scripts/run_experiment.py` | 候选定义、指纹、证据、judge、对比报告 | 中 |
| `api/routes/*` | 实验/证据只读接口与过滤 | 低 |
| `frontend/src` | 实验对比面板、证据抽屉、详情字段 | 中 |
| 测试/CI | 指纹稳定性、脱敏、保留、judge 门禁/预算、比较分母；CI 仍只用假 judge | 中 |

## 5. 工作量预估（1 名开发者，含测试与文档）

| 阶段 | 内容 | 预估 |
| --- | --- | --- |
| Phase A | 指纹 + schema v4/candidates + 证据包 + 测试 | **3–4 人日** |
| Phase B | 独立评分（含校准/预算/一致率）+ 对比报告 | **2–3 人日** |
| Phase C | API + 前端实验对比/证据查看 + 文档/CI/基线 | **2–3 人日** |
| 真实运行验证 | 受控真实模型 + judge 校准 + 人工抽查 | **0.5–1 人日 + 费用** |
| **合计** | | **8–11 人日**（可分 3 个批次交付） |

建议顺序：Phase A → 用假模型验收 → Phase B → 一次受控真实实验 → Phase C。
不建议一次性做完再验证。

## 6. 成本预估（真实运行）

- 单候选单轮：10 case × 1 次执行；按之前实测约 1,300–6,500 tokens/配置；
- 3 候选 × 10 case × 2 seeds ≈ 60 次执行 ≈ 3–5 万 tokens（gpt-4o-mini 量级）；
- 若加 LLM judge（每 case 一次）：额外 3–5 万 tokens；
- 按 gpt-4o-mini 价位估算，一轮完整真实对比为**几美分到十几美分**量级（以服务商实际定价为准）；
- 可先用 `--limit 3` 冒烟，再全量；所有真实运行显式开启、有预算上限。

## 7. 验收标准（全部满足才算完成）

1. 同配置指纹稳定，改提示词/参数指纹变化，换密钥指纹不变；
2. 证据包无密钥/连接配置，体积受限，保留策略生效，关闭时零写入；
3. 独立 judge 默认零调用、门禁可验证、预算可控、失败/缺失分别记录、与 rubric 一致率可复现；
4. 候选对比报告分母为全部 case，含样本量与不确定性说明，证据与 trace 可跳转；
5. 后端/前端测试全绿，基线重跑，文档更新；
6. 默认假模型路径不联网、不产生费用；真实实验单独受控执行。

## 8. 需要你决定的事项

1. 证据包默认关闭（推荐）还是实验默认开启？
2. 证据保留期（建议 30 或 90 天）与存储位置（仅本地）；
3. 独立 judge 用哪个模型、单人预算上限（如单轮 ≤ 50 次调用）；
4. 是否本轮就做前端面板，还是先 API + Markdown 报告、UI 延后；
5. Phase A/B 验收后是否允许一次真实模型对比实验（预算几美分到十几美分）。
