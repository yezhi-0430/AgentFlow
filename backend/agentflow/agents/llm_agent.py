"""
LLM Agent - 基于大语言模型的 Agent 实现
"""
import json
import time
from typing import Optional

from agentflow.core.agent import Agent, AgentConfig
from agentflow.core.message import Message, MessageType
from agentflow.adapters.base import LLMAdapter


class LLMAgent(Agent):
    """基于 LLM 的 Agent"""

    def __init__(self, config: AgentConfig, llm_adapter: LLMAdapter):
        """
        初始化 LLM Agent

        Args:
            config: Agent 配置
            llm_adapter: LLM 适配器
        """
        super().__init__(config)
        self.llm_adapter = llm_adapter
        # 原生 function calling：由执行器在群聊回合临时注入
        self.tools = None
        self.tool_handler = None
        self.max_tool_rounds = 3

    def _build_messages(self, message: Message) -> list:
        """构建发送给 LLM 的消息列表"""
        messages = []

        # 添加系统提示词
        messages.append({
            "role": "system",
            "content": self.config.system_prompt
        })

        # 添加历史上下文（最近几条，不包含当前消息）
        for mem in self.get_context(limit=5):
            if mem.sender == self.name:
                messages.append({
                    "role": "assistant",
                    "content": mem.content
                })
            else:
                messages.append({
                    "role": "user",
                    "content": f"[{mem.sender}]: {mem.content}"
                })

        # 添加当前消息
        messages.append({
            "role": "user",
            "content": message.content
        })

        return messages

    async def process(self, message: Message) -> Message:
        """处理消息；配置了 tools 时执行原生 function calling 循环。"""
        self.update_state(status="running", current_message=message.id)

        try:
            messages = self._build_messages(message)
            self.add_to_memory(message)

            start_time = time.time()
            usage_total = {}
            usage_seen = False
            tool_rounds = 0
            last_data = {}
            while True:
                kwargs = {}
                if self.tools:
                    kwargs["tools"] = self.tools
                    kwargs["tool_choice"] = "auto"
                response_data = await self.llm_adapter.complete(
                    messages=messages,
                    model=self.config.model,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                    **kwargs,
                )
                last_data = response_data
                usage = response_data.get("usage")
                if isinstance(usage, dict) and usage:
                    usage_seen = True
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        if key in usage:
                            usage_total[key] = usage_total.get(key, 0) + int(usage.get(key) or 0)

                tool_calls = response_data.get("tool_calls") or []
                if not tool_calls:
                    break
                if not self.tool_handler:
                    raise RuntimeError("model requested tools but no tool handler is configured")
                if tool_rounds >= self.max_tool_rounds:
                    raise RuntimeError(f"tool call budget exceeded ({self.max_tool_rounds})")

                messages.append({
                    "role": "assistant",
                    "content": response_data.get("content"),
                    "tool_calls": tool_calls,
                })
                for call in tool_calls:
                    function = call.get("function") or {}
                    name = str(function.get("name") or "")
                    raw_args = function.get("arguments") or "{}"
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                    except (TypeError, ValueError):
                        args = {"raw": str(raw_args)}
                    try:
                        result = await self.tool_handler(name, args if isinstance(args, dict) else {"raw": args})
                    except Exception as exc:  # noqa: BLE001 - 工具错误返回给模型
                        result = f"Tool error: {type(exc).__name__}: {exc}"
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call.get("id") or name,
                        "content": str(result),
                    })
                    tool_rounds += 1

            duration = time.time() - start_time
            content = last_data.get("content") or ""
            if not content:
                raise RuntimeError("model returned an empty final response after tool calls")

            response = Message(
                sender=self.name,
                receiver=message.sender,
                content=content,
                message_type=MessageType.RESPONSE,
                metadata={
                    "model": last_data.get("model"),
                    "usage": usage_total if usage_seen else None,
                    "finish_reason": last_data.get("finish_reason"),
                    "duration": duration,
                    "tool_rounds": tool_rounds,
                },
                parent_id=message.id,
            )
            self.add_to_memory(response)
            self.state.messages_processed += 1
            self.state.total_tokens += int(usage_total.get("total_tokens") or 0)
            self.state.total_time += duration
            self.update_state(status="completed")
            return response

        except Exception as e:
            error_msg = str(e)
            self.state.errors.append(error_msg)
            self.update_state(status="error")
            return Message(
                sender=self.name,
                receiver=message.sender,
                content=f"Error: {error_msg}",
                message_type=MessageType.RESPONSE,
                metadata={"error": True, "error_message": error_msg},
                parent_id=message.id,
            )
