"""诊断脚本 - 检查完整追踪链路"""
import sys
sys.path.insert(0, '.')

print("开始诊断...")
print("=" * 60)

# 步骤1：加载环境变量
from dotenv import load_dotenv
load_dotenv()

import os
print(f"1. ENABLE_LANGFUSE_TRACING = {os.getenv('ENABLE_LANGFUSE_TRACING')}")

# 步骤2：检查路由函数
from agentflow.api.routes.workflow import _is_tracing_enabled
print(f"2. _is_tracing_enabled() = {_is_tracing_enabled()}")

# 步骤3：检查 WorkflowExecutor 初始化
from agentflow.core.workflow import WorkflowExecutor, WorkflowConfig, WorkflowPattern, TRACING_AVAILABLE
print(f"3. TRACING_AVAILABLE = {TRACING_AVAILABLE}")

config = WorkflowConfig(name='test', pattern=WorkflowPattern.SEQUENTIAL, steps=[], agents=[])

print("\n创建 WorkflowExecutor (enable_tracing=True)...")
try:
    executor = WorkflowExecutor(config, enable_tracing=True)
    print(f"4. executor.enable_tracing = {executor.enable_tracing}")
    print(f"5. executor.tracer = {executor.tracer}")
    if executor.tracer:
        print(f"6. executor.tracer.enabled = {executor.tracer.enabled}")
        print(f"7. executor.tracer.client = {executor.tracer.client}")
except Exception as e:
    print(f"错误: {e}")
    import traceback
    traceback.print_exc()

print("=" * 60)
print("诊断完成")
