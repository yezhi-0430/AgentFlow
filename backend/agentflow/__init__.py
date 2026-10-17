"""
AgentFlow - 轻量级多 Agent 协作框架
"""

__version__ = "0.1.0"
__author__ = "AgentFlow Team"

from agentflow.core.agent import Agent, AgentConfig, AgentRole
from agentflow.core.message import Message, MessageType
from agentflow.core.workflow import WorkflowExecutor, WorkflowConfig, WorkflowPattern

__all__ = [
    "Agent",
    "AgentConfig",
    "AgentRole",
    "Message",
    "MessageType",
    "WorkflowExecutor",
    "WorkflowConfig",
    "WorkflowPattern",
]
