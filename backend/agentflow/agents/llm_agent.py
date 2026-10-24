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
        """处理消息"""
        # 更新状态
        self.update_state(
            status="running",
            current_message=message.id
        )

        # 注意：先构建消息再记录，避免当前消息重复进入上下文
        # 记录到记忆在返回响应前完成

        try:
            # 构建消息（此时 memory 中还没有当前消息）
            messages = self._build_messages(message)

            # 现在记录输入消息到记忆
            self.add_to_memory(message)

            # 调用 LLM
            start_time = time.time()
            response_data = await self.llm_adapter.complete(
                messages=messages,
                model=self.config.model,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )
            duration = time.time() - start_time

            # 提取用量信息
            usage = response_data.get("usage", {})
            total_tokens = usage.get("total_tokens", 0)

            # 创建响应消息
            response = Message(
                sender=self.name,
                receiver=message.sender,
                content=response_data["content"],
                message_type=MessageType.RESPONSE,
                metadata={
                    "model": response_data.get("model"),
                    "usage": usage,
                    "finish_reason": response_data.get("finish_reason"),
                    "duration": duration,
                },
                parent_id=message.id,
            )

            # 记录响应
            self.add_to_memory(response)

            # 更新统计
            self.state.messages_processed += 1
            self.state.total_tokens += total_tokens
            self.state.total_time += duration
            self.update_state(status="completed")

            return response

        except Exception as e:
            # 错误处理
            error_msg = str(e)
            self.state.errors.append(error_msg)
            self.update_state(status="error")

            # 返回错误消息，标记为错误
            return Message(
                sender=self.name,
                receiver=message.sender,
                content=f"Error: {error_msg}",
                message_type=MessageType.RESPONSE,
                metadata={"error": True, "error_message": error_msg},
                parent_id=message.id,
            )
