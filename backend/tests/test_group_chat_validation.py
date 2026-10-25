"""群聊多模型：边界校验、dispatch 样式与消息 run_id。"""
import pytest
from fastapi.testclient import TestClient

from agentflow.api.app import app
from agentflow.api.routes import workflow


class FakeAdapter:
    async def complete(self, messages, model, **kwargs):
        return {"content": "processed", "model": model, "usage": {"total_tokens": 3}}


@pytest.fixture
def client(monkeypatch):
    workflow.workflows.clear()
    monkeypatch.setattr(workflow.AdapterFactory, "create_adapter", lambda **kwargs: FakeAdapter())
    with TestClient(app) as test_client:
        yield test_client
    workflow.workflows.clear()


def _payload(group_chat):
    return {
        "name": "validation",
        "pattern": "group_chat",
        "config": {
            "llm_provider": "openrouter",
            "api_key": "sk-or-test",
            "model": "openai/gpt-4o",
            "group_chat": group_chat,
        },
    }


@pytest.mark.parametrize("group_chat", [
    {"enable_lead": True, "lead_model": "x", "members": []},
    {"enable_lead": True, "lead_model": "x", "members": [{"name": f"m{i}", "model": "m"} for i in range(5)] + [{"name": "m5", "model": "m"}, {"name": "m6", "model": "m"}]},
    {"enable_lead": False, "members": [{"name": "member_1", "model": "m"}]},
    {"enable_lead": True, "members": [{"name": "member_1", "model": "m"}]},
    {"enable_lead": True, "lead_model": "x", "members": [{"name": "system", "model": "m"}]},
])
def test_group_chat_rejects_invalid_model_configs(client, group_chat):
    assert client.post("/api/workflows", json=_payload(group_chat)).status_code == 400


def test_group_chat_dispatch_is_system_and_messages_have_run_id(client):
    response = client.post("/api/workflows", json=_payload({
        "enable_lead": True,
        "lead_model": "openai/gpt-4o",
        "max_turns": 1,
        "members": [{"name": "member_1", "model": "deepseek/deepseek-chat"}],
    }))
    assert response.status_code == 200, response.text
    workflow_id = response.json()["workflow_id"]
    execute = client.post(f"/api/workflows/{workflow_id}/execute", json={"task": "task"})
    assert execute.status_code == 200
    messages = client.get("/api/messages", params={
        "workflow_id": workflow_id, "include_internal": True, "limit": 200,
    }).json()["messages"]
    assert all(message.get("run_id") for message in messages)
    dispatch = [
        message for message in messages
        if message["sender"] == "lead" and message["receiver"] == "member_1"
        and (message.get("metadata") or {}).get("step_id", "").startswith("turn_")
    ]
    assert dispatch
    assert all((message.get("metadata") or {}).get("visibility") == "system" for message in dispatch)
