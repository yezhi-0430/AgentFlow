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
import os
import re
import time
import uuid

from agentflow.core.agent import Agent, AgentConfig
from agentflow.core.message import Message, MessageType
from agentflow.core.redaction import redact_text
from agentflow.core.run import WorkflowRun, StepResult, RunStatus, UsageType

try:
    from agentflow.storage import get_db, RunRepository
    STORAGE_AVAILABLE = True
except ImportError:
    STORAGE_AVAILABLE = False

try:
    from agentflow.tracing import LangfuseTracer
    TRACING_AVAILABLE = True
except ImportError:
    TRACING_AVAILABLE = False


SUPPORTED_PATTERNS = ("sequential", "parallel")
MAX_RUNS_IN_MEMORY = 50
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
    """工作流模式；只有 SEQUENTIAL / PARALLEL 可执行"""
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    DEBATE = "debate"
    VOTING = "voting"
    HIERARCHICAL = "hierarchical"
    DYNAMIC = "dynamic"


def ensure_supported_pattern(pattern: WorkflowPattern) -> None:
    value = pattern.value if isinstance(pattern, WorkflowPattern) else str(pattern)
    if value not in SUPPORTED_PATTERNS:
        raise UnsupportedPatternError(
            f"Workflow pattern '{value}' is not supported yet. "
            f"Supported patterns: {', '.join(SUPPORTED_PATTERNS)}"
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
            else:
                workflow_result = await self._execute_parallel(initial_task, run, trace)

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
