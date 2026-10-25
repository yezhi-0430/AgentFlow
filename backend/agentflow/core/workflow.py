"""
工作流引擎 - 负责编排和执行 Agent 协作

第一批：run 实例隔离、错误/停止语义、统一记录、可关闭追踪、实验入口。
第二批：步骤超时/重试/错误分类、多尝试用量聚合、异步持久化与保留策略、
        记录脱敏、trace_id 关联、可选 API Token（在 API 层）。

设计要点：
- workflow_id 标识定义，run_id 标识一次执行；同一执行器同一时刻只允许一个运行；
- 每次运行独立记忆/统计/消息；顺序失败即停，并行区分成功/部分/失败/取消；
- StepResult 记录输入输出、模型、状态、错误类型、尝试次数、用量类型；
- 本地 SQLite 增量保存（异步线程写入 + 串行化），历史回看不调用模型。
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from enum import Enum
import asyncio
import json
import os
import re
import time
import uuid

from agentflow.core.agent import Agent, AgentConfig
from agentflow.core.message import Message, MessageType
from agentflow.core.redaction import redact_text
from agentflow.core.run import WorkflowRun, StepResult, RunStatus, UsageType

try:
    from agentflow.storage import MessageRepository, get_db, RunRepository
    STORAGE_AVAILABLE = True
except ImportError:
    STORAGE_AVAILABLE = False

try:
    from agentflow.tracing import LangfuseTracer
    TRACING_AVAILABLE = True
except ImportError:
    TRACING_AVAILABLE = False


SUPPORTED_PATTERNS = (
    "sequential",
    "parallel",
    "hierarchical",
    "debate",
    "voting",
    "dynamic",
    "group_chat",
)
# 各模式对智能体数量的最低要求：协调者/裁判需要独立成员
MIN_AGENTS_BY_PATTERN = {
    "sequential": 1,
    "parallel": 1,
    "hierarchical": 2,
    "debate": 3,
    "voting": 3,
    "dynamic": 2,
    "group_chat": 2,
}
# 群聊最多 6 人，避免上下文和成本失控；其余模式沿用全局上限 10
MAX_AGENTS_BY_PATTERN = {
    "group_chat": 6,
}
MAX_RUNS_IN_MEMORY = 50
MAX_GROUP_TOOL_CALLS = 3
PARALLEL_STOP_POLL_INTERVAL = 0.05
TERMINAL_STATUSES = {
    RunStatus.COMPLETED,
    RunStatus.FAILED,
    RunStatus.STOPPED,
    RunStatus.PARTIAL,
    RunStatus.CANCELLED,
}
# 只有这些错误类型值得重试；鉴权/参数错误重试没有意义
RETRYABLE_ERROR_TYPES = {"timeout", "rate_limit", "network", "server"}


class RunAlreadyRunningError(RuntimeError):
    """同一工作流已有运行在执行时抛出（显式拒绝并发）"""


class UnsupportedPatternError(ValueError):
    """未支持的工作流模式"""


class WorkflowPattern(Enum):
    """工作流模式；全部模式由执行器实现，group_chat 为共享群聊。"""
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    DEBATE = "debate"
    VOTING = "voting"
    HIERARCHICAL = "hierarchical"
    DYNAMIC = "dynamic"
    GROUP_CHAT = "group_chat"


def ensure_supported_pattern(pattern: WorkflowPattern) -> None:
    value = pattern.value if isinstance(pattern, WorkflowPattern) else str(pattern)
    if value not in SUPPORTED_PATTERNS:
        raise UnsupportedPatternError(
            f"Workflow pattern '{value}' is not supported yet. "
            f"Supported patterns: {', '.join(SUPPORTED_PATTERNS)}"
        )


def validate_pattern_agents(pattern: WorkflowPattern, agent_count: int) -> None:
    """校验模式要求的智能体数量范围。"""
    value = pattern.value if isinstance(pattern, WorkflowPattern) else str(pattern)
    minimum = MIN_AGENTS_BY_PATTERN.get(value, 1)
    if agent_count < minimum:
        raise ValueError(
            f"Workflow pattern '{value}' requires at least {minimum} agents "
            f"(got {agent_count})"
        )
    maximum = MAX_AGENTS_BY_PATTERN.get(value, 10)
    if agent_count > maximum:
        raise ValueError(
            f"Workflow pattern '{value}' supports at most {maximum} agents "
            f"(got {agent_count})"
        )


@dataclass
class WorkflowStep:
    """工作流步骤"""
    id: str
    agent_name: str
    input_from: Optional[str] = None
    condition: Optional[Callable] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowConfig:
    """工作流配置"""
    name: str
    pattern: WorkflowPattern
    steps: List[WorkflowStep]
    agents: List[AgentConfig]
    max_iterations: int = 10
    convergence_check: Optional[Callable] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        value = float(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def _env_int(name: str, default: int, minimum: int = 0, maximum: int = 10**9) -> int:
    try:
        value = int(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _extract_usage(raw_usage: Any) -> Tuple[Optional[Dict[str, Any]], UsageType]:
    """把提供商返回的 usage 映射为记录值 + 可信度类型（未知不填 0）。"""
    if not isinstance(raw_usage, dict) or not raw_usage:
        return None, UsageType.UNKNOWN

    numeric: Dict[str, int] = {}
    invalid = False
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if key not in raw_usage:
            continue
        value = raw_usage[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            invalid = True
            continue
        numeric[key] = int(value)

    if not numeric or invalid:
        return None, UsageType.UNKNOWN

    usage = dict(raw_usage)
    usage.update(numeric)
    if "total_tokens" in numeric:
        return usage, UsageType.ACTUAL
    if "prompt_tokens" in numeric and "completion_tokens" in numeric:
        usage["total_tokens"] = numeric["prompt_tokens"] + numeric["completion_tokens"]
        return usage, UsageType.ACTUAL
    return usage, UsageType.PARTIAL


def _aggregate_attempt_usage(
    attempts: List[Tuple[Optional[Dict[str, Any]], UsageType]]
) -> Tuple[Optional[Dict[str, Any]], UsageType]:
    """聚合多次尝试的用量：全部已知为 ACTUAL，部分未知为 PARTIAL，全未知为 UNKNOWN。"""
    if not attempts:
        return None, UsageType.UNKNOWN

    totals: Dict[str, int] = {}
    known = 0
    unknown = 0
    actual = 0
    for usage, usage_type in attempts:
        if not usage:
            unknown += 1
            continue
        known += 1
        if usage_type == UsageType.ACTUAL:
            actual += 1
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = usage.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                totals[key] = totals.get(key, 0) + int(value)

    if known == 0:
        return None, UsageType.UNKNOWN
    if unknown > 0 or actual < known:
        return (totals or None), UsageType.PARTIAL
    return totals, UsageType.ACTUAL


def classify_error(exc: Optional[BaseException] = None, message: Optional[str] = None) -> str:
    """把异常/错误文本归类为可展示的 error_type"""
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout"
    text = (message or (str(exc) if exc else "")).lower()
    if "timed out" in text or "timeout" in text:
        return "timeout"
    if "rate limit" in text or "too many requests" in text or "429" in text:
        return "rate_limit"
    if (
        "401" in text
        or "403" in text
        or "unauthorized" in text
        or "invalid api key" in text
        or "incorrect api key" in text
        or "authentication" in text
        or "permission" in text
    ):
        return "auth"
    if any(token in text for token in ("connection", "network", "dns", "proxy", "econn", "ssl")):
        return "network"
    if any(code in text for code in ("500", "502", "503", "504")) or "server error" in text:
        return "server"
    if "invalid" in text or "validation" in text or "400" in text:
        return "validation"
    return "provider" if exc is not None else "unknown"


class WorkflowExecutor:
    """工作流执行器"""

    def __init__(
        self,
        config: WorkflowConfig,
        enable_persistence: bool = True,
        enable_tracing: bool = False,
        workflow_id: Optional[str] = None,
    ):
        ensure_supported_pattern(config.pattern)

        self.config = config
        self.workflow_id = workflow_id or str(uuid.uuid4())
        self.description: str = ""
        self.connection: Dict[str, Any] = {}
        self.agents: Dict[str, Agent] = {}

        self.message_history: List[Message] = []
        self.run_messages: Dict[str, List[Message]] = {}

        self.status = "idle"
        self.current_step = 0
        self.start_time: Optional[float] = None
        self.callbacks: Dict[str, List[Callable]] = {}

        self.runs: Dict[str, WorkflowRun] = {}
        self.current_run: Optional[WorkflowRun] = None
        self._active_run: Optional[WorkflowRun] = None

        self.enable_persistence = enable_persistence and STORAGE_AVAILABLE
        self.enable_tracing = enable_tracing and TRACING_AVAILABLE
        self.tracer = LangfuseTracer(enabled=self.enable_tracing) if TRACING_AVAILABLE else None

        # 执行策略（环境变量，默认保持旧行为：不超时、不重试）
        self.step_timeout_seconds = _env_float("AGENTFLOW_STEP_TIMEOUT_SECONDS", 0.0)
        self.max_attempts = _env_int("AGENTFLOW_MAX_ATTEMPTS", 1, minimum=1, maximum=5)
        self.record_text_limit = _env_int("AGENTFLOW_RECORD_TEXT_LIMIT", 20000)
        self.max_runs = _env_int("AGENTFLOW_MAX_RUNS", 1000)
        self.retention_days = _env_float("AGENTFLOW_RUN_RETENTION_DAYS", 0.0)

        self.auto_evaluate = os.getenv("AUTO_EVALUATE", "false").lower() in ("true", "1", "yes")
        if self.auto_evaluate and not self.enable_tracing:
            print("[WorkflowExecutor] 警告: AUTO_EVALUATE=true 但追踪未启用，评估将被禁用")
            self.auto_evaluate = False

    # ---------------------------------------------------------------- registry
    @property
    def requires_credentials(self) -> bool:
        return len(self.agents) == 0

    def to_definition(self):
        from agentflow.core.definition import WorkflowDefinition

        return WorkflowDefinition(
            workflow_id=self.workflow_id,
            name=self.config.name,
            pattern=self.config.pattern.value,
            description=self.description,
            agents=[agent_config.to_dict() for agent_config in self.config.agents],
            steps=[
                {"id": step.id, "agent_name": step.agent_name, "input_from": step.input_from}
                for step in self.config.steps
            ],
            max_iterations=self.config.max_iterations,
            connection=dict(self.connection),
            metadata=dict(self.config.metadata or {}),
        )

    def register_agent(self, agent: Agent):
        self.agents[agent.name] = agent

    def on(self, event: str, callback: Callable):
        self.callbacks.setdefault(event, []).append(callback)

    async def _emit(self, event: str, data: Any):
        for callback in self.callbacks.get(event, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(data)
                else:
                    callback(data)
            except Exception as e:  # noqa: BLE001
                print(f"Workflow callback '{event}' failed: {e}")

    # ------------------------------------------------------------------ state
    def is_busy(self) -> bool:
        return self._active_run is not None

    def _record_text(self, text: Optional[str]) -> Optional[str]:
        """落库前截断文本，避免单条记录无限膨胀；0 表示不限制"""
        if text is None:
            return None
        value = str(text)
        if self.record_text_limit and len(value) > self.record_text_limit:
            return value[: self.record_text_limit] + "...[truncated]"
        return value

    def _config_snapshot(self) -> Dict[str, Any]:
        return {
            "name": self.config.name,
            "pattern": self.config.pattern.value,
            "max_iterations": self.config.max_iterations,
            "execution_policy": {
                "step_timeout_seconds": self.step_timeout_seconds,
                "max_attempts": self.max_attempts,
                "record_text_limit": self.record_text_limit,
            },
            "steps": [
                {"id": step.id, "agent_name": step.agent_name, "input_from": step.input_from}
                for step in self.config.steps
            ],
            "agents": [
                {
                    "name": agent_config.name,
                    "role": agent_config.role.value if hasattr(agent_config.role, "value") else str(agent_config.role),
                    "system_prompt": agent_config.system_prompt,
                    "model": agent_config.model,
                    "temperature": agent_config.temperature,
                    "max_tokens": agent_config.max_tokens,
                }
                for agent_config in self.config.agents
            ],
        }

    # -------------------------------------------------------------- persistence
    def _persist_sync(self, run: WorkflowRun) -> None:
        if not self.enable_persistence:
            return
        try:
            with get_db() as db:
                RunRepository.save_run(db, run)
                if run.status in TERMINAL_STATUSES and (
                    self.max_runs > 0 or self.retention_days > 0
                ):
                    RunRepository.prune_runs(
                        db, max_runs=self.max_runs, retention_days=self.retention_days
                    )
        except Exception as e:  # noqa: BLE001
            print(f"Failed to persist run {run.run_id}: {e}")

    async def _persist_run(self, run: WorkflowRun) -> None:
        """异步线程写入，避免阻塞事件循环"""
        if not self.enable_persistence:
            return
        try:
            await asyncio.to_thread(self._persist_sync, run)
        except Exception as e:  # noqa: BLE001
            print(f"Failed to persist run {run.run_id}: {e}")

    async def _persist_group_message(self, message: Message, run: WorkflowRun) -> None:
        """群聊消息落库（失败不影响执行）；其他模式不写消息表。"""
        if not self.enable_persistence or not STORAGE_AVAILABLE:
            return

        def _write() -> None:
            with get_db() as db:
                MessageRepository.save(
                    db, message, workflow_id=self.workflow_id, run_id=run.run_id
                )

        try:
            await asyncio.to_thread(_write)
        except Exception as e:  # noqa: BLE001
            print(f"Failed to persist group message {message.id}: {e}")

    # ---------------------------------------------------------------- execute
    async def execute(
        self,
        initial_task: str,
        run_id: Optional[str] = None,
        *,
        experiment_id: Optional[str] = None,
        candidate_id: Optional[str] = None,
        case_id: Optional[str] = None,
        fingerprint: Optional[str] = None,
    ) -> Dict[str, Any]:
        ensure_supported_pattern(self.config.pattern)
        if self._active_run is not None:
            raise RunAlreadyRunningError(
                f"Workflow {self.workflow_id} already has a running run "
                f"({self._active_run.run_id}); concurrent runs are not allowed"
            )

        run = WorkflowRun(
            run_id=run_id or str(uuid.uuid4()),
            workflow_id=self.workflow_id,
            workflow_name=self.config.name,
            task_input=self._record_text(initial_task) or "",
            config_snapshot=self._config_snapshot(),
            experiment_id=experiment_id,
            candidate_id=candidate_id,
            case_id=case_id,
            fingerprint=fingerprint,
        )

        self._active_run = run
        self.current_run = run
        self.runs[run.run_id] = run
        self._trim_runs_in_memory()

        self.message_history = []
        self.run_messages[run.run_id] = self.message_history
        for agent in self.agents.values():
            reset = getattr(agent, "reset_for_run", None)
            if callable(reset):
                reset()
            else:
                clear = getattr(agent, "clear_memory", None)
                if callable(clear):
                    clear()

        self.status = "running"
        self.start_time = time.time()
        self.current_step = 0
        run.mark_started()
        await self._persist_run(run)

        trace = None
        trace_error: Optional[str] = None
        workflow_result: Optional[Dict[str, Any]] = None
        if self.tracer:
            try:
                trace = self.tracer.trace_workflow(
                    workflow_id=self.workflow_id,
                    run_id=run.run_id,
                    name=self.config.name,
                    metadata={"pattern": self.config.pattern.value, "task": initial_task},
                )
                run.trace_id = getattr(trace, "trace_id", None)
                if not isinstance(run.trace_id, str):
                    run.trace_id = None
                if run.trace_id:
                    await self._persist_run(run)
            except Exception as e:  # noqa: BLE001
                print(f"[Langfuse] trace 创建异常已忽略: {e}")
                trace = None

        await self._emit("workflow_started", {
            "workflow_id": self.workflow_id,
            "run_id": run.run_id,
            "task": initial_task,
        })

        try:
            if self.config.pattern == WorkflowPattern.SEQUENTIAL:
                workflow_result = await self._execute_sequential(initial_task, run, trace)
            elif self.config.pattern == WorkflowPattern.PARALLEL:
                workflow_result = await self._execute_parallel(initial_task, run, trace)
            elif self.config.pattern == WorkflowPattern.HIERARCHICAL:
                workflow_result = await self._execute_hierarchical(initial_task, run, trace)
            elif self.config.pattern == WorkflowPattern.DEBATE:
                workflow_result = await self._execute_debate(initial_task, run, trace)
            elif self.config.pattern == WorkflowPattern.VOTING:
                workflow_result = await self._execute_voting(initial_task, run, trace)
            elif self.config.pattern == WorkflowPattern.DYNAMIC:
                workflow_result = await self._execute_dynamic(initial_task, run, trace)
            elif self.config.pattern == WorkflowPattern.GROUP_CHAT:
                workflow_result = await self._execute_group_chat(initial_task, run, trace)
            else:  # pragma: no cover - ensure_supported_pattern 已保证不会到这里
                raise UnsupportedPatternError(f"Unhandled pattern: {self.config.pattern}")

            self._finalize_run(run, workflow_result)
            await self._persist_run(run)

            if run.status != RunStatus.COMPLETED and isinstance(workflow_result, dict):
                workflow_result = dict(workflow_result)
                workflow_result["final_result"] = None
                workflow_result["error"] = run.error

            elapsed_time = time.time() - self.start_time
            await self._emit("workflow_completed", {
                "workflow_id": self.workflow_id,
                "run_id": run.run_id,
                "status": run.status.value,
                "result": workflow_result,
                "elapsed_time": elapsed_time,
            })

            return {
                "status": run.status.value,
                "run_id": run.run_id,
                "workflow_id": self.workflow_id,
                "trace_id": run.trace_id,
                "result": workflow_result,
                "elapsed_time": elapsed_time,
                "messages": len(self.message_history),
                "total_tokens": run.total_tokens,
                "error": run.error,
            }

        except asyncio.CancelledError:
            run.mark_stopped("execution cancelled")
            self.status = "stopped"
            raise
        except Exception as e:
            trace_error = redact_text(str(e))
            run.mark_failed(trace_error)
            self.status = "failed"
            await self._emit("workflow_error", {
                "workflow_id": self.workflow_id,
                "run_id": run.run_id,
                "error": trace_error,
            })
            raise
        finally:
            await self._persist_run(run)

            if self.tracer:
                try:
                    self.tracer.end_trace(
                        trace,
                        output={
                            "status": run.status.value,
                            "run_id": run.run_id,
                            "steps": len(run.step_results),
                            "total_tokens": run.total_tokens,
                        },
                        metadata={
                            "elapsed_time": (time.time() - self.start_time) if self.start_time else None,
                            "messages": len(self.message_history),
                        },
                        level=(
                            "ERROR"
                            if run.status in (RunStatus.FAILED, RunStatus.PARTIAL, RunStatus.CANCELLED)
                            else None
                        ),
                        status_message=trace_error or run.error,
                    )
                except Exception as e:  # noqa: BLE001
                    print(f"Failed to end Langfuse trace {run.run_id}: {e}")

                self._flush()

                if self.auto_evaluate:
                    try:
                        from agentflow.core.auto_evaluate import auto_evaluate_workflow

                        await auto_evaluate_workflow(
                            self.tracer,
                            run,
                            workflow_result,
                            trace_id=run.trace_id,
                        )
                    except Exception as e:  # noqa: BLE001
                        print(f"[自动评估] 跳过（{run.run_id}）: {e}")
                    self._flush()

            self._active_run = None

    def _finalize_run(self, run: WorkflowRun, workflow_result: Optional[Dict[str, Any]]):
        if run.should_stop():
            run.mark_stopped(run.error or "stopped by request")
            self.status = "stopped"
            return
        if run.status == RunStatus.FAILED:
            self.status = "failed"
            return
        if run.status == RunStatus.PARTIAL:
            self.status = "partial"
            return
        final_result = None
        if isinstance(workflow_result, dict):
            final_result = workflow_result.get("final_result") or workflow_result.get("aggregated")
        run.mark_completed(self._record_text(final_result))
        self.status = "completed"

    def _trim_runs_in_memory(self):
        if len(self.runs) <= MAX_RUNS_IN_MEMORY:
            return
        for old_run_id in list(self.runs.keys())[: len(self.runs) - MAX_RUNS_IN_MEMORY]:
            self.runs.pop(old_run_id, None)
            self.run_messages.pop(old_run_id, None)

    # ------------------------------------------------------- execution policy
    async def _process_with_policy(self, agent: Agent, message: Message, run: WorkflowRun) -> Dict[str, Any]:
        """执行一次步骤（含超时/重试），返回结构化结果。

        返回字段：response/last_response/attempts/error/error_type/cancelled/
                 usage/usage_type。
        """
        attempts_meta: List[Tuple[Optional[Dict[str, Any]], UsageType]] = []
        last_error: Optional[str] = None
        last_error_type: Optional[str] = None
        last_response: Optional[Message] = None
        attempt_number = 0

        while attempt_number < self.max_attempts:
            if attempt_number > 0 and run.should_stop():
                usage, usage_type = _aggregate_attempt_usage(attempts_meta)
                return {
                    "response": None, "last_response": last_response,
                    "attempts": attempt_number, "error": "stopped by request",
                    "error_type": "cancelled", "cancelled": True,
                    "usage": usage, "usage_type": usage_type,
                }
            attempt_number += 1
            attempt_usage: Optional[Dict[str, Any]] = None
            attempt_usage_type = UsageType.UNKNOWN

            try:
                process_coro = agent.process(message)
                if self.step_timeout_seconds > 0:
                    response = await asyncio.wait_for(process_coro, timeout=self.step_timeout_seconds)
                else:
                    response = await process_coro
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                last_error = f"step timed out after {self.step_timeout_seconds:g}s"
                last_error_type = "timeout"
                attempts_meta.append((None, UsageType.UNKNOWN))
            except Exception as e:  # noqa: BLE001
                last_error = str(e)
                last_error_type = classify_error(exc=e)
                attempts_meta.append((None, UsageType.UNKNOWN))
            else:
                last_response = response
                usage, usage_type = _extract_usage((response.metadata or {}).get("usage"))
                attempt_usage, attempt_usage_type = usage, usage_type
                attempts_meta.append((attempt_usage, attempt_usage_type))
                metadata = response.metadata or {}
                if not metadata.get("error"):
                    aggregate_usage, aggregate_type = _aggregate_attempt_usage(attempts_meta)
                    return {
                        "response": response, "last_response": response,
                        "attempts": attempt_number, "error": None, "error_type": None,
                        "cancelled": False,
                        "usage": aggregate_usage, "usage_type": aggregate_type,
                    }
                last_error = metadata.get("error_message") or response.content
                last_error_type = classify_error(message=str(last_error))

            if last_error_type in RETRYABLE_ERROR_TYPES and attempt_number < self.max_attempts:
                print(
                    f"[retry] {agent.name} attempt {attempt_number}/{self.max_attempts} "
                    f"failed ({last_error_type}); retrying"
                )
                continue

            usage, usage_type = _aggregate_attempt_usage(attempts_meta)
            return {
                "response": None, "last_response": last_response,
                "attempts": attempt_number, "error": last_error,
                "error_type": last_error_type, "cancelled": False,
                "usage": usage, "usage_type": usage_type,
            }

        usage, usage_type = _aggregate_attempt_usage(attempts_meta)
        return {
            "response": None, "last_response": last_response,
            "attempts": attempt_number, "error": last_error,
            "error_type": last_error_type or "unknown", "cancelled": False,
            "usage": usage, "usage_type": usage_type,
        }

    # -------------------------------------------------------------- sequential
    async def _execute_sequential(self, task: str, run: WorkflowRun, trace=None) -> Dict[str, Any]:
        current_input = task

        for index, step in enumerate(self.config.steps):
            if run.should_stop():
                break

            self.current_step = index + 1
            agent = self.agents.get(step.agent_name)
            if not agent:
                raise ValueError(f"Agent not found: {step.agent_name}")

            step_result = StepResult(
                step_id=step.id,
                agent_name=step.agent_name,
                status=RunStatus.RUNNING,
                step_index=index,
                input_text=self._record_text(current_input),
                started_at=time.time(),
            )
            message = Message(
                sender="system",
                receiver=step.agent_name,
                content=current_input,
                message_type=MessageType.TASK,
                metadata={"step_id": step.id, "step_index": index, "run_id": run.run_id},
            )
            step_result.input_message_id = message.id
            self.message_history.append(message)

            await self._emit("step_started", {
                "workflow_id": self.workflow_id,
                "run_id": run.run_id,
                "step": step.id,
                "step_index": index,
                "agent": step.agent_name,
                "message": message.to_dict(),
            })

            span = self._trace_step(trace, step, index, current_input, agent)
            step_start = time.time()
            try:
                outcome = await self._process_with_policy(agent, message, run)
            except asyncio.CancelledError:
                step_result.status = RunStatus.CANCELLED
                step_result.error = "cancelled before completion; provider state unknown"
                step_result.error_type = "cancelled"
                step_result.completed_at = time.time()
                step_result.duration = step_result.completed_at - step_start
                run.add_step_result(step_result)
                await self._persist_run(run)
                raise

            step_result.attempts = outcome["attempts"]
            step_result.error_type = outcome["error_type"]
            step_result.usage = outcome["usage"]
            step_result.usage_type = outcome["usage_type"]
            step_result.completed_at = time.time()
            step_result.duration = step_result.completed_at - step_start

            response = outcome.get("response") or outcome.get("last_response")
            if response is not None:
                step_result.output_message_id = response.id
                step_result.output_text = self._record_text(response.content)
                model, finish_reason = self._extract_response_meta(response)
                step_result.model = model
                step_result.finish_reason = finish_reason
                self.message_history.append(response)

            if outcome["cancelled"]:
                step_result.status = RunStatus.CANCELLED
                step_result.error = redact_text(outcome["error"] or "stopped by request")
                run.add_step_result(step_result)
                await self._persist_run(run)
                self._update_span(span, error=step_result.error)
                await self._emit("step_cancelled", {
                    "workflow_id": self.workflow_id,
                    "run_id": run.run_id,
                    "step": step.id,
                    "agent": step.agent_name,
                })
                break

            if outcome["error"]:
                step_result.status = RunStatus.FAILED
                step_result.error = redact_text(outcome["error"])
                run.add_step_result(step_result)
                run.mark_failed(step_result.error or "step failed")
                await self._persist_run(run)
                self._update_span(span, error=step_result.error)
                await self._emit("step_failed", {
                    "workflow_id": self.workflow_id,
                    "run_id": run.run_id,
                    "step": step.id,
                    "agent": step.agent_name,
                    "error": step_result.error,
                    "error_type": step_result.error_type,
                    "attempts": step_result.attempts,
                    "duration": step_result.duration,
                })
                break

            step_result.status = RunStatus.COMPLETED
            current_input = response.content
            run.add_step_result(step_result)
            await self._persist_run(run)
            self._update_span(span, output=response.content, usage=outcome["usage"])

            await self._emit("step_completed", {
                "workflow_id": self.workflow_id,
                "run_id": run.run_id,
                "step": step.id,
                "agent": step.agent_name,
                "result": response.content,
                "duration": step_result.duration,
                "attempts": step_result.attempts,
            })

            if run.should_stop():
                break

        return {"final_result": current_input}

    # ---------------------------------------------------------------- parallel
    async def _execute_parallel(self, task: str, run: WorkflowRun, trace=None) -> Dict[str, Any]:
        tasks: List[asyncio.Future] = []
        entries: List[Dict[str, Any]] = []

        for index, step in enumerate(self.config.steps):
            if run.should_stop():
                break

            agent = self.agents.get(step.agent_name)
            if not agent:
                raise ValueError(f"Agent not found: {step.agent_name}")

            message = Message(
                sender="system",
                receiver=step.agent_name,
                content=task,
                message_type=MessageType.TASK,
                metadata={"step_id": step.id, "step_index": index, "run_id": run.run_id},
            )
            step_result = StepResult(
                step_id=step.id,
                agent_name=step.agent_name,
                status=RunStatus.RUNNING,
                step_index=index,
                input_text=self._record_text(task),
                input_message_id=message.id,
                started_at=time.time(),
            )
            self.message_history.append(message)

            span = self._trace_step(trace, step, index, task, agent)
            entries.append({"step": step, "agent": agent, "message": message,
                            "step_result": step_result, "index": index, "span": span})
            tasks.append(asyncio.ensure_future(self._process_with_policy(agent, message, run)))

        pending = set(tasks)
        while pending:
            if run.should_stop():
                for task_future in pending:
                    task_future.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                break
            await asyncio.wait(
                pending,
                timeout=PARALLEL_STOP_POLL_INTERVAL,
                return_when=asyncio.FIRST_COMPLETED,
            )
            pending = {task_future for task_future in pending if not task_future.done()}

        results = await asyncio.gather(*tasks, return_exceptions=True)

        success_results: List[str] = []
        failed_steps: List[str] = []
        cancelled_steps: List[str] = []

        for entry, result in zip(entries, results):
            step = entry["step"]
            step_result: StepResult = entry["step_result"]
            message = entry["message"]
            span = entry.get("span")
            step_result.completed_at = time.time()
            step_result.duration = step_result.completed_at - (step_result.started_at or step_result.completed_at)

            if isinstance(result, asyncio.CancelledError):
                step_result.status = RunStatus.CANCELLED
                step_result.error = "stopped before completion; provider state unknown"
                step_result.error_type = "cancelled"
                step_result.usage = None
                step_result.usage_type = UsageType.UNKNOWN
                cancelled_steps.append(step.agent_name)
                run.add_step_result(step_result)
                self._update_span(span, error="cancelled (provider state unknown)")
                await self._emit("step_cancelled", {
                    "workflow_id": self.workflow_id,
                    "run_id": run.run_id,
                    "step": step.id,
                    "agent": step.agent_name,
                })
                continue

            if isinstance(result, Exception):
                step_result.status = RunStatus.FAILED
                step_result.error = redact_text(str(result))
                step_result.error_type = classify_error(exc=result)
                step_result.usage_type = UsageType.UNKNOWN
                failed_steps.append(step.agent_name)
                run.add_step_result(step_result)
                error_response = Message(
                    sender=step.agent_name,
                    receiver="system",
                    content=f"Error: {result}",
                    message_type=MessageType.RESPONSE,
                    metadata={"error": True, "error_message": str(result), "run_id": run.run_id},
                    parent_id=message.id,
                )
                self.message_history.append(error_response)
                step_result.output_message_id = error_response.id
                step_result.output_text = self._record_text(error_response.content)
                self._update_span(span, error=str(result))
                continue

            outcome = result
            step_result.attempts = outcome["attempts"]
            step_result.error_type = outcome["error_type"]
            step_result.usage = outcome["usage"]
            step_result.usage_type = outcome["usage_type"]

            response = outcome.get("response") or outcome.get("last_response")
            if response is not None:
                step_result.output_message_id = response.id
                step_result.output_text = self._record_text(response.content)
                model, finish_reason = self._extract_response_meta(response)
                step_result.model = model
                step_result.finish_reason = finish_reason
                self.message_history.append(response)

            if outcome["cancelled"]:
                step_result.status = RunStatus.CANCELLED
                step_result.error = redact_text(outcome["error"] or "stopped by request")
                cancelled_steps.append(step.agent_name)
                run.add_step_result(step_result)
                self._update_span(span, error=step_result.error)
                continue

            if outcome["error"]:
                step_result.status = RunStatus.FAILED
                step_result.error = redact_text(outcome["error"])
                failed_steps.append(step.agent_name)
                run.add_step_result(step_result)
                self._update_span(span, error=step_result.error)
                continue

            step_result.status = RunStatus.COMPLETED
            success_results.append(response.content)
            run.add_step_result(step_result)
            self._update_span(span, output=response.content, usage=outcome["usage"])

        await self._persist_run(run)

        if run.should_stop():
            run.mark_stopped("stopped by request")
        elif failed_steps:
            run.mark_partial("all steps failed" if not success_results else "some steps failed")
            if not success_results:
                run.status = RunStatus.FAILED
                run.mark_failed("all parallel steps failed")
        else:
            run.mark_completed(self._record_text("\n\n".join(success_results) if success_results else None))

        return {
            "results": success_results,
            "aggregated": "\n\n".join(success_results) if success_results else "",
            "failed_steps": failed_steps,
            "cancelled_steps": cancelled_steps,
            "total_steps": len(entries),
            "successful_steps": len(success_results),
        }

    # -------------------------------------------------- recorded step helper
    async def _execute_recorded_step(
        self,
        *,
        step: WorkflowStep,
        agent: Agent,
        input_text: str,
        run: WorkflowRun,
        trace,
        index: int,
        sender: str = "system",
        receiver: Optional[str] = None,
        response_receiver: Optional[str] = None,
        message_content: Optional[str] = None,
    ) -> Dict[str, Any]:
        """执行单个步骤并写记录；供层次/辩论/投票/动态模式复用。

        返回 {ok, content, cancelled, error, error_type}。失败时只记录步骤，
        run 的终态由调用方决定（例如部分 worker 失败仍可继续汇总）。
        """
        if run.should_stop():
            return {
                "ok": False, "content": None, "cancelled": True,
                "error": "stopped by request", "error_type": "cancelled",
            }

        self.current_step = index + 1
        step_result = StepResult(
            step_id=step.id,
            agent_name=step.agent_name,
            status=RunStatus.RUNNING,
            step_index=index,
            input_text=self._record_text(input_text),
            started_at=time.time(),
        )
        metadata = {"step_id": step.id, "step_index": index, "run_id": run.run_id}
        if message_content is not None:
            # 完整 prompt 仍交给模型；短文案只用于聊天时间线展示
            metadata["display_content"] = message_content
        message = Message(
            sender=sender,
            receiver=receiver or step.agent_name,
            content=input_text,
            message_type=MessageType.TASK,
            metadata=metadata,
        )
        step_result.input_message_id = message.id
        self.message_history.append(message)
        if self.config.pattern == WorkflowPattern.GROUP_CHAT:
            await self._persist_group_message(message, run)

        await self._emit("step_started", {
            "workflow_id": self.workflow_id,
            "run_id": run.run_id,
            "step": step.id,
            "step_index": index,
            "agent": step.agent_name,
            "message": message.to_dict(),
        })
        span = self._trace_step(trace, step, index, input_text, agent)
        step_start = time.time()

        try:
            outcome = await self._process_with_policy(agent, message, run)
        except asyncio.CancelledError:
            step_result.status = RunStatus.CANCELLED
            step_result.error = "cancelled before completion; provider state unknown"
            step_result.error_type = "cancelled"
            step_result.completed_at = time.time()
            step_result.duration = step_result.completed_at - step_start
            run.add_step_result(step_result)
            await self._persist_run(run)
            raise

        step_result.attempts = outcome["attempts"]
        step_result.error_type = outcome["error_type"]
        step_result.usage = outcome["usage"]
        step_result.usage_type = outcome["usage_type"]
        step_result.completed_at = time.time()
        step_result.duration = step_result.completed_at - step_start

        response = outcome.get("response") or outcome.get("last_response")
        if response is not None:
            if response_receiver:
                response.sender = step.agent_name
                response.receiver = response_receiver
            step_result.output_message_id = response.id
            step_result.output_text = self._record_text(response.content)
            model, finish_reason = self._extract_response_meta(response)
            step_result.model = model
            step_result.finish_reason = finish_reason
            self.message_history.append(response)
            if self.config.pattern == WorkflowPattern.GROUP_CHAT:
                await self._persist_group_message(response, run)

        if outcome["cancelled"]:
            step_result.status = RunStatus.CANCELLED
            step_result.error = redact_text(outcome["error"] or "stopped by request")
            run.add_step_result(step_result)
            await self._persist_run(run)
            self._update_span(span, error=step_result.error)
            await self._emit("step_cancelled", {
                "workflow_id": self.workflow_id,
                "run_id": run.run_id,
                "step": step.id,
                "agent": step.agent_name,
            })
            return {
                "ok": False, "content": None, "cancelled": True,
                "error": step_result.error, "error_type": "cancelled",
            }

        if outcome["error"]:
            step_result.status = RunStatus.FAILED
            step_result.error = redact_text(outcome["error"])
            run.add_step_result(step_result)
            await self._persist_run(run)
            self._update_span(span, error=step_result.error)
            await self._emit("step_failed", {
                "workflow_id": self.workflow_id,
                "run_id": run.run_id,
                "step": step.id,
                "agent": step.agent_name,
                "error": step_result.error,
                "error_type": step_result.error_type,
                "attempts": step_result.attempts,
                "duration": step_result.duration,
            })
            return {
                "ok": False, "content": None, "cancelled": False,
                "error": step_result.error, "error_type": step_result.error_type,
            }

        step_result.status = RunStatus.COMPLETED
        run.add_step_result(step_result)
        await self._persist_run(run)
        self._update_span(span, output=response.content, usage=outcome["usage"])
        await self._emit("step_completed", {
            "workflow_id": self.workflow_id,
            "run_id": run.run_id,
            "step": step.id,
            "agent": step.agent_name,
            "result": response.content,
            "duration": step_result.duration,
            "attempts": step_result.attempts,
        })
        return {
            "ok": True, "content": response.content, "cancelled": False,
            "error": None, "error_type": None,
        }

    # ------------------------------------------------------------ hierarchical
    async def _execute_hierarchical(self, task: str, run: WorkflowRun, trace=None) -> Dict[str, Any]:
        """协调者规划 → 工作者依次执行 → 协调者汇总。"""
        if len(self.config.agents) < 2:
            raise ValueError("hierarchical pattern requires at least 2 agents")

        coordinator = self.agents.get(self.config.agents[0].name)
        worker_names = [cfg.name for cfg in self.config.agents[1:]]
        if coordinator is None or not worker_names:
            raise ValueError("hierarchical pattern requires a coordinator and workers")

        index = 0
        plan_input = (
            f"{task}\n\n[协调者] 请把任务拆解为 {len(worker_names)} 个以内的子任务，"
            "给出简洁执行计划；不要直接给最终答案。"
        )
        plan = await self._execute_recorded_step(
            step=WorkflowStep(id="plan", agent_name=self.config.agents[0].name),
            agent=coordinator, input_text=plan_input, run=run, trace=trace, index=index,
        )
        index += 1
        if not plan["ok"]:
            if not plan["cancelled"]:
                run.mark_failed(plan["error"] or "coordinator plan failed")
            return {"final_result": None, "plan": None, "worker_results": []}

        plan_text = plan["content"] or ""
        worker_results: List[str] = []
        failed_workers: List[str] = []
        for worker_name in worker_names:
            if run.should_stop():
                break
            agent = self.agents.get(worker_name)
            if agent is None:
                failed_workers.append(worker_name)
                continue
            worker_input = (
                f"{task}\n\n[执行计划]\n{plan_text}\n\n"
                f"[你的分工] 请执行计划中适合你的部分（工作者：{worker_name}），给出阶段结果。"
            )
            outcome = await self._execute_recorded_step(
                step=WorkflowStep(id=f"worker_{index}", agent_name=worker_name),
                agent=agent, input_text=worker_input, run=run, trace=trace, index=index,
            )
            index += 1
            if outcome["ok"]:
                worker_results.append(f"[{worker_name}]\n{outcome['content']}")
            elif outcome["cancelled"]:
                break
            else:
                failed_workers.append(worker_name)

        if not worker_results:
            run.mark_failed("all workers failed")
            return {"final_result": None, "plan": plan_text, "worker_results": []}

        synthesis_input = (
            f"{task}\n\n[执行计划]\n{plan_text}\n\n[工作者结果]\n"
            + "\n\n".join(worker_results)
            + "\n\n[协调者] 请综合以上结果，给出最终答案。"
        )
        synthesis = await self._execute_recorded_step(
            step=WorkflowStep(id="synthesis", agent_name=self.config.agents[0].name),
            agent=coordinator, input_text=synthesis_input, run=run, trace=trace, index=index,
        )
        if not synthesis["ok"]:
            if not synthesis["cancelled"]:
                run.mark_failed(synthesis["error"] or "coordinator synthesis failed")
            return {"final_result": None, "plan": plan_text, "worker_results": worker_results}

        if failed_workers:
            run.mark_partial("some workers failed")
        return {
            "final_result": synthesis["content"],
            "plan": plan_text,
            "worker_results": worker_results,
            "failed_workers": failed_workers,
        }

    # ------------------------------------------------------------------ debate
    async def _execute_debate(self, task: str, run: WorkflowRun, trace=None) -> Dict[str, Any]:
        """多辩手两轮讨论 → 裁判综合出最终答案。"""
        if len(self.config.agents) < 3:
            raise ValueError("debate pattern requires at least 3 agents")

        debater_names = [cfg.name for cfg in self.config.agents[:-1]]
        judge_name = self.config.agents[-1].name
        judge = self.agents.get(judge_name)
        if judge is None:
            raise ValueError("debate pattern requires a judge agent")

        rounds = max(1, min(2, int(self.config.max_iterations or 2)))
        index = 0
        positions: Dict[str, str] = {}
        failed: List[str] = []

        for round_no in range(1, rounds + 1):
            for name in debater_names:
                if run.should_stop():
                    break
                agent = self.agents.get(name)
                if agent is None:
                    failed.append(name)
                    continue
                others = [
                    f"[{other}]\n{positions[other]}"
                    for other in debater_names
                    if other != name and other in positions
                ]
                if round_no == 1:
                    input_text = (
                        f"{task}\n\n[辩论第 1 轮] 请独立给出你的观点与答案，"
                        "简洁说明理由。"
                    )
                else:
                    input_text = (
                        f"{task}\n\n[你的上一轮观点]\n{positions.get(name, '（无）')}\n\n"
                        f"[其他辩手观点]\n" + ("\n\n".join(others) or "（无）") + "\n\n"
                        "[第 2 轮] 请回应其他观点、修正自己的立场，并给出最终答案。"
                    )
                outcome = await self._execute_recorded_step(
                    step=WorkflowStep(id=f"debate_r{round_no}_{name}", agent_name=name),
                    agent=agent, input_text=input_text, run=run, trace=trace, index=index,
                )
                index += 1
                if outcome["ok"]:
                    positions[name] = outcome["content"] or ""
                elif outcome["cancelled"]:
                    break
                else:
                    failed.append(name)

        if not positions:
            run.mark_failed("all debaters failed")
            return {"final_result": None, "positions": {}}

        judge_input = (
            f"{task}\n\n[辩手最终观点]\n"
            + "\n\n".join(f"[{name}]\n{text}" for name, text in positions.items())
            + "\n\n[裁判] 请综合评判各辩手观点，给出最终答案。"
        )
        verdict = await self._execute_recorded_step(
            step=WorkflowStep(id="judge", agent_name=judge_name),
            agent=judge, input_text=judge_input, run=run, trace=trace, index=index,
        )
        if not verdict["ok"]:
            if not verdict["cancelled"]:
                run.mark_failed(verdict["error"] or "judge failed")
            return {"final_result": None, "positions": positions}

        if failed:
            run.mark_partial("some debaters failed")
        return {"final_result": verdict["content"], "positions": positions, "failed_debaters": failed}

    # ------------------------------------------------------------------ voting
    async def _execute_voting(self, task: str, run: WorkflowRun, trace=None) -> Dict[str, Any]:
        """多个候选独立作答 → 裁判比较并裁决出最终答案。"""
        if len(self.config.agents) < 3:
            raise ValueError("voting pattern requires at least 3 agents")

        candidate_names = [cfg.name for cfg in self.config.agents[:-1]]
        judge_name = self.config.agents[-1].name
        judge = self.agents.get(judge_name)
        if judge is None:
            raise ValueError("voting pattern requires a judge agent")

        index = 0
        candidates: List[str] = []
        failed: List[str] = []
        for name in candidate_names:
            if run.should_stop():
                break
            agent = self.agents.get(name)
            if agent is None:
                failed.append(name)
                continue
            input_text = (
                f"{task}\n\n[候选方案] 请独立完成任务并给出你的答案；"
                "不要假设其他候选的存在。"
            )
            outcome = await self._execute_recorded_step(
                step=WorkflowStep(id=f"candidate_{name}", agent_name=name),
                agent=agent, input_text=input_text, run=run, trace=trace, index=index,
            )
            index += 1
            if outcome["ok"]:
                candidates.append(f"[{name}]\n{outcome['content']}")
            elif outcome["cancelled"]:
                break
            else:
                failed.append(name)

        if not candidates:
            run.mark_failed("all candidates failed")
            return {"final_result": None, "candidates": []}

        judge_input = (
            f"{task}\n\n[候选答案]\n" + "\n\n".join(candidates)
            + "\n\n[裁决] 请比较各候选答案，选出最佳答案并给出最终答复。"
        )
        verdict = await self._execute_recorded_step(
            step=WorkflowStep(id="judge", agent_name=judge_name),
            agent=judge, input_text=judge_input, run=run, trace=trace, index=index,
        )
        if not verdict["ok"]:
            if not verdict["cancelled"]:
                run.mark_failed(verdict["error"] or "judge failed")
            return {"final_result": None, "candidates": candidates}

        if failed:
            run.mark_partial("some candidates failed")
        return {"final_result": verdict["content"], "candidates": candidates, "failed_candidates": failed}

    # ----------------------------------------------------------------- dynamic
    @staticmethod
    def _parse_dynamic_plan(text: Optional[str]) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:]
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(cleaned[start:end + 1])
        except (TypeError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    async def _execute_dynamic(self, task: str, run: WorkflowRun, trace=None) -> Dict[str, Any]:
        """协调者逐轮决定下一位工作者，最多 max_iterations 轮，最后汇总。"""
        if len(self.config.agents) < 2:
            raise ValueError("dynamic pattern requires at least 2 agents")

        coordinator_name = self.config.agents[0].name
        worker_names = [cfg.name for cfg in self.config.agents[1:]]
        coordinator = self.agents.get(coordinator_name)
        if coordinator is None or not worker_names:
            raise ValueError("dynamic pattern requires a coordinator and workers")

        max_rounds = max(1, min(10, int(self.config.max_iterations or 10)))
        index = 0
        history: List[str] = []
        failed = False
        plan_errors = 0

        for round_no in range(1, max_rounds + 1):
            if run.should_stop():
                break
            history_text = "\n\n".join(history) or "（尚无执行记录）"
            plan_input = (
                f"{task}\n\n[协调者] 可用工作者：{', '.join(worker_names)}\n"
                f"[已有执行记录]\n{history_text}\n\n"
                "请决定下一步：只输出 JSON，不要输出其他文字。格式："
                '{"done": false, "next": "工作者名", "task": "给该工作者的具体子任务"}；'
                '如果已经可以结束，输出 {"done": true}。'
            )
            plan = await self._execute_recorded_step(
                step=WorkflowStep(id=f"dynamic_plan_{round_no}", agent_name=coordinator_name),
                agent=coordinator, input_text=plan_input, run=run, trace=trace, index=index,
            )
            index += 1
            if not plan["ok"]:
                if not plan["cancelled"]:
                    run.mark_failed(plan["error"] or "coordinator planning failed")
                return {"final_result": None, "history": history}

            payload = self._parse_dynamic_plan(plan["content"])
            if payload is None:
                plan_errors += 1
                if round_no == max_rounds:
                    break
                next_name = worker_names[0]
                subtask = plan["content"] or "继续推进任务"
            else:
                if payload.get("done") is True:
                    break
                next_name = payload.get("next") or payload.get("worker") or worker_names[0]
                subtask = payload.get("task") or payload.get("subtask") or "继续推进任务"
                if next_name not in worker_names:
                    plan_errors += 1
                    next_name = worker_names[0]

            worker = self.agents.get(next_name)
            if worker is None:
                failed = True
                break
            worker_input = (
                f"{task}\n\n[协调者安排的子任务]\n{subtask}\n\n"
                f"[已有执行记录]\n{history_text}\n\n请完成该子任务并给出结果。"
            )
            outcome = await self._execute_recorded_step(
                step=WorkflowStep(id=f"dynamic_step_{round_no}", agent_name=next_name),
                agent=worker, input_text=worker_input, run=run, trace=trace, index=index,
            )
            index += 1
            if outcome["ok"]:
                history.append(f"[{next_name}]\n{outcome['content']}")
            elif outcome["cancelled"]:
                break
            else:
                failed = True
                break

        final_input = (
            f"{task}\n\n[执行记录]\n" + ("\n\n".join(history) or "（无）")
            + "\n\n[协调者] 请根据以上执行记录给出最终答案。"
        )
        final = await self._execute_recorded_step(
            step=WorkflowStep(id="dynamic_final", agent_name=coordinator_name),
            agent=coordinator, input_text=final_input, run=run, trace=trace, index=index,
        )
        if not final["ok"]:
            if not final["cancelled"]:
                run.mark_failed(final["error"] or "coordinator finalization failed")
            return {"final_result": None, "history": history}

        if failed or plan_errors:
            run.mark_partial("dynamic execution had fallback/failed steps")
        return {
            "final_result": final["content"],
            "history": history,
            "rounds": len(history),
            "plan_errors": plan_errors,
        }

    # -------------------------------------------------------------- group chat
    def _parse_group_tool(self, content: str) -> Optional[Dict[str, str]]:
        """解析执行器中介的工具调用：ask_agent / handoff_to。

        返回 None 表示不是工具指令；返回带 invalid 的字典表示工具指令格式/目标非法，
        调用方应标记 partial，而不是把这段 JSON 当普通回答继续。
        """
        payload = self._parse_dynamic_plan(content)
        if not payload or "tool" not in payload:
            return None
        tool = str(payload.get("tool") or "").strip().lower()
        if tool not in ("ask_agent", "handoff_to"):
            return {"tool": tool, "invalid": "unknown_tool"}
        target = str(payload.get("agent") or payload.get("target") or "").strip()
        task = str(payload.get("task") or payload.get("question") or "").strip()
        if not target or not task:
            return {"tool": tool, "invalid": "missing_agent_or_task"}
        return {"tool": tool, "agent": target, "task": task}

    async def _execute_group_tool(
        self,
        *,
        caller_name: str,
        content: str,
        task: str,
        member_names: List[str],
        transcript: List[Tuple[str, str]],
        run: WorkflowRun,
        trace,
        index: int,
        tool_calls: int,
    ) -> Tuple[bool, int, int, bool]:
        """执行 Agent 发起的 ask_agent / handoff_to；返回 (handled, index, calls, ok)。"""
        directive = self._parse_group_tool(content)
        if not directive:
            return False, index, tool_calls, True
        if directive.get("invalid"):
            return True, index, tool_calls, False
        if tool_calls >= MAX_GROUP_TOOL_CALLS:
            return True, index, tool_calls, False
        target = directive["agent"]
        if target not in member_names:
            return True, index, tool_calls, False
        agent = self.agents.get(target)
        if agent is None:
            return True, index, tool_calls, False

        recent = "\n\n".join(f"[{speaker}] {text}" for speaker, text in transcript[-16:]) or "（尚无发言）"
        tool_prompt = (
            f"{task}\n\n[群聊记录]\n{recent}\n\n"
            f"[工具调用 ask_agent] {caller_name} 请求你（{target}）处理：{directive['task']}\n"
            "请直接完成这个请求，并把结果清楚地返回给调用者。"
        )
        tool_result = await self._execute_recorded_step(
            step=WorkflowStep(id=f"tool_{tool_calls + 1}_{caller_name}_{target}", agent_name=target),
            agent=agent, input_text=tool_prompt, run=run, trace=trace, index=index,
            sender=caller_name, receiver=target, response_receiver=caller_name,
            message_content=f"[工具] {caller_name} → {target}: {directive['task']}",
        )
        index += 1
        tool_calls += 1
        if not tool_result["ok"]:
            return True, index, tool_calls, False
        transcript.append((target, tool_result["content"] or ""))

        if directive["tool"] == "ask_agent":
            follow_prompt = (
                f"{task}\n\n[群聊记录]\n"
                + "\n\n".join(f"[{speaker}] {text}" for speaker, text in transcript[-16:])
                + f"\n\n[工具结果] {target} 已返回结果。请作为 {caller_name} 基于该结果给出最终回答。"
            )
            follow = await self._execute_recorded_step(
                step=WorkflowStep(id=f"tool_followup_{tool_calls}_{caller_name}", agent_name=caller_name),
                agent=self.agents[caller_name], input_text=follow_prompt, run=run, trace=trace, index=index,
                sender=target, receiver=caller_name, response_receiver="group",
                message_content="基于工具结果给出最终回答",
            )
            index += 1
            if not follow["ok"]:
                return True, index, tool_calls, False
            transcript.append((caller_name, follow["content"] or ""))
        return True, index, tool_calls, True

    async def _execute_group_chat(self, task: str, run: WorkflowRun, trace=None) -> Dict[str, Any]:
        """受控 Agent 群聊：Lead 可选；共享 transcript；最多 max_iterations 轮。

        有 Lead（第一个 coordinator）时：Lead 每轮决定下一位发言者/子任务，成员回应；
        没有 Lead 时：成员按 round-robin 轮流发言。成员回复中的 @name 会优先成为
        下一位发言者（仅无 Lead 模式），用于轻量的互相点名。
        """
        if len(self.config.agents) < 2:
            raise ValueError("group_chat pattern requires at least 2 agents")

        max_turns = max(1, min(20, int(self.config.max_iterations or 12)))
        first = self.config.agents[0]
        first_role = getattr(first.role, "value", str(first.role))
        lead_config = first if first_role == "coordinator" else None
        lead_name = lead_config.name if lead_config else None
        member_names = [cfg.name for cfg in self.config.agents if cfg.name != lead_name]
        if lead_name and not member_names:
            raise ValueError("group_chat with a lead requires at least one member")
        if not member_names:
            raise ValueError("group_chat requires at least one member")

        transcript: List[Tuple[str, str]] = []
        index = 0
        had_failure = False
        plan_errors = 0
        tool_calls = 0

        def transcript_text(limit: int = 16) -> str:
            recent = transcript[-limit:]
            return "\n\n".join(f"[{speaker}] {content}" for speaker, content in recent) or "（尚无发言）"

        def remember(speaker: str, content: str) -> None:
            if content:
                transcript.append((speaker, content))

        if lead_config:
            lead = self.agents.get(lead_name)
            if lead is None:
                raise ValueError(f"Agent not found: {lead_name}")
            finished_summary: Optional[str] = None
            for turn in range(1, max_turns + 1):
                if run.should_stop():
                    break
                plan_input = (
                    f"[原始任务] {task}\n\n[群聊记录]\n{transcript_text()}\n\n"
                    f"[Lead 指令] 你是 {lead_name}。请决定下一步：只输出 JSON，不要输出其他文字。"
                    "格式：{\"done\": false, \"next\": \"成员名\", \"task\": \"给该成员的具体子任务\"}；"
                    "如果已经可以结束，输出 {\"done\": true, \"summary\": \"最终总结\"}。"
                    f"next 只能是以下成员之一：{', '.join(member_names)}；"
                    "task 必须直接服务于原始任务，禁止编造不存在的成员或无关项目；"
                    "如果原始任务很明确，请让子任务直接推进它（例如解释 list/tuple），不要泛泛讨论项目。"
                )
                plan = await self._execute_recorded_step(
                    step=WorkflowStep(id=f"lead_plan_{turn}", agent_name=lead_name),
                    agent=lead, input_text=plan_input, run=run, trace=trace, index=index,
                    sender="group", receiver=lead_name, response_receiver="group",
                    message_content="[系统] 请 Lead 决定下一位发言者与子任务",
                )
                index += 1
                if not plan["ok"]:
                    if not plan["cancelled"]:
                        run.mark_failed(plan["error"] or "lead planning failed")
                    return {"final_result": None, "transcript": transcript}

                payload = self._parse_dynamic_plan(plan["content"])
                remember(lead_name, plan["content"] or "")
                if payload and payload.get("done") is True:
                    finished_summary = str(payload.get("summary") or plan["content"] or "")
                    break

                if payload:
                    next_name = str(payload.get("next") or payload.get("worker") or "").strip()
                    subtask = str(payload.get("task") or payload.get("subtask") or "继续推进任务")
                else:
                    plan_errors += 1
                    next_name = ""
                    # Lead 没按 JSON 返回时，绝不把它的闲聊当成子任务，回退到原始任务
                    subtask = f"请直接完成原始任务：{task}"
                if next_name not in member_names:
                    if next_name:
                        plan_errors += 1
                    next_name = member_names[(turn - 1) % len(member_names)]

                member = self.agents.get(next_name)
                if member is None:
                    had_failure = True
                    break
                member_input = (
                    f"{task}\n\n[群聊记录]\n{transcript_text()}\n\n"
                    f"[Lead 指派] {subtask}\n请作为 {next_name} 回应并推进原始任务；"
                    "只围绕原始任务作答，不要编造无关的项目背景或成员；"
                    "如果 Lead 的子任务与原始任务无关，请忽略它，直接完成原始任务。"
                    f"如需另一位成员协助，可只输出 JSON：{{\"tool\": \"ask_agent\", "
                    f"\"agent\": \"成员名\", \"task\": \"...\"}}；可用成员：{', '.join(member_names)}。"
                )
                reply = await self._execute_recorded_step(
                    step=WorkflowStep(id=f"turn_{turn}_{next_name}", agent_name=next_name),
                    agent=member, input_text=member_input, run=run, trace=trace, index=index,
                    sender=lead_name, receiver=next_name, response_receiver="group",
                    message_content=subtask,
                )
                index += 1
                if reply["ok"]:
                    remember(next_name, reply["content"] or "")
                    handled, index, tool_calls, tool_ok = await self._execute_group_tool(
                        caller_name=next_name, content=reply["content"] or "", task=task,
                        member_names=member_names, transcript=transcript,
                        run=run, trace=trace, index=index, tool_calls=tool_calls,
                    )
                    if handled:
                        if not tool_ok:
                            had_failure = True
                            break
                        continue
                elif reply["cancelled"]:
                    break
                else:
                    had_failure = True
                    break

            if run.should_stop():
                return {"final_result": None, "transcript": transcript}

            if finished_summary is not None:
                final_content = finished_summary
            else:
                summary_input = (
                    f"{task}\n\n[群聊记录]\n{transcript_text()}\n\n"
                    f"[Lead 总结] 你是 {lead_name}，请根据以上讨论给出最终交付。"
                )
                final = await self._execute_recorded_step(
                    step=WorkflowStep(id="lead_summary", agent_name=lead_name),
                    agent=lead, input_text=summary_input, run=run, trace=trace, index=index,
                    sender="group", receiver=lead_name, response_receiver="group",
                    message_content="请总结以上群聊并给出最终交付",
                )
                if not final["ok"]:
                    if not final["cancelled"]:
                        run.mark_failed(final["error"] or "lead summary failed")
                    return {"final_result": None, "transcript": transcript}
                final_content = final["content"]

            if had_failure or plan_errors:
                run.mark_partial("group chat had failed turns or fallback plans")
            return {
                "final_result": final_content,
                "transcript": transcript,
                "turns": len(transcript),
                "plan_errors": plan_errors,
            }

        # 无 Lead：round-robin，并用 @name 或 JSON handoff 做轻量交接
        next_index = 0
        pending_handoff_task = ""
        for turn in range(1, max_turns + 1):
            if run.should_stop():
                break
            speaker = member_names[next_index % len(member_names)]
            agent = self.agents.get(speaker)
            if agent is None:
                had_failure = True
                break
            handoff_note = f"\n[上一位交接的任务] {pending_handoff_task}" if pending_handoff_task else ""
            group_input = (
                f"{task}\n\n[群聊记录]\n{transcript_text()}\n\n"
                f"[群聊] 你是 {speaker}。请阅读以上讨论，补充观点或推进任务；"
                "如需点名其他人，可在回复中使用 @成员名。"
                "如需另一位成员协助，可只输出 JSON：{\"tool\": \"ask_agent\", \"agent\": \"成员名\", \"task\": \"...\"}。"
                + handoff_note
            )
            outcome = await self._execute_recorded_step(
                step=WorkflowStep(id=f"turn_{turn}_{speaker}", agent_name=speaker),
                agent=agent, input_text=group_input, run=run, trace=trace, index=index,
                sender="group", receiver=speaker, response_receiver="group",
                message_content="请继续群聊，补充观点或推进任务",
            )
            index += 1
            if outcome["ok"]:
                content = outcome["content"] or ""
                remember(speaker, content)
                handled, index, tool_calls, tool_ok = await self._execute_group_tool(
                    caller_name=speaker, content=content, task=task,
                    member_names=member_names, transcript=transcript,
                    run=run, trace=trace, index=index, tool_calls=tool_calls,
                )
                if handled:
                    if not tool_ok:
                        had_failure = True
                    pending_handoff_task = ""
                    break
                pending_handoff_task = ""
                handoff = self._parse_dynamic_plan(content)
                handoff_target = str(handoff.get("handoff") or handoff.get("next") or "") if handoff else ""
                mention = re.search(r"@([A-Za-z0-9_\-]+)", content)
                if handoff_target in member_names:
                    next_index = member_names.index(handoff_target)
                    pending_handoff_task = str(handoff.get("task") or "").strip()
                elif mention and mention.group(1) in member_names:
                    next_index = member_names.index(mention.group(1))
                else:
                    next_index += 1
            elif outcome["cancelled"]:
                break
            else:
                had_failure = True
                break

        if not transcript:
            run.mark_failed("group chat produced no replies")
            return {"final_result": None, "transcript": transcript}
        if had_failure:
            run.mark_partial("some group chat turns failed")
        return {
            "final_result": transcript[-1][1],
            "transcript": transcript,
            "turns": len(transcript),
            "plan_errors": 0,
        }

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _extract_response_meta(response: Message) -> Tuple[Optional[str], Optional[str]]:
        metadata = response.metadata or {}
        model = metadata.get("model")
        finish_reason = metadata.get("finish_reason")
        return (
            str(model) if isinstance(model, (str, int, float)) else None,
            str(finish_reason) if finish_reason is not None else None,
        )

    def _trace_step(self, trace, step: WorkflowStep, index: int, input_text: str, agent: Agent):
        if not (self.tracer and trace):
            return None
        try:
            return self.tracer.trace_step(
                trace=trace,
                step_id=step.id,
                agent_name=step.agent_name,
                input_text=input_text,
                metadata={
                    "step_index": index,
                    "agent_model": getattr(getattr(agent, "config", None), "model", None),
                },
            )
        except Exception as e:  # noqa: BLE001
            print(f"[Langfuse] step 追踪异常已忽略: {e}")
            return None

    def _update_span(self, span, **kwargs):
        if not (self.tracer and span):
            return
        try:
            self.tracer.update_step(span=span, **kwargs)
        except Exception as e:  # noqa: BLE001
            print(f"[Langfuse] span 更新异常已忽略: {e}")

    def _flush(self):
        if not self.tracer:
            return
        try:
            self.tracer.flush()
        except Exception as e:  # noqa: BLE001
            print(f"[Langfuse] flush 异常已忽略: {e}")

    # --------------------------------------------------------------- controls
    def pause(self):
        if self._active_run is not None:
            self.status = "paused"

    def resume(self):
        if self._active_run is not None:
            self.status = "running"

    def stop(self):
        run = self._active_run or self.current_run
        if run is None or run.status not in (RunStatus.PENDING, RunStatus.RUNNING):
            return False
        run.request_stop()
        self.status = "stopping"
        return True

    def get_status(self) -> Dict[str, Any]:
        active_run = self._active_run or self.current_run
        status_dict: Dict[str, Any] = {
            "workflow_id": self.workflow_id,
            "status": self.status,
            "current_step": self.current_step,
            "total_steps": len(self.config.steps),
            "pattern": self.config.pattern.value,
            "messages": len(self.message_history),
            "elapsed_time": time.time() - self.start_time if self.start_time else 0,
            "is_busy": self.is_busy(),
            "stop_requested": active_run.stop_requested if active_run else False,
            "execution_policy": {
                "step_timeout_seconds": self.step_timeout_seconds,
                "max_attempts": self.max_attempts,
            },
        }
        if active_run:
            status_dict["run_id"] = active_run.run_id
            status_dict["trace_id"] = active_run.trace_id
            status_dict["current_run"] = {
                "run_id": active_run.run_id,
                "status": active_run.status.value,
                "trace_id": active_run.trace_id,
                "total_tokens": active_run.total_tokens,
                "step_results": len(active_run.step_results),
                "stop_requested": active_run.stop_requested,
                "error": active_run.error,
            }
        return status_dict

    def get_run(self, run_id: str) -> Optional[WorkflowRun]:
        return self.runs.get(run_id)

    def get_run_messages(self, run_id: str) -> List[Message]:
        return list(self.run_messages.get(run_id, []))

    def list_runs(self) -> List[Dict[str, Any]]:
        return [
            {
                "run_id": run.run_id,
                "status": run.status.value,
                "created_at": run.created_at,
                "total_tokens": run.total_tokens,
            }
            for run in self.runs.values()
        ]
