"""
工作流运行机制回归测试 - 使用假适配器，不调用真实模型
"""
import pytest
import asyncio

from agentflow.core.workflow import WorkflowExecutor, WorkflowConfig, WorkflowPattern, WorkflowStep
from agentflow.core.agent import AgentConfig, AgentRole
from agentflow.core.run import RunStatus, UsageType
from agentflow.agents.llm_agent import LLMAgent


class FakeAdapter:
    """假适配器，返回可控结果"""

    def __init__(self, fail_on_step=None, response_prefix="processed"):
        self.fail_on_step = fail_on_step
        self.response_prefix = response_prefix
        self.call_count = 0

    async def complete(self, messages, model, **kwargs):
        self.call_count += 1

        # 检查是否应该失败
        if self.fail_on_step is not None and self.call_count == self.fail_on_step:
            raise RuntimeError("Simulated failure")

        # 提取最后一条用户消息
        user_message = messages[-1]["content"]

        return {
            "content": f"{self.response_prefix}: {user_message}",
            "model": model,
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
            "finish_reason": "stop",
        }


def create_test_workflow(agent_count=3, pattern=WorkflowPattern.SEQUENTIAL):
    """创建测试工作流"""
    agent_configs = []
    workflow_steps = []

    for i in range(agent_count):
        agent_config = AgentConfig(
            name=f"worker_{i+1}",
            role=AgentRole.WORKER,
            system_prompt=f"You are worker {i+1}.",
            model="test-model",
        )
        agent_configs.append(agent_config)

        if pattern == WorkflowPattern.SEQUENTIAL:
            step = WorkflowStep(
                id=f"step_{i+1}",
                agent_name=f"worker_{i+1}",
                input_from=f"step_{i}" if i > 0 else None,
            )
        else:  # PARALLEL
            step = WorkflowStep(
                id=f"step_{i+1}",
                agent_name=f"worker_{i+1}",
                input_from=None,
            )
        workflow_steps.append(step)

    workflow_config = WorkflowConfig(
        name="Test Workflow",
        pattern=pattern,
        steps=workflow_steps,
        agents=agent_configs,
    )

    return workflow_config


@pytest.mark.asyncio
async def test_sequential_workflow_with_run_id():
    """测试顺序工作流生成独立 run_id"""
    config = create_test_workflow(agent_count=2)
    executor = WorkflowExecutor(config)

    adapter = FakeAdapter()
    for agent_config in config.agents:
        agent = LLMAgent(agent_config, adapter)
        executor.register_agent(agent)

    result = await executor.execute("test task")

    assert result["status"] == "completed"
    assert "run_id" in result
    assert result["run_id"] in executor.runs

    run = executor.runs[result["run_id"]]
    assert run.workflow_id == executor.workflow_id
    assert run.task_input == "test task"
    assert run.status == RunStatus.COMPLETED
    assert len(run.step_results) == 2


@pytest.mark.asyncio
async def test_error_stops_sequential_execution():
    """测试顺序执行中错误停止后续步骤"""
    config = create_test_workflow(agent_count=3)
    executor = WorkflowExecutor(config)

    # 第二步失败
    adapter = FakeAdapter(fail_on_step=2)
    for agent_config in config.agents:
        agent = LLMAgent(agent_config, adapter)
        executor.register_agent(agent)

    # 执行不会抛出异常，但会标记为失败
    result = await executor.execute("test task")

    # 检查只执行了前两步
    assert adapter.call_count == 2

    # 检查运行记录
    run = executor.runs[result["run_id"]]
    assert run.status == RunStatus.FAILED
    assert len(run.step_results) == 2

    # 第一步成功
    assert run.step_results[0].status == RunStatus.COMPLETED
    assert run.step_results[0].error is None

    # 第二步失败
    assert run.step_results[1].status == RunStatus.FAILED
    assert run.step_results[1].error == "Simulated failure"


@pytest.mark.asyncio
async def test_message_not_duplicated_in_context():
    """测试消息不会重复进入上下文"""
    config = create_test_workflow(agent_count=2)
    executor = WorkflowExecutor(config)

    # 使用能够记录调用的适配器
    messages_received = []

    class TrackingAdapter(FakeAdapter):
        async def complete(self, messages, model, **kwargs):
            messages_received.append(messages)
            return await super().complete(messages, model, **kwargs)

    adapter = TrackingAdapter()
    for agent_config in config.agents:
        agent = LLMAgent(agent_config, adapter)
        executor.register_agent(agent)

    await executor.execute("initial task")

    # 第一个 agent 应该只收到系统提示和初始任务
    first_call = messages_received[0]
    assert len(first_call) == 2  # system + user message
    assert first_call[0]["role"] == "system"
    assert first_call[1]["role"] == "user"
    assert first_call[1]["content"] == "initial task"


@pytest.mark.asyncio
async def test_parallel_execution_records_all_steps():
    """测试并行执行记录所有步骤"""
    config = create_test_workflow(agent_count=3, pattern=WorkflowPattern.PARALLEL)
    executor = WorkflowExecutor(config)

    adapter = FakeAdapter()
    for agent_config in config.agents:
        agent = LLMAgent(agent_config, adapter)
        executor.register_agent(agent)

    result = await executor.execute("parallel task")

    assert result["status"] == "completed"

    run = executor.runs[result["run_id"]]
    assert len(run.step_results) == 3

    # 所有步骤都应该成功
    for step_result in run.step_results:
        assert step_result.status == RunStatus.COMPLETED
        assert step_result.input_message_id is not None
        assert step_result.output_message_id is not None
        assert step_result.duration is not None


@pytest.mark.asyncio
async def test_parallel_execution_handles_partial_failure():
    """测试并行执行处理部分失败"""
    config = create_test_workflow(agent_count=3, pattern=WorkflowPattern.PARALLEL)
    executor = WorkflowExecutor(config)

    # 让第二次调用失败
    adapter = FakeAdapter(fail_on_step=2)
    for agent_config in config.agents:
        agent = LLMAgent(agent_config, adapter)
        executor.register_agent(agent)

    result = await executor.execute("parallel task")

    # 部分完成
    run = executor.runs[result["run_id"]]
    assert run.status == RunStatus.PARTIAL

    # 检查结果
    completed = [r for r in run.step_results if r.status == RunStatus.COMPLETED]
    failed = [r for r in run.step_results if r.status == RunStatus.FAILED]

    assert len(completed) == 2  # 2个成功
    assert len(failed) == 1      # 1个失败

    # 失败的步骤应该有错误信息
    assert failed[0].error is not None


@pytest.mark.asyncio
async def test_stop_request_stops_execution():
    """测试停止请求阻止后续执行"""
    config = create_test_workflow(agent_count=3)
    executor = WorkflowExecutor(config)

    # 在第一步完成后停止
    class StoppingAdapter(FakeAdapter):
        def __init__(self, executor_ref):
            super().__init__()
            self.executor = executor_ref

        async def complete(self, messages, model, **kwargs):
            result = await super().complete(messages, model, **kwargs)
            if self.call_count == 1:
                # 第一步完成后请求停止
                self.executor.stop()
            return result

    adapter = StoppingAdapter(executor)
    for agent_config in config.agents:
        agent = LLMAgent(agent_config, adapter)
        executor.register_agent(agent)

    result = await executor.execute("test task")

    assert result["status"] == "stopped"

    run = executor.runs[result["run_id"]]
    assert run.status == RunStatus.STOPPED
    # 只执行了第一步
    assert len(run.step_results) == 1


@pytest.mark.asyncio
async def test_independent_runs_do_not_share_memory():
    """测试独立运行不共享记忆"""
    config = create_test_workflow(agent_count=1)
    executor = WorkflowExecutor(config)

    adapter = FakeAdapter()
    for agent_config in config.agents:
        agent = LLMAgent(agent_config, adapter)
        executor.register_agent(agent)

    # 第一次运行
    result1 = await executor.execute("first task")
    run1 = executor.runs[result1["run_id"]]

    # 第二次运行
    result2 = await executor.execute("second task")
    run2 = executor.runs[result2["run_id"]]

    # 两次运行应该有不同的 run_id
    assert result1["run_id"] != result2["run_id"]

    # Agent 的记忆应该在第二次运行前被清空
    # 检查 agent 当前记忆只包含第二次运行的消息
    agent = list(executor.agents.values())[0]
    # 第二次运行有 2 条消息（输入 + 输出）
    assert len(agent.memory) == 2


@pytest.mark.asyncio
async def test_usage_type_tracking():
    """测试用量类型追踪"""
    config = create_test_workflow(agent_count=2)
    executor = WorkflowExecutor(config)

    adapter = FakeAdapter()
    for agent_config in config.agents:
        agent = LLMAgent(agent_config, adapter)
        executor.register_agent(agent)

    result = await executor.execute("test task")

    run = executor.runs[result["run_id"]]

    for step_result in run.step_results:
        # 假适配器返回用量信息，应该标记为 ACTUAL
        assert step_result.usage_type == UsageType.ACTUAL
        assert step_result.usage is not None
        assert "total_tokens" in step_result.usage


@pytest.mark.asyncio
async def test_workflow_status_includes_run_info():
    """测试工作流状态包含运行信息"""
    config = create_test_workflow(agent_count=2)
    executor = WorkflowExecutor(config)

    adapter = FakeAdapter()
    for agent_config in config.agents:
        agent = LLMAgent(agent_config, adapter)
        executor.register_agent(agent)

    # 启动执行（在后台）
    task = asyncio.create_task(executor.execute("test task"))

    # 等待一点时间让执行开始
    await asyncio.sleep(0.01)

    # 获取状态
    status = executor.get_status()

    assert "current_run" in status
    assert status["current_run"]["status"] in ["pending", "running", "completed"]

    # 等待完成
    await task
