"""OpenRouter 模型目录 API 测试（不访问网络）。"""
import pytest
from fastapi.testclient import TestClient

from agentflow.api.app import app
from agentflow.api.routes import models


@pytest.fixture(autouse=True)
def clear_cache():
    models._cache["expires_at"] = 0
    models._cache["payload"] = None
    models._cache["retry_after"] = 0
    yield
    models._cache["expires_at"] = 0
    models._cache["payload"] = None
    models._cache["retry_after"] = 0


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_openrouter_models_remote(client, monkeypatch):
    async def fake_fetch():
        return [{
            "id": "openai/gpt-5",
            "name": "GPT-5",
            "provider": "OpenAI",
            "context_length": 128000,
            "pricing": {"prompt": "0.001"},
            "supports_tools": True,
        }]

    monkeypatch.setattr(models, "_fetch_openrouter_models", fake_fetch)
    data = client.get("/api/models/openrouter").json()
    assert data["source"] == "remote"
    assert data["models"][0]["id"] == "openai/gpt-5"


def test_openrouter_models_fallback(client, monkeypatch):
    async def fail():
        raise RuntimeError("offline")

    monkeypatch.setattr(models, "_fetch_openrouter_models", fail)
    data = client.get("/api/models/openrouter").json()
    assert data["source"] == "fallback"
    assert len(data["models"]) >= 6
    assert all({"id", "name", "provider"} <= set(item) for item in data["models"])
    assert all(item.get("description") for item in data["models"])
    assert any(item["id"] == "openai/gpt-6.1-sol" for item in data["models"])
    assert not any(item["id"] in {"openai/gpt-4o", "anthropic/claude-3.5-sonnet"} for item in data["models"])


def test_openrouter_models_are_cached(client, monkeypatch):
    calls = {"n": 0}

    async def fake_fetch():
        calls["n"] += 1
        return [{"id": "x/y", "name": "Y", "provider": "X", "context_length": 1,
                 "pricing": {}, "supports_tools": False}]

    monkeypatch.setattr(models, "_fetch_openrouter_models", fake_fetch)
    client.get("/api/models/openrouter")
    client.get("/api/models/openrouter")
    assert calls["n"] == 1
