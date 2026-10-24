"""pytest 全局配置：测试离线、不产生费用、不污染本地数据库。"""
import os
import tempfile

# 必须在任何 agentflow 模块导入前设置：让持久化测试使用独立临时数据库，
# 避免写入用户本地的 backend/agentflow_data.db。
os.environ.setdefault(
    "AGENTFLOW_DB_PATH",
    os.path.join(tempfile.mkdtemp(prefix="agentflow-tests-"), "agentflow_test.db"),
)
# 默认不采集/外发内容（Langfuse 追踪测试可按需覆盖）
os.environ.setdefault("LANGFUSE_CAPTURE_CONTENT", "false")

import pytest


@pytest.fixture(scope="session", autouse=True)
def _init_test_database():
    """使用 conftest 顶部的临时数据库，并建表（避免污染本地数据）。"""
    from agentflow.storage import init_db

    init_db()
    yield


@pytest.fixture(autouse=True)
def _clean_workflow_definitions():
    """每个测试开始前清空持久化的工作流定义，保证测试相互隔离。

    需要验证"重启恢复"的测试可以在用例内部自行创建定义并调用 restore。
    """
    try:
        from agentflow.storage import WorkflowDefinitionRepository, get_db

        with get_db() as db:
            for definition in WorkflowDefinitionRepository.list_all(db):
                WorkflowDefinitionRepository.delete(db, definition.workflow_id)
    except Exception:
        pass
    yield


@pytest.fixture(autouse=True)
def _disable_auto_evaluate(monkeypatch):
    """测试默认关闭 AUTO_EVALUATE。

    需要验证自动评估链路的用例，可在用例内部
    ``monkeypatch.setenv("AUTO_EVALUATE", "true")`` 覆盖本夹具。
    """
    monkeypatch.setenv("AUTO_EVALUATE", "false")
