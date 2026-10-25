"""
运行记录存储库 - 数据访问层

记录数据是本地历史回看用途：只读写本地数据库，不触发任何模型调用。
写入操作串行化：SQLite 的写锁在并发工作流下容易冲突，统一用进程内锁保护。
"""
import threading
import time
from typing import Any, Dict, List, Optional

from sqlalchemy import asc, desc
from sqlalchemy.orm import Session

from agentflow.core.definition import DefinitionValidationError, WorkflowDefinition
from agentflow.core.run import (
    RECORD_SCHEMA_VERSION,
    RunStatus,
    StepResult,
    UsageType,
    WorkflowRun,
)
from agentflow.storage.models import (
    ExperimentCandidateModel,
    ExperimentModel,
    RunStatusEnum,
    StepResultModel,
    UsageTypeEnum,
    WorkflowDefinitionModel,
    WorkflowMessageModel,
    WorkflowRunModel,
)

_RUN_STATUS_TO_ENUM = {
    RunStatus.PENDING: RunStatusEnum.PENDING,
    RunStatus.RUNNING: RunStatusEnum.RUNNING,
    RunStatus.COMPLETED: RunStatusEnum.COMPLETED,
    RunStatus.FAILED: RunStatusEnum.FAILED,
    RunStatus.STOPPED: RunStatusEnum.STOPPED,
    RunStatus.PARTIAL: RunStatusEnum.PARTIAL,
    RunStatus.CANCELLED: RunStatusEnum.CANCELLED,
}

_ENUM_TO_RUN_STATUS = {value: key for key, value in _RUN_STATUS_TO_ENUM.items()}

_USAGE_TYPE_TO_ENUM = {
    UsageType.ACTUAL: UsageTypeEnum.ACTUAL,
    UsageType.ESTIMATED: UsageTypeEnum.ESTIMATED,
    UsageType.PARTIAL: UsageTypeEnum.PARTIAL,
    UsageType.UNKNOWN: UsageTypeEnum.UNKNOWN,
}

_ENUM_TO_USAGE_TYPE = {value: key for key, value in _USAGE_TYPE_TO_ENUM.items()}

# 进程内写锁：SQLite 写入串行化，避免多工作流并发时 database is locked
_WRITE_LOCK = threading.RLock()


def _serialized_write(func):
    def wrapper(*args, **kwargs):
        with _WRITE_LOCK:
            return func(*args, **kwargs)

    wrapper.__name__ = func.__name__
    return wrapper


class RunRepository:
    """运行记录存储库"""

    @staticmethod
    def _run_status_to_enum(status: RunStatus) -> RunStatusEnum:
        return _RUN_STATUS_TO_ENUM[status]

    @staticmethod
    def _enum_to_run_status(enum_val: RunStatusEnum) -> RunStatus:
        return _ENUM_TO_RUN_STATUS[enum_val]

    @staticmethod
    def _usage_type_to_enum(usage_type: UsageType) -> UsageTypeEnum:
        return _USAGE_TYPE_TO_ENUM[usage_type]

    @staticmethod
    def _enum_to_usage_type(enum_val: UsageTypeEnum) -> UsageType:
        return _ENUM_TO_USAGE_TYPE[enum_val]

    # ------------------------------------------------------------------ mapping
    @staticmethod
    def _apply_run_fields(model: WorkflowRunModel, run: WorkflowRun) -> None:
        model.workflow_id = run.workflow_id
        model.workflow_name = run.workflow_name or None
        model.task_input = run.task_input
        model.status = RunRepository._run_status_to_enum(run.status)
        model.schema_version = run.schema_version or RECORD_SCHEMA_VERSION
        model.trace_id = run.trace_id
        model.experiment_id = run.experiment_id
        model.candidate_id = run.candidate_id
        model.case_id = run.case_id
        model.fingerprint = run.fingerprint
        model.evidence_ref = run.evidence_ref
        model.score = run.score
        model.passed = run.passed
        model.score_status = run.score_status
        model.score_source = run.score_source
        model.created_at = run.created_at
        model.started_at = run.started_at
        model.completed_at = run.completed_at
        model.final_result = run.final_result
        model.error = run.error
        model.stop_requested = bool(run.stop_requested)
        model.config_snapshot = run.config_snapshot
        model.total_tokens = run.total_tokens
        model.total_duration = run.total_duration

    @staticmethod
    def _build_step_model(step_result: StepResult) -> StepResultModel:
        return StepResultModel(
            run_id="",  # 由 relationship 负责关联
            step_id=step_result.step_id,
            step_index=step_result.step_index,
            agent_name=step_result.agent_name,
            status=RunRepository._run_status_to_enum(step_result.status),
            input_message_id=step_result.input_message_id,
            output_message_id=step_result.output_message_id,
            input_text=step_result.input_text,
            output_text=step_result.output_text,
            model=step_result.model,
            finish_reason=step_result.finish_reason,
            error=step_result.error,
            error_type=step_result.error_type,
            attempts=step_result.attempts,
            started_at=step_result.started_at,
            completed_at=step_result.completed_at,
            duration=step_result.duration,
            usage=step_result.usage,
            usage_type=RunRepository._usage_type_to_enum(step_result.usage_type),
        )

    @staticmethod
    def _step_model_to_result(model: StepResultModel) -> StepResult:
        return StepResult(
            step_id=model.step_id,
            agent_name=model.agent_name,
            status=RunRepository._enum_to_run_status(model.status),
            step_index=model.step_index,
            input_message_id=model.input_message_id,
            output_message_id=model.output_message_id,
            input_text=model.input_text,
            output_text=model.output_text,
            error=model.error,
            error_type=model.error_type,
            attempts=model.attempts or 1,
            model=model.model,
            finish_reason=model.finish_reason,
            started_at=model.started_at,
            completed_at=model.completed_at,
            duration=model.duration,
            usage=model.usage,
            usage_type=RunRepository._enum_to_usage_type(model.usage_type),
        )

    @staticmethod
    def _model_to_run(model: WorkflowRunModel) -> WorkflowRun:
        run = WorkflowRun(
            run_id=model.run_id,
            workflow_id=model.workflow_id,
            workflow_name=model.workflow_name or "",
            task_input=model.task_input,
            status=RunRepository._enum_to_run_status(model.status),
            schema_version=model.schema_version if model.schema_version is not None else 1,
            trace_id=model.trace_id,
            experiment_id=model.experiment_id,
            candidate_id=model.candidate_id,
            case_id=model.case_id,
            fingerprint=model.fingerprint,
            evidence_ref=model.evidence_ref,
            score=model.score,
            passed=model.passed,
            score_status=model.score_status,
            score_source=model.score_source,
            created_at=model.created_at,
            started_at=model.started_at,
            completed_at=model.completed_at,
            final_result=model.final_result,
            error=model.error,
            stop_requested=bool(model.stop_requested),
            config_snapshot=model.config_snapshot or {},
            total_tokens=model.total_tokens or 0,
            total_duration=model.total_duration or 0.0,
        )
        for step_model in model.step_results:
            run.step_results.append(RunRepository._step_model_to_result(step_model))
        return run

    # ------------------------------------------------------------------ writes
    @staticmethod
    @_serialized_write
    def save_run(db: Session, run: WorkflowRun) -> WorkflowRunModel:
        """保存或更新运行记录（含步骤结果）"""
        existing = db.query(WorkflowRunModel).filter_by(run_id=run.run_id).first()

        if existing:
            RunRepository._apply_run_fields(existing, run)
            # 步骤结果整体替换，避免重复
            db.query(StepResultModel).filter_by(run_id=run.run_id).delete()
            existing.step_results = [
                RunRepository._build_step_model(step_result)
                for step_result in run.step_results
            ]
            db.commit()
            db.refresh(existing)
            return existing

        run_model = WorkflowRunModel(run_id=run.run_id)
        RunRepository._apply_run_fields(run_model, run)
        run_model.step_results = [
            RunRepository._build_step_model(step_result) for step_result in run.step_results
        ]
        db.add(run_model)
        db.commit()
        db.refresh(run_model)
        return run_model

    # ------------------------------------------------------------------- reads
    @staticmethod
    def get_run(db: Session, run_id: str) -> Optional[WorkflowRun]:
        """获取运行记录（只读，不触发模型调用）"""
        run_model = db.query(WorkflowRunModel).filter_by(run_id=run_id).first()
        if not run_model:
            return None
        return RunRepository._model_to_run(run_model)

    @staticmethod
    def list_runs(
        db: Session,
        workflow_id: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
        experiment_id: Optional[str] = None,
        candidate_id: Optional[str] = None,
        fingerprint: Optional[str] = None,
        case_id: Optional[str] = None,
    ) -> List[WorkflowRun]:
        """列出运行记录（只读，不触发模型调用）"""
        query = db.query(WorkflowRunModel)
        if workflow_id:
            query = query.filter_by(workflow_id=workflow_id)
        if experiment_id:
            query = query.filter_by(experiment_id=experiment_id)
        if candidate_id:
            query = query.filter_by(candidate_id=candidate_id)
        if fingerprint:
            query = query.filter_by(fingerprint=fingerprint)
        if case_id:
            query = query.filter_by(case_id=case_id)
        query = query.order_by(desc(WorkflowRunModel.created_at))
        query = query.limit(max(1, min(limit, 500))).offset(max(0, offset))

        return [RunRepository._model_to_run(model) for model in query.all()]

    @staticmethod
    def get_run_by_experiment_case(
        db: Session, experiment_id: str, candidate_id: str, case_id: str
    ) -> Optional[WorkflowRun]:
        model = (
            db.query(WorkflowRunModel)
            .filter_by(experiment_id=experiment_id, candidate_id=candidate_id, case_id=case_id)
            .order_by(desc(WorkflowRunModel.created_at))
            .first()
        )
        return RunRepository._model_to_run(model) if model else None

    @staticmethod
    @_serialized_write
    def set_evidence_ref(db: Session, run_id: str, evidence_ref: str) -> bool:
        model = db.query(WorkflowRunModel).filter_by(run_id=run_id).first()
        if not model:
            return False
        model.evidence_ref = evidence_ref
        db.commit()
        return True

    @staticmethod
    @_serialized_write
    def update_scoring(
        db: Session,
        run_id: str,
        *,
        score: Optional[float],
        passed: Optional[bool],
        score_status: Optional[str],
        score_source: Optional[str],
    ) -> bool:
        model = db.query(WorkflowRunModel).filter_by(run_id=run_id).first()
        if not model:
            return False
        model.score = score
        model.passed = passed
        model.score_status = score_status
        model.score_source = score_source
        db.commit()
        return True

    @staticmethod
    def count_runs(db: Session, workflow_id: Optional[str] = None) -> int:
        """统计运行记录总数（用于分页）"""
        query = db.query(WorkflowRunModel)
        if workflow_id:
            query = query.filter_by(workflow_id=workflow_id)
        return query.count()

    @staticmethod
    @_serialized_write
    def prune_runs(
        db: Session,
        max_runs: int = 1000,
        retention_days: float = 0.0,
    ) -> int:
        """按保留策略清理旧运行记录，返回删除数量。

        - retention_days > 0：删除创建时间早于保留窗口的记录；
        - max_runs > 0：只保留最近 max_runs 条（按 created_at 升序删除更旧的）。
        """
        deleted = 0
        if retention_days and retention_days > 0:
            cutoff = time.time() - retention_days * 86400
            old_ids = [
                row.run_id
                for row in db.query(WorkflowRunModel.run_id)
                .filter(WorkflowRunModel.created_at < cutoff)
                .all()
            ]
            if old_ids:
                db.query(StepResultModel).filter(StepResultModel.run_id.in_(old_ids)).delete(
                    synchronize_session=False
                )
                deleted += db.query(WorkflowRunModel).filter(
                    WorkflowRunModel.run_id.in_(old_ids)
                ).delete(synchronize_session=False)

        if max_runs and max_runs > 0:
            total = db.query(WorkflowRunModel).count()
            if total > max_runs:
                excess = total - max_runs
                old_ids = [
                    row.run_id
                    for row in db.query(WorkflowRunModel.run_id)
                    .order_by(asc(WorkflowRunModel.created_at))
                    .limit(excess)
                    .all()
                ]
                if old_ids:
                    db.query(StepResultModel).filter(StepResultModel.run_id.in_(old_ids)).delete(
                        synchronize_session=False
                    )
                    deleted += db.query(WorkflowRunModel).filter(
                        WorkflowRunModel.run_id.in_(old_ids)
                    ).delete(synchronize_session=False)

        if deleted:
            db.commit()
        return deleted

    @staticmethod
    @_serialized_write
    def delete_run(db: Session, run_id: str) -> bool:
        """删除运行记录"""
        run_model = db.query(WorkflowRunModel).filter_by(run_id=run_id).first()
        if run_model:
            db.delete(run_model)
            db.commit()
            return True
        return False


class WorkflowDefinitionRepository:
    """工作流定义存储库（不含密钥）"""

    @staticmethod
    @_serialized_write
    def save(db: Session, definition: WorkflowDefinition) -> WorkflowDefinitionModel:
        """按 workflow_id upsert 定义"""
        payload = definition.to_dict()
        model = (
            db.query(WorkflowDefinitionModel)
            .filter_by(workflow_id=definition.workflow_id)
            .first()
        )
        if model is None:
            model = WorkflowDefinitionModel(workflow_id=definition.workflow_id)
            db.add(model)
        model.name = definition.name
        model.pattern = definition.pattern
        model.schema_version = definition.schema_version
        model.definition_json = payload
        model.created_at = definition.created_at
        model.updated_at = definition.updated_at
        db.commit()
        db.refresh(model)
        return model

    @staticmethod
    def get(db: Session, workflow_id: str) -> Optional[WorkflowDefinition]:
        model = (
            db.query(WorkflowDefinitionModel)
            .filter_by(workflow_id=workflow_id)
            .first()
        )
        if model is None:
            return None
        try:
            return WorkflowDefinition.from_dict(model.definition_json)
        except DefinitionValidationError as e:
            print(f"Skipping invalid workflow definition {workflow_id}: {e}")
            return None

    @staticmethod
    def list_all(db: Session) -> List[WorkflowDefinition]:
        definitions = []
        models = (
            db.query(WorkflowDefinitionModel)
            .order_by(WorkflowDefinitionModel.created_at)
            .all()
        )
        for model in models:
            try:
                definitions.append(WorkflowDefinition.from_dict(model.definition_json))
            except DefinitionValidationError as e:
                print(f"Skipping invalid workflow definition {model.workflow_id}: {e}")
        return definitions

    @staticmethod
    @_serialized_write
    def delete(db: Session, workflow_id: str) -> bool:
        model = (
            db.query(WorkflowDefinitionModel)
            .filter_by(workflow_id=workflow_id)
            .first()
        )
        if model is None:
            return False
        db.delete(model)
        db.commit()
        return True


class ExperimentRepository:
    """Harness²-lite 实验/候选元数据存储（不含密钥）"""

    @staticmethod
    @_serialized_write
    def save_experiment(
        db: Session,
        *,
        experiment_id: str,
        name: str,
        dataset_id: Optional[str] = None,
        dataset_version: Optional[str] = None,
        scorer_id: Optional[str] = None,
        scorer_version: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> ExperimentModel:
        model = db.query(ExperimentModel).filter_by(experiment_id=experiment_id).first()
        if model is None:
            model = ExperimentModel(experiment_id=experiment_id)
            db.add(model)
        model.name = name
        model.dataset_id = dataset_id
        model.dataset_version = dataset_version
        model.scorer_id = scorer_id
        model.scorer_version = scorer_version
        model.notes = notes
        if model.created_at is None:
            model.created_at = time.time()
        db.commit()
        db.refresh(model)
        return model

    @staticmethod
    def get_experiment(db: Session, experiment_id: str) -> Optional[ExperimentModel]:
        return db.query(ExperimentModel).filter_by(experiment_id=experiment_id).first()

    @staticmethod
    def list_experiments(db: Session) -> List[ExperimentModel]:
        return db.query(ExperimentModel).order_by(desc(ExperimentModel.created_at)).all()

    @staticmethod
    @_serialized_write
    def save_candidate(
        db: Session,
        *,
        candidate_id: str,
        experiment_id: str,
        name: str,
        fingerprint: str,
        config_json: Optional[Dict[str, Any]] = None,
    ) -> ExperimentCandidateModel:
        model = (
            db.query(ExperimentCandidateModel)
            .filter_by(candidate_id=candidate_id)
            .first()
        )
        if model is None:
            model = ExperimentCandidateModel(candidate_id=candidate_id)
            db.add(model)
        model.experiment_id = experiment_id
        model.name = name
        model.fingerprint = fingerprint
        model.config_json = config_json or {}
        if model.created_at is None:
            model.created_at = time.time()
        db.commit()
        db.refresh(model)
        return model

    @staticmethod
    def list_candidates(db: Session, experiment_id: str) -> List[ExperimentCandidateModel]:
        return (
            db.query(ExperimentCandidateModel)
            .filter_by(experiment_id=experiment_id)
            .order_by(ExperimentCandidateModel.created_at)
            .all()
        )


class MessageRepository:
    """群聊消息持久化：按 run / workflow 回放，写入前脱敏。"""

    @staticmethod
    @_serialized_write
    def save(db: Session, message: Any, *, workflow_id: str, run_id: Optional[str] = None) -> bool:
        from agentflow.core.redaction import redact_text

        message_id = str(getattr(message, "id", "") or "")
        if not message_id:
            return False
        if db.query(WorkflowMessageModel).filter_by(id=message_id).first():
            return False
        message_type = getattr(message, "message_type", "task")
        message_type = getattr(message_type, "value", message_type)
        model = WorkflowMessageModel(
            id=message_id,
            workflow_id=workflow_id,
            run_id=run_id,
            sender=str(getattr(message, "sender", "") or ""),
            receiver=str(getattr(message, "receiver", "") or ""),
            content=redact_text(str(getattr(message, "content", "") or ""), limit=20_000),
            message_type=str(message_type or "task"),
            meta_json=getattr(message, "metadata", None) or {},
            timestamp=float(getattr(message, "timestamp", None) or time.time()),
            parent_id=getattr(message, "parent_id", None),
            created_at=time.time(),
        )
        db.add(model)
        db.commit()
        return True

    @staticmethod
    def list_by_run(db: Session, run_id: str) -> List[Dict[str, Any]]:
        rows = (
            db.query(WorkflowMessageModel)
            .filter_by(run_id=run_id)
            .order_by(asc(WorkflowMessageModel.timestamp))
            .all()
        )
        return [MessageRepository._to_dict(row) for row in rows]

    @staticmethod
    def list_by_workflow(
        db: Session, workflow_id: str, limit: int = 500
    ) -> List[Dict[str, Any]]:
        rows = (
            db.query(WorkflowMessageModel)
            .filter_by(workflow_id=workflow_id)
            .order_by(asc(WorkflowMessageModel.timestamp))
            .limit(max(1, min(limit, 2000)))
            .all()
        )
        return [MessageRepository._to_dict(row) for row in rows]

    @staticmethod
    def _to_dict(row: WorkflowMessageModel) -> Dict[str, Any]:
        return {
            "id": row.id,
            "sender": row.sender,
            "receiver": row.receiver,
            "content": row.content,
            "message_type": row.message_type,
            "metadata": row.meta_json or {},
            "timestamp": row.timestamp,
            "parent_id": row.parent_id,
            "workflow_id": row.workflow_id,
            "run_id": row.run_id,
        }
