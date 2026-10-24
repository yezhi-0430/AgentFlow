"""
Langfuse 追踪加固回归测试（完全离线：假 SDK 客户端，不联网、不使用真实密钥）

覆盖任务要求的五类行为：
1. ``LANGFUSE_CAPTURE_CONTENT`` 默认关闭：task / 输入 / 输出 / 错误正文不落库，
   只保留 id、pattern、step_index、model、usage、level 与错误摘要；
2. 开启后内容可以记录，但 API Key / Bearer / Authorization / 环境变量值 /
   连接配置先被 ``sanitize()`` 脱敏；
3. 关闭追踪 / 缺密钥 / 缺 SDK 时优雅降级为 dummy 句柄；
4. SDK（初始化、create_trace_id、start_observation、update/end、flush）抛异常时
   业务返回值不变、last_error 有值、后续调用不受影响，且不吞掉业务原始异常；
5. 并行/异步步骤的 observation 都挂到同一个 trace，父节点正确。
"""
import asyncio
import hashlib
import json
import os
from unittest.mock import patch

import pytest

import agentflow.tracing.langfuse as langfuse_module
from agentflow.tracing.langfuse import (
    REDACTED,
    LangfuseTracer,
    TraceHandle,
    _DummySpan,
    _DummyTrace,
    optional_tracing,
    sanitize,
    sanitize_text,
)

def _fake_sk(rest: str) -> str:
    """构造测试用假 key；拆开拼接避免被仓库凭据扫描误判。"""
    return "sk-lf-" + rest


DEFAULT_PUBLIC_KEY = "pk-lf-test-public-key-0123456789"
DEFAULT_SECRET_KEY = _fake_sk("test-secret-key-" + "0123456789abcdef")
_UNSET = object()


# --------------------------------------------------------------- fake SDK 客户端
class FakeObservation:
    """假 observation：记录创建参数、更新、子节点与 end 次数。"""

    def __init__(self, name, trace_id, observation_type="span", parent=None):
        self.name = name
        self.trace_id = trace_id
        self.observation_type = observation_type
        self.parent = parent
        self.id = hashlib.md5(f"{trace_id}:{name}:{id(self)}".encode()).hexdigest()[:16]
        self.create_kwargs = {}
        self.children = []
        self.updates = {}
        self.ended = False
        self.end_calls = 0
        self.raise_on_update = False
        self.raise_on_child = False

    def update(self, **kwargs):
        if self.raise_on_update:
            raise RuntimeError("update boom")
        self.updates.update(kwargs)
        return self

    def end(self):
        self.ended = True
        self.end_calls += 1

    def start_observation(self, **kwargs):
        if self.raise_on_child:
            raise RuntimeError("child boom")
        child = FakeObservation(
            kwargs.get("name"), self.trace_id, kwargs.get("as_type", "span"), parent=self
        )
        child.create_kwargs = dict(kwargs)
        self.children.append(child)
        return child


class FakeLangfuse:
    """假 Langfuse 客户端：不联网，可注入各类异常。"""

    instances = []

    def __init__(self, public_key=None, secret_key=None, host=None, **kwargs):
        self.public_key = public_key
        self.secret_key = secret_key
        self.host = host
        self.seeds = []
        self.roots = []
        self.flush_calls = 0
        self.raise_on_create_trace_id = False
        self.raise_on_start_observation = False
        self.raise_on_flush = False
        FakeLangfuse.instances.append(self)

    def create_trace_id(self, seed=None):
        if self.raise_on_create_trace_id:
            raise RuntimeError("create_trace_id boom")
        self.seeds.append(seed)
        return hashlib.md5(f"langfuse-trace::{seed}".encode("utf-8")).hexdigest()

    def start_observation(self, **kwargs):
        if self.raise_on_start_observation:
            raise RuntimeError("start_observation boom")
        trace_context = kwargs.get("trace_context") or {}
        root = FakeObservation(
            kwargs.get("name"), trace_context.get("trace_id"), kwargs.get("as_type", "span")
        )
        root.create_kwargs = dict(kwargs)
        self.roots.append(root)
        return root

    def flush(self):
        self.flush_calls += 1
        if self.raise_on_flush:
            raise RuntimeError("flush boom")


class ExplodingLangfuse:
    """构造就抛异常，用于验证初始化失败隔离。"""

    def __init__(self, **kwargs):
        raise RuntimeError("langfuse init boom")


class FlushFailingLangfuse(FakeLangfuse):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.raise_on_flush = True


@pytest.fixture(autouse=True)
def _isolate_langfuse_state():
    """每个用例前后清空客户端缓存/假实例，避免相互污染。"""
    langfuse_module._CLIENTS.clear()
    FakeLangfuse.instances.clear()
    yield
    langfuse_module._CLIENTS.clear()
    FakeLangfuse.instances.clear()


def _install_fake_sdk(monkeypatch, secret_key=DEFAULT_SECRET_KEY, host=None, sdk_class=FakeLangfuse):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", DEFAULT_PUBLIC_KEY)
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", secret_key)
    if host:
        monkeypatch.setenv("LANGFUSE_HOST", host)
    else:
        monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.setattr(langfuse_module, "Langfuse", sdk_class)
    monkeypatch.setattr(langfuse_module, "SDK_AVAILABLE", True)


def make_tracer(monkeypatch, capture_content=_UNSET, secret_key=DEFAULT_SECRET_KEY, host=None):
    """构造一个启用追踪、注入假 SDK 客户端的 tracer。

    - ``capture_content`` 省略：按环境变量（默认未设置 -> false）决定；
    - ``capture_content=None``：显式清掉 env，走默认 false；
    - ``True/False``：显式设置 env 并传给构造函数。
    """
    _install_fake_sdk(monkeypatch, secret_key=secret_key, host=host)
    kwargs = {}
    if capture_content is not _UNSET:
        if capture_content is None:
            monkeypatch.delenv("LANGFUSE_CAPTURE_CONTENT", raising=False)
            kwargs["capture_content"] = None
        else:
            monkeypatch.setenv(
                "LANGFUSE_CAPTURE_CONTENT", "true" if capture_content else "false"
            )
            kwargs["capture_content"] = bool(capture_content)
    tracer = LangfuseTracer(enabled=True, **kwargs)
    assert tracer.enabled is True
    assert isinstance(tracer.client, FakeLangfuse)
    return tracer


def _json(value):
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def _observation_payload(observation):
    """把 observation 树上所有会被上传的数据摊平成可检索结构。"""
    payload = {"create": observation.create_kwargs, "updates": observation.updates}
    for child in observation.children:
        payload[f"child:{child.name}"] = _observation_payload(child)
    return payload


# ---------------------------------------------------------------- 1. sanitize 单元
@pytest.mark.parametrize(
    "raw, banned",
    [
        ("prefix " + _fake_sk("0123456789abcdef" * 2) + " suffix", _fake_sk("0123456789abcdef" * 2)),
        ("pk-lf-abcdef1234567890", "pk-lf-abcdef1234567890"),
        ("sk-or-v1-aaaaaaaaaaaaaaaa", "sk-or-v1-aaaaaaaaaaaaaaaa"),
        ("Authorization: Bearer abcdef1234567890", "abcdef1234567890"),
        ("Bearer eyJhbGciOiJIUzI1NiJ9.abcdef", "eyJhbGciOiJIUzI1NiJ9.abcdef"),
        ("OPENAI_API_KEY=sk-or-v1-ffffffffffff", "sk-or-v1-ffffffffffff"),
        ("LANGFUSE_SECRET_KEY=sk-lf-valuesecret123456", "valuesecret123456"),
        ("token " + "a" * 40, "a" * 40),
        ("hex " + "deadbeef" * 8, "deadbeef" * 8),
        ("base_url=https://cloud.langfuse.com", "cloud.langfuse.com"),
        ("LANGFUSE_HOST=https://langfuse.internal", "langfuse.internal"),
    ],
)
def test_sanitize_text_redacts_secret_shapes(raw, banned):
    cleaned = sanitize_text(raw)
    assert banned not in cleaned, f"敏感值未被脱敏: {cleaned!r}"
    assert REDACTED in cleaned


def test_sanitize_text_keeps_harmless_content():
    raw = "hello world 你好，这是普通内容。"
    assert sanitize_text(raw) == raw


def test_sanitize_text_redacts_authorization_header_labels():
    cleaned = sanitize_text("Authorization: Bearer abcdef1234567890")
    assert "Authorization" in cleaned
    assert "Bearer" not in cleaned
    assert "abcdef1234567890" not in cleaned


def test_sanitize_redacts_dict_secret_keys_and_drops_connection_config():
    cleaned = sanitize(
        {
            "api_key": "whatever-value",
            "OPENAI_API_KEY": "whatever-value",
            "Authorization": "Bearer whatever-token-123456",
            "host": "https://langfuse.internal",
            "base_url": "https://langfuse.internal",
            "task": "normal task",
            "usage": {"total_tokens": 30},
            "nested": {"secret": "abc123456"},
        }
    )
    assert cleaned["api_key"] == REDACTED
    assert cleaned["OPENAI_API_KEY"] == REDACTED
    assert cleaned["Authorization"] == REDACTED
    assert "host" not in cleaned
    assert "base_url" not in cleaned
    assert cleaned["task"] == "normal task"
    assert cleaned["usage"]["total_tokens"] == 30
    assert cleaned["nested"]["secret"] == REDACTED


def test_sanitize_extra_secrets_are_masked():
    cleaned = sanitize("value=my-super-custom-credential", extra_secrets=["my-super-custom-credential"])
    assert "my-super-custom-credential" not in cleaned
    assert REDACTED in cleaned


def test_sanitize_is_idempotent():
    once = sanitize_text("Authorization: Bearer abcdef1234567890")
    assert sanitize_text(once) == once


# ------------------------------------------------- 2. 内容采集开关 / 默认不落内容
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("true", True),
        ("1", True),
        ("YES", True),
        ("on", True),
        ("false", False),
        ("0", False),
        ("off", False),
        ("", False),
        ("unknown-value", False),
    ],
)
def test_capture_content_env_flag(monkeypatch, raw, expected):
    monkeypatch.setenv("LANGFUSE_CAPTURE_CONTENT", raw)
    tracer = LangfuseTracer(enabled=False)
    assert tracer.capture_content is expected
    assert tracer.enabled is False


def test_capture_content_disabled_by_default(monkeypatch):
    tracer = make_tracer(monkeypatch, capture_content=None)
    assert tracer.capture_content is False

    handle = tracer.trace_workflow(
        workflow_id="wf-1",
        run_id="run-1",
        name="demo",
        metadata={"pattern": "sequential", "task": "TOP SECRET TASK BODY"},
    )
    assert isinstance(handle, TraceHandle)
    root = tracer.client.roots[0]

    payload = _json(_observation_payload(root))
    assert "TOP SECRET TASK BODY" not in payload
    assert "task" not in root.create_kwargs["metadata"]
    assert root.create_kwargs["metadata"]["workflow_id"] == "wf-1"
    assert root.create_kwargs["metadata"]["run_id"] == "run-1"
    assert root.create_kwargs["metadata"]["pattern"] == "sequential"
    assert root.create_kwargs["input"]["workflow_id"] == "wf-1"
    assert "task" not in root.create_kwargs["input"]

    span = tracer.trace_step(
        trace=handle,
        step_id="step_1",
        agent_name="worker_1",
        input_text="USER INPUT TEXT",
        metadata={"step_index": 0, "agent_model": "gpt-4o-mini"},
    )
    assert "input" not in span.create_kwargs
    assert span.create_kwargs["metadata"]["step_id"] == "step_1"
    assert span.create_kwargs["metadata"]["step_index"] == 0
    assert span.create_kwargs["model"] == "gpt-4o-mini"

    tracer.update_step(
        span=span,
        output="MODEL OUTPUT TEXT",
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    )
    assert "output" not in span.updates
    assert span.updates["usage_details"] == {"input": 10, "output": 5, "total": 15}
    assert span.ended is True

    # 错误正文不落库，只保留类型 + 截断到 200 字符的摘要
    error_span = tracer.trace_step(
        trace=handle, step_id="step_2", agent_name="worker_2", input_text="x"
    )
    big_error = "ValueError: secret-detail " + "E" * 500
    tracer.update_step(span=error_span, error=big_error)
    assert error_span.updates["level"] == "ERROR"
    summary = error_span.updates["status_message"]
    assert len(summary) <= 200
    assert "E" * 500 not in summary
    assert error_span.ended is True

    tracer.end_trace(
        handle,
        output={
            "status": "completed",
            "final_result": "FINAL OUTPUT TEXT",
            "run_id": "run-1",
            "steps": 2,
        },
        metadata={"elapsed_time": 1.25, "messages": 3},
        level="ERROR",
        status_message=big_error,
    )
    assert root.ended is True
    assert "FINAL OUTPUT TEXT" not in _json(root.updates)
    assert root.updates["output"]["status"] == "completed"
    assert root.updates["output"]["run_id"] == "run-1"
    assert "final_result" not in root.updates["output"]
    assert root.updates["metadata"]["elapsed_time"] == 1.25
    assert root.updates["metadata"]["messages"] == 3
    assert len(root.updates["status_message"]) <= 200
    assert tracer.last_error is None


def test_capture_content_enabled_records_sanitized_content(monkeypatch):
    secret = "sk-lf-real-secret-0123456789abcdef"
    tracer = make_tracer(monkeypatch, capture_content=True, secret_key=secret)
    assert tracer.capture_content is True

    task = (
        f"please use token {secret} and "
        "OPENAI_API_KEY=sk-or-v1-abcdefghijklmnop and "
        "Authorization: Bearer tokentokentoken1234"
    )
    handle = tracer.trace_workflow(
        workflow_id="wf",
        run_id="run",
        name="demo",
        metadata={
            "pattern": "sequential",
            "task": task,
            "host": "https://langfuse.internal",
            "base_url": "https://langfuse.internal",
        },
    )
    root = tracer.client.roots[0]
    payload = _json(_observation_payload(root))

    # 内容本身允许记录，但所有敏感值必须已被替换
    assert "please use token" in payload
    assert task not in payload
    assert secret not in payload
    assert "sk-or-v1-abcdefghijklmnop" not in payload
    assert "tokentokentoken1234" not in payload
    assert "langfuse.internal" not in payload
    assert os.environ["LANGFUSE_SECRET_KEY"] not in payload
    assert REDACTED in payload
    assert "task" in root.create_kwargs["metadata"]
    assert "task" in root.create_kwargs["input"]
    assert "host" not in root.create_kwargs["metadata"]
    assert "base_url" not in root.create_kwargs["metadata"]

    span = tracer.trace_step(
        trace=handle,
        step_id="s1",
        agent_name="worker",
        input_text=f"input with {secret}",
        metadata={"step_index": 0, "agent_model": "gpt-4o"},
    )
    tracer.update_step(span=span, output=f"output with Bearer {secret}", usage={"total_tokens": 7})
    tracer.end_trace(
        handle,
        output={"status": "completed", "final_result": f"final {secret}"},
        metadata={"elapsed_time": 0.5},
    )

    payload = _json(_observation_payload(root))
    assert secret not in payload
    assert "output with" in payload
    assert "Bearer [REDACTED]" in payload
    assert REDACTED in payload
    assert tracer.last_error is None


# ----------------------------------------------------- 3. 降级为 dummy（关闭/缺配置）
def test_missing_credentials_returns_dummy(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.setattr(langfuse_module, "Langfuse", FakeLangfuse)
    monkeypatch.setattr(langfuse_module, "SDK_AVAILABLE", True)

    tracer = LangfuseTracer(enabled=True)
    assert tracer.enabled is False
    assert tracer.client is None

    trace = tracer.trace_workflow(
        workflow_id="wf", run_id="run", name="demo", metadata={"task": "t"}
    )
    span = tracer.trace_step(trace=trace, step_id="s", agent_name="a", input_text="i")
    assert isinstance(trace, _DummyTrace)
    assert isinstance(span, _DummySpan)

    tracer.update_step(span=span, output="o", error="e")
    tracer.end_trace(trace, output="o", level="ERROR", status_message="boom")
    tracer.flush()
    assert tracer.trace_id_for_run("run") is None
    assert tracer.last_error is None


def test_sdk_missing_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(langfuse_module, "SDK_AVAILABLE", False)
    tracer = LangfuseTracer(enabled=True)
    assert tracer.enabled is False
    assert isinstance(
        tracer.trace_workflow(workflow_id="wf", run_id="r", name="n"), _DummyTrace
    )


def test_disabled_tracer_returns_dummy(monkeypatch):
    tracer = LangfuseTracer(enabled=False)
    assert tracer.enabled is False
    trace = tracer.trace_workflow(workflow_id="wf", run_id="r", name="n")
    span = tracer.trace_step(trace=trace, step_id="s", agent_name="a", input_text="i")
    assert isinstance(trace, _DummyTrace)
    assert isinstance(span, _DummySpan)
    tracer.update_step(span=span, output="o")
    tracer.end_trace(trace, output={})
    tracer.flush()


def test_init_exception_is_isolated(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", DEFAULT_PUBLIC_KEY)
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", DEFAULT_SECRET_KEY)
    monkeypatch.setattr(langfuse_module, "Langfuse", ExplodingLangfuse)
    monkeypatch.setattr(langfuse_module, "SDK_AVAILABLE", True)

    tracer = LangfuseTracer(enabled=True)
    assert tracer.enabled is False
    assert tracer.client is None
    assert tracer.last_error and "init boom" in tracer.last_error
    assert isinstance(
        tracer.trace_workflow(workflow_id="wf", run_id="r", name="n"), _DummyTrace
    )


# --------------------------------------------------------- 4. SDK 异常失败隔离
def test_sdk_errors_never_change_business_flow(monkeypatch):
    tracer = make_tracer(monkeypatch)

    # 1) create_trace_id 抛错 -> dummy，业务继续
    tracer.client.raise_on_create_trace_id = True
    trace = tracer.trace_workflow(
        workflow_id="wf", run_id="r", name="n", metadata={"task": "t"}
    )
    assert isinstance(trace, _DummyTrace)
    assert tracer.last_error and "create_trace_id boom" in tracer.last_error

    # 2) 根 span 创建抛错 -> dummy
    tracer.client.raise_on_create_trace_id = False
    tracer.client.raise_on_start_observation = True
    trace = tracer.trace_workflow(workflow_id="wf", run_id="r", name="n")
    assert isinstance(trace, _DummyTrace)
    assert tracer.last_error and "start_observation boom" in tracer.last_error

    # 3) 恢复后新调用完全不受影响
    tracer.client.raise_on_start_observation = False
    handle = tracer.trace_workflow(workflow_id="wf", run_id="run-ok", name="n")
    assert isinstance(handle, TraceHandle)
    span = tracer.trace_step(trace=handle, step_id="s1", agent_name="a", input_text="i")
    assert span.parent is tracer.client.roots[0]
    assert span.trace_id == handle.trace_id

    # 4) span.update 抛错时 end 仍执行；后续步骤仍正常
    span.raise_on_update = True
    tracer.update_step(span=span, output="o", usage={"total_tokens": 1})
    assert span.ended is True
    assert span.end_calls == 1
    assert tracer.last_error and "update boom" in tracer.last_error

    # 5) 父 span 派生抛错 -> dummy，之后子 span 仍能正确挂回父节点
    root = tracer.client.roots[0]
    root.raise_on_child = True
    bad = tracer.trace_step(trace=handle, step_id="s2", agent_name="a", input_text="i")
    assert isinstance(bad, _DummySpan)
    assert tracer.last_error and "child boom" in tracer.last_error
    root.raise_on_child = False
    good = tracer.trace_step(trace=handle, step_id="s3", agent_name="a", input_text="i")
    assert good.parent is root

    # 6) end_trace 的 update 抛错时根 span 仍 end
    root.raise_on_update = True
    tracer.end_trace(
        handle,
        output={"status": "completed"},
        metadata={"elapsed_time": 1.0},
        level="ERROR",
        status_message="boom",
    )
    assert root.ended is True
    assert tracer.last_error and "update boom" in tracer.last_error


def test_step_falls_back_to_trace_context_when_root_span_missing(monkeypatch):
    tracer = make_tracer(monkeypatch)
    handle = TraceHandle(span=None, trace_id="d" * 32, metadata={})
    span = tracer.trace_step(trace=handle, step_id="s", agent_name="a", input_text="i")
    root = tracer.client.roots[0]
    assert root.create_kwargs["trace_context"] == {"trace_id": "d" * 32}
    assert span.trace_id == "d" * 32


def test_error_summary_keeps_type_and_truncates(monkeypatch):
    tracer = make_tracer(monkeypatch)
    handle = tracer.trace_workflow(workflow_id="wf", run_id="r", name="n")
    span = tracer.trace_step(trace=handle, step_id="s", agent_name="a", input_text="i")

    tracer.update_step(span=span, error=ValueError("detail " + "x" * 500))
    summary = span.updates["status_message"]
    assert summary.startswith("ValueError")
    assert "detail" in summary
    assert len(summary) <= 200

    big = RuntimeError("boom " + "y" * 500)
    tracer.end_trace(handle, output={"status": "failed"}, level="ERROR", status_message=big)
    root = tracer.client.roots[0]
    assert root.updates["level"] == "ERROR"
    assert len(root.updates["status_message"]) <= 200


def test_flush_exception_is_isolated(monkeypatch):
    tracer = make_tracer(monkeypatch)
    tracer.client.raise_on_flush = True
    tracer.flush()
    assert tracer.last_error and "flush boom" in tracer.last_error
    tracer.flush()  # 重复调用同样安全
    assert tracer.client.flush_calls == 2


def test_business_exception_survives_optional_tracing_flush_error(monkeypatch):
    """finally 路径里的 flush 异常不能覆盖业务方正在抛出的原始异常。"""
    _install_fake_sdk(monkeypatch, sdk_class=FlushFailingLangfuse)

    with pytest.raises(ValueError, match="business boom"):
        with optional_tracing(enabled=True) as tracer:
            assert tracer is not None
            assert tracer.enabled is True
            raise ValueError("business boom")


def test_secrets_and_connection_config_are_not_printed(monkeypatch, capsys):
    secret = _fake_sk("print-secret-" + "0123456789abcdef")
    tracer = make_tracer(
        monkeypatch,
        capture_content=True,
        secret_key=secret,
        host="https://langfuse.internal.example",
    )
    handle = tracer.trace_workflow(
        workflow_id="wf",
        run_id="run",
        name="demo",
        metadata={"pattern": "sequential", "task": f"task with {secret}"},
    )
    span = tracer.trace_step(
        trace=handle, step_id="s", agent_name="a", input_text=f"input {secret}"
    )
    tracer.update_step(span=span, output=f"output {secret}", error=f"error {secret}")
    tracer.end_trace(handle, output=f"final {secret}", status_message=f"error {secret}")
    tracer.flush()

    printed = capsys.readouterr().out
    assert secret not in printed
    assert "langfuse.internal.example" not in printed


# ------------------------------------------- 5. 并行/异步父子关系（离线假 SDK）
@pytest.mark.asyncio
async def test_parallel_steps_share_trace_and_parent(monkeypatch):
    tracer = make_tracer(monkeypatch)
    handle = tracer.trace_workflow(
        workflow_id="wf",
        run_id="run-parallel",
        name="demo",
        metadata={"pattern": "parallel", "task": "parallel task"},
    )
    root = tracer.client.roots[0]

    async def create_step(index):
        return tracer.trace_step(
            trace=handle,
            step_id=f"step_{index}",
            agent_name=f"worker_{index}",
            input_text=f"input {index}",
            metadata={"step_index": index, "agent_model": "fake-model"},
        )

    spans = await asyncio.gather(*(create_step(i) for i in range(4)))

    assert len(root.children) == 4, "并行步骤都必须挂到同一个根 span"
    assert handle.trace_id == root.trace_id
    for index, span in enumerate(spans):
        assert span.parent is root
        assert span.trace_id == root.trace_id
        assert span.create_kwargs["metadata"]["step_id"] == f"step_{index}"
        assert span.create_kwargs["metadata"]["step_index"] == index

    # 完成顺序与创建顺序不同（并行完成），父子关系不受影响
    for span in reversed(spans):
        tracer.update_step(span=span, output="done", usage={"total_tokens": 3})
    assert all(span.ended for span in spans)
    assert root.ended is False

    tracer.end_trace(handle, output={"status": "completed", "run_id": "run-parallel"})
    assert root.ended is True
    assert tracer.last_error is None


def test_parallel_failure_does_not_poison_other_steps(monkeypatch):
    tracer = make_tracer(monkeypatch, capture_content=True)
    handle = tracer.trace_workflow(
        workflow_id="wf",
        run_id="run-fail",
        name="demo",
        metadata={"pattern": "parallel", "task": "task"},
    )
    root = tracer.client.roots[0]
    span_a = tracer.trace_step(trace=handle, step_id="a", agent_name="agent_a", input_text="a")
    span_b = tracer.trace_step(trace=handle, step_id="b", agent_name="agent_b", input_text="b")
    assert [child.name for child in root.children] == ["agent_a", "agent_b"]

    # 一个步骤的 update 抛异常：自己仍然被 end，另一个步骤不受影响
    span_a.raise_on_update = True
    tracer.update_step(span=span_a, output="will fail")
    assert span_a.ended is True
    assert tracer.last_error and "update boom" in tracer.last_error

    tracer.update_step(span=span_b, output="still ok")
    assert span_b.updates["output"] == "still ok"
    assert span_b.ended is True

    # 父节点派生一次失败：后续步骤仍然正确挂到父节点
    root.raise_on_child = True
    dummy = tracer.trace_step(trace=handle, step_id="c", agent_name="agent_c", input_text="c")
    assert isinstance(dummy, _DummySpan)
    root.raise_on_child = False
    span_d = tracer.trace_step(trace=handle, step_id="d", agent_name="agent_d", input_text="d")
    assert span_d.parent is root
    assert [child.name for child in root.children] == ["agent_a", "agent_b", "agent_d"]

    tracer.end_trace(handle, output={"status": "partial"})
    assert root.ended is True
