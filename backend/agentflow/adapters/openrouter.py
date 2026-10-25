"""
OpenRouter 适配器 - 统一的多模型调用接口
支持 OpenAI, Anthropic, DeepSeek 等所有模型通过 OpenRouter 调用
"""
from typing import Any, Dict, List, Optional
from agentflow.adapters.base import LLMAdapter, serialize_tool_calls


class OpenRouterAdapter(LLMAdapter):
    """OpenRouter 统一适配器"""

    # OpenRouter 主流新模型别名；也支持直接传完整 model id。
    SUPPORTED_MODELS = {
        "gpt-6.1-sol": "openai/gpt-6.1-sol",
        "gpt-6-luna": "openai/gpt-6-luna",
        "claude-sonnet-5.5": "anthropic/claude-sonnet-5.5",
        "claude-opus-5.5": "anthropic/claude-opus-5.5",
        "gemini-4-argon": "google/gemini-4-argon",
        "deepseek-v4.1-flash": "deepseek/deepseek-v4.1-flash-1017",
        "qwen3.8-max-prime": "qwen/qwen3.8-max-prime",
        "grok-4.7": "x-ai/grok-4.7",
        "mistral-large-4": "mistralai/mistral-large-4-0",
        "kimi-k3.1-pro": "moonshotai/kimi-k3.1-pro",
        "minimax-m3.1-flash": "minimax/minimax-m3.1-flash",
        "glm-5.3-prime": "z-ai/glm-5.3-prime",
        "command-a-plus": "cohere/command-a-plus",
        "mimo-v2.6-pro": "xiaomi/mimo-v2.6-pro",
        "muse-wonder": "meta/muse-wonder",
        "nemotron-3.5-super-vl": "nvidia/nemotron-3.5-super-vl",
    }

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        site_url: Optional[str] = None,
        app_name: Optional[str] = "AgentFlow"
    ):
        """
        初始化 OpenRouter 适配器

        Args:
            api_key: OpenRouter API Key
            base_url: OpenRouter API 地址
            site_url: 你的网站地址（可选，用于 OpenRouter 统计）
            app_name: 应用名称（可选）
        """
        self.api_key = api_key
        self.base_url = base_url
        self.site_url = site_url
        self.app_name = app_name
        self.client = None

    def _ensure_client(self):
        """延迟初始化客户端"""
        if self.client is None:
            try:
                from openai import AsyncOpenAI

                # OpenRouter 推荐的 headers
                extra_headers = {}
                if self.site_url:
                    extra_headers["HTTP-Referer"] = self.site_url
                if self.app_name:
                    extra_headers["X-Title"] = self.app_name

                self.client = AsyncOpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                    default_headers=extra_headers
                )
            except ImportError:
                raise ImportError(
                    "OpenAI library not installed. "
                    "Please install it with: pip install openai"
                )

    def _resolve_model(self, model: str) -> str:
        """
        解析模型名称为 OpenRouter 格式

        Args:
            model: 模型名称（简写或完整格式）

        Returns:
            OpenRouter 格式的模型名称
        """
        # 如果已经是完整的 OpenRouter 模型名（包含 /），直接返回
        if "/" in model:
            return model

        # 从映射表中查找
        resolved = self.SUPPORTED_MODELS.get(model)
        if resolved:
            return resolved

        # 如果找不到，假设是完整的模型名
        return model

    async def complete(
        self,
        messages: List[Dict[str, str]],
        model: str = "gpt-4",
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs
    ) -> Dict[str, Any]:
        """
        生成补全

        Args:
            messages: 消息列表
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大 token 数
            **kwargs: 其他参数

        Returns:
            包含响应内容和元数据的字典
        """
        self._ensure_client()

        # 解析模型名称
        resolved_model = self._resolve_model(model)

        response = await self.client.chat.completions.create(
            model=resolved_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )

        return {
            "content": response.choices[0].message.content,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
            "model": response.model,
            "finish_reason": response.choices[0].finish_reason,
            "tool_calls": serialize_tool_calls(response.choices[0].message),
        }

    async def stream_complete(
        self,
        messages: List[Dict[str, str]],
        model: str = "gpt-4",
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs
    ):
        """
        流式生成补全

        Args:
            messages: 消息列表
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大 token 数
            **kwargs: 其他参数

        Yields:
            生成的文本片段
        """
        self._ensure_client()

        # 解析模型名称
        resolved_model = self._resolve_model(model)

        stream = await self.client.chat.completions.create(
            model=resolved_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            **kwargs
        )

        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
