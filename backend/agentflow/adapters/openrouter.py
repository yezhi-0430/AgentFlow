"""
OpenRouter 适配器 - 统一的多模型调用接口
支持 OpenAI, Anthropic, DeepSeek 等所有模型通过 OpenRouter 调用
"""
from typing import Any, Dict, List, Optional
from agentflow.adapters.base import LLMAdapter, serialize_tool_calls


class OpenRouterAdapter(LLMAdapter):
    """OpenRouter 统一适配器"""

    # OpenRouter 支持的模型列表（精简版 - 只保留指定模型）
    SUPPORTED_MODELS = {
        # OpenAI 模型
        "gpt-4o": "openai/gpt-4o",
        "gpt-4o-mini": "openai/gpt-4o-mini",
        "gpt-5": "openai/gpt-5",

        # Anthropic 模型
        "claude-3.5-sonnet": "anthropic/claude-3.5-sonnet",
        "claude-3-5-sonnet": "anthropic/claude-3.5-sonnet",
        "claude-sonnet-4.5": "anthropic/claude-sonnet-4.5",

        # Google 模型
        "gemini-2.0-flash": "google/gemini-2.0-flash-001",
        "gemini-2.5-pro": "google/gemini-2.5-pro",

        # DeepSeek 模型
        "deepseek-chat": "deepseek/deepseek-chat",
        "deepseek-chat-v3.1": "deepseek/deepseek-chat-v3.1",

        # Qwen / xAI / Mistral / Meta / Moonshot / Zhipu / MiniMax / Cohere
        "qwen-2.5-72b": "qwen/qwen-2.5-72b-instruct",
        "grok-2": "x-ai/grok-2-1212",
        "mistral-large": "mistralai/mistral-large",
        "llama-3.3-70b": "meta-llama/llama-3.3-70b-instruct",
        "kimi-k2": "moonshotai/kimi-k2",
        "glm-4.5": "z-ai/glm-4.5",
        "minimax-m2": "minimax/minimax-m2",
        "command-a": "cohere/command-a",
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
