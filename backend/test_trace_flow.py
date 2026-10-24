# -*- coding: utf-8 -*-
"""
完整测试 Langfuse 追踪流程（手动脚本）

说明：只想确认"追踪链路是否真的通"时，请优先运行
    python scripts/verify_langfuse_tracing.py
它会真的把数据推到服务端并回查校验。

本脚本保留为最小示例：创建 trace -> 创建步骤 span -> 更新 -> 结束 trace -> flush。
注意 Langfuse 5.x 中"根 span 必须 end 才会导出"，因此 end_trace 不能省略。
"""
import sys

sys.path.insert(0, ".")

from dotenv import load_dotenv

load_dotenv()

import os

print("=" * 60)
print("完整追踪流程测试")
print("=" * 60)

print("\n1. 环境变量:")
print(f"   ENABLE_LANGFUSE_TRACING: {os.getenv('ENABLE_LANGFUSE_TRACING')}")
print(f"   LANGFUSE_PUBLIC_KEY: {(os.getenv('LANGFUSE_PUBLIC_KEY') or 'None')[:20]}...")
print(f"   LANGFUSE_SECRET_KEY: {(os.getenv('LANGFUSE_SECRET_KEY') or 'None')[:20]}...")

from agentflow.tracing import LangfuseTracer

print("\n2. 初始化追踪器:")
tracer = LangfuseTracer(enabled=True)
print(f"   tracer.enabled: {tracer.enabled}")
print(f"   tracer.client: {tracer.client}")

print("\n3. 创建 trace:")
trace = tracer.trace_workflow(
    workflow_id="test-workflow",
    run_id="test-run-123",
    name="测试工作流",
    metadata={"test": True},
)
print(f"   trace 创建: {trace}")
print(f"   trace_id: {getattr(trace, 'trace_id', None)}（由 run_id 稳定推导）")

print("\n4. 创建 span:")
span = tracer.trace_step(
    trace=trace,
    step_id="step-1",
    agent_name="test_agent",
    input_text="测试输入",
    metadata={"agent_model": "fake-model"},
)
print(f"   span 创建: {span}")

print("\n5. 更新 span（update + end 都会执行）:")
tracer.update_step(
    span=span,
    output="测试输出",
    usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
)
print("   span 更新完成")

print("\n6. 结束 trace 并刷新:")
tracer.end_trace(trace, output={"final": "测试输出"})
tracer.flush()
print("   刷新完成")

print("\n" + "=" * 60)
print("测试完成！请在 Langfuse 中按 trace_id 查看。")
print("更进一步：python scripts/verify_langfuse_tracing.py")
print("=" * 60)
