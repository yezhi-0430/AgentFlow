"""API smoke tests use a local fake model and never call an external provider."""
import pytest
from fastapi.testclient import TestClient

from agentflow.api.app import app
from agentflow.api.routes import workflow


class FakeAdapter:
    async def complete(self, messages, model, **kwargs):
        return {
            "content": f"processed: {messages[-1]['content']}",
            "model": model,
            "usage": {"total_tokens": 10},
        }


@pytest.fixture
def client(monkeypatch):
    workflow.workflows.clear()
    monkeypatch.setattr(workflow.AdapterFactory, "create_adapter", lambda **kwargs: FakeAdapter())
    with TestClient(app) as test_client:
        yield test_client
    workflow.workflows.clear()


def create_workflow(client):
    response = client.post("/api/workflows", json={
        "name": "API smoke test",
        "description": "No real model calls",
        "pattern": "sequential",
        "config": {"agent_count": 3, "llm_provider": "openai", "api_key": "test-only-not-a-real-key", "model": "test-model"},
    })
    assert response.status_code == 200
    return response.json()["workflow_id"]


def test_health(client):
    assert client.get("/health").json() == {"status": "healthy"}
    assert "openrouter" in client.get("/api/workflows/providers").json()["providers"]


def test_create_execute_messages_and_delete(client):
    identifier = create_workflow(client)
    status_url = f"/api/workflows/{identifier}/status"
    assert client.get(status_url).json()["total_steps"] == 3
    response = client.post(f"/api/workflows/{identifier}/execute", json={"task": "test task"})
    assert response.status_code == 200
    assert client.get(status_url).json()["status"] == "completed"
    messages = client.get("/api/messages", params={"workflow_id": identifier}).json()["messages"]
    assert len(messages) == 6
    assert messages[-1]["content"] == "processed: processed: processed: test task"
    assert client.delete(f"/api/workflows/{identifier}").status_code == 200
    assert client.get(status_url).status_code == 404
    assert client.get("/api/workflows").json()["workflows"] == []


def test_workflow_details_include_model_and_existing_state_fields(client):
    identifier = create_workflow(client)
    response = client.get(f"/api/workflows/{identifier}")
    assert response.status_code == 200
    data = response.json()
    assert data["agents"][0]["model"] == "test-model"
    assert data["agents"][0]["messages_sent"] == 0
    assert data["agents"][0]["messages_received"] == 0
    assert "test-only-not-a-real-key" not in response.text


def test_missing_api_key_returns_client_error(client):
    response = client.post("/api/workflows", json={"name": "Missing key", "pattern": "sequential", "config": {}})
    assert response.status_code == 400


def test_unknown_workflow_returns_not_found(client):
    assert client.get("/api/workflows/missing/status").status_code == 404
    assert client.delete("/api/workflows/missing").status_code == 404
