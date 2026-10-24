"""
Agent 基类 - 所有 Agent 的抽象基类
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum

from agentflow.core.message import Message


class AgentRole(Enum):
    """Agent 角色类型"""
    COORDINATOR = "coordinator"  # 协调者
    WORKER = "worker"           # 工作者
    REVIEWER = "reviewer"       # 审查者
    HUMAN = "human"            # 人类代理


@dataclass
class AgentConfig:
    """Agent 配置"""
    name: str
    role: AgentRole
    system_prompt: str
    model: str = "gpt-4"
    temperature: float = 0.7
    max_tokens: int = 2000
    tools: Optional[List[str]] = None
    capabilities: Optional[List[str]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "role": self.role.value,
            "system_prompt": self.system_prompt,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "tools": self.tools,
            "capabilities": self.capabilities,
            "metadata": self.metadata,
        }


@dataclass
class AgentState:
    """Agent 状态"""
    status: str = "idle"  # idle, running, completed, error
    current_message: Optional[str] = None
    messages_processed: int = 0
    total_tokens: int = 0
    total_time: float = 0.0
    errors: List[str] = field(default_factory=list)


class Agent(ABC):
    """Agent 基类"""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.name = config.name
        self.role = config.role
        self.memory: List[Message] = []
        self.state = AgentState()

    @abstractmethod
    async def process(self, message: Message) -> Message:
        """
        处理消息并返回响应

        Args:
            message: 输入消息

        Returns:
            响应消息
        """
        pass

    def add_to_memory(self, message: Message):
        """添加到记忆"""
        self.memory.append(message)
        # 限制记忆大小
        if len(self.memory) > 50:
            self.memory = self.memory[-50:]

    def get_context(self, limit: int = 10) -> List[Message]:
        """获取最近的上下文"""
        return self.memory[-limit:]

    def clear_memory(self):
        """清空记忆"""
        self.memory.clear()

    def reset_for_run(self):
        """为一次新的运行重置记忆与统计。

        Agent 对象会被同一工作流的多次运行复用；如果只清记忆而保留
        messages_processed / total_tokens，重复执行会累积旧统计。延续会话必须
        由调用方显式恢复上下文，不能依赖对象复用隐式发生。
        """
        self.memory.clear()
        self.state = AgentState()

    def get_state(self) -> Dict[str, Any]:
        """获取当前状态"""
        return {
            "name": self.name,
            "role": self.role.value,
            "status": self.state.status,
            "messages_processed": self.state.messages_processed,
            "total_tokens": self.state.total_tokens,
            "total_time": self.state.total_time,
            "memory_size": len(self.memory),
        }

    def update_state(self, **kwargs):
        """更新状态"""
        for key, value in kwargs.items():
            if hasattr(self.state, key):
                setattr(self.state, key, value)
