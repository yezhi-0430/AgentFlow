# 提交分组建议（未执行）

当前工作区包含第一批、第二批与 Harness²-lite 的全部未提交改动。建议按以下 4 组提交，
保证每组可独立构建/测试；**不要**提交 `.env`、`backend/evidence/`、`*.db`、`dist/`
（这些已在 `.gitignore` 中）。

> 本文件只是建议，未执行 `git add/commit`。提交前先 `git status --short` 人工复核。

## 组 1：后端运行平台与追踪基础

```bash
git add backend/agentflow backend/tests backend/pyproject.toml backend/.env.example README_LANGFUSE.md
git add backend/diagnose.py backend/test_langfuse_manual.py backend/test_trace_flow.py
git commit -m "feat(backend): durable run records, Langfuse tracing and score pipeline"
```

内容：run schema v3/v4、存储与迁移、执行/停止语义、追踪与脱敏、自动评分、定义持久化、
experiments/candidates 数据模型与 API、对应测试。

## 组 2：实验 runner 与报告资产

```bash
git add backend/scripts experiments docs/EXPERIMENTS_REPORT.md docs/experiments_results.json \
  docs/BASELINE_REPORT.md docs/baseline_results.json \
  docs/HARNESS2_COMPARISON.md docs/harness2_results.json \
  docs/HARNESS2_REAL_COMPARISON.md docs/real_harness2_results.json \
  docs/images/harness2-experiment-panel.png docs/images/harness2-evidence-drawer.png
git commit -m "feat(experiments): deterministic eval, real comparison and harness2 reports"
```

注意：真实实验 JSON 含模型输出（无密钥）；如不希望入库，可将 `docs/real_harness2_results.json`
与 `docs/HARNESS2_REAL_COMPARISON.md` 移到本地不提交。

## 组 3：前端

```bash
git add frontend/src frontend/tests
git commit -m "feat(frontend): run history, workflow library and harness2 experiment panel"
```

## 组 4：文档、CI 与收尾

```bash
git add README.md docs/development.md docs/limitations.md docs/BATCH_1_OPTIMIZATION.md \
  docs/BATCH_2_REPORT.md docs/BATCH_2B_REPORT.md docs/HARNESS2_LITE_REPORT.md \
  docs/HARNESS2_LITE_PLAN.md docs/COMMIT_PLAN.md .github/workflows/ci.yml .gitignore
git commit -m "docs: update capabilities, limitations, baselines and CI"
```

## 提交前检查

```bash
git status --short
git diff --cached --stat
python scripts/check_repo.py    # 需要先 git add，检查已跟踪文件
```

如果只想提交一部分，可先执行组 1/3/4，实验数据（组 2 的大 JSON）留到确认后再提交。
