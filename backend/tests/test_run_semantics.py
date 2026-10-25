"""
第一批优化：运行语义 / 记录一致性 / 隔离 / 停止 / 并发 / 追踪失败隔离 的确定性回归
全部使用假适配器，不访问外部模型。
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

from agentflow.adapters.base import LLMAdapter
from agentflow.agents.llm_agent import LLMAgent
from agentflow.core.agent import AgentConfig, AgentRole
from agentflow.core.run import RunStatus, UsageType, RECORD_SCHEMA_VERSION
from agentflow.core.workflow import (
    RunAlreadyRunningError,
    UnsupportedPatternError,
    WorkflowConfig,
    WorkflowExecutor,
    WorkflowPattern,
    WorkflowStep,
)
from agentflow.storage import RunRepository, get_db


class FakeAdapter(LLMAdapter):
    """可控假适配器：可失败、可省略 usage、可延迟、记录收到的消息"""

    def __init__(self, prefix="out", fail=False, error_metadata=False,
                 omit_usage=False, partial_usage=False, delay=0.0):
        self.prefix = prefix
        self.fail = fail
        self.error_metadata = error_metadata
        self.omit_usage = omit_usage
        self.partial_usage = partial_usage
        self.delay = delay
        self.calls = []
        self.call_count = 0

    async def complete(self, messages, model, temperature=0.7, max_tokens=2000, **kwargs):
        self.call_count += 1
        self.calls.append([dict(message) for message in messages])
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail or self.error_metadata:
            # LLMAgent 捕获异常后返回 metadata.error=True 的错误消息，
            # 这正是执行器需要识别并停止下游的真实路径。
            raise RuntimeError(f"simulated error #{self.call_count}")

        content = f"{self.prefix}-{self.call_count}"
        result = {
            "content": content,
            "model": f"{model}-resolved",
            "finish_reason": "stop",
        }
        if self.partial_usage:
            result["usage"] = {"prompt_tokens": 10}
        elif not self.omit_usage:
            result["usage"] = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        return result

    async def stream_complete(self, messages, model, temperature=0.7, max_tokens=2000, **kwargs):
        yield self.prefix


def make_config(pattern, names=("worker_1", "worker_2", "worker_3")):
    steps = [
        WorkflowStep(id=f"step_{i + 1}", agent_name=name,
                     input_from=f"step_{i}" if pattern == WorkflowPattern.SEQUENTIAL and i else None)
        for i, name in enumerate(names)
    ]
    agents = [
        AgentConfig(name=name, role=AgentRole.WORKER, system_prompt=f"You are {name}.",
                    model="test-model")
        for name in names
    ]
    return WorkflowConfig(name="semantics-test", pattern=pattern, steps=steps, agents=agents)


def build_executor(pattern, adapters, persistence=False, tracing=False):
    """adapters: name -> FakeAdapter"""
    config = make_config(pattern, tuple(adapters.keys()))
    executor = WorkflowExecutor(
        config,
        enable_persistence=persistence,
        enable_tracing=tracing,
    )
    for name, adapter in adapters.items():
        executor.register_agent(LLMAgent(
            AgentConfig(name=name, role=AgentRole.WORKER, system_prompt=f"You are {name}.",
                        model="test-model"),
            adapter,
        ))
    return executor


def agent_adapters(names, adapter_factory=None):
    adapter_factory = adapter_factory or FakeAdapter
    result = {}
    for index, name in enumerate(names):
        result[name] = adapter_factory(index, name)
    return result


# --------------------------------------------------------------- sequential
@pytest.mark.asyncio
async def test_sequential_handoff_and_unified_records():
    adapters = {name: FakeAdapter(prefix=name) for name in ("worker_1", "worker_2")}
    executor = build_executor(WorkflowPattern.SEQUENTIAL, adapters)

    result = await executor.execute("initial task")

    assert result["status"] == "completed"
    run = executor.runs[result["run_id"]]
    assert run.schema_version == RECORD_SCHEMA_VERSION
    assert run.status == RunStatus.COMPLETED
    assert len(run.step_results) == 2

    first, second = run.step_results
    assert first.step_index == 0 and second.step_index == 1
    assert first.input_text == "initial task"
    assert first.output_text == "worker_1-1"
    assert second.input_text == "worker_1-1"          # 顺序交接
    assert second.output_text == "worker_2-1"
    assert first.model == "test-model-resolved"
    assert first.finish_reason == "stop"
    assert first.usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    assert first.usage_type == UsageType.ACTUAL
    assert run.total_tokens == 30
    # 消息历史只属于本次运行，且输入输出成对
    assert len(executor.message_history) == 4
    assert len(executor.get_run_messages(run.run_id)) == 4


@pytest.mark.asyncio
async def test_sequential_failure_stops_downstream():
    adapters = {
        "worker_1": FakeAdapter(prefix="w1"),
        "worker_2": FakeAdapter(prefix="w2", error_metadata=True),
        "worker_3": FakeAdapter(prefix="w3"),
    }
    executor = build_executor(WorkflowPattern.SEQUENTIAL, adapters)

    result = await executor.execute("task")

    assert result["status"] == "failed"
    run = executor.runs[result["run_id"]]
    assert run.status == RunStatus.FAILED
    # 第三步没有被调用
    assert adapters["worker_3"].call_count == 0
    assert [step.step_id for step in run.step_results] == ["step_1", "step_2"]
    assert run.step_results[0].status == RunStatus.COMPLETED
    assert run.step_results[1].status == RunStatus.FAILED
    assert "simulated error" in (run.step_results[1].error or "")
    # 失败内容没有被当作正常材料交给下游，也不能把失败前的输入当成最终答案
    assert run.step_results[1].output_text.startswith("Error:")
    assert result["result"]["final_result"] is None
    assert "simulated error" in (result["result"]["error"] or "")


@pytest.mark.asyncio
async def test_sequential_adapter_exception_is_failure_not_content():
    class BoomAdapter(FakeAdapter):
        async def complete(self, messages, model, **kwargs):
            self.call_count += 1
            raise RuntimeError("boom")

    adapters = {"worker_1": BoomAdapter(prefix="w1"), "worker_2": FakeAdapter()}
    executor = build_executor(WorkflowPattern.SEQUENTIAL, adapters)
    result = await executor.execute("task")

    assert result["status"] == "failed"
    assert adapters["worker_2"].call_count == 0
    run = executor.runs[result["run_id"]]
    assert run.step_results[0].error and "boom" in run.step_results[0].error


@pytest.mark.asyncio
async def test_metadata_error_response_stops_downstream():
    """覆盖 LLMAgent 返回 metadata.error=True 的显式错误路径"""
    from agentflow.core.message import Message, MessageType

    class ErrorAgent:
        def __init__(self, name):
            self.name = name
            self.config = AgentConfig(name=name, role=AgentRole.WORKER,
                                      system_prompt="x", model="test-model")
            self.memory = []
            self.state = None

        def reset_for_run(self):
            self.memory.clear()

        async def process(self, message):
            return Message(
                sender=self.name, receiver="system", content="Error: rejected",
                message_type=MessageType.RESPONSE,
                metadata={"error": True, "error_message": "rejected by agent"},
            )

    config = make_config(WorkflowPattern.SEQUENTIAL, ("worker_1", "worker_2"))
    executor = WorkflowExecutor(config, enable_persistence=False)
    executor.register_agent(ErrorAgent("worker_1"))
    executor.register_agent(ErrorAgent("worker_2"))

    result = await executor.execute("task")

    assert result["status"] == "failed"
    run = executor.runs[result["run_id"]]
    assert len(run.step_results) == 1
    assert run.step_results[0].status == RunStatus.FAILED
    assert run.step_results[0].error == "rejected by agent"


@pytest.mark.asyncio
async def test_current_input_is_not_duplicated_in_request():
    adapters = {"worker_1": FakeAdapter(prefix="w1"), "worker_2": FakeAdapter(prefix="w2")}
    executor = build_executor(WorkflowPattern.SEQUENTIAL, adapters)

    await executor.execute("initial task")

    first_call = adapters["worker_1"].calls[0]
    assert [message["role"] for message in first_call] == ["system", "user"]
    assert first_call[-1]["content"] == "initial task"
    # 当前输入只作为最后一条 user 出现一次
    assert sum(1 for message in first_call if message["content"] == "initial task") == 1

    second_call = adapters["worker_2"].calls[0]
    assert second_call[-1]["content"] == "w1-1"


# ----------------------------------------------------------------- parallel
@pytest.mark.asyncio
async def test_parallel_all_success_and_stable_step_mapping():
    adapters = {name: FakeAdapter(prefix=name) for name in ("worker_1", "worker_2", "worker_3")}
    executor = build_executor(WorkflowPattern.PARALLEL, adapters)

    result = await executor.execute("parallel task")

    assert result["status"] == "completed"
    run = executor.runs[result["run_id"]]
    assert run.status == RunStatus.COMPLETED
    assert [step.step_id for step in run.step_results] == ["step_1", "step_2", "step_3"]
    assert [step.output_text for step in run.step_results] == ["worker_1-1", "worker_2-1", "worker_3-1"]
    assert all(step.status == RunStatus.COMPLETED for step in run.step_results)
    assert all(step.input_text == "parallel task" for step in run.step_results)
    assert run.total_tokens == 45
    assert "worker_1-1" in result["result"]["aggregated"]


@pytest.mark.asyncio
async def test_parallel_partial_failure():
    adapters = {
        "worker_1": FakeAdapter(prefix="w1"),
        "worker_2": FakeAdapter(prefix="w2", error_metadata=True),
        "worker_3": FakeAdapter(prefix="w3"),
    }
    executor = build_executor(WorkflowPattern.PARALLEL, adapters)

    result = await executor.execute("parallel task")

    assert result["status"] == "partial"
    run = executor.runs[result["run_id"]]
    assert run.status == RunStatus.PARTIAL
    assert run.step_results[0].status == RunStatus.COMPLETED
    assert run.step_results[1].status == RunStatus.FAILED
    assert run.step_results[2].status == RunStatus.COMPLETED
    assert result["result"]["failed_steps"] == ["worker_2"]
    assert executor.status == "partial"


@pytest.mark.asyncio
async def test_parallel_all_failure():
    adapters = {name: FakeAdapter(error_metadata=True) for name in ("worker_1", "worker_2")}
    executor = build_executor(WorkflowPattern.PARALLEL, adapters)

    result = await executor.execute("parallel task")

    assert result["status"] == "failed"
    run = executor.runs[result["run_id"]]
    assert run.status == RunStatus.FAILED
    assert all(step.status == RunStatus.FAILED for step in run.step_results)


@pytest.mark.asyncio
async def test_parallel_stop_cancels_unfinished_steps():
    adapters = {name: FakeAdapter(prefix=name, delay=0.5) for name in ("worker_1", "worker_2")}
    executor = build_executor(WorkflowPattern.PARALLEL, adapters)

    task = asyncio.create_task(executor.execute("slow task"))
    await asyncio.sleep(0.1)
    assert executor.stop() is True
    result = await task

    assert result["status"] == "stopped"
    run = executor.runs[result["run_id"]]
    assert run.status == RunStatus.STOPPED
    assert all(step.status == RunStatus.CANCELLED for step in run.step_results)
    assert all(step.usage_type == UsageType.UNKNOWN for step in run.step_results)
    assert all(step.usage is None for step in run.step_results)


# ----------------------------------------------------------- stop semantics
@pytest.mark.asyncio
async def test_stop_during_sequential_blocks_remaining_steps():
    class StoppingAdapter(FakeAdapter):
        def __init__(self, executor_ref, **kwargs):
            super().__init__(**kwargs)
            self.executor = executor_ref

        async def complete(self, messages, model, **kwargs):
            result = await super().complete(messages, model, **kwargs)
            if self.call_count == 1:
                self.executor.stop()
            return result

    adapters = {name: FakeAdapter(prefix=name) for name in ("worker_1", "worker_2")}
    executor = build_executor(WorkflowPattern.SEQUENTIAL, adapters)
    # 把停止逻辑注入第一个 agent 的 adapter
    stopping = StoppingAdapter(executor, prefix="w1")
    executor.agents["worker_1"] = LLMAgent(
        AgentConfig(name="worker_1", role=AgentRole.WORKER, system_prompt="w1", model="test-model"),
        stopping,
    )

    result = await executor.execute("task")

    assert result["status"] == "stopped"
    run = executor.runs[result["run_id"]]
    assert run.status == RunStatus.STOPPED
    assert len(run.step_results) == 1
    assert adapters["worker_2"].call_count == 0
    # 停止后不能被覆盖成 completed
    assert executor.status == "stopped"


def test_stop_is_noop_when_idle():
    executor = build_executor(WorkflowPattern.SEQUENTIAL, {"worker_1": FakeAdapter()})
    assert executor.stop() is False
    assert executor.status == "idle"


# --------------------------------------------------- isolation / repeat runs
@pytest.mark.asyncio
async def test_repeated_runs_are_isolated_and_reset_stats():
    adapters = {"worker_1": FakeAdapter(prefix="w1")}
    executor = build_executor(WorkflowPattern.SEQUENTIAL, adapters)

    first = await executor.execute("first task")
    second = await executor.execute("second task")

    assert first["run_id"] != second["run_id"]
    run1 = executor.runs[first["run_id"]]
    run2 = executor.runs[second["run_id"]]
    assert run1.task_input == "first task"
    assert run2.task_input == "second task"

    agent = executor.agents["worker_1"]
    # 统计只反映第二次运行（reset_for_run 生效）
    assert agent.state.messages_processed == 1
    assert agent.state.total_tokens == 15
    # 记忆只保留第二次运行
    assert len(agent.memory) == 2
    # 消息历史只属于当前运行；历史运行消息仍可按 run 回看
    assert len(executor.message_history) == 2
    assert len(executor.get_run_messages(run1.run_id)) == 2
    assert len(executor.get_run_messages(run2.run_id)) == 2
    # 第一次运行的步骤记录没有被第二次覆盖
    assert len(run1.step_results) == 1
    assert run1.step_results[0].input_text == "first task"


@pytest.mark.asyncio
async def test_concurrent_execute_is_rejected():
    adapters = {"worker_1": FakeAdapter(delay=0.3)}
    executor = build_executor(WorkflowPattern.SEQUENTIAL, adapters)

    first = asyncio.create_task(executor.execute("slow"))
    await asyncio.sleep(0.05)
    with pytest.raises(RunAlreadyRunningError):
        await executor.execute("second")
    result = await first
    assert result["status"] == "completed"


# ------------------------------------------------------------ usage handling
@pytest.mark.asyncio
async def test_missing_usage_is_unknown_not_failure():
    adapters = {"worker_1": FakeAdapter(omit_usage=True)}
    executor = build_executor(WorkflowPattern.SEQUENTIAL, adapters)

    result = await executor.execute("task")

    assert result["status"] == "completed"
    run = executor.runs[result["run_id"]]
    step = run.step_results[0]
    assert step.status == RunStatus.COMPLETED
    assert step.usage is None
    assert step.usage_type == UsageType.UNKNOWN
    assert run.total_tokens == 0  # 未知不能填 0 冒充真实用量，但统计保持 0


@pytest.mark.asyncio
async def test_partial_usage_is_marked_partial():
    adapters = {"worker_1": FakeAdapter(partial_usage=True)}
    executor = build_executor(WorkflowPattern.SEQUENTIAL, adapters)

    result = await executor.execute("task")

    step = executor.runs[result["run_id"]].step_results[0]
    assert step.status == RunStatus.COMPLETED
    assert step.usage == {"prompt_tokens": 10}
    assert step.usage_type == UsageType.PARTIAL


# ------------------------------------------------------- tracing robustness
@pytest.mark.asyncio
async def test_tracing_disabled_still_runs():
    adapters = {"worker_1": FakeAdapter()}
    executor = build_executor(WorkflowPattern.SEQUENTIAL, adapters, tracing=False)
    assert executor.tracer is None or not executor.tracer.enabled
    result = await executor.execute("task")
    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_broken_tracer_never_changes_business_result(monkeypatch):
    import agentflow.core.workflow as workflow_module

    class BrokenTracer:
        def __init__(self, enabled=False):
            self.enabled = enabled

        def trace_workflow(self, **kwargs):
            raise RuntimeError("tracing down")

        def trace_step(self, **kwargs):
            raise RuntimeError("tracing down")

        def update_step(self, **kwargs):
            raise RuntimeError("tracing down")

        def end_trace(self, **kwargs):
            raise RuntimeError("tracing down")

        def flush(self):
            raise RuntimeError("tracing down")

    monkeypatch.setattr(workflow_module, "LangfuseTracer", BrokenTracer)
    adapters = {"worker_1": FakeAdapter()}
    executor = build_executor(WorkflowPattern.SEQUENTIAL, adapters, tracing=True)

    result = await executor.execute("task")

    assert result["status"] == "completed"
    assert result["result"]["final_result"] == "out-1"


# ------------------------------------------------------------- persistence
@pytest.mark.asyncio
async def test_persistence_incremental_and_versioned_record():
    adapters = {"worker_1": FakeAdapter(), "worker_2": FakeAdapter(error_metadata=True)}
    executor = build_executor(WorkflowPattern.SEQUENTIAL, adapters, persistence=True)

    result = await executor.execute("persisted task")

    with get_db() as db:
        stored = RunRepository.get_run(db, result["run_id"])

    assert stored is not None
    assert stored.schema_version == RECORD_SCHEMA_VERSION
    assert stored.status == RunStatus.FAILED
    assert stored.workflow_name == "semantics-test"
    assert len(stored.step_results) == 2
    assert stored.step_results[0].input_text == "persisted task"
    assert stored.step_results[0].output_text == "out-1"
    assert stored.step_results[0].model == "test-model-resolved"
    assert stored.step_results[1].status == RunStatus.FAILED
    # 配置快照不能包含密钥
    assert "api_key" not in str(stored.config_snapshot).lower()


@pytest.mark.asyncio
async def test_running_run_is_visible_in_history_before_finish():
    adapters = {"worker_1": FakeAdapter(delay=0.25)}
    executor = build_executor(WorkflowPattern.SEQUENTIAL, adapters, persistence=True)

    task = asyncio.create_task(executor.execute("long task"))
    await asyncio.sleep(0.1)
    run_id = executor.get_status()["run_id"]
    with get_db() as db:
        stored = RunRepository.get_run(db, run_id)
    assert stored is not None
    assert stored.status == RunStatus.RUNNING
    await task


# ------------------------------------------------------------------- API
@pytest.fixture
def api_client(monkeypatch):
    from agentflow.api.app import app
    from agentflow.api.routes import workflow as workflow_routes

    workflow_routes.workflows.clear()
    monkeypatch.setattr(workflow_routes.AdapterFactory, "create_adapter", lambda **kwargs: FakeAdapter())
    with TestClient(app) as client:
        yield client
    workflow_routes.workflows.clear()


def _create_api_workflow(client, pattern="sequential", name="API run semantics", agent_count=2):
    response = client.post("/api/workflows", json={
        "name": name,
        "pattern": pattern,
        "config": {
            "agent_count": agent_count,
            "llm_provider": "openai",
            "api_key": "test-only-not-a-real-key",
            "model": "test-model",
        },
    })
    assert response.status_code == 200, response.text
    return response.json()["workflow_id"]


def test_api_execute_returns_run_id_and_status(api_client):
    workflow_id = _create_api_workflow(api_client)
    response = api_client.post(f"/api/workflows/{workflow_id}/execute", json={"task": "api task"})
    assert response.status_code == 200
    run_id = response.json()["run_id"]
    assert run_id

    status = api_client.get(f"/api/workflows/{workflow_id}/status").json()
    assert status["status"] == "completed"
    assert status["run_id"] == run_id

    detail = api_client.get(f"/api/runs/{run_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["run_id"] == run_id
    assert body["status"] == "completed"
    assert body["step_results"][0]["input_text"] == "api task"
    assert body["step_results"][0]["output_text"].startswith("out-")


def test_api_supports_all_patterns_and_enforces_minimum_agents(api_client):
    for pattern, count in (
        ("hierarchical", 2),
        ("debate", 3),
        ("voting", 3),
        ("dynamic", 2),
        ("group_chat", 2),
    ):
        response = api_client.post("/api/workflows", json={
            "name": f"pattern-{pattern}",
            "pattern": pattern,
            "config": {"agent_count": count, "llm_provider": "openai",
                       "api_key": "test-only", "model": "test-model"},
        })
        assert response.status_code == 200, response.text
        assert response.json()["pattern"] == pattern

    too_few = api_client.post("/api/workflows", json={
        "name": "bad-debate",
        "pattern": "debate",
        "config": {"agent_count": 2, "llm_provider": "openai",
                   "api_key": "test-only", "model": "test-model"},
    })
    assert too_few.status_code == 400
    assert "at least 3" in too_few.json()["detail"]

    too_many_group = api_client.post("/api/workflows", json={
        "name": "bad-group-chat",
        "pattern": "group_chat",
        "config": {"agent_count": 7, "llm_provider": "openai",
                   "api_key": "test-only", "model": "test-model"},
    })
    assert too_many_group.status_code == 400
    assert "at most 6" in too_many_group.json()["detail"]


def test_api_executes_all_seven_patterns(api_client):
    cases = [
        ("sequential", 2, "completed"),
        ("parallel", 2, "completed"),
        ("hierarchical", 3, "completed"),
        ("debate", 3, "completed"),
        ("voting", 3, "completed"),
        ("dynamic", 3, "partial"),
        ("group_chat", 3, "partial"),
    ]
    for pattern, count, expected in cases:
        workflow_id = _create_api_workflow(api_client, pattern=pattern, agent_count=count,
                                           name=f"pattern-{pattern}")
        response = api_client.post(f"/api/workflows/{workflow_id}/execute", json={"task": "api task"})
        assert response.status_code == 200, (pattern, response.text)
        status = api_client.get(f"/api/workflows/{workflow_id}/status").json()
        assert status["status"] == expected, (pattern, status)
        assert status["pattern"] == pattern


def test_group_chat_lead_can_be_disabled(api_client):
    with_lead = api_client.post("/api/workflows", json={
        "name": "group-with-lead",
        "pattern": "group_chat",
        "config": {"agent_count": 3, "llm_provider": "openai",
                   "api_key": "test-only", "model": "test-model"},
    })
    assert with_lead.status_code == 200, with_lead.text
    assert [agent["name"] for agent in with_lead.json()["agents"]] == ["lead", "member_1", "member_2"]

    without_lead = api_client.post("/api/workflows", json={
        "name": "group-without-lead",
        "pattern": "group_chat",
        "config": {"agent_count": 2, "llm_provider": "openai",
                   "api_key": "test-only", "model": "test-model",
                   "group_chat": {"enable_lead": False}},
    })
    assert without_lead.status_code == 200, without_lead.text
    assert [agent["name"] for agent in without_lead.json()["agents"]] == ["member_1", "member_2"]


def test_api_rejects_second_concurrent_execute(api_client):
    workflow_id = _create_api_workflow(api_client)
    from agentflow.api.routes import workflow as workflow_routes

    executor = workflow_routes.workflows[workflow_id]
    executor._active_run = object()  # 模拟已有运行
    response = api_client.post(f"/api/workflows/{workflow_id}/execute", json={"task": "x"})
    assert response.status_code == 409
    executor._active_run = None


def test_api_stop_without_active_run_is_conflict(api_client):
    workflow_id = _create_api_workflow(api_client)
    assert api_client.post(f"/api/workflows/{workflow_id}/stop").status_code == 409


def test_api_history_replay_does_not_call_model(api_client):
    workflow_id = _create_api_workflow(api_client)
    api_client.post(f"/api/workflows/{workflow_id}/execute", json={"task": "api task"})
    from agentflow.api.routes import workflow as workflow_routes

    executor = workflow_routes.workflows[workflow_id]
    adapter = executor.agents["worker_1"].llm_adapter
    calls_after_run = adapter.call_count

    assert api_client.get(f"/api/workflows/{workflow_id}/runs").status_code == 200
    run_id = executor.get_status()["run_id"]
    assert api_client.get(f"/api/runs/{run_id}").status_code == 200
    assert api_client.get("/api/messages", params={"run_id": run_id}).status_code == 200

    assert adapter.call_count == calls_after_run, "历史回看不能触发模型调用"


def test_api_run_history_shape_and_totals(api_client):
    workflow_id = _create_api_workflow(api_client)
    api_client.post(f"/api/workflows/{workflow_id}/execute", json={"task": "task one"})
    api_client.post(f"/api/workflows/{workflow_id}/execute", json={"task": "task two"})

    response = api_client.get(f"/api/workflows/{workflow_id}/runs", params={"limit": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 2, "total 必须是数据库总数，而不是当前页条数"
    assert len(body["runs"]) == 1
    assert body["runs"][0]["schema_version"] == RECORD_SCHEMA_VERSION
    assert "step_results" in body["runs"][0]

    all_runs = api_client.get("/api/runs", params={"limit": 2}).json()
    assert all_runs["runs"][0]["step_results"], "全部运行列表也要返回统一步骤记录"
    compare = api_client.get("/api/runs/compare", params={"run_ids": body["runs"][0]["run_id"]})
    assert compare.status_code == 200, compare.text
    assert compare.json()["summary"]["total_runs"] == 1


def test_api_unknown_run_messages_404(api_client):
    response = api_client.get("/api/messages", params={"run_id": "missing-run"})
    assert response.status_code == 404
