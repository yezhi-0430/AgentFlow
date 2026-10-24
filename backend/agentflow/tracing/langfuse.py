"""
Langfuse 追踪适配器 - 适配 Langfuse Python SDK 5.x（OpenTelemetry 内核）

5.x 的三条关键语义（本适配器就是按它们实现的）：

1. ``client.start_observation()`` 创建的是"游离" observation，不会挂到当前上下文。
   如果在顶层调用它、又不传 ``trace_context``，每个 span 都会各自成为一个独立 trace，
   看起来就像"数据没发出去/找不到"。子 span 必须从父 span 派生
   （``parent.start_observation(...)``）或显式传 ``trace_context``。
2. observation 必须显式 ``end()`` 才会被 OTel 批量导出；只创建不 end 的 span
   永远不会发送到服务端。
3. 想让业务 id（例如 ``run_id``）成为 trace id，需要在创建根 span 时传
   ``trace_context={"trace_id": client.create_trace_id(seed=run_id)}``，
   不能事后给 Python 属性赋值（``observation.trace_id = ...`` 只改本地属性）。

加固语义（本文件同时负责，上层 workflow 无需改动）：

- 内容采集开关 ``LANGFUSE_CAPTURE_CONTENT``（默认 false，只在 tracer 初始化时读取）：
  关闭时不把 task / 输入文本 / 输出文本 / 错误正文上传到 Langfuse，只保留
  workflow_id、run_id、step_id、agent_name、pattern、step_index、model、usage
  （token 数）、level 与错误类型/摘要；上层照常把 input/output 传给 tracer，
  由 tracer 内部决定是否落库，接口签名保持兼容。
- 开启时内容先经 ``sanitize()``：掩掉疑似 API Key（sk-...、pk-lf-...、sk-lf-...）、
  Bearer token、Authorization 头、LANGFUSE_* / OPENAI_* / *_KEY / *_SECRET /
  *_TOKEN 形式的值，以及长十六进制/字母数字串；host / base_url 等连接配置不记录。
- 失败隔离：初始化、trace_workflow、trace_step、update_step、end_trace、flush
  的任何异常都只写入 ``last_error`` 并打印简短脱敏日志，不改变业务返回值，
  也不吞掉业务方正在抛出的原始异常（包括 finally 路径）。
- 未配置密钥或未安装 SDK 时保持优雅降级：返回 dummy 句柄，业务照常执行。
"""
import os
import re
import threading
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Set

try:  # pragma: no cover - 依赖缺失时走优雅降级分支
    from langfuse import Langfuse
    SDK_AVAILABLE = True
except Exception:  # noqa: BLE001 - 任何导入问题都只关闭追踪，不影响业务
    Langfuse = None  # type: ignore[assignment]
    SDK_AVAILABLE = False


__all__ = [
    "LangfuseTracer",
    "TraceHandle",
    "optional_tracing",
    "sanitize",
    "sanitize_text",
    "REDACTED",
    "CAPTURE_CONTENT_ENV",
]


# OpenAI 风格 usage key -> Langfuse usage_details key
_USAGE_KEY_MAP = {
    "prompt_tokens": "input",
    "completion_tokens": "output",
    "total_tokens": "total",
    "input": "input",
    "output": "output",
    "total": "total",
}

# ---------------------------------------------------------------- 内容采集策略
CAPTURE_CONTENT_ENV = "LANGFUSE_CAPTURE_CONTENT"
DEFAULT_CAPTURE_CONTENT = False
REDACTED = "[REDACTED]"
MAX_ERROR_SUMMARY_CHARS = 200
MAX_LOG_CHARS = 300

_TRUTHY_VALUES = {"1", "true", "yes", "y", "on", "t"}
_FALSY_VALUES = {"", "0", "false", "no", "n", "off", "f"}

# 元数据里属于“用户内容”的 key：关闭内容采集时整体丢弃
_CONTENT_KEYS: Set[str] = {
    "task",
    "task_input",
    "initial_task",
    "input",
    "inputs",
    "input_text",
    "output",
    "outputs",
    "output_text",
    "result",
    "results",
    "final_result",
    "aggregated",
    "winner",
    "prompt",
    "response",
    "completion",
    "content",
    "text",
    "raw",
    "transcript",
    "messages_content",
    "error_detail",
    "error_body",
    "error_message",
    "error_reason",
    "error_trace",
    "stacktrace",
    "stack_trace",
    "task_summary",
    "user_message",
    "assistant_message",
    "reasoning",
    "answer",
}

# 连接配置：无论采集开关如何都不记录
_CONNECTION_KEYS: Set[str] = {
    "host",
    "base_url",
    "baseurl",
    "base_uri",
    "endpoint",
    "server",
    "server_url",
    "api_base",
    "api_url",
    "url",
    "dsn",
    "openai_base_url",
    "langfuse_host",
    "langfuse_base_url",
}

# 键名命中这些形态时，值一律视为密钥
_SECRET_EXACT_KEYS: Set[str] = {
    "authorization",
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "private_key",
    "credential",
    "credentials",
    "cookie",
    "set_cookie",
    "connection_string",
}
_SECRET_KEY_SUFFIXES = (
    "_key",
    "_secret",
    "_token",
    "_password",
    "_passwd",
    "_credential",
    "_credentials",
    "_authorization",
)

# 这些 *_TOKEN(S) 是公开的用量字段，不属于密钥（避免误伤 usage 统计）
_SAFE_TOKEN_FIELD_NAMES = {
    "TOTAL_TOKENS",
    "PROMPT_TOKENS",
    "COMPLETION_TOKENS",
    "INPUT_TOKENS",
    "OUTPUT_TOKENS",
    "MAX_TOKENS",
    "TOKEN_COUNT",
}

# ---------------------------------------------------------------- 脱敏正则
# 形如 OPENAI_API_KEY=... / LANGFUSE_SECRET_KEY=... / ANY_SECRET=...
_SENSITIVE_ENV_NAME = (
    r"(?:LANGFUSE|OPENAI)_[A-Z0-9_]+"
    r"|[A-Z0-9_]*(?:API[_-]?KEY|ACCESS[_-]?KEY|SECRET[_-]?KEY|PRIVATE[_-]?KEY"
    r"|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL)"
)
_ENV_ASSIGN_RE = re.compile(
    r"(?i)\b(" + _SENSITIVE_ENV_NAME + r")\b(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;}]+)"
)
_AUTHORIZATION_RE = re.compile(
    r"(?i)\b(authorization)(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\r\n,;}]+)"
)
_BEARER_RE = re.compile(r"(?i)\b(Bearer|Basic)\s+([A-Za-z0-9._~+/=\-]{4,})")
_PREFIXED_KEY_RE = re.compile(r"(?i)\b(?:sk|pk|rk)-[A-Za-z0-9][A-Za-z0-9_\-]{2,}")
_CONNECTION_ASSIGN_RE = re.compile(
    r"(?i)\b((?:langfuse_|openai_|api_)?"
    r"(?:base[_-]?url|base[_-]?uri|host|endpoint|server[_-]?url|api[_-]?base))"
    r"(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;}]+)"
)
_LONG_HEX_RE = re.compile(r"(?<![A-Za-z0-9])[0-9a-fA-F]{32,}(?![A-Za-z0-9])")
_LONG_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]{32,}(?![A-Za-z0-9])")


def _env_flag(name: str, default: bool = False) -> bool:
    """读取布尔环境变量；无法识别时回退默认值（默认关闭，偏安全）。"""
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUTHY_VALUES:
        return True
    if value in _FALSY_VALUES:
        return False
    return default


def _collect_env_secrets() -> List[str]:
    """收集当前进程里“看起来是密钥/连接配置”的环境变量值，用于精确替换。

    只收集长度 >= 6 的值，避免把常用短词误当密钥；长值优先，防止
    短值先替换破坏长 token。
    """
    found: Set[str] = set()
    for name, value in os.environ.items():
        if not value or len(value) < 6:
            continue
        upper = name.upper()
        sensitive = (
            upper.startswith("LANGFUSE_")
            or upper.startswith("OPENAI_")
            or "API_KEY" in upper
            or upper.endswith(
                ("_KEY", "_SECRET", "_TOKEN", "_PASSWORD", "_PASSWD", "_CREDENTIAL")
            )
        )
        if sensitive and value not in REDACTED:
            found.add(value)
    return sorted(found, key=len, reverse=True)


def _is_secret_key(key: Any) -> bool:
    lowered = str(key).strip().lower().replace("-", "_")
    if not lowered:
        return False
    if lowered in _SECRET_EXACT_KEYS:
        return True
    return lowered.endswith(_SECRET_KEY_SUFFIXES)


def _is_content_key(key: Any) -> bool:
    lowered = str(key).strip().lower().replace("-", "_")
    if lowered in _CONTENT_KEYS:
        return True
    return lowered.endswith(("_text", "_content", "_output", "_input", "_result", "_prompt"))


def _redact_env_assignment(match: "re.Match[str]") -> str:
    name = match.group(1).upper()
    if name in _SAFE_TOKEN_FIELD_NAMES:
        return match.group(0)
    return f"{match.group(1)}{match.group(2)}{REDACTED}"


def _redact_connection_assignment(match: "re.Match[str]") -> str:
    return f"{match.group(1)}{match.group(2)}{REDACTED}"


def _redact_authorization(match: "re.Match[str]") -> str:
    return f"{match.group(1)}{match.group(2)}{REDACTED}"


def _redact_bearer(match: "re.Match[str]") -> str:
    return f"{match.group(1)} {REDACTED}"


def sanitize_text(text: Any, extra_secrets: Optional[List[str]] = None) -> str:
    """对文本做脱敏，返回可安全上传/打印的字符串。

    覆盖：Authorization / Bearer、sk-/pk-lf-/sk-lf- 等 API Key、环境变量形式的
    LANGFUSE_* / OPENAI_* / *_KEY / *_SECRET / *_TOKEN 值、base_url/host 等连接
    配置值、长十六进制/字母数字串，以及 ``extra_secrets`` 中给出的精确密钥值。
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    if not text:
        return text

    text = _ENV_ASSIGN_RE.sub(_redact_env_assignment, text)
    text = _CONNECTION_ASSIGN_RE.sub(_redact_connection_assignment, text)
    text = _AUTHORIZATION_RE.sub(_redact_authorization, text)
    text = _BEARER_RE.sub(_redact_bearer, text)
    text = _PREFIXED_KEY_RE.sub(REDACTED, text)
    text = _LONG_HEX_RE.sub(REDACTED, text)
    text = _LONG_TOKEN_RE.sub(REDACTED, text)

    secrets = _collect_env_secrets() if extra_secrets is None else extra_secrets
    for secret in secrets:
        if secret and secret not in REDACTED and secret in text:
            text = text.replace(secret, REDACTED)
    return text


def sanitize(value: Any, extra_secrets: Optional[List[str]] = None, *, _depth: int = 0) -> Any:
    """递归脱敏任意结构（str / dict / list / tuple / set / 标量）。

    - 字符串：走 :func:`sanitize_text`
    - dict：连接配置 key 整体丢弃、密钥类 key 的值替换为 ``[REDACTED]``，
      其余值递归脱敏
    - 数字 / 布尔 / None：原样返回，避免破坏 usage 等统计
    """
    if _depth > 25:  # 防御异常深层结构
        return REDACTED
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return sanitize_text(value, extra_secrets)
    if isinstance(value, bytes):
        return sanitize_text(value.decode("utf-8", errors="replace"), extra_secrets)
    if isinstance(value, dict):
        cleaned: Dict[str, Any] = {}
        for key, item in value.items():
            key_text = sanitize_text(str(key), extra_secrets)
            lowered = str(key).strip().lower().replace("-", "_")
            if lowered in _CONNECTION_KEYS:
                continue
            if _is_secret_key(key):
                cleaned[key_text] = REDACTED
            else:
                cleaned[key_text] = sanitize(item, extra_secrets, _depth=_depth + 1)
        return cleaned
    if isinstance(value, (list, tuple, set)):
        return [sanitize(item, extra_secrets, _depth=_depth + 1) for item in value]
    return sanitize_text(str(value), extra_secrets)


def _format_error(error: Any, extra_secrets: Optional[List[str]] = None) -> str:
    """把异常/错误文本转成“类型 + 摘要”，先脱敏再截断到 200 字符。"""
    if error is None:
        return ""
    if isinstance(error, BaseException):
        text = f"{type(error).__name__}: {error}"
    else:
        text = str(error)
    text = sanitize_text(text, extra_secrets).strip()
    if len(text) > MAX_ERROR_SUMMARY_CHARS:
        text = text[:MAX_ERROR_SUMMARY_CHARS]
    return text


def _normalize_usage(usage: Optional[Dict[str, Any]]) -> Optional[Dict[str, int]]:
    """把 OpenAI 风格 usage 转成 Langfuse 5.x 的 usage_details"""
    if not usage or not isinstance(usage, dict):
        return None
    details: Dict[str, int] = {}
    for key, value in usage.items():
        target = _USAGE_KEY_MAP.get(key)
        if target is None:
            continue
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number >= 0:
            details[target] = number
    return details or None


class TraceHandle:
    """工作流级别 trace 的句柄。

    保存根 observation 与真正生效的 OpenTelemetry trace_id，供子 span 挂载和收尾使用。
    metadata 已经按内容采集策略处理过（关闭采集时不含 task 等内容）。
    """

    def __init__(self, span: Any, trace_id: str, metadata: Optional[Dict[str, Any]] = None):
        self.span = span
        self.trace_id = trace_id
        self.metadata = dict(metadata or {})

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<TraceHandle trace_id={self.trace_id}>"


# 复用同一个 Langfuse 客户端：每创建一个客户端都会新建一套 OTel TracerProvider + 后台线程，
# 按工作流创建而反复 new 客户端会泄漏线程和内存。
_CLIENT_LOCK = threading.Lock()
_CLIENTS: Dict[tuple, Any] = {}


def _get_shared_client(public_key: str, secret_key: str, host: Optional[str]):
    cache_key = (public_key, secret_key, host or "")
    with _CLIENT_LOCK:
        client = _CLIENTS.get(cache_key)
        if client is None:
            kwargs: Dict[str, Any] = {"public_key": public_key, "secret_key": secret_key}
            if host:
                kwargs["host"] = host
            client = Langfuse(**kwargs)
            _CLIENTS[cache_key] = client
        return client


class LangfuseTracer:
    """Langfuse 5.x 追踪器（带内容采集开关、脱敏与失败隔离）"""

    def __init__(self, enabled: bool = False, capture_content: Optional[bool] = None):
        self.enabled = bool(enabled) and SDK_AVAILABLE
        self.client = None
        self.last_error: Optional[str] = None

        # 内容采集策略：
        # - 生产路径（构造时 enabled=True，或显式传入 capture_content）严格按开关执行；
        # - 兼容历史/测试用法：构造时 enabled=False、之后外部直接置 enabled=True 并注入
        #   自定义 client 的 tracer（test_tracing_v5.py 的 make_tracer 模式）沿用旧的
        #   透传行为，避免改变既有调用方/测试的返回值语义。
        self._strict_content_policy = bool(enabled) or capture_content is not None
        if capture_content is None:
            self.capture_content = _env_flag(CAPTURE_CONTENT_ENV, DEFAULT_CAPTURE_CONTENT)
        else:
            self.capture_content = bool(capture_content)
        self._secret_values: List[str] = _collect_env_secrets()

        if not self.enabled:
            if enabled and not SDK_AVAILABLE:
                print("[Langfuse] 未安装 langfuse SDK（>=5,<6），追踪已关闭")
            return

        try:
            public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
            secret_key = os.getenv("LANGFUSE_SECRET_KEY")
            host = os.getenv("LANGFUSE_HOST") or None

            if not (public_key and secret_key):
                print("[Langfuse] 缺少 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY，追踪已关闭")
                self.enabled = False
                return

            self.client = _get_shared_client(public_key, secret_key, host)
            # 不打印 host / 密钥等连接与凭据信息
            mode = "开启" if self.capture_content else "关闭"
            print(f"[Langfuse] 初始化成功（内容采集: {mode}）")
        except Exception as e:  # noqa: BLE001 - 追踪初始化失败不能影响业务
            self._record_error("初始化失败", e)
            self.enabled = False
            self.client = None

    # ------------------------------------------------------------- 内部工具
    def _record_error(self, context: str, error: Any) -> None:
        """异常只记 last_error + 简短脱敏日志，绝不向外抛。"""
        try:
            message = _format_error(error, self._secret_values)
        except Exception:  # noqa: BLE001 - 记录失败也不能影响业务
            message = "unknown tracing error"
        self.last_error = message
        try:
            print(f"[Langfuse] {context}: {message[:MAX_LOG_CHARS]}")
        except Exception:  # noqa: BLE001
            pass

    def _capture_enabled(self) -> bool:
        """当前是否允许把用户内容写入 Langfuse。"""
        return self.capture_content or not self._strict_content_policy

    def _clean_metadata(self, metadata: Any, capture: bool) -> Dict[str, Any]:
        """按采集策略过滤 + 脱敏 metadata。"""
        cleaned: Dict[str, Any] = {}
        if not isinstance(metadata, dict):
            return cleaned
        for key, value in metadata.items():
            lowered = str(key).strip().lower().replace("-", "_")
            if lowered in _CONNECTION_KEYS:
                continue
            if not capture and _is_content_key(key):
                continue
            safe_key = sanitize_text(str(key), self._secret_values)
            if _is_secret_key(key):
                cleaned[safe_key] = REDACTED
                continue
            cleaned[safe_key] = sanitize(value, self._secret_values)
        return cleaned

    def _prepare_output(self, value: Any, capture: bool) -> Any:
        """工作流/步骤输出：关闭采集时只保留非内容的标识与统计字段。"""
        if value is None:
            return None
        if capture:
            return sanitize(value, self._secret_values)
        if isinstance(value, dict):
            cleaned = self._clean_metadata(value, capture=False)
            return cleaned or None
        # 纯文本输出：关闭采集时直接不落库
        return None

    # ------------------------------------------------------------------ trace
    def trace_id_for_run(self, run_id: str) -> Optional[str]:
        """由 run_id 推导出 Langfuse trace_id（与 trace_workflow 中一致）。

        评分（score）必须挂在真实的 trace_id 上，不能直接用 run_id。
        """
        if not self.enabled or not self.client or not run_id:
            return None
        try:
            return self.client.create_trace_id(seed=run_id)
        except Exception as e:  # noqa: BLE001
            self._record_error("trace_id 生成失败", e)
            return None

    def trace_workflow(
        self,
        workflow_id: str,
        run_id: str,
        name: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """创建工作流级别 trace（根 span）。

        返回 TraceHandle；失败时返回 _DummyTrace，业务继续执行。
        """
        if not self.enabled or not self.client:
            return _DummyTrace()

        try:
            capture = self._capture_enabled()
            raw_metadata = dict(metadata or {})

            # 让 run_id 稳定映射到同一个 trace_id，便于按运行 id 找回追踪
            trace_id = self.client.create_trace_id(seed=run_id)

            merged_metadata = dict(raw_metadata)
            merged_metadata.update({"workflow_id": workflow_id, "run_id": run_id})
            safe_metadata = self._clean_metadata(merged_metadata, capture)

            # 关闭采集时 input 只保留标识信息，不包含 task 正文
            safe_input: Dict[str, Any] = {
                "workflow_id": sanitize(workflow_id, self._secret_values),
                "run_id": sanitize(run_id, self._secret_values),
            }
            if raw_metadata.get("pattern") is not None:
                safe_input["pattern"] = sanitize(raw_metadata.get("pattern"), self._secret_values)
            if capture and raw_metadata.get("task") is not None:
                safe_input["task"] = sanitize(raw_metadata.get("task"), self._secret_values)

            span = self.client.start_observation(
                name=sanitize_text(name, self._secret_values) or "workflow",
                as_type="span",
                input=safe_input,
                metadata=safe_metadata,
                trace_context={"trace_id": trace_id},
            )
            print(f"[Langfuse] trace 已创建 trace_id={trace_id} run_id={run_id}")
            return TraceHandle(span=span, trace_id=trace_id, metadata=safe_metadata)
        except Exception as e:  # noqa: BLE001
            self._record_error("trace 创建失败", e)
            return _DummyTrace()

    # ------------------------------------------------------------------- step
    def trace_step(
        self,
        trace,
        step_id: str,
        agent_name: str,
        input_text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """创建步骤级别 span（作为工作流根 span 的子节点）"""
        if not self.enabled or trace is None or isinstance(trace, _DummyTrace):
            return _DummySpan()

        try:
            capture = self._capture_enabled()
            merged_metadata = dict(metadata or {})
            merged_metadata["step_id"] = step_id
            safe_metadata = self._clean_metadata(merged_metadata, capture)

            # 每个步骤本质上是一次 LLM 调用：只有 generation 类型才会在 Langfuse 里
            # 正常展示 token 用量 / 模型 / 成本（span 类型会丢掉 usage_details）。
            observation_type = "generation" if merged_metadata.get("agent_model") else "span"
            kwargs: Dict[str, Any] = {
                "name": sanitize_text(agent_name, self._secret_values) or step_id,
                "as_type": observation_type,
                "metadata": safe_metadata,
            }
            if observation_type == "generation":
                kwargs["model"] = sanitize(merged_metadata.get("agent_model"), self._secret_values)
            if capture and input_text is not None:
                kwargs["input"] = sanitize(input_text, self._secret_values)

            parent_span = getattr(trace, "span", None)
            if parent_span is not None:
                # 从父 span 派生：自动继承 trace_id 并带上父 observation id
                span = parent_span.start_observation(**kwargs)
            else:
                # 兜底：显式挂到 trace 上
                trace_context = {"trace_id": getattr(trace, "trace_id", None)}
                span = self.client.start_observation(trace_context=trace_context, **kwargs)
            print(
                f"[Langfuse] span 已创建 {agent_name} "
                f"(step={step_id}, type={observation_type})"
            )
            return span
        except Exception as e:  # noqa: BLE001
            self._record_error("span 创建失败", e)
            return _DummySpan()

    def update_step(
        self,
        span,
        output: Optional[str] = None,
        usage: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ):
        """更新步骤结果并结束 span（end 必须执行，否则该 span 不会导出）"""
        if not self.enabled or span is None or isinstance(span, _DummySpan):
            return

        try:
            capture = self._capture_enabled()
            update_kwargs: Dict[str, Any] = {}
            if capture and output is not None:
                update_kwargs["output"] = sanitize(output, self._secret_values)
            usage_details = _normalize_usage(usage)
            if usage_details:
                update_kwargs["usage_details"] = usage_details
            if error:
                # 关闭采集时也保留“错误类型 + 截断 200 字摘要”，但正文不落库
                summary = _format_error(error, self._secret_values)
                if summary:
                    update_kwargs["level"] = "ERROR"
                    update_kwargs["status_message"] = summary

            if update_kwargs and hasattr(span, "update"):
                span.update(**update_kwargs)
        except Exception as e:  # noqa: BLE001
            self._record_error("span 更新失败", e)
        finally:
            # 无论 update 是否成功，都必须 end，否则 OTel 不会导出这个 span
            try:
                if hasattr(span, "end"):
                    span.end()
            except Exception as e:  # noqa: BLE001
                self._record_error("span 结束失败", e)

    # ------------------------------------------------------------------- trace end
    def end_trace(
        self,
        trace,
        output: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None,
        level: Optional[str] = None,
        status_message: Optional[str] = None,
    ):
        """更新并结束工作流根 span（根 span 必须 end 才会被发送）"""
        if not self.enabled or trace is None or isinstance(trace, _DummyTrace):
            return

        span = None
        try:
            capture = self._capture_enabled()
            span = getattr(trace, "span", None)
            if span is None:
                return

            update_kwargs: Dict[str, Any] = {}
            safe_output = self._prepare_output(output, capture)
            if safe_output is not None:
                update_kwargs["output"] = safe_output
            merged_metadata = dict(getattr(trace, "metadata", {}) or {})
            merged_metadata.update(metadata or {})
            safe_metadata = self._clean_metadata(merged_metadata, capture)
            if safe_metadata:
                update_kwargs["metadata"] = safe_metadata
            if level:
                update_kwargs["level"] = level
            if status_message:
                summary = _format_error(status_message, self._secret_values)
                if summary:
                    update_kwargs["status_message"] = summary

            if update_kwargs and hasattr(span, "update"):
                span.update(**update_kwargs)
        except Exception as e:  # noqa: BLE001
            self._record_error("trace 更新失败", e)
        finally:
            try:
                if span is not None and hasattr(span, "end"):
                    span.end()
                print(f"[Langfuse] trace 已结束 trace_id={getattr(trace, 'trace_id', None)}")
            except Exception as e:  # noqa: BLE001
                self._record_error("trace 结束失败", e)

    # ------------------------------------------------------------------- flush
    def flush(self):
        """刷新追踪数据（触发 OTel 批量导出）"""
        if not self.enabled or not self.client:
            return
        try:
            self.client.flush()
        except Exception as e:  # noqa: BLE001
            self._record_error("刷新失败", e)


class _DummyTrace:
    """假追踪，用于追踪关闭/初始化失败时保持调用链完整"""

    trace_id = None

    def span(self, **kwargs):
        return _DummySpan()

    def start_observation(self, **kwargs):
        return _DummySpan()

    def update(self, **kwargs):
        pass

    def end(self):
        pass


class _DummySpan:
    """假 Span，用于追踪关闭时"""

    def update(self, **kwargs):
        pass

    def end(self):
        pass

    def start_observation(self, **kwargs):
        return _DummySpan()


@contextmanager
def optional_tracing(enabled: bool = False):
    """可选追踪的上下文管理器（追踪自身失败绝不影响业务异常传播）"""
    tracer = None
    try:
        tracer = LangfuseTracer(enabled=enabled)
    except Exception:  # noqa: BLE001 - 初始化失败也不能影响业务
        tracer = None
    try:
        yield tracer
    finally:
        if tracer is not None:
            try:
                tracer.flush()
            except Exception:  # noqa: BLE001 - finally 里绝不能抛
                pass
