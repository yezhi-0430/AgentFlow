"""
Langfuse 集成测试
"""
import pytest
import os
from unittest.mock import Mock, patch

from agentflow.core.workflow import WorkflowExecutor, WorkflowConfig, WorkflowPattern, WorkflowStep
from agentflow.core.agent import Agent, AgentConfig


@pytest.fixture
def mock_agent():
    """创建模拟 Agent"""
    agent = Mock(spec=Agent)
    agent.name = "test_agent"
    agent.config = AgentConfig(
        name="test_agent",
        role="worker",
        model="fake-model",
        system_prompt="You are a test agent.",
    )

    async def mock_process(message):
        response = Mock()
        response.id = "resp-1"
        response.content = "test result"
        response.metadata = {"usage": {"total_tokens": 10}}
        return response

    agent.process = mock_process
    agent.clear_memory = Mock()

    return agent


@pytest.fixture
def workflow_config():
    """创建工作流配置"""
    return WorkflowConfig(
        name="test_workflow",
        pattern=WorkflowPattern.SEQUENTIAL,
        steps=[
            WorkflowStep(id="step-1", agent_name="test_agent"),
        ],
        agents=[
            AgentConfig(
                name="test_agent",
                role="worker",
                model="fake-model",
                system_prompt="You are a test agent.",
            ),
        ],
    )


@pytest.mark.asyncio
async def test_langfuse_tracing_disabled_by_default(workflow_config, mock_agent):
    """测试 Langfuse 追踪默认关闭"""
    executor = WorkflowExecutor(workflow_config, enable_tracing=False)
    executor.register_agent(mock_agent)

    # 追踪应该是关闭的
    assert executor.enable_tracing is False

    # 执行不应该报错
    result = await executor.execute("test task")
    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_langfuse_tracing_graceful_degradation(workflow_config, mock_agent):
    """测试 Langfuse 追踪优雅降级（无配置时）"""
    # 清除环境变量
    env_backup = {
        "LANGFUSE_PUBLIC_KEY": os.environ.pop("LANGFUSE_PUBLIC_KEY", None),
        "LANGFUSE_SECRET_KEY": os.environ.pop("LANGFUSE_SECRET_KEY", None),
    }

    try:
        # 尝试启用追踪但无配置
        executor = WorkflowExecutor(workflow_config, enable_tracing=True)
        executor.register_agent(mock_agent)

        # 应该自动关闭追踪
        # 执行不应该报错
        result = await executor.execute("test task")
        assert result["status"] == "completed"

    finally:
        # 恢复环境变量
        for key, value in env_backup.items():
            if value is not None:
                os.environ[key] = value


@pytest.mark.asyncio
async def test_langfuse_tracing_with_mock(workflow_config, mock_agent):
    """测试 Langfuse 追踪（使用 mock）"""
    # 注意：workflow.py 通过 `from agentflow.tracing import LangfuseTracer` 绑定了符号，
    # 所以必须 patch workflow 模块内的名字，patch tracing 模块里的类不会生效。
    with patch("agentflow.core.workflow.LangfuseTracer") as MockTracer:
        # 设置 mock 追踪器
        mock_tracer = Mock()
        mock_trace = Mock()
        mock_span = Mock()

        mock_tracer.trace_workflow.return_value = mock_trace
        mock_tracer.trace_step.return_value = mock_span
        mock_tracer.update_step.return_value = None
        mock_tracer.end_trace.return_value = None
        mock_tracer.flush.return_value = None

        MockTracer.return_value = mock_tracer

        # 创建启用追踪的执行器
        executor = WorkflowExecutor(workflow_config, enable_tracing=True)
        executor.register_agent(mock_agent)

        # 执行工作流
        result = await executor.execute("test task")

        # 验证追踪调用
        assert result["status"] == "completed"
        mock_tracer.trace_workflow.assert_called_once()
        mock_tracer.trace_step.assert_called_once()
        mock_tracer.update_step.assert_called_once()
        mock_tracer.end_trace.assert_called_once()
        mock_tracer.flush.assert_called_once()


@pytest.mark.asyncio
async def test_langfuse_records_step_error(workflow_config):
    """测试 Langfuse 记录步骤错误"""
    # 创建会失败的 Agent
    error_agent = Mock(spec=Agent)
    error_agent.name = "test_agent"
    error_agent.config = AgentConfig(
        name="test_agent",
        role="worker",
        model="fake",
        system_prompt="You are a test agent.",
    )

    async def mock_error_process(message):
        response = Mock()
        response.id = "resp-error"
        response.content = "Error occurred"
        response.metadata = {"error": True, "error_message": "Test error"}
        return response

    error_agent.process = mock_error_process
    error_agent.clear_memory = Mock()

    with patch("agentflow.core.workflow.LangfuseTracer") as MockTracer:
        mock_tracer = Mock()
        mock_trace = Mock()
        mock_span = Mock()

        mock_tracer.trace_workflow.return_value = mock_trace
        mock_tracer.trace_step.return_value = mock_span
        mock_tracer.update_step.return_value = None
        mock_tracer.end_trace.return_value = None
        mock_tracer.flush.return_value = None

        MockTracer.return_value = mock_tracer

        executor = WorkflowExecutor(workflow_config, enable_tracing=True)
        executor.register_agent(error_agent)

        # 执行会失败的工作流
        result = await executor.execute("test task")

        # 验证追踪记录了错误
        assert result["status"] == "failed"

        # 检查 update_step 被调用时带有 error 参数
        update_calls = mock_tracer.update_step.call_args_list
        assert len(update_calls) > 0

        # 检查最后一次调用是否包含错误
        last_call = update_calls[-1]
        assert "error" in last_call.kwargs or (len(last_call.args) > 0 and "error" in str(last_call))


@pytest.mark.asyncio
async def test_langfuse_records_usage(workflow_config, mock_agent):
    """测试 Langfuse 记录用量信息"""
    with patch("agentflow.core.workflow.LangfuseTracer") as MockTracer:
        mock_tracer = Mock()
        mock_trace = Mock()
        mock_span = Mock()

        mock_tracer.trace_workflow.return_value = mock_trace
        mock_tracer.trace_step.return_value = mock_span

        # 捕获 update_step 调用
        update_calls = []
        def capture_update(*args, **kwargs):
            update_calls.append(kwargs)

        mock_tracer.update_step = capture_update
        mock_tracer.end_trace.return_value = None
        mock_tracer.flush.return_value = None

        MockTracer.return_value = mock_tracer

        executor = WorkflowExecutor(workflow_config, enable_tracing=True)
        executor.register_agent(mock_agent)

        result = await executor.execute("test task")

        # 验证用量被记录
        assert result["status"] == "completed"
        assert len(update_calls) > 0

        # 检查是否记录了 usage
        usage_recorded = any("usage" in call for call in update_calls)
        assert usage_recorded, "Usage should be recorded in Langfuse"
