"""
工作流定义持久化 / 导入导出 / 重启恢复 测试

全部使用假适配器与临时数据库，不访问外部模型。
"""
import json

import pytest
from fastapi.testclient import TestClient

from agentflow.adapters.base import LLMAdapter
from agentflow.api.app import app
from agentflow.api.routes import workflow as workflow_routes
from agentflow.core.definition import DefinitionValidationError, WorkflowDefinition
from agentflow.storage import WorkflowDefinitionRepository, get_db
from agentflow.storage.models import WorkflowDefinitionModel


class FakeAdapter(LLMAdapter):
    def __init__(self):
        self.call_count = 0

    async def complete(self, messages, model, temperature=0.7, max_tokens=2000, **kwargs):
        self.call_count += 1
        return {
            "content": f"processed: {messages[-1]['content']}",
            "model": model,
            "usage": {"prompt_tokens": 5, "completion_tokens": 6, "total_tokens": 11},
            "finish_reason": "stop",
        }

    async def stream_complete(self, messages, model, temperature=0.7, max_tokens=2000, **kwargs):
        yield "x"


SECRET = "test-secret-key-abc123"


@pytest.fixture
def client(monkeypatch):
    workflow_routes.workflows.clear()
    # 清理可能残留的定义，避免生命周期恢复干扰断言
    with get_db() as db:
        for definition in WorkflowDefinitionRepository.list_all(db):
            WorkflowDefinitionRepository.delete(db, definition.workflow_id)
    monkeypatch.setattr(
        workflow_routes.AdapterFactory, "create_adapter", lambda **kwargs: FakeAdapter()
    )
    with TestClient(app) as test_client:
        yield test_client
    workflow_routes.workflows.clear()


def _create(client, name="definition test", pattern="sequential", count=2):
    response = client.post("/api/workflows", json={
        "name": name,
        "description": "for definition tests",
        "pattern": pattern,
        "config": {
            "agent_count": count,
            "llm_provider": "openrouter",
            "api_key": SECRET,
            "base_url": "https://openrouter.ai/api/v1",
            "model": "openai/gpt-4o-mini",
        },
    })
    assert response.status_code == 200, response.text
    return response.json()["workflow_id"]


# ------------------------------------------------------------------ persistence
def test_definition_is_persisted_without_secrets(client):
    workflow_id = _create(client)

    with get_db() as db:
        definition = WorkflowDefinitionRepository.get(db, workflow_id)
        raw_row = (
            db.query(WorkflowDefinitionModel)
            .filter_by(workflow_id=workflow_id)
            .first()
        )
        raw_json = json.dumps(raw_row.definition_json, ensure_ascii=False)

    assert definition is not None
    assert definition.schema_version == 1
    assert definition.pattern == "sequential"
    assert len(definition.agents) == 2
    assert SECRET not in raw_json
    assert "api_key" not in json.dumps(definition.to_dict(), ensure_ascii=False)


def test_export_import_roundtrip(client):
    workflow_id = _create(client, name="export me")
    exported = client.get(f"/api/workflows/{workflow_id}/definition")
    assert exported.status_code == 200
    payload = exported.json()
    assert payload["schema_version"] == 1
    assert payload["workflow_id"] == workflow_id
    assert SECRET not in json.dumps(payload, ensure_ascii=False)

    imported = client.post("/api/workflows/import", json=payload)
    assert imported.status_code == 200, imported.text
    body = imported.json()
    assert body["workflow_id"] != workflow_id, "导入必须分配新的 workflow_id"
    assert body["requires_credentials"] is True
    assert body["pattern"] == payload["pattern"]

    definition = client.get(f"/api/workflows/{body['workflow_id']}/definition").json()
    assert definition["name"] == payload["name"]
    assert [step["id"] for step in definition["steps"]] == [s["id"] for s in payload["steps"]]
    assert [agent["name"] for agent in definition["agents"]] == [a["name"] for a in payload["agents"]]

    # 导入的工作流没有密钥：执行返回清晰错误；提供密钥后可以执行
    missing = client.post(f"/api/workflows/{body['workflow_id']}/execute", json={"task": "hi"})
    assert missing.status_code == 400
    assert "api key" in missing.json()["detail"].lower()

    executed = client.post(
        f"/api/workflows/{body['workflow_id']}/execute",
        json={"task": "hi", "api_key": SECRET},
    )
    assert executed.status_code == 200
    status = client.get(f"/api/workflows/{body['workflow_id']}/status").json()
    assert status["status"] == "completed"
    assert status["requires_credentials"] is False


def test_delete_removes_definition(client):
    workflow_id = _create(client)
    assert client.delete(f"/api/workflows/{workflow_id}").status_code == 200
    with get_db() as db:
        assert WorkflowDefinitionRepository.get(db, workflow_id) is None


def test_restart_restores_definition_and_requires_key(client):
    workflow_id = _create(client, name="restart me")
    with get_db() as db:
        stored = WorkflowDefinitionRepository.get(db, workflow_id)
    assert stored is not None

    # 模拟后端重启：清空内存工作流，再从数据库恢复
    workflow_routes.workflows.clear()
    restored = workflow_routes.restore_workflows()
    assert restored >= 1
    assert workflow_id in workflow_routes.workflows

    executor = workflow_routes.workflows[workflow_id]
    assert executor.requires_credentials is True

    listing = client.get("/api/workflows").json()["workflows"]
    item = next(w for w in listing if w["workflow_id"] == workflow_id)
    assert item["requires_credentials"] is True
    assert item["name"] == "restart me"

    detail = client.get(f"/api/workflows/{workflow_id}").json()
    assert detail["requires_credentials"] is True
    assert len(detail["agents"]) == 2
    assert detail["agents"][0]["status"] == "unavailable"
    assert detail["agents"][0]["model"] == "openai/gpt-4o-mini"

    status = client.get(f"/api/workflows/{workflow_id}/status").json()
    assert status["requires_credentials"] is True

    # 恢复后执行：无密钥 → 400；带密钥 → 使用（内存）适配器执行
    assert client.post(
        f"/api/workflows/{workflow_id}/execute", json={"task": "x"}
    ).status_code == 400
    assert client.post(
        f"/api/workflows/{workflow_id}/execute", json={"task": "x", "api_key": SECRET}
    ).status_code == 200
    assert client.get(f"/api/workflows/{workflow_id}/status").json()["status"] == "completed"

    # 运行记录落在同一个 workflow_id 下
    runs = client.get(f"/api/workflows/{workflow_id}/runs").json()
    assert runs["total"] >= 1
    assert runs["runs"][0]["workflow_id"] == workflow_id


def test_restore_skips_corrupt_definition(client):
    workflow_id = _create(client)

    with get_db() as db:
        row = db.query(WorkflowDefinitionModel).filter_by(workflow_id=workflow_id).first()
        row.definition_json = {"schema_version": 999, "name": "broken"}
        db.commit()

    workflow_routes.workflows.clear()
    assert workflow_routes.restore_workflows() == 0
    assert workflow_id not in workflow_routes.workflows


# ---------------------------------------------------------------- validation
def test_import_rejects_invalid_definitions(client):
    base = {
        "schema_version": 1,
        "workflow_id": "x",
        "name": "bad",
        "pattern": "sequential",
        "agents": [{"name": "worker_1", "role": "worker", "model": "m"}],
        "steps": [{"id": "step_1", "agent_name": "worker_1"}],
    }

    too_new = dict(base, schema_version=99)
    assert client.post("/api/workflows/import", json=too_new).status_code == 400

    no_agents = dict(base, agents=[])
    assert client.post("/api/workflows/import", json=no_agents).status_code == 400

    unknown_agent = dict(
        base, steps=[{"id": "step_1", "agent_name": "ghost"}]
    )
    assert client.post("/api/workflows/import", json=unknown_agent).status_code == 400

    unsupported = dict(base, pattern="debate")
    assert client.post("/api/workflows/import", json=unsupported).status_code == 400

    duplicate_step = dict(
        base,
        steps=[
            {"id": "step_1", "agent_name": "worker_1"},
            {"id": "step_1", "agent_name": "worker_1"},
        ],
    )
    assert client.post("/api/workflows/import", json=duplicate_step).status_code == 400


def test_import_strips_secret_fields(client):
    payload = {
        "schema_version": 1,
        "workflow_id": "incoming",
        "name": "imported secrets",
        "pattern": "parallel",
        "agents": [
            {
                "name": "worker_1",
                "role": "worker",
                "model": "m",
                "api_key": "sk-should-not-survive",
                "metadata": {"secret_token": "sk-should-not-survive"},
            }
        ],
        "steps": [{"id": "step_1", "agent_name": "worker_1"}],
        "connection": {"provider": "openai", "api_key": "sk-should-not-survive"},
    }
    response = client.post("/api/workflows/import", json=payload)
    assert response.status_code == 200, response.text

    imported_id = response.json()["workflow_id"]
    exported = client.get(f"/api/workflows/{imported_id}/definition")
    text = json.dumps(exported.json(), ensure_ascii=False)
    assert "sk-should-not-survive" not in text
    assert "api_key" not in text
    assert "secret_token" not in text


def test_definition_from_dict_validates_and_strips():
    payload = {
        "schema_version": 1,
        "workflow_id": "abc",
        "name": "valid",
        "pattern": "sequential",
        "agents": [{"name": "a", "role": "worker", "model": "m", "api_key": "sk-x"}],
        "steps": [{"id": "s", "agent_name": "a"}],
        "connection": {"provider": "openai", "base_url": "https://x"},
    }
    definition = WorkflowDefinition.from_dict(payload)
    assert "api_key" not in definition.agents[0]
    assert definition.connection == {"provider": "openai", "base_url": "https://x"}

    with pytest.raises(DefinitionValidationError):
        WorkflowDefinition.from_dict({"schema_version": 1, "name": "no agents"})
