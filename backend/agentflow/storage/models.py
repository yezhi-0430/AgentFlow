"""
数据库模型 - 持久化工作流运行记录
"""
from sqlalchemy import (
    Boolean,
    Column,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship, declarative_base
import enum

Base = declarative_base()


class RunStatusEnum(enum.Enum):
    """运行状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


class UsageTypeEnum(enum.Enum):
    """用量类型枚举"""
    ACTUAL = "actual"
    ESTIMATED = "estimated"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class WorkflowRunModel(Base):
    """工作流运行记录表"""
    __tablename__ = "workflow_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(36), unique=True, nullable=False, index=True)
    workflow_id = Column(String(36), nullable=False, index=True)
    workflow_name = Column(String(200), nullable=True)
    task_input = Column(Text, nullable=False)
    status = Column(SQLEnum(RunStatusEnum), nullable=False, default=RunStatusEnum.PENDING)

    # 记录格式版本（便于后续迁移）：新记录为 3，旧记录迁移后标记为 1/2
    schema_version = Column(Integer, nullable=True, default=3)

    # 外部追踪关联（Langfuse trace_id）
    trace_id = Column(String(64), nullable=True, index=True)

    # Harness²-lite：实验/候选/case/指纹/证据关联
    experiment_id = Column(String(64), nullable=True, index=True)
    candidate_id = Column(String(64), nullable=True, index=True)
    case_id = Column(String(64), nullable=True, index=True)
    fingerprint = Column(String(64), nullable=True, index=True)
    evidence_ref = Column(String(500), nullable=True)

    # 评分（0-1 归一化）
    score = Column(Float, nullable=True)
    passed = Column(Boolean, nullable=True)
    score_status = Column(String(32), nullable=True)
    score_source = Column(String(32), nullable=True)

    # 时间戳
    created_at = Column(Float, nullable=False)
    started_at = Column(Float, nullable=True)
    completed_at = Column(Float, nullable=True)

    # 结果
    final_result = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    stop_requested = Column(Boolean, nullable=False, default=False)

    # 配置快照（不含密钥/连接配置）
    config_snapshot = Column(JSON, nullable=True)

    # 统计
    total_tokens = Column(Integer, default=0)
    total_duration = Column(Float, default=0.0)

    # 关系
    step_results = relationship("StepResultModel", back_populates="run", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<WorkflowRun {self.run_id} status={self.status.value}>"


class StepResultModel(Base):
    """步骤结果表"""
    __tablename__ = "step_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(36), ForeignKey("workflow_runs.run_id", ondelete="CASCADE"), nullable=False, index=True)
    step_id = Column(String(100), nullable=False)
    step_index = Column(Integer, nullable=True)
    agent_name = Column(String(100), nullable=False)
    status = Column(SQLEnum(RunStatusEnum), nullable=False)

    # 消息 ID
    input_message_id = Column(String(36), nullable=True)
    output_message_id = Column(String(36), nullable=True)

    # 输入输出内容（本地留存，用于历史回看；不回传外部平台）
    input_text = Column(Text, nullable=True)
    output_text = Column(Text, nullable=True)

    # 模型信息
    model = Column(String(100), nullable=True)
    finish_reason = Column(String(50), nullable=True)

    # 错误
    error = Column(Text, nullable=True)
    error_type = Column(String(32), nullable=True)

    # 执行控制
    attempts = Column(Integer, nullable=False, default=1)

    # 时间
    started_at = Column(Float, nullable=True)
    completed_at = Column(Float, nullable=True)
    duration = Column(Float, nullable=True)

    # 用量
    usage = Column(JSON, nullable=True)
    usage_type = Column(SQLEnum(UsageTypeEnum), default=UsageTypeEnum.UNKNOWN)

    # 关系
    run = relationship("WorkflowRunModel", back_populates="step_results")

    def __repr__(self):
        return f"<StepResult {self.step_id} {self.agent_name} status={self.status.value}>"


class WorkflowDefinitionModel(Base):
    """工作流定义表

    只保存定义（名称、模式、Agent、步骤、非敏感连接信息）；
    API Key/secret/token 不落库。定义 JSON 由 core.definition 负责版本化与校验。
    """

    __tablename__ = "workflow_definitions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_id = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    pattern = Column(String(32), nullable=False)
    schema_version = Column(Integer, nullable=False, default=1)
    definition_json = Column(JSON, nullable=False)
    created_at = Column(Float, nullable=False)
    updated_at = Column(Float, nullable=False)

    def __repr__(self):
        return f"<WorkflowDefinition {self.workflow_id} '{self.name}'>"


class ExperimentModel(Base):
    """Harness²-lite 实验元数据"""

    __tablename__ = "experiments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    experiment_id = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    dataset_id = Column(String(100), nullable=True)
    dataset_version = Column(String(32), nullable=True)
    scorer_id = Column(String(100), nullable=True)
    scorer_version = Column(String(32), nullable=True)
    created_at = Column(Float, nullable=False)
    notes = Column(Text, nullable=True)

    def __repr__(self):
        return f"<Experiment {self.experiment_id} '{self.name}'>"


class ExperimentCandidateModel(Base):
    """实验候选配置（含配置指纹，不含密钥）"""

    __tablename__ = "experiment_candidates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(String(64), unique=True, nullable=False, index=True)
    experiment_id = Column(String(64), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    fingerprint = Column(String(64), nullable=False, index=True)
    config_json = Column(JSON, nullable=True)
    created_at = Column(Float, nullable=False)

    def __repr__(self):
        return f"<ExperimentCandidate {self.candidate_id} fp={self.fingerprint[:8]}>"

