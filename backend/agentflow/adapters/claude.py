"""
Claude 适配器 - OpenRouter 兼容格式
使用 OpenAI SDK 调用，完全兼容 OpenRouter
"""
from typing import Any, Dict, List, Optional
from agentflow.adapters.base import LLMAdapter, serialize_tool_calls


class ClaudeAdapter(LLMAdapter):
    """Claude 适配器 - OpenRouter 兼容格式"""

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None
    ):
        """
        初始化 Claude 适配器

        Args:
            api_key: Anthropic API Key 或 OpenRouter API Key
            base_url: API 地址（默认使用 Anthropic 官方，可设置为 OpenRouter）
        """
        self.api_key = api_key
        self.base_url = base_url or "https://openrouter.ai/api/v1"
        self.client = None

    def _ensure_client(self):
        """延迟初始化客户端 - 使用 OpenAI SDK"""
        if self.client is None:
            try:
                from openai import AsyncOpenAI

                # 使用 OpenAI SDK 调用 Claude（OpenRouter 官方方法）
                self.client = AsyncOpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url
                )
            except ImportError:
                raise ImportError(
                    "OpenAI library not installed. "
                    "Please install it with: pip install openai"
                )

    async def complete(
        self,
        messages: List[Dict[str, str]],
        model: str = "anthropic/claude-3.5-sonnet",
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs
    ) -> Dict[str, Any]:
        """
        生成补全 - OpenRouter 兼容格式

        使用 OpenAI SDK 调用 Claude，完全按照 OpenRouter 官方文档
        """
        self._ensure_client()

        response = await self.client.chat.completions.create(
            model=model,
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
        model: str = "anthropic/claude-3.5-sonnet",
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs
    ):
        """
        流式生成补全 - OpenRouter 兼容格式

        使用 OpenAI SDK 流式调用 Claude
        """
        self._ensure_client()

        stream = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            **kwargs
        )

        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
