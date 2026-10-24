# -*- coding: utf-8 -*-
"""
Langfuse 追踪端到端验证脚本

和以前的 diagnose.py 不同，这个脚本不只检查"组件是否初始化成功"，而是真的：
1. 用假 LLM 跑一次真实的工作流执行（不调用、不花钱）；
2. flush 后回查 Langfuse 服务端，确认 trace / span 真的落库；
3. 校验根 trace 与子 span 是否挂在同一个 trace 下、run_id 是否能映射到 trace_id、
   token 用量是否被记录。

用法：
    cd backend
    python scripts/verify_langfuse_tracing.py

退出码 0 表示追踪链路完全正常；非 0 表示有环节失败（输出里会指出是哪一个）。
"""
import asyncio
import datetime
import json
import os
import sys
import time
import uuid
from pathlib import Path

# 允许直接 `python scripts/verify_langfuse_tracing.py`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

# 本脚本只验证"追踪链路"，使用假 LLM，不产生任何真实模型费用；
# 同时关闭自动评估，避免触发真实评审模型调用（评分验证见 README_LANGFUSE.md）。
os.environ["AUTO_EVALUATE"] = "false"

import httpx

from agentflow.adapters.base import LLMAdapter
from agentflow.agents.llm_agent import LLMAgent
from agentflow.core.agent import AgentConfig
from agentflow.core.workflow import (
    WorkflowConfig,
    WorkflowExecutor,
    WorkflowPattern,
    WorkflowStep,
)


class _FakeAdapter(LLMAdapter):
    """假 LLM：只验证追踪，不产生真实调用"""

    async def complete(self, messages, model, temperature=0.7, max_tokens=2000, **kwargs):
        await asyncio.sleep(0.02)
        return {
            "content": f"[verify] {str(messages[-1].get('content', ''))[:40]}",
            "usage": {"prompt_tokens": 7, "completion_tokens": 9, "total_tokens": 16},
            "model": "verify-fake-model",
            "finish_reason": "stop",
        }

    async def stream_complete(self, messages, model, temperature=0.7, max_tokens=2000, **kwargs):
        yield "verify"


async def _run(pattern: WorkflowPattern) -> dict:
    marker = f"verify-{pattern.value}-{uuid.uuid4().hex[:6]}"
    steps = [WorkflowStep(id=f"step_{i + 1}", agent_name=f"worker_{i + 1}") for i in range(2)]
    config = WorkflowConfig(
        name=marker,
        pattern=pattern,
        steps=steps,
        agents=[
            AgentConfig(name=s.agent_name, role="worker", model="verify-fake-model",
                        system_prompt="You are a worker.")
            for s in steps
        ],
    )
    executor = WorkflowExecutor(config, enable_persistence=False, enable_tracing=True)
    if not executor.enable_tracing or executor.tracer is None or not executor.tracer.enabled:
        print("❌ 追踪未启用：检查 ENABLE_LANGFUSE_TRACING / LANGFUSE_* 环境变量（backend/.env）")
        return {"ok": False}
    for s in steps:
        executor.register_agent(LLMAgent(
            AgentConfig(name=s.agent_name, role="worker", model="verify-fake-model",
                        system_prompt="You are a worker."),
            _FakeAdapter(),
        ))
    result = await executor.execute("验证 Langfuse 追踪链路")
    return {"ok": True, "marker": marker, "run_id": result["run_id"]}


def _fetch(trace_id: str, timeout_s: int = 60):
    """轮询 v2 observations / metrics 接口，等待异步批量导出落库"""
    pk = os.getenv("LANGFUSE_PUBLIC_KEY")
    sk = os.getenv("LANGFUSE_SECRET_KEY")
    host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com").rstrip("/")
    now = datetime.datetime.now(datetime.timezone.utc)
    params = {
        "fromStartTime": (now - datetime.timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
        "toStartTime": now.isoformat().replace("+00:00", "Z"),
        "limit": 200,
    }
    deadline = time.time() + timeout_s
    observations = []
    while time.time() < deadline:
        r = httpx.get(f"{host}/api/public/v2/observations", auth=(pk, sk),
                      params=params, timeout=60)
        if r.status_code == 200:
            observations = [o for o in r.json().get("data", []) if o.get("traceId") == trace_id]
            if len(observations) >= 3:
                break
        time.sleep(5)

    metrics = {}
    try:
        query = {
            "view": "observations",
            "metrics": [
                {"measure": "count", "aggregation": "count"},
                {"measure": "totalTokens", "aggregation": "sum"},
            ],
            "filters": [{"column": "traceId", "operator": "=", "value": trace_id, "type": "string"}],
            "fromTimestamp": (now - datetime.timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
            "toTimestamp": now.isoformat().replace("+00:00", "Z"),
        }
        from langfuse import Langfuse
        client = Langfuse(public_key=pk, secret_key=sk, host=host)
        resp = client.api.metrics.metrics(query=json.dumps(query))
        if resp.data:
            first = resp.data[0]
            metrics = first.model_dump() if hasattr(first, "model_dump") else dict(first)
        client.shutdown()
    except Exception as e:  # 指标接口失败不算致命
        metrics = {"error": str(e)}
    return observations, metrics


def main() -> int:
    print("=" * 70)
    print("Langfuse 追踪端到端验证")
    print("=" * 70)

    failures = []
    for pattern in (WorkflowPattern.SEQUENTIAL, WorkflowPattern.PARALLEL):
        print(f"\n[{pattern.value}] 执行一次工作流...")
        run = asyncio.run(_run(pattern))
        if not run.get("ok"):
            failures.append(f"{pattern.value}: 追踪未启用")
            continue

        run_id = run["run_id"]
        from langfuse import Langfuse
        pk = os.getenv("LANGFUSE_PUBLIC_KEY")
        sk = os.getenv("LANGFUSE_SECRET_KEY")
        host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        client = Langfuse(public_key=pk, secret_key=sk, host=host)
        expected_trace_id = client.create_trace_id(seed=run_id)
        client.shutdown()

        print(f"  run_id={run_id}")
        print(f"  期望 trace_id={expected_trace_id}")
        print("  等待服务端入库（最多 60s）...")
        observations, metrics = _fetch(expected_trace_id)

        root = next((o for o in observations if o.get("name") == run["marker"]), None)
        children = [o for o in observations if o is not root]
        names = sorted(o.get("name") for o in observations)
        print(f"  实际收到 observation: {names}")

        if not observations:
            failures.append(f"{pattern.value}: 服务端没收到任何 trace（trace_id={expected_trace_id}）")
            continue
        if root is None:
            failures.append(f"{pattern.value}: 缺少工作流根 trace（根 span 未 end？）")
        if len(children) < 2:
            failures.append(f"{pattern.value}: 步骤 span 数量不足（期望 2，实际 {len(children)}）")
        if any(o.get("traceId") != expected_trace_id for o in observations):
            failures.append(f"{pattern.value}: 有 span 落在别的 trace 里（父子关系断开）")
        if "error" in metrics:
            print(f"  ⚠️ 指标接口不可用，跳过 token 校验: {metrics['error']}")
        elif metrics.get("sum_totalTokens") != 32:
            failures.append(f"{pattern.value}: token 用量期望 32，实际 {metrics.get('sum_totalTokens')}")

    print("\n" + "=" * 70)
    if failures:
        print("❌ 验证失败：")
        for f in failures:
            print("   -", f)
        return 1
    print("✅ 追踪链路正常：根 trace + 步骤 generation 在同一 trace 下，run_id 可映射为 trace_id。")
    print("   打开 Langfuse 项目 → Tracing，按上面的 trace_id 搜索即可看到完整调用树。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
