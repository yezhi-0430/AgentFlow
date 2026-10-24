"""
持久化功能测试 - 验证运行记录保存和查询
"""
import pytest
import os
import tempfile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agentflow.storage.models import Base, WorkflowRunModel, StepResultModel, RunStatusEnum, UsageTypeEnum
from agentflow.storage.repository import RunRepository
from agentflow.core.run import WorkflowRun, StepResult, RunStatus, UsageType


@pytest.fixture
def test_db():
    """创建临时测试数据库"""
    # 使用临时文件
    temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    temp_db.close()

    db_url = f"sqlite:///{temp_db.name}"
    engine = create_engine(db_url)
    Base.metadata.create_all(bind=engine)

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    yield session

    # 清理
    session.close()
    engine.dispose()

    # Windows 文件锁问题：尝试删除，失败也继续
    try:
        os.unlink(temp_db.name)
    except (PermissionError, OSError):
        pass  # Windows 可能仍持有文件锁


def test_save_and_retrieve_run(test_db):
    """测试保存和检索运行记录"""
    # 创建运行记录
    run = WorkflowRun(
        run_id="test-run-1",
        workflow_id="test-workflow",
        task_input="test task",
        status=RunStatus.COMPLETED,
    )

    run.mark_started()
    run.mark_completed("test result")

    # 添加步骤结果
    step = StepResult(
        step_id="step-1",
        agent_name="worker_1",
        status=RunStatus.COMPLETED,
        started_at=1.0,
        completed_at=2.0,
        duration=1.0,
        usage={"total_tokens": 100},
        usage_type=UsageType.ACTUAL,
    )
    run.add_step_result(step)

    # 保存
    RunRepository.save_run(test_db, run)

    # 检索
    retrieved = RunRepository.get_run(test_db, "test-run-1")

    assert retrieved is not None
    assert retrieved.run_id == "test-run-1"
    assert retrieved.workflow_id == "test-workflow"
    assert retrieved.status == RunStatus.COMPLETED
    assert len(retrieved.step_results) == 1
    assert retrieved.step_results[0].step_id == "step-1"
    assert retrieved.step_results[0].usage_type == UsageType.ACTUAL


def test_update_existing_run(test_db):
    """测试更新现有运行记录"""
    # 创建初始运行
    run = WorkflowRun(
        run_id="test-run-2",
        workflow_id="test-workflow",
        task_input="test task",
        status=RunStatus.RUNNING,
    )

    RunRepository.save_run(test_db, run)

    # 更新状态
    run.mark_completed("final result")
    run.add_step_result(StepResult(
        step_id="step-1",
        agent_name="worker_1",
        status=RunStatus.COMPLETED,
    ))

    RunRepository.save_run(test_db, run)

    # 检索验证
    retrieved = RunRepository.get_run(test_db, "test-run-2")

    assert retrieved.status == RunStatus.COMPLETED
    assert retrieved.final_result == "final result"
    assert len(retrieved.step_results) == 1


def test_list_runs_by_workflow(test_db):
    """测试按工作流列出运行"""
    # 创建多个运行
    for i in range(3):
        run = WorkflowRun(
            run_id=f"run-{i}",
            workflow_id="workflow-1",
            task_input=f"task {i}",
        )
        RunRepository.save_run(test_db, run)

    # 创建另一个工作流的运行
    other_run = WorkflowRun(
        run_id="run-other",
        workflow_id="workflow-2",
        task_input="other task",
    )
    RunRepository.save_run(test_db, other_run)

    # 查询
    runs = RunRepository.list_runs(test_db, workflow_id="workflow-1")

    assert len(runs) == 3
    assert all(r.workflow_id == "workflow-1" for r in runs)


def test_list_all_runs_with_pagination(test_db):
    """测试分页列出所有运行"""
    # 创建多个运行
    for i in range(5):
        run = WorkflowRun(
            run_id=f"run-{i}",
            workflow_id="workflow-1",
            task_input=f"task {i}",
        )
        RunRepository.save_run(test_db, run)

    # 第一页
    page1 = RunRepository.list_runs(test_db, limit=2, offset=0)
    assert len(page1) == 2

    # 第二页
    page2 = RunRepository.list_runs(test_db, limit=2, offset=2)
    assert len(page2) == 2

    # 确保不重复
    page1_ids = {r.run_id for r in page1}
    page2_ids = {r.run_id for r in page2}
    assert len(page1_ids & page2_ids) == 0


def test_delete_run(test_db):
    """测试删除运行记录"""
    # 创建运行
    run = WorkflowRun(
        run_id="run-to-delete",
        workflow_id="workflow-1",
        task_input="task",
    )
    RunRepository.save_run(test_db, run)

    # 确认存在
    assert RunRepository.get_run(test_db, "run-to-delete") is not None

    # 删除
    success = RunRepository.delete_run(test_db, "run-to-delete")
    assert success is True

    # 确认已删除
    assert RunRepository.get_run(test_db, "run-to-delete") is None

    # 删除不存在的记录
    success = RunRepository.delete_run(test_db, "non-existent")
    assert success is False


def test_step_results_cascade_delete(test_db):
    """测试删除运行时级联删除步骤结果"""
    # 创建带步骤的运行
    run = WorkflowRun(
        run_id="run-with-steps",
        workflow_id="workflow-1",
        task_input="task",
    )

    for i in range(3):
        run.add_step_result(StepResult(
            step_id=f"step-{i}",
            agent_name=f"worker_{i}",
            status=RunStatus.COMPLETED,
        ))

    RunRepository.save_run(test_db, run)

    # 验证步骤已保存
    retrieved = RunRepository.get_run(test_db, "run-with-steps")
    assert len(retrieved.step_results) == 3

    # 删除运行
    RunRepository.delete_run(test_db, "run-with-steps")

    # 验证步骤也被删除
    step_count = test_db.query(StepResultModel).filter_by(run_id="run-with-steps").count()
    assert step_count == 0


def test_usage_type_persistence(test_db):
    """测试用量类型的持久化"""
    run = WorkflowRun(
        run_id="run-usage-types",
        workflow_id="workflow-1",
        task_input="task",
    )

    # 添加不同用量类型的步骤
    usage_types = [
        UsageType.ACTUAL,
        UsageType.ESTIMATED,
        UsageType.PARTIAL,
        UsageType.UNKNOWN,
    ]

    for i, usage_type in enumerate(usage_types):
        run.add_step_result(StepResult(
            step_id=f"step-{i}",
            agent_name=f"worker_{i}",
            status=RunStatus.COMPLETED,
            usage_type=usage_type,
        ))

    RunRepository.save_run(test_db, run)

    # 检索验证
    retrieved = RunRepository.get_run(test_db, "run-usage-types")

    for i, expected_type in enumerate(usage_types):
        assert retrieved.step_results[i].usage_type == expected_type
