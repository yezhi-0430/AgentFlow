"""
第二批：执行控制（超时/重试/错误分类/用量聚合）、记录截断与脱敏、
异步持久化/保留策略、trace_id、可选 API Token 的确定性回归。

全部离线，使用假适配器。
"""
import asyncio
import os
import tempfile
import time

import pytest
from fastapi.testclient import TestClient

from agentflow.adapters.base import LLMAdapter
from agentflow.agents.llm_agent import LLMAgent
from agentflow.api.app import app
from agentflow.core.agent import AgentConfig, AgentRole
from agentflow.core.run import RunStatus, UsageType
from agentflow.core.workflow import WorkflowConfig, WorkflowExecutor, WorkflowPattern, WorkflowStep
from agentflow.storage import RunRepository, get_db


class FlakyAdapter(LLMAdapter):
    def __init__(self, failures=0, error="provider failure", delay=0.0,
                 content="ok", usage=None):
        self.failures = failures
        self.error = error
        self.delay = delay
        self.content = content
        self.usage = usage if usage is not None else {
            "prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7
        }
        self.calls = 0

    async def complete(self, messages, model, temperature=0.7, max_tokens=2000, **kwargs):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.calls <= self.failures:
            raise RuntimeError(self.error)
        return {
            "content": self.content,
            "model": model,
            "finish_reason": "stop",
            "usage": self.usage,
        }

    async def stream_complete(self, messages, model, temperature=0.7, max_tokens=2000, **kwargs):
        yield "x"


def build_executor(adapters, pattern=WorkflowPattern.SEQUENTIAL, persistence=False, tracing=False):
    names = tuple(adapters.keys())
    steps = [
        WorkflowStep(id=f"step_{i + 1}", agent_name=name,
                     input_from=f"step_{i}" if pattern == WorkflowPattern.SEQUENTIAL and i else None)
        for i, name in enumerate(names)
    ]
    config = WorkflowConfig(
        name="controls-test",
        pattern=pattern,
        steps=steps,
        agents=[AgentConfig(name=name, role=AgentRole.WORKER, system_prompt="x",
                            model="test-model") for name in names],
    )
    executor = WorkflowExecutor(
        config, enable_persistence=persistence, enable_tracing=tracing
    )
    for name, adapter in adapters.items():
        executor.register_agent(LLMAgent(
            AgentConfig(name=name, role=AgentRole.WORKER, system_prompt="x", model="test-model"),
            adapter,
        ))
    return executor


@pytest.mark.asyncio
async def test_timeout_is_classified(monkeypatch):
    monkeypatch.setenv("AGENTFLOW_STEP_TIMEOUT_SECONDS", "0.05")
    adapters = {"worker_1": FlakyAdapter(delay=0.3)}
    executor = build_executor(adapters)

    result = await executor.execute("task")

    assert result["status"] == "failed"
    step = executor.runs[result["run_id"]].step_results[0]
    assert step.status == RunStatus.FAILED
    assert step.error_type == "timeout"
    assert step.attempts == 1
    assert step.usage is None and step.usage_type == UsageType.UNKNOWN
    assert "timed out" in (step.error or "").lower()


@pytest.mark.asyncio
async def test_retry_succeeds_and_aggregates_usage(monkeypatch):
    monkeypatch.setenv("AGENTFLOW_MAX_ATTEMPTS", "2")
    adapters = {"worker_1": FlakyAdapter(failures=1, error="connection reset by peer")}
    executor = build_executor(adapters)

    result = await executor.execute("task")

    assert result["status"] == "completed"
    step = executor.runs[result["run_id"]].step_results[0]
    assert step.status == RunStatus.COMPLETED
    assert step.attempts == 2
    # 第一次尝试未知用量 + 第二次实际用量 → PARTIAL，只累计已知部分
    assert step.usage_type == UsageType.PARTIAL
    assert step.usage["total_tokens"] == 7
    assert adapters["worker_1"].calls == 2


@pytest.mark.asyncio
async def test_retry_exhaustion_records_attempts(monkeypatch):
    monkeypatch.setenv("AGENTFLOW_MAX_ATTEMPTS", "3")
    adapters = {"worker_1": FlakyAdapter(failures=3, error="connection reset")}
    executor = build_executor(adapters)

    result = await executor.execute("task")

    assert result["status"] == "failed"
    step = executor.runs[result["run_id"]].step_results[0]
    assert step.attempts == 3
    assert step.error_type == "network"
    assert adapters["worker_1"].calls == 3


@pytest.mark.asyncio
async def test_auth_error_is_not_retried(monkeypatch):
    monkeypatch.setenv("AGENTFLOW_MAX_ATTEMPTS", "3")
    adapters = {"worker_1": FlakyAdapter(failures=3, error="401 invalid api key")}
    executor = build_executor(adapters)

    result = await executor.execute("task")

    step = executor.runs[result["run_id"]].step_results[0]
    assert step.status == RunStatus.FAILED
    assert step.error_type == "auth"
    assert step.attempts == 1, "鉴权错误不应重试"
    assert adapters["worker_1"].calls == 1


@pytest.mark.asyncio
async def test_record_text_truncation(monkeypatch):
    monkeypatch.setenv("AGENTFLOW_RECORD_TEXT_LIMIT", "20")
    long_text = "x" * 100
    adapters = {"worker_1": FlakyAdapter(content=long_text)}
    executor = build_executor(adapters)

    result = await executor.execute("task")

    step = executor.runs[result["run_id"]].step_results[0]
    assert step.output_text.endswith("...[truncated]")
    assert len(step.output_text) < len(long_text)
    assert executor.runs[result["run_id"]].final_result.endswith("...[truncated]")


@pytest.mark.asyncio
async def test_error_text_is_redacted(monkeypatch):
    adapters = {
        "worker_1": FlakyAdapter(failures=1, error="boom sk-abcdefghijklmnop1234567890"),
    }
    executor = build_executor(adapters)

    result = await executor.execute("task")

    step = executor.runs[result["run_id"]].step_results[0]
    assert step.status == RunStatus.FAILED
    assert "sk-abcdefghijklmnop1234567890" not in (step.error or "")
    assert "[REDACTED]" in (step.error or "")


@pytest.mark.asyncio
async def test_trace_id_is_recorded(monkeypatch):
    import agentflow.core.workflow as workflow_module

    class FakeHandle:
        trace_id = "a" * 32

    class FakeTracer:
        def __init__(self, enabled=False):
            self.enabled = enabled

        def trace_workflow(self, **kwargs):
            return FakeHandle()

        def trace_step(self, **kwargs):
            return object()

        def update_step(self, **kwargs):
            pass

        def end_trace(self, **kwargs):
            pass

        def flush(self):
            pass

    monkeypatch.setattr(workflow_module, "LangfuseTracer", FakeTracer)
    adapters = {"worker_1": FlakyAdapter()}
    executor = build_executor(adapters, persistence=True, tracing=True)

    result = await executor.execute("task")

    assert result["trace_id"] == "a" * 32
    with get_db() as db:
        stored = RunRepository.get_run(db, result["run_id"])
    assert stored.trace_id == "a" * 32
    assert stored.step_results[0].attempts == 1
    assert stored.step_results[0].error_type is None


@pytest.mark.asyncio
async def test_persistence_uses_worker_thread(monkeypatch):
    calls = []
    original = asyncio.to_thread

    async def spy(func, *args, **kwargs):
        calls.append(func.__name__)
        return await original(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", spy)
    adapters = {"worker_1": FlakyAdapter()}
    executor = build_executor(adapters, persistence=True)

    await executor.execute("task")

    assert calls, "持久化应通过 asyncio.to_thread 移出事件循环"
    assert calls[0] == "_persist_sync"


@pytest.mark.asyncio
async def test_concurrent_executors_persist_without_locking():
    executors = []
    for index in range(3):
        executor = build_executor({"worker_1": FlakyAdapter()}, persistence=True)
        executors.append(executor)

    results = await asyncio.gather(*[executor.execute(f"task-{i}") for i, executor in enumerate(executors)])

    assert all(result["status"] == "completed" for result in results)
    with get_db() as db:
        for result in results:
            assert RunRepository.get_run(db, result["run_id"]) is not None


def test_prune_runs_keeps_newest():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from agentflow.storage.models import Base
    from agentflow.core.run import WorkflowRun

    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
        db_url = f"sqlite:///{tmp.name}"
    engine = create_engine(db_url)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        for index in range(4):
            run = WorkflowRun(run_id=f"run-{index}", workflow_id="wf", task_input="t")
            run.created_at = time.time() + index
            RunRepository.save_run(session, run)
        deleted = RunRepository.prune_runs(session, max_runs=2, retention_days=0)
        assert deleted == 2
        remaining = RunRepository.list_runs(session, limit=10)
        assert [run.run_id for run in remaining] == ["run-3", "run-2"]
    finally:
        session.close()
        engine.dispose()
        try:
            os.unlink(tmp.name)
        except (PermissionError, OSError):
            pass


def test_optional_api_token(monkeypatch):
    from agentflow.api.routes import workflow as workflow_routes

    workflow_routes.workflows.clear()
    monkeypatch.setenv("AGENTFLOW_API_TOKEN", "local-test-token")
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/workflows").status_code == 401
        headers = {"Authorization": "Bearer local-test-token"}
        assert client.get("/api/workflows", headers=headers).status_code == 200
        assert client.get("/api/workflows", headers={"Authorization": "Bearer wrong"}).status_code == 401
    workflow_routes.workflows.clear()


@pytest.mark.asyncio
async def test_parallel_retry_attempts_recorded(monkeypatch):
    monkeypatch.setenv("AGENTFLOW_MAX_ATTEMPTS", "2")
    adapters = {
        "worker_1": FlakyAdapter(failures=1, error="timeout while connecting"),
        "worker_2": FlakyAdapter(),
    }
    executor = build_executor(adapters, pattern=WorkflowPattern.PARALLEL)

    result = await executor.execute("task")

    assert result["status"] == "completed"
    steps = executor.runs[result["run_id"]].step_results
    by_name = {step.agent_name: step for step in steps}
    assert by_name["worker_1"].attempts == 2
    assert by_name["worker_1"].status == RunStatus.COMPLETED
    assert by_name["worker_2"].attempts == 1
