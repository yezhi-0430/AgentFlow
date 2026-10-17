"""
消息模型 - Agent 间通信的基础
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from enum import Enum
import time
import uuid


class MessageType(Enum):
    """消息类型"""
    TASK = "task"           # 任务分配
    RESPONSE = "response"   # 响应结果
    QUESTION = "question"   # 提问
    FEEDBACK = "feedback"   # 反馈
    SYSTEM = "system"       # 系统消息


@dataclass
class Message:
    """消息对象"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    sender: str = ""
    receiver: str = ""  # 可以是 "all" 表示广播
    content: str = ""
    message_type: MessageType = MessageType.TASK
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    parent_id: Optional[str] = None  # 用于消息链追踪

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "sender": self.sender,
            "receiver": self.receiver,
            "content": self.content,
            "message_type": self.message_type.value,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
            "parent_id": self.parent_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        """从字典创建"""
        data = data.copy()
        if "message_type" in data:
            data["message_type"] = MessageType(data["message_type"])
        return cls(**data)
