"""OpenRouter 模型目录代理：缓存远程目录，失败时回退到精选列表。"""
import time
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter

router = APIRouter()

_CACHE_TTL_SECONDS = 600
_cache: Dict[str, Any] = {"expires_at": 0.0, "payload": None}

FALLBACK_MODELS: List[Dict[str, Any]] = [
    {"id": "openai/gpt-4o", "name": "GPT-4o", "provider": "OpenAI",
     "context_length": 128000, "pricing": {}, "supports_tools": True},
    {"id": "anthropic/claude-3.5-sonnet", "name": "Claude 3.5 Sonnet", "provider": "Anthropic",
     "context_length": 200000, "pricing": {}, "supports_tools": True},
    {"id": "google/gemini-2.0-flash-001", "name": "Gemini 2.0 Flash", "provider": "Google",
     "context_length": 1000000, "pricing": {}, "supports_tools": True},
    {"id": "deepseek/deepseek-chat", "name": "DeepSeek Chat", "provider": "DeepSeek",
     "context_length": 64000, "pricing": {}, "supports_tools": True},
    {"id": "qwen/qwen-2.5-72b-instruct", "name": "Qwen 2.5 72B", "provider": "Qwen",
     "context_length": 131072, "pricing": {}, "supports_tools": True},
    {"id": "x-ai/grok-2-1212", "name": "Grok 2", "provider": "xAI",
     "context_length": 131072, "pricing": {}, "supports_tools": True},
    {"id": "mistralai/mistral-large", "name": "Mistral Large", "provider": "Mistral",
     "context_length": 128000, "pricing": {}, "supports_tools": True},
]


def _normalise_model(item: Dict[str, Any]) -> Dict[str, Any]:
    model_id = str(item.get("id") or "")
    provider = model_id.split("/", 1)[0] if "/" in model_id else ""
    parameters = item.get("supported_parameters") or []
    return {
        "id": model_id,
        "name": str(item.get("name") or model_id),
        "provider": str(item.get("provider") or provider),
        "context_length": int(item.get("context_length") or 0),
        "pricing": item.get("pricing") or {},
        "supports_tools": "tools" in parameters,
    }


async def _fetch_openrouter_models() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get("https://openrouter.ai/api/v1/models")
        response.raise_for_status()
        payload = response.json()
    return [
        _normalise_model(item)
        for item in payload.get("data", [])
        if isinstance(item, dict) and item.get("id")
    ]


@router.get("/openrouter")
async def list_openrouter_models():
    now = time.time()
    if _cache["payload"] is not None and now < _cache["expires_at"]:
        return _cache["payload"]

    try:
        models = await _fetch_openrouter_models()
        if not models:
            raise RuntimeError("empty model catalog")
        result = {"models": models, "source": "remote"}
        _cache["payload"] = result
        _cache["expires_at"] = now + _CACHE_TTL_SECONDS
        return result
    except Exception:
        return {"models": FALLBACK_MODELS, "source": "fallback"}
