"""
工作流运行模型 - 分离工作流定义与执行实例

记录格式版本化：修改字段语义时必须提升 RECORD_SCHEMA_VERSION。
v3：新增 run.trace_id、step.attempts、step.error_type（超时/重试/错误分类）。
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum
import time
import uuid

RECORD_SCHEMA_VERSION = 4


class RunStatus(Enum):
    """运行状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


class UsageType(Enum):
    """用量类型"""
    ACTUAL = "actual"
    ESTIMATED = "estimated"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


@dataclass
class StepResult:
    """步骤执行结果"""
    step_id: str
    agent_name: str
    status: RunStatus
    step_index: Optional[int] = None
    input_message_id: Optional[str] = None
    output_message_id: Optional[str] = None
    input_text: Optional[str] = None
    output_text: Optional[str] = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    attempts: int = 1
    model: Optional[str] = None
    finish_reason: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    duration: Optional[float] = None

    usage: Optional[Dict[str, Any]] = None
    usage_type: UsageType = UsageType.UNKNOWN

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "step_index": self.step_index,
            "agent_name": self.agent_name,
            "status": self.status.value,
            "input_message_id": self.input_message_id,
            "output_message_id": self.output_message_id,
            "input_text": self.input_text,
            "output_text": self.output_text,
            "error": self.error,
            "error_type": self.error_type,
            "attempts": self.attempts,
            "model": self.model,
            "finish_reason": self.finish_reason,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration": self.duration,
            "usage": self.usage,
            "usage_type": self.usage_type.value if self.usage_type else None,
        }


@dataclass
class WorkflowRun:
    """工作流运行实例"""
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    workflow_id: str = ""
    workflow_name: str = ""
    task_input: str = ""
    status: RunStatus = RunStatus.PENDING

    schema_version: int = RECORD_SCHEMA_VERSION

    # 外部追踪关联（Langfuse trace_id；未启用追踪时为 None）
    trace_id: Optional[str] = None

    # Harness²-lite：实验/候选/case/指纹/证据关联（可选）
    experiment_id: Optional[str] = None
    candidate_id: Optional[str] = None
    case_id: Optional[str] = None
    fingerprint: Optional[str] = None
    evidence_ref: Optional[str] = None

    # 评分（独立评分或确定性 rubric；0-1 归一化）
    score: Optional[float] = None
    passed: Optional[bool] = None
    score_status: Optional[str] = None
    score_source: Optional[str] = None

    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    final_result: Optional[str] = None
    error: Optional[str] = None
    step_results: List[StepResult] = field(default_factory=list)

    config_snapshot: Dict[str, Any] = field(default_factory=dict)

    stop_requested: bool = False

    total_tokens: int = 0
    total_duration: float = 0.0

    _should_stop: bool = False

    def mark_started(self):
        self.status = RunStatus.RUNNING
        self.started_at = time.time()

    def mark_completed(self, final_result: Optional[str] = None):
        self.status = RunStatus.COMPLETED
        self.completed_at = time.time()
        if final_result is not None:
            self.final_result = final_result

    def mark_failed(self, error: str):
        self.status = RunStatus.FAILED
        self.error = error
        self.completed_at = time.time()
        if self.step_results and not self.step_results[-1].error:
            self.step_results[-1].error = error

    def mark_stopped(self, reason: Optional[str] = None):
        self.status = RunStatus.STOPPED
        if reason:
            self.error = reason
        self.completed_at = time.time()

    def mark_partial(self, reason: Optional[str] = None):
        self.status = RunStatus.PARTIAL
        if reason:
            self.error = reason
        self.completed_at = time.time()

    def request_stop(self):
        self.stop_requested = True
        self._should_stop = True

    def should_stop(self) -> bool:
        return self._should_stop or self.stop_requested

    def add_step_result(self, result: StepResult):
        if result.step_index is None:
            result.step_index = len(self.step_results)
        self.step_results.append(result)

        if result.usage and result.usage.get("total_tokens"):
            self.total_tokens += result.usage["total_tokens"]
        if result.duration:
            self.total_duration += result.duration

    def get_step_result(self, step_id: str) -> Optional[StepResult]:
        for result in self.step_results:
            if result.step_id == step_id:
                return result
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "schema_version": self.schema_version,
            "trace_id": self.trace_id,
            "experiment_id": self.experiment_id,
            "candidate_id": self.candidate_id,
            "case_id": self.case_id,
            "fingerprint": self.fingerprint,
            "evidence_ref": self.evidence_ref,
            "score": self.score,
            "passed": self.passed,
            "score_status": self.score_status,
            "score_source": self.score_source,
            "task_input": self.task_input,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "final_result": self.final_result,
            "error": self.error,
            "stop_requested": self.stop_requested,
            "step_results": [r.to_dict() for r in self.step_results],
            "config_snapshot": self.config_snapshot,
            "total_tokens": self.total_tokens,
            "total_duration": self.total_duration,
        }
