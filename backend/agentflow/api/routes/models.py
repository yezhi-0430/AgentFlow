"""OpenRouter 模型目录代理：缓存远程目录，失败时回退到精选列表。"""
import time
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter

router = APIRouter()

_CACHE_TTL_SECONDS = 600
_cache: Dict[str, Any] = {"expires_at": 0.0, "payload": None, "retry_after": 0.0}

FALLBACK_MODELS: List[Dict[str, Any]] = [
    {"id": "openai/gpt-6.1-sol", "name": "GPT-6.1 Sol", "provider": "OpenAI",
     "context_length": 1050000, "pricing": {}, "supports_tools": True,
     "description": "旗舰综合模型，超长上下文，适合 Lead、复杂规划与最终总结"},
    {"id": "openai/gpt-6-luna", "name": "GPT-6 Luna", "provider": "OpenAI",
     "context_length": 1050000, "pricing": {}, "supports_tools": True,
     "description": "低成本高吞吐，适合大规模成员发言与草稿"},
    {"id": "anthropic/claude-sonnet-5.5", "name": "Claude Sonnet 5.5", "provider": "Anthropic",
     "context_length": 1000000, "pricing": {}, "supports_tools": True,
     "description": "推理与代码均衡，长上下文，适合评审与实现"},
    {"id": "anthropic/claude-opus-5.5", "name": "Claude Opus 5.5", "provider": "Anthropic",
     "context_length": 1000000, "pricing": {}, "supports_tools": True,
     "description": "深度推理与长文写作，质量优先、成本较高"},
    {"id": "google/gemini-4-argon", "name": "Gemini 4 Argon", "provider": "Google",
     "context_length": 1048576, "pricing": {}, "supports_tools": True,
     "description": "原生多模态，支持图像/音频与搜索，适合资料分析"},
    {"id": "deepseek/deepseek-v4.1-flash-1017", "name": "DeepSeek V4.1 Flash", "provider": "DeepSeek",
     "context_length": 1048576, "pricing": {}, "supports_tools": True,
     "description": "极低成本高速度，适合并行成员与高频讨论"},
    {"id": "qwen/qwen3.8-max-prime", "name": "Qwen3.8 Max Prime", "provider": "Qwen",
     "context_length": 1000000, "pricing": {}, "supports_tools": True,
     "description": "中文与多语言强项，适合中文产品与运营讨论"},
    {"id": "x-ai/grok-4.7", "name": "Grok 4.7", "provider": "xAI",
     "context_length": 500000, "pricing": {}, "supports_tools": True,
     "description": "实时风格与搜索增强，适合观点碰撞和趋势判断"},
    {"id": "mistralai/mistral-large-4-0", "name": "Mistral Large 4", "provider": "Mistral",
     "context_length": 1048576, "pricing": {}, "supports_tools": True,
     "description": "欧洲模型生态，推理效率高，适合结构化输出"},
    {"id": "moonshotai/kimi-k3.1-pro", "name": "Kimi K3.1 Pro", "provider": "Moonshot",
     "context_length": 1048576, "pricing": {}, "supports_tools": True,
     "description": "中文长文档与资料整理能力强，适合研究型讨论"},
    {"id": "minimax/minimax-m3.1-flash", "name": "MiniMax M3.1 Flash", "provider": "MiniMax",
     "context_length": 1048576, "pricing": {}, "supports_tools": True,
     "description": "低价快速，适合草稿、多轮和轻量成员"},
    {"id": "z-ai/glm-5.3-prime", "name": "GLM 5.3 Prime", "provider": "Zhipu",
     "context_length": 1000000, "pricing": {}, "supports_tools": True,
     "description": "中文 Agent 与代码优化，适合工具型协作"},
    {"id": "cohere/command-a-plus", "name": "Command A+", "provider": "Cohere",
     "context_length": 192000, "pricing": {}, "supports_tools": True,
     "description": "企业 RAG/检索增强，适合知识库问答"},
    {"id": "xiaomi/mimo-v2.6-pro", "name": "MiMo-V2.6-Pro", "provider": "Xiaomi",
     "context_length": 1050000, "pricing": {}, "supports_tools": True,
     "description": "高性价比中文模型，适合成本敏感的群聊"},
    {"id": "meta/muse-wonder", "name": "Meta Muse Wonder", "provider": "Meta",
     "context_length": 1048576, "pricing": {}, "supports_tools": True,
     "description": "Meta 创意与多模态，适合头脑风暴和内容创作"},
    {"id": "nvidia/nemotron-3.5-super-vl", "name": "Nemotron 3.5 Super VL", "provider": "NVIDIA",
     "context_length": 1048576, "pricing": {}, "supports_tools": True,
     "description": "开源多模态，适合视觉资料与开放模型实验"},
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
        "description": str(item.get("description") or "")[:220],
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
    if now < _cache["retry_after"]:
        return {"models": FALLBACK_MODELS, "source": "fallback"}

    try:
        models = await _fetch_openrouter_models()
        if not models:
            raise RuntimeError("empty model catalog")
        result = {"models": models, "source": "remote"}
        _cache["payload"] = result
        _cache["expires_at"] = now + _CACHE_TTL_SECONDS
        _cache["retry_after"] = 0.0
        return result
    except Exception:
        _cache["retry_after"] = now + 60
        return {"models": FALLBACK_MODELS, "source": "fallback"}
