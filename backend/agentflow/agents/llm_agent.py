"""
LLM Agent - 基于大语言模型的 Agent 实现
"""
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

    def _build_messages(self, message: Message) -> list:
        """构建发送给 LLM 的消息列表"""
        messages = []

        # 添加系统提示词
        messages.append({
            "role": "system",
            "content": self.config.system_prompt
        })

        # 添加历史上下文（最近几条）
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
        """处理消息"""
        # 更新状态
        self.update_state(
            status="running",
            current_message=message.id
        )

        # 记录到记忆
        self.add_to_memory(message)

        try:
            # 构建消息
            messages = self._build_messages(message)

            # 调用 LLM
            start_time = time.time()
            response_data = await self.llm_adapter.complete(
                messages=messages,
                model=self.config.model,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )
            duration = time.time() - start_time

            # 创建响应消息
            response = Message(
                sender=self.name,
                receiver=message.sender,
                content=response_data["content"],
                message_type=MessageType.RESPONSE,
                metadata={
                    "model": response_data["model"],
                    "usage": response_data["usage"],
                    "duration": duration,
                },
                parent_id=message.id,
            )

            # 记录响应
            self.add_to_memory(response)

            # 更新统计
            self.state.messages_processed += 1
            self.state.total_tokens += response_data["usage"]["total_tokens"]
            self.state.total_time += duration
            self.update_state(status="completed")

            return response

        except Exception as e:
            # 错误处理
            self.state.errors.append(str(e))
            self.update_state(status="error")

            # 返回错误消息
            return Message(
                sender=self.name,
                receiver=message.sender,
                content=f"Error: {str(e)}",
                message_type=MessageType.RESPONSE,
                metadata={"error": True},
                parent_id=message.id,
            )
