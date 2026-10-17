"""
DeepSeek 适配器
"""
from typing import Any, Dict, List, Optional
from agentflow.adapters.base import LLMAdapter


class DeepSeekAdapter(LLMAdapter):
    """DeepSeek 适配器"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com/v1"
    ):
        """
        初始化 DeepSeek 适配器

        Args:
            api_key: DeepSeek API Key
            base_url: DeepSeek API 地址
        """
        self.api_key = api_key
        self.base_url = base_url
        self.client = None

    def _ensure_client(self):
        """延迟初始化客户端"""
        if self.client is None:
            try:
                from openai import AsyncOpenAI
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
        model: str = "deepseek-chat",
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs
    ) -> Dict[str, Any]:
        """生成补全"""
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
        }

    async def stream_complete(
        self,
        messages: List[Dict[str, str]],
        model: str = "deepseek-chat",
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs
    ):
        """流式生成补全"""
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
