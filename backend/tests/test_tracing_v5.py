"""
Langfuse 5.x 追踪适配器回归测试（完全离线，不联网、不依赖真实密钥）

覆盖之前导致"追踪数据未发送"的四个根因：
1. 根 span 从未 end -> 从不导出
2. 子 span 未挂到根 trace -> 各自成为独立 trace
3. run_id 没有真正映射成 trace_id
4. 并行/辩论/投票模式完全没有创建 span
"""
import pytest
from unittest.mock import patch

from agentflow.tracing.langfuse import LangfuseTracer, _DummySpan, _DummyTrace


# ---------------------------------------------------------------- fake SDK
class FakeSpan:
    def __init__(self, name, trace_id="a" * 32, span_id="b" * 16):
        self.name = name
        self.trace_id = trace_id
        self.id = span_id
        self.updates = {}
        self.kwargs = {}
        self.children = []
        self.ended = False
        self.end_calls = 0
        self.raise_on_update = False

    def update(self, **kwargs):
        if self.raise_on_update:
            raise RuntimeError("update boom")
        self.updates.update(kwargs)
        return self

    def end(self):
        self.ended = True
        self.end_calls += 1

    def start_observation(self, **kwargs):
        child = FakeSpan(kwargs.get("name"), trace_id=self.trace_id)
        child.kwargs = kwargs
        self.children.append(child)
        return child


class FakeClient:
    def __init__(self):
        self.trace_id = "c" * 32
        self.seed = None
        self.root_kwargs = None
        self.root_span = None
        self.flush_count = 0

    def create_trace_id(self, seed=None):
        self.seed = seed
        return self.trace_id

    def start_observation(self, **kwargs):
        self.root_kwargs = kwargs
        self.root_span = FakeSpan(kwargs.get("name"), trace_id=self.trace_id)
        self.root_span.kwargs = kwargs
        return self.root_span

    def flush(self):
        self.flush_count += 1


def make_tracer():
    tracer = LangfuseTracer(enabled=False)
    tracer.enabled = True
    tracer.client = FakeClient()
    return tracer


# ------------------------------------------------------------ tracer 单元测试
def test_trace_workflow_seeds_trace_id_from_run_id():
    tracer = make_tracer()
    handle = tracer.trace_workflow(
        workflow_id="wf-1", run_id="run-abc", name="demo",
        metadata={"pattern": "sequential", "task": "do it"},
    )

    assert tracer.client.seed == "run-abc"
    assert handle.trace_id == tracer.client.trace_id
    # run_id 必须真正进入 trace_context，而不是事后给属性赋值
    assert tracer.client.root_kwargs["trace_context"] == {"trace_id": tracer.client.trace_id}
    assert tracer.client.root_kwargs["metadata"]["run_id"] == "run-abc"
    assert tracer.client.root_kwargs["metadata"]["workflow_id"] == "wf-1"


def test_step_span_is_child_of_root():
    tracer = make_tracer()
    handle = tracer.trace_workflow(workflow_id="wf-1", run_id="run-abc", name="demo")

    span = tracer.trace_step(
        trace=handle, step_id="step_1", agent_name="worker_1",
        input_text="hello", metadata={"step_index": 0},
    )

    root = tracer.client.root_span
    assert root.children == [span]
    assert span.kwargs["name"] == "worker_1"
    assert span.kwargs["metadata"]["step_id"] == "step_1"
    # 同一个 trace，而不是新 trace
    assert span.trace_id == root.trace_id


def test_step_with_model_uses_generation_type():
    """有模型信息的步骤要建成 generation，否则 Langfuse 会丢掉 token 用量"""
    tracer = make_tracer()
    handle = tracer.trace_workflow(workflow_id="wf", run_id="run", name="demo")

    span = tracer.trace_step(
        trace=handle, step_id="s1", agent_name="worker_1", input_text="in",
        metadata={"agent_model": "gpt-4o-mini"},
    )

    assert span.kwargs["as_type"] == "generation"
    assert span.kwargs["model"] == "gpt-4o-mini"


def test_update_step_end_is_always_called_even_if_update_fails():
    tracer = make_tracer()
    handle = tracer.trace_workflow(workflow_id="wf", run_id="run", name="demo")
    span = tracer.trace_step(trace=handle, step_id="s1", agent_name="a", input_text="in")

    span.raise_on_update = True
    tracer.update_step(span=span, output="out")

    # update 抛异常时也必须 end，否则 OTel 不会导出
    assert span.ended is True
    assert span.end_calls == 1


def test_usage_is_normalized_for_langfuse():
    tracer = make_tracer()
    handle = tracer.trace_workflow(workflow_id="wf", run_id="run", name="demo")
    span = tracer.trace_step(trace=handle, step_id="s1", agent_name="a", input_text="in")

    tracer.update_step(
        span=span, output="out",
        usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    )

    assert span.updates["usage_details"] == {"input": 10, "output": 20, "total": 30}
    assert span.ended is True


def test_end_trace_closes_root_span():
    tracer = make_tracer()
    handle = tracer.trace_workflow(
        workflow_id="wf", run_id="run", name="demo", metadata={"task": "t"},
    )

    tracer.end_trace(
        handle, output={"status": "completed"},
        metadata={"elapsed_time": 1.23},
        level="ERROR", status_message="boom",
    )

    root = tracer.client.root_span
    assert root.ended is True
    assert root.updates["output"] == {"status": "completed"}
    assert root.updates["level"] == "ERROR"
    assert root.updates["status_message"] == "boom"
    # 原有 metadata 不能被覆盖丢失
    assert root.updates["metadata"]["run_id"] == "run"
    assert root.updates["metadata"]["task"] == "t"
    assert root.updates["metadata"]["elapsed_time"] == 1.23


def test_disabled_tracer_degrades_to_dummy():
    tracer = LangfuseTracer(enabled=False)
    trace = tracer.trace_workflow(workflow_id="wf", run_id="run", name="demo")
    span = tracer.trace_step(trace=trace, step_id="s", agent_name="a", input_text="i")

    assert isinstance(trace, _DummyTrace)
    assert isinstance(span, _DummySpan)
    tracer.update_step(span=span, output="o")
    tracer.end_trace(trace, output={})
    tracer.flush()


# ------------------------------------------------------- 工作流执行链路测试
class RecordingTracer:
    """记录调用的假 tracer"""

    instances = []

    def __init__(self, enabled=False):
        self.enabled = enabled
        self.workflow_calls = []
        self.step_calls = []
        self.updates = []
        self.ended = []
        self.flush_count = 0
        RecordingTracer.instances.append(self)

    def trace_workflow(self, **kwargs):
        self.workflow_calls.append(kwargs)
        return object()

    def trace_step(self, **kwargs):
        self.step_calls.append(kwargs)
        return object()

    def update_step(self, **kwargs):
        self.updates.append(kwargs)

    def end_trace(self, trace, **kwargs):
        self.ended.append(kwargs)

    def flush(self):
        self.flush_count += 1


class FakeAgent:
    def __init__(self, name="worker_1", error=False):
        self.name = name
        self.error = error
        from agentflow.core.agent import AgentConfig
        self.config = AgentConfig(name=name, role="worker", model="fake-model",
                                  system_prompt="you are fake")

    def clear_memory(self):
        pass

    async def process(self, message):
        from types import SimpleNamespace
        if self.error:
            return SimpleNamespace(id="e1", content="boom", metadata={
                "error": True, "error_message": "boom"})
        return SimpleNamespace(id="r1", content="result", metadata={
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}})


def build_config(pattern, steps, agents):
    from agentflow.core.workflow import WorkflowConfig, WorkflowStep
    return WorkflowConfig(
        name="tracing-test",
        pattern=pattern,
        steps=[WorkflowStep(id=sid, agent_name=name) for sid, name in steps],
        agents=[a.config for a in agents],
    )


@pytest.mark.asyncio
async def test_parallel_pattern_creates_spans_and_ends_trace():
    from agentflow.core.workflow import WorkflowExecutor, WorkflowPattern

    RecordingTracer.instances.clear()
    agents = [FakeAgent("worker_1"), FakeAgent("worker_2")]
    config = build_config(WorkflowPattern.PARALLEL,
                          [("step_1", "worker_1"), ("step_2", "worker_2")], agents)

    with patch("agentflow.core.workflow.LangfuseTracer", RecordingTracer):
        executor = WorkflowExecutor(config, enable_persistence=False, enable_tracing=True)
        for agent in agents:
            executor.register_agent(agent)
        result = await executor.execute("task")

    assert result["status"] == "completed"
    tracer = RecordingTracer.instances[0]
    assert len(tracer.step_calls) == 2, "并行模式必须为每个步骤创建 span"
    assert len(tracer.updates) == 2
    assert len(tracer.ended) == 1
    assert tracer.flush_count == 1


@pytest.mark.asyncio
async def test_sequential_step_span_ends_and_trace_closed():
    from agentflow.core.workflow import WorkflowExecutor, WorkflowPattern

    RecordingTracer.instances.clear()
    agent = FakeAgent()
    config = build_config(WorkflowPattern.SEQUENTIAL, [("step_1", "worker_1")], [agent])

    with patch("agentflow.core.workflow.LangfuseTracer", RecordingTracer):
        executor = WorkflowExecutor(config, enable_persistence=False, enable_tracing=True)
        executor.register_agent(agent)
        result = await executor.execute("task")

    tracer = RecordingTracer.instances[0]
    assert result["status"] == "completed"
    assert len(tracer.workflow_calls) == 1
    assert len(tracer.step_calls) == 1
    assert tracer.updates[0]["usage"] == {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}
    assert tracer.ended and tracer.ended[0].get("level") is None


@pytest.mark.asyncio
async def test_failed_workflow_ends_trace_with_error_level():
    from agentflow.core.workflow import WorkflowExecutor, WorkflowPattern

    RecordingTracer.instances.clear()
    agent = FakeAgent(error=True)
    config = build_config(WorkflowPattern.SEQUENTIAL, [("step_1", "worker_1")], [agent])

    with patch("agentflow.core.workflow.LangfuseTracer", RecordingTracer):
        executor = WorkflowExecutor(config, enable_persistence=False, enable_tracing=True)
        executor.register_agent(agent)
        result = await executor.execute("task")

    tracer = RecordingTracer.instances[0]
    assert result["status"] == "failed"
    assert tracer.ended, "失败的运行也必须结束 trace"
    assert tracer.ended[0]["level"] == "ERROR"
    assert tracer.ended[0]["status_message"] == "boom"


def test_unsupported_pattern_is_rejected():
    """未完成的模式必须显式拒绝，而不是半执行"""
    from agentflow.core.workflow import (
        UnsupportedPatternError,
        WorkflowExecutor,
        WorkflowPattern,
    )

    agent = FakeAgent()
    config = build_config(WorkflowPattern.DEBATE, [("step_1", "worker_1")], [agent])
    config.max_iterations = 1

    with pytest.raises(UnsupportedPatternError):
        WorkflowExecutor(config, enable_persistence=False, enable_tracing=False)


@pytest.mark.asyncio
async def test_auto_evaluate_runs_when_enabled(monkeypatch):
    """AUTO_EVALUATE=true 时，执行结束必须调用自动评估（此前从未被调用）"""
    from unittest.mock import AsyncMock
    from agentflow.core.workflow import WorkflowExecutor, WorkflowPattern

    RecordingTracer.instances.clear()
    monkeypatch.setenv("AUTO_EVALUATE", "true")
    agent = FakeAgent()
    config = build_config(WorkflowPattern.SEQUENTIAL, [("step_1", "worker_1")], [agent])

    fake_eval = AsyncMock(return_value={"score": 88})
    with patch("agentflow.core.workflow.LangfuseTracer", RecordingTracer), \
            patch("agentflow.core.auto_evaluate.auto_evaluate_workflow", new=fake_eval):
        executor = WorkflowExecutor(config, enable_persistence=False, enable_tracing=True)
        executor.register_agent(agent)
        await executor.execute("task")

    assert fake_eval.await_count == 1
    _, kwargs = fake_eval.await_args
    assert "trace_id" in kwargs


@pytest.mark.asyncio
async def test_auto_evaluate_skipped_by_default(monkeypatch):
    from unittest.mock import AsyncMock
    from agentflow.core.workflow import WorkflowExecutor, WorkflowPattern

    RecordingTracer.instances.clear()
    monkeypatch.setenv("AUTO_EVALUATE", "false")
    agent = FakeAgent()
    config = build_config(WorkflowPattern.SEQUENTIAL, [("step_1", "worker_1")], [agent])

    fake_eval = AsyncMock(return_value=None)
    with patch("agentflow.core.workflow.LangfuseTracer", RecordingTracer), \
            patch("agentflow.core.auto_evaluate.auto_evaluate_workflow", new=fake_eval):
        executor = WorkflowExecutor(config, enable_persistence=False, enable_tracing=True)
        executor.register_agent(agent)
        await executor.execute("task")

    assert fake_eval.await_count == 0
