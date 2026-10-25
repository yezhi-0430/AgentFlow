"""
LLM 适配器基类 - 统一不同 LLM 提供商的接口
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


def serialize_tool_calls(message: Any) -> Optional[List[Dict[str, Any]]]:
    """把 OpenAI SDK message.tool_calls 转成可序列化字典；无工具调用返回 None。"""
    calls = getattr(message, "tool_calls", None)
    if not calls:
        return None
    serialized: List[Dict[str, Any]] = []
    for call in calls:
        function = getattr(call, "function", None)
        if function is None:
            continue
        serialized.append({
            "id": getattr(call, "id", ""),
            "type": getattr(call, "type", "function"),
            "function": {
                "name": getattr(function, "name", ""),
                "arguments": getattr(function, "arguments", "") or "{}",
            },
        })
    return serialized or None


class LLMAdapter(ABC):
    """LLM 适配器基类"""

    @abstractmethod
    async def complete(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs
    ) -> Dict[str, Any]:
        """
        生成补全

        Args:
            messages: 消息列表，格式: [{"role": "user", "content": "..."}]
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大 token 数
            **kwargs: 其他参数

        Returns:
            {
                "content": "生成的内容",
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150
                },
                "model": "模型名称"
            }
        """
        pass

    @abstractmethod
    async def stream_complete(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs
    ):
        """
        流式生成补全

        Args:
            同 complete

        Yields:
            生成的文本片段
        """
        pass
