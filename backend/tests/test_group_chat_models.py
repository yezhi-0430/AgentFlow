"""群聊多模型配置 API 测试：全程使用假 Adapter，不访问外部模型。"""
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


def _multi_model_payload():
    return {
        "name": "multi-model",
        "pattern": "group_chat",
        "config": {
            "llm_provider": "openrouter",
            "api_key": "sk-or-test",
            "model": "openai/gpt-5",
            "group_chat": {
                "enable_lead": True,
                "lead_model": "anthropic/claude-sonnet-4.5",
                "max_turns": 1,
                "members": [
                    {"name": "member_1", "model": "openai/gpt-5"},
                    {"name": "member_2", "model": "google/gemini-2.5-pro"},
                ],
            },
        },
    }


def _create(client, payload):
    return client.post("/api/workflows", json=payload)


def test_group_chat_accepts_per_member_models(client):
    response = _create(client, _multi_model_payload())
    assert response.status_code == 200, response.text
    agents = {a["name"]: a["model"] for a in response.json()["agents"]}
    assert agents == {
        "lead": "anthropic/claude-sonnet-4.5",
        "member_1": "openai/gpt-5",
        "member_2": "google/gemini-2.5-pro",
    }


def test_group_chat_old_config_still_works(client):
    response = _create(client, {
        "name": "old", "pattern": "group_chat",
        "config": {"agent_count": 3, "llm_provider": "openai",
                   "api_key": "test-only-not-a-real-key", "model": "test-model"},
    })
    assert response.status_code == 200, response.text
    assert [a["model"] for a in response.json()["agents"]] == ["test-model"] * 3


def test_group_chat_rejects_non_openrouter(client):
    response = _create(client, {
        "name": "bad", "pattern": "group_chat",
        "config": {"llm_provider": "openai", "api_key": "x", "model": "gpt-4",
                   "group_chat": {"members": [
                       {"name": "member_1", "model": "openai/gpt-5"},
                       {"name": "member_2", "model": "google/gemini-2.5-pro"},
                   ]}},
    })
    assert response.status_code == 400
    assert "OpenRouter" in response.json()["detail"]


@pytest.mark.parametrize("members", [
    [],
    [{"name": "member_1", "model": "a"}, {"name": "member_1", "model": "b"}],
])
def test_group_chat_rejects_invalid_members(client, members):
    response = _create(client, {
        "name": "bad", "pattern": "group_chat",
        "config": {"llm_provider": "openrouter", "api_key": "sk-or-test",
                   "model": "openai/gpt-5",
                   "group_chat": {"members": members}},
    })
    assert response.status_code == 400


def test_group_chat_allows_lead_plus_one_member(client):
    response = _create(client, {
        "name": "lead-one", "pattern": "group_chat",
        "config": {"llm_provider": "openrouter", "api_key": "sk-or-test",
                   "model": "openai/gpt-5",
                   "group_chat": {"enable_lead": True,
                                  "lead_model": "anthropic/claude-sonnet-4.5",
                                  "max_turns": 1,
                                  "members": [{"name": "member_1", "model": "openai/gpt-5"}]}},
    })
    assert response.status_code == 200, response.text
    assert len(response.json()["agents"]) == 2


def _execute(client, workflow_id, task="task"):
    response = client.post(f"/api/workflows/{workflow_id}/execute", json={"task": task})
    assert response.status_code == 200, response.text
    return client.get(f"/api/workflows/{workflow_id}/status").json()


def test_messages_hide_internal_by_default(client):
    response = _create(client, _multi_model_payload())
    assert response.status_code == 200, response.text
    workflow_id = response.json()["workflow_id"]
    _execute(client, workflow_id)
    visible = client.get("/api/messages", params={"workflow_id": workflow_id}).json()["messages"]
    assert all(m["metadata"].get("visibility") != "internal" for m in visible)
    hidden = client.get(
        "/api/messages",
        params={"workflow_id": workflow_id, "include_internal": True},
    ).json()["messages"]
    assert any(m["metadata"].get("visibility") == "internal" for m in hidden)


def test_messages_keep_history_across_runs(client):
    response = _create(client, _multi_model_payload())
    assert response.status_code == 200, response.text
    workflow_id = response.json()["workflow_id"]
    _execute(client, workflow_id, "first")
    _execute(client, workflow_id, "second")
    messages = client.get(
        "/api/messages", params={"workflow_id": workflow_id, "limit": 200}
    ).json()["messages"]
    assert len({m["run_id"] for m in messages}) >= 2
    assert [m["timestamp"] for m in messages] == sorted(m["timestamp"] for m in messages)


def test_status_exposes_active_agent(client):
    response = _create(client, _multi_model_payload())
    workflow_id = response.json()["workflow_id"]
    status = _execute(client, workflow_id)
    assert "active_agent" in status
