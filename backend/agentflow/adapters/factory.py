"""
适配器工厂 - 统一创建各种 LLM 适配器
"""
from typing import Optional
from agentflow.adapters.base import LLMAdapter
from agentflow.adapters.openai import OpenAIAdapter
from agentflow.adapters.claude import ClaudeAdapter
from agentflow.adapters.deepseek import DeepSeekAdapter
from agentflow.adapters.openrouter import OpenRouterAdapter


class AdapterFactory:
    """适配器工厂"""

    @staticmethod
    def create_adapter(
        provider: str,
        api_key: str,
        base_url: Optional[str] = None,
        **kwargs
    ) -> LLMAdapter:
        """
        创建适配器

        Args:
            provider: 提供商名称 (openai, claude, deepseek, openrouter)
            api_key: API Key
            base_url: 可选的自定义 API 地址
            **kwargs: 其他参数

        Returns:
            LLMAdapter 实例

        Raises:
            ValueError: 不支持的提供商
        """
        provider = provider.lower()

        if provider == "openai":
            return OpenAIAdapter(api_key=api_key, base_url=base_url)

        elif provider == "claude" or provider == "anthropic":
            return ClaudeAdapter(api_key=api_key, base_url=base_url)

        elif provider == "deepseek":
            if base_url is None:
                base_url = "https://api.deepseek.com/v1"
            return DeepSeekAdapter(api_key=api_key, base_url=base_url)

        elif provider == "openrouter":
            if base_url is None:
                base_url = "https://openrouter.ai/api/v1"
            return OpenRouterAdapter(
                api_key=api_key,
                base_url=base_url,
                site_url=kwargs.get("site_url"),
                app_name=kwargs.get("app_name", "AgentFlow")
            )

        else:
            raise ValueError(
                f"Unsupported provider: {provider}. "
                f"Supported providers: openai, claude, deepseek, openrouter"
            )

    @staticmethod
    def get_supported_providers():
        """获取支持的提供商列表"""
        return ["openai", "claude", "anthropic", "deepseek", "openrouter"]

    @staticmethod
    def get_provider_info():
        """获取提供商信息"""
        return {
            "openai": {
                "name": "OpenAI",
                "base_url": "https://api.openai.com/v1",
                "models": [
                    {
                        "id": "gpt-6.1-sol",
                        "name": "GPT-6.1-SOL",
                        "description": "综合最强：最新最强大的模型，综合能力顶尖",
                        "context_length": 128000,
                        "strengths": ["综合能力", "复杂推理", "多语言", "创意写作"],
                        "pricing": "较贵",
                        "speed": "快",
                        "recommended": True
                    }
                ],
                "description": "OpenAI 官方 API"
            },
            "anthropic": {
                "name": "Anthropic Claude",
                "base_url": "https://api.anthropic.com",
                "models": [
                    {
                        "id": "claude-3-5-haiku",
                        "name": "Claude 3.5 Haiku",
                        "description": "极速响应：价格低廉，适合快速任务和高并发场景",
                        "context_length": 200000,
                        "strengths": ["极速响应", "价格便宜", "简单任务", "高并发"],
                        "pricing": "便宜",
                        "speed": "极快",
                        "recommended": True
                    },
                    {
                        "id": "claude-opus-5-5",
                        "name": "Claude Opus 5.5",
                        "description": "最强推理：200K上下文，适合复杂分析和长文本处理",
                        "context_length": 200000,
                        "strengths": ["复杂推理", "长上下文", "深度分析", "学术写作"],
                        "pricing": "最贵",
                        "speed": "中等",
                        "recommended": False
                    }
                ],
                "description": "Anthropic Claude 官方 API"
            },
            "deepseek": {
                "name": "DeepSeek",
                "base_url": "https://api.deepseek.com/v1",
                "models": [
                    {
                        "id": "deepseek-v4-flash",
                        "name": "DeepSeek V4 Flash",
                        "description": "国产之光：极速且便宜，中文能力强，性价比之王",
                        "context_length": 64000,
                        "strengths": ["极速", "超便宜", "中文能力", "编程能力"],
                        "pricing": "极便宜",
                        "speed": "极快",
                        "recommended": True
                    }
                ],
                "description": "DeepSeek 官方 API（国产，价格最便宜）"
            },
            "openrouter": {
                "name": "OpenRouter",
                "base_url": "https://openrouter.ai/api/v1",
                "models": [
                    {
                        "id": "openai/gpt-6.1-sol",
                        "name": "GPT-6.1-SOL",
                        "description": "🚀 综合最强 | 最新最强大的模型",
                        "strengths": ["综合能力", "复杂推理", "多语言"],
                        "pricing": "较贵",
                        "speed": "快",
                        "recommended": True
                    },
                    {
                        "id": "deepseek/deepseek-v4-flash",
                        "name": "DeepSeek V4 Flash",
                        "description": "⚡ 极速便宜 | 性价比之王，国产模型",
                        "strengths": ["极速", "超便宜", "中文能力"],
                        "pricing": "极便宜",
                        "speed": "极快",
                        "recommended": True
                    },
                    {
                        "id": "anthropic/claude-3-5-haiku",
                        "name": "Claude 3.5 Haiku",
                        "description": "💨 快速响应 | Anthropic 快速版",
                        "strengths": ["极速响应", "价格便宜"],
                        "pricing": "便宜",
                        "speed": "极快",
                        "recommended": False
                    },
                    {
                        "id": "anthropic/claude-opus-5-5",
                        "name": "Claude Opus 5.5",
                        "description": "🧠 最强推理 | 200K上下文，复杂任务",
                        "strengths": ["复杂推理", "长上下文"],
                        "pricing": "最贵",
                        "speed": "中等",
                        "recommended": False
                    }
                ],
                "description": "OpenRouter 统一 API（推荐使用，一个 Key 访问所有模型）"
            }
        }
