# -*- coding: utf-8 -*-
"""
批量评估已有运行记录 —— 把评分写进 Langfuse 的"评分"页

数据来源是本地数据库（backend/agentflow_data.db）里的历史运行记录（final_result），
而不是 Langfuse 的 trace：Langfuse 5.x / v4 的公开读接口只返回 trace 结构，
不返回 input/output 文本，无法据此评估。

注意：
- 评分会挂在 trace_id = create_trace_id(seed=run_id) 上，与本次追踪修复后的真实 trace 一致；
- 追踪修复前的旧运行没有对应 trace，分数仍会写入，但 Langfuse 里可能找不到对应 trace；
- 重复执行会对同一次运行产生多条同名评分（Langfuse 不自动去重）。

用法：
    cd backend
    python scripts/evaluate_existing_runs.py --limit 5        # 先看看要评估多少条
    python scripts/evaluate_existing_runs.py --limit 5 --yes  # 真正调用评审模型并写入评分
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

# 允许直接 `python scripts/evaluate_existing_runs.py`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from agentflow.core.auto_evaluate import auto_evaluate_workflow
from agentflow.storage import RunRepository, get_db
from agentflow.tracing import LangfuseTracer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="批量评估历史运行并写入 Langfuse 评分")
    parser.add_argument("--limit", type=int, default=10, help="最多评估多少条运行（默认 10）")
    parser.add_argument("--yes", action="store_true", help="跳过确认，直接调用评审模型（会产生少量 token 费用）")
    return parser


async def run(args) -> int:
    tracer = LangfuseTracer(enabled=True)
    if not tracer.enabled or tracer.client is None:
        print("错误：Langfuse 追踪未启用。请检查 backend/.env 中的 LANGFUSE_* 与 ENABLE_LANGFUSE_TRACING。")
        return 1

    with get_db() as db:
        runs = RunRepository.list_runs(db, limit=args.limit)

    candidates = [r for r in runs if (r.final_result or "").strip()]
    skipped = len(runs) - len(candidates)

    print("=" * 66)
    print(f"读取到 {len(runs)} 条运行记录，其中 {len(candidates)} 条有最终输出可评估（跳过 {skipped} 条空输出）")
    print(f"评审模型: {os.getenv('EVAL_MODEL', 'openai/gpt-4o-mini')}  (base_url={os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1')})")
    print("=" * 66)

    if not candidates:
        print("没有可评估的运行。")
        return 0

    for i, candidate in enumerate(candidates, 1):
        trace_id = tracer.trace_id_for_run(candidate.run_id)
        print(f"[{i}/{len(candidates)}] run_id={candidate.run_id} trace_id={trace_id} status={candidate.status.value}")

    if not args.yes:
        try:
            answer = input("\n确认调用评审模型并写入评分？[y/N] ").strip().lower()
        except EOFError:
            # 非交互环境（管道/CI）下默认取消，避免误产生费用
            answer = ""
        if answer not in ("y", "yes"):
            print("已取消（非交互环境请加 --yes）。")
            return 0

    evaluated = 0
    failed = 0
    print()
    for i, candidate in enumerate(candidates, 1):
        print(f"[{i}/{len(candidates)}] 评估 run_id={candidate.run_id} ...")
        outcome = await auto_evaluate_workflow(
            tracer,
            candidate,
            {"result": {"final_result": candidate.final_result}},
        )
        if outcome:
            evaluated += 1
        else:
            failed += 1

    tracer.flush()

    print("\n" + "=" * 66)
    print(f"完成：成功写入 {evaluated} 条评分，跳过/失败 {failed} 条。")
    print("打开 Langfuse →「评分」即可看到；也可以在「追踪」打开对应 trace 查看挂载的评分。")
    print(f"地址: {os.getenv('LANGFUSE_HOST', 'https://cloud.langfuse.com')}")
    return 0


def main() -> int:
    args = build_parser().parse_args()

    required = ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "OPENAI_API_KEY"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        print(f"错误：缺少环境变量: {', '.join(missing)}（请在 backend/.env 中配置）")
        return 1

    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
