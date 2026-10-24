"""
自动评估（LLM-as-a-Judge）→ Langfuse 评分 的离线测试

覆盖之前的两个问题：
1. auto_evaluate_workflow 从未被调用（现在由 WorkflowExecutor 在 finally 里调用）
2. 写评分用了 v5 不存在的 client.score / 用 run_id 当 trace_id
"""
import json
from types import SimpleNamespace

import pytest

from agentflow.core.auto_evaluate import auto_evaluate_workflow, extract_final_output


class FakeScoreClient:
    def __init__(self):
        self.scores = []

    def create_score(self, **kwargs):
        self.scores.append(kwargs)


class FakeTracer:
    def __init__(self, enabled=True, client=None):
        self.enabled = enabled
        self.client = client if client is not None else FakeScoreClient()
        self.trace_id_calls = []

    def trace_id_for_run(self, run_id):
        self.trace_id_calls.append(run_id)
        return "f" * 32


class FakeRun:
    def __init__(self, run_id="run-1", final_result="最终输出内容", step_results=None):
        self.run_id = run_id
        self.final_result = final_result
        self.step_results = step_results or []


@pytest.fixture(autouse=True)
def eval_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("EVAL_MODEL", "test-model")


def fake_openai(monkeypatch, content='{"score": 85, "reasoning": "很好"}', raises=None):
    class FakeCompletions:
        async def create(self, **kwargs):
            if raises is not None:
                raise raises
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
            )

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            self.init_kwargs = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeAsyncOpenAI)


@pytest.mark.asyncio
async def test_score_is_written_to_langfuse(monkeypatch):
    fake_openai(monkeypatch)
    monkeypatch.setenv("LANGFUSE_CAPTURE_CONTENT", "true")
    tracer = FakeTracer()

    outcome = await auto_evaluate_workflow(
        tracer, FakeRun(), {"result": {"final_result": "待评估文本"}}
    )

    assert outcome["score"] == 85
    assert outcome["trace_id"] == "f" * 32
    assert tracer.trace_id_calls == ["run-1"], "必须由 run_id 推导真实 trace_id"

    score = tracer.client.scores[0]
    assert score["name"] == "auto-quality"
    assert score["value"] == 85
    assert score["trace_id"] == "f" * 32
    assert score["data_type"] == "NUMERIC"
    assert score["comment"] == "很好"
    assert score["metadata"]["model"] == "test-model"


@pytest.mark.asyncio
async def test_score_comment_is_gated_by_capture_flag(monkeypatch):
    """默认不采集内容：评分仍写入，但不带评审理由文本"""
    fake_openai(monkeypatch)
    monkeypatch.delenv("LANGFUSE_CAPTURE_CONTENT", raising=False)
    tracer = FakeTracer()

    await auto_evaluate_workflow(tracer, FakeRun(), {"result": {"final_result": "x"}})

    score = tracer.client.scores[0]
    assert score["value"] == 85
    assert score["comment"] is None
    assert score["metadata"]["run_id"] == "run-1"


@pytest.mark.asyncio
async def test_explicit_trace_id_is_preferred(monkeypatch):
    fake_openai(monkeypatch)
    tracer = FakeTracer()

    await auto_evaluate_workflow(
        tracer, FakeRun(), {"result": {"final_result": "x"}}, trace_id="a" * 32
    )

    assert tracer.client.scores[0]["trace_id"] == "a" * 32
    assert tracer.trace_id_calls == []


@pytest.mark.asyncio
async def test_skips_without_api_key(monkeypatch):
    fake_openai(monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    tracer = FakeTracer()

    outcome = await auto_evaluate_workflow(
        tracer, FakeRun(), {"result": {"final_result": "x"}}
    )

    assert outcome is None
    assert tracer.client.scores == []


@pytest.mark.asyncio
async def test_skips_when_tracing_disabled(monkeypatch):
    fake_openai(monkeypatch)
    tracer = FakeTracer(enabled=False)

    outcome = await auto_evaluate_workflow(
        tracer, FakeRun(), {"result": {"final_result": "x"}}
    )

    assert outcome is None
    assert tracer.client.scores == []


@pytest.mark.asyncio
async def test_skips_when_no_output(monkeypatch):
    fake_openai(monkeypatch)
    tracer = FakeTracer()
    run = FakeRun(final_result=None, step_results=[])

    outcome = await auto_evaluate_workflow(tracer, run, None)

    assert outcome is None
    assert tracer.client.scores == []


@pytest.mark.asyncio
async def test_judge_failure_never_raises(monkeypatch):
    fake_openai(monkeypatch, raises=RuntimeError("network down"))
    tracer = FakeTracer()

    outcome = await auto_evaluate_workflow(
        tracer, FakeRun(), {"result": {"final_result": "x"}}
    )

    assert outcome is None
    assert tracer.client.scores == []


@pytest.mark.asyncio
async def test_unparsable_judge_output_skipped(monkeypatch):
    fake_openai(monkeypatch, content="这不是 JSON")
    tracer = FakeTracer()

    outcome = await auto_evaluate_workflow(
        tracer, FakeRun(), {"result": {"final_result": "x"}}
    )

    assert outcome is None
    assert tracer.client.scores == []


def test_extract_final_output_across_patterns():
    assert extract_final_output(None, {"result": {"final_result": "seq"}}) == "seq"
    assert extract_final_output(None, {"result": {"aggregated": "par"}}) == "par"
    assert extract_final_output(None, {"result": {"winner": "vote"}}) == "vote"
    assert extract_final_output(FakeRun(final_result="run-final"), None) == "run-final"


def test_extract_final_output_truncates_long_text():
    long_text = "x" * 5000
    text = extract_final_output(FakeRun(final_result=long_text), None)
    assert text.endswith("...")
    assert len(text) == 2000 + 3
