"""
工作流引擎 - 负责编排和执行 Agent 协作
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from enum import Enum
import asyncio
import time
import uuid

from agentflow.core.agent import Agent, AgentConfig
from agentflow.core.message import Message, MessageType


class WorkflowPattern(Enum):
    """工作流模式"""
    SEQUENTIAL = "sequential"      # 串行
    PARALLEL = "parallel"          # 并行
    DEBATE = "debate"              # 辩论
    VOTING = "voting"              # 投票
    HIERARCHICAL = "hierarchical"  # 层级
    DYNAMIC = "dynamic"            # 动态路由


@dataclass
class WorkflowStep:
    """工作流步骤"""
    id: str
    agent_name: str
    input_from: Optional[str] = None  # 前一步的 ID
    condition: Optional[Callable] = None  # 条件判断函数
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowConfig:
    """工作流配置"""
    name: str
    pattern: WorkflowPattern
    steps: List[WorkflowStep]
    agents: List[AgentConfig]
    max_iterations: int = 10
    convergence_check: Optional[Callable] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class WorkflowExecutor:
    """工作流执行器"""

    def __init__(self, config: WorkflowConfig):
        self.config = config
        self.workflow_id = str(uuid.uuid4())
        self.agents: Dict[str, Agent] = {}
        self.message_history: List[Message] = []
        self.status = "idle"  # idle, running, paused, completed, error
        self.current_step = 0
        self.start_time: Optional[float] = None
        self.callbacks: Dict[str, List[Callable]] = {}

    def register_agent(self, agent: Agent):
        """注册 Agent"""
        self.agents[agent.name] = agent

    def on(self, event: str, callback: Callable):
        """注册事件回调"""
        if event not in self.callbacks:
            self.callbacks[event] = []
        self.callbacks[event].append(callback)

    async def _emit(self, event: str, data: Any):
        """触发事件"""
        if event in self.callbacks:
            for callback in self.callbacks[event]:
                if asyncio.iscoroutinefunction(callback):
                    await callback(data)
                else:
                    callback(data)

    async def execute(self, initial_task: str) -> Dict[str, Any]:
        """
        执行工作流

        Args:
            initial_task: 初始任务描述

        Returns:
            执行结果
        """
        self.status = "running"
        self.start_time = time.time()
        self.current_step = 0

        await self._emit("workflow_started", {
            "workflow_id": self.workflow_id,
            "task": initial_task,
        })

        try:
            # 根据 pattern 选择执行策略
            if self.config.pattern == WorkflowPattern.SEQUENTIAL:
                result = await self._execute_sequential(initial_task)
            elif self.config.pattern == WorkflowPattern.PARALLEL:
                result = await self._execute_parallel(initial_task)
            elif self.config.pattern == WorkflowPattern.DEBATE:
                result = await self._execute_debate(initial_task)
            elif self.config.pattern == WorkflowPattern.VOTING:
                result = await self._execute_voting(initial_task)
            else:
                raise ValueError(f"Unsupported pattern: {self.config.pattern}")

            self.status = "completed"
            elapsed_time = time.time() - self.start_time

            await self._emit("workflow_completed", {
                "workflow_id": self.workflow_id,
                "result": result,
                "elapsed_time": elapsed_time,
            })

            return {
                "status": "completed",
                "result": result,
                "elapsed_time": elapsed_time,
                "messages": len(self.message_history),
            }

        except Exception as e:
            self.status = "error"
            await self._emit("workflow_error", {
                "workflow_id": self.workflow_id,
                "error": str(e),
            })
            raise

    async def _execute_sequential(self, task: str) -> Dict[str, Any]:
        """串行执行"""
        result = task

        for i, step in enumerate(self.config.steps):
            self.current_step = i + 1

            agent = self.agents.get(step.agent_name)
            if not agent:
                raise ValueError(f"Agent not found: {step.agent_name}")

            # 创建消息
            message = Message(
                sender="system",
                receiver=step.agent_name,
                content=result,
                message_type=MessageType.TASK,
                metadata={"step_id": step.id, "step_index": i},
            )

            await self._emit("step_started", {
                "workflow_id": self.workflow_id,
                "step": step.id,
                "agent": step.agent_name,
                "message": message.to_dict(),
            })

            # 执行
            step_start = time.time()
            response = await agent.process(message)
            step_duration = time.time() - step_start

            # 记录消息
            self.message_history.append(message)
            self.message_history.append(response)

            result = response.content

            await self._emit("step_completed", {
                "workflow_id": self.workflow_id,
                "step": step.id,
                "agent": step.agent_name,
                "result": result,
                "duration": step_duration,
            })

        return {"final_result": result}

    async def _execute_parallel(self, task: str) -> Dict[str, Any]:
        """并行执行"""
        tasks = []

        for i, step in enumerate(self.config.steps):
            agent = self.agents.get(step.agent_name)
            if not agent:
                raise ValueError(f"Agent not found: {step.agent_name}")

            message = Message(
                sender="system",
                receiver=step.agent_name,
                content=task,
                message_type=MessageType.TASK,
                metadata={"step_id": step.id, "step_index": i},
            )

            tasks.append(agent.process(message))

        # 并行执行所有 agent
        responses = await asyncio.gather(*tasks)

        # 收集结果
        results = [resp.content for resp in responses]

        return {
            "results": results,
            "aggregated": "\n\n".join(results),
        }

    async def _execute_debate(self, task: str) -> Dict[str, Any]:
        """辩论模式 - 多个 agent 多轮交互"""
        debate_history = []
        current_topic = task

        for iteration in range(self.config.max_iterations):
            round_responses = []

            # 每个 agent 发表观点
            for step in self.config.steps:
                agent = self.agents.get(step.agent_name)
                if not agent:
                    continue

                # 构建上下文：包含之前的讨论
                context = f"主题: {task}\n\n"
                if debate_history:
                    context += "之前的讨论:\n"
                    for entry in debate_history[-6:]:  # 最近 6 轮
                        context += f"{entry['agent']}: {entry['content']}\n\n"
                context += f"请给出你的观点："

                message = Message(
                    sender="system",
                    receiver=step.agent_name,
                    content=context,
                    message_type=MessageType.TASK,
                    metadata={"iteration": iteration},
                )

                response = await agent.process(message)
                round_responses.append({
                    "agent": step.agent_name,
                    "content": response.content,
                })
                debate_history.append({
                    "agent": step.agent_name,
                    "content": response.content,
                    "iteration": iteration,
                })

            # 检查是否收敛
            if self.config.convergence_check and self.config.convergence_check(debate_history):
                break

        return {
            "debate_history": debate_history,
            "iterations": iteration + 1,
        }

    async def _execute_voting(self, task: str) -> Dict[str, Any]:
        """投票模式 - 多个 agent 投票决策"""
        votes = []

        # 每个 agent 给出答案
        for step in self.config.steps:
            agent = self.agents.get(step.agent_name)
            if not agent:
                continue

            message = Message(
                sender="system",
                receiver=step.agent_name,
                content=task,
                message_type=MessageType.TASK,
            )

            response = await agent.process(message)
            votes.append({
                "agent": step.agent_name,
                "vote": response.content,
            })

        # 简单的多数投票（实际应用中可以更复杂）
        from collections import Counter
        vote_counts = Counter([v["vote"] for v in votes])
        winner = vote_counts.most_common(1)[0] if vote_counts else (None, 0)

        return {
            "votes": votes,
            "winner": winner[0],
            "count": winner[1],
        }

    def pause(self):
        """暂停执行"""
        self.status = "paused"

    def resume(self):
        """恢复执行"""
        self.status = "running"

    def stop(self):
        """停止执行"""
        self.status = "stopped"

    def get_status(self) -> Dict[str, Any]:
        """获取执行状态"""
        return {
            "workflow_id": self.workflow_id,
            "status": self.status,
            "current_step": self.current_step,
            "total_steps": len(self.config.steps),
            "messages": len(self.message_history),
            "elapsed_time": time.time() - self.start_time if self.start_time else 0,
        }
