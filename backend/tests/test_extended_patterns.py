"""
层次/辩论/投票/动态协作模式的离线测试（假 Agent，不联网）。
"""
from types import SimpleNamespace

import pytest

from agentflow.core.agent import AgentConfig, AgentRole
from agentflow.core.workflow import (
    WorkflowConfig,
    WorkflowExecutor,
    WorkflowPattern,
    WorkflowStep,
)


class ScriptedAgent:
    """按调用顺序返回脚本化内容的假 Agent。"""

    def __init__(self, name: str, role: AgentRole, responses):
        self.name = name
        self.calls = []
        self._responses = list(responses)
        self.config = AgentConfig(name=name, role=role, model="fake-model",
                                  system_prompt=f"you are {name}")

    async def process(self, message):
        self.calls.append(message.content)
        content = self._responses[min(len(self.calls) - 1, len(self._responses) - 1)]
        return SimpleNamespace(id=f"{self.name}-{len(self.calls)}", content=content, metadata={
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })


def build_executor(pattern, agents, steps=None, max_iterations=10):
    config = WorkflowConfig(
        name=f"{pattern.value}-test",
        pattern=pattern,
        steps=steps or [],
        agents=[agent.config for agent in agents],
        max_iterations=max_iterations,
    )
    executor = WorkflowExecutor(config, enable_persistence=False, enable_tracing=False)
    for agent in agents:
        executor.register_agent(agent)
    return executor


def _coordinator(plan="计划", synthesis="最终答案"):
    return ScriptedAgent("coordinator", AgentRole.COORDINATOR, [plan, synthesis, synthesis])


@pytest.mark.asyncio
async def test_hierarchical_plan_workers_synthesis():
    coordinator = _coordinator()
    worker_a = ScriptedAgent("worker_1", AgentRole.WORKER, ["W1"])
    worker_b = ScriptedAgent("worker_2", AgentRole.WORKER, ["W2"])
    executor = build_executor(WorkflowPattern.HIERARCHICAL, [coordinator, worker_a, worker_b])

    result = await executor.execute("task")

    assert result["status"] == "completed"
    assert result["result"]["final_result"] == "最终答案"
    run = executor.get_run(result["run_id"])
    assert [step.status.value for step in run.step_results] == ["completed"] * 4
    assert [step.step_id for step in run.step_results] == ["plan", "worker_1", "worker_2", "synthesis"]
    assert worker_a.calls and worker_b.calls
    assert "W1" in coordinator.calls[-1] and "W2" in coordinator.calls[-1]


@pytest.mark.asyncio
async def test_debate_two_rounds_then_judge():
    debater_a = ScriptedAgent("debater_1", AgentRole.WORKER, ["A1", "A2"])
    debater_b = ScriptedAgent("debater_2", AgentRole.WORKER, ["B1", "B2"])
    judge = ScriptedAgent("judge", AgentRole.REVIEWER, ["裁决"])
    executor = build_executor(WorkflowPattern.DEBATE, [debater_a, debater_b, judge])

    result = await executor.execute("task")

    assert result["status"] == "completed"
    assert result["result"]["final_result"] == "裁决"
    run = executor.get_run(result["run_id"])
    assert len(run.step_results) == 5
    assert run.step_results[-1].step_id == "judge"
    assert "B1" in debater_a.calls[1]  # 第二轮看到对方第一轮观点
    assert "A2" in judge.calls[0] and "B2" in judge.calls[0]


@pytest.mark.asyncio
async def test_voting_candidates_then_judge():
    candidate_a = ScriptedAgent("candidate_1", AgentRole.WORKER, ["C1"])
    candidate_b = ScriptedAgent("candidate_2", AgentRole.WORKER, ["C2"])
    judge = ScriptedAgent("judge", AgentRole.REVIEWER, ["最佳答案"])
    executor = build_executor(WorkflowPattern.VOTING, [candidate_a, candidate_b, judge])

    result = await executor.execute("task")

    assert result["status"] == "completed"
    assert result["result"]["final_result"] == "最佳答案"
    run = executor.get_run(result["run_id"])
    assert len(run.step_results) == 3
    assert run.step_results[-1].step_id == "judge"
    assert "C1" in judge.calls[0] and "C2" in judge.calls[0]


@pytest.mark.asyncio
async def test_dynamic_coordinator_selects_worker_then_finishes():
    coordinator = ScriptedAgent(
        "coordinator", AgentRole.COORDINATOR,
        ['{"done": false, "next": "worker_1", "task": "子任务"}',
         '{"done": true}', "动态最终答案"],
    )
    worker = ScriptedAgent("worker_1", AgentRole.WORKER, ["动态结果"])
    executor = build_executor(WorkflowPattern.DYNAMIC, [coordinator, worker], max_iterations=3)

    result = await executor.execute("task")

    assert result["status"] == "completed"
    assert result["result"]["final_result"] == "动态最终答案"
    run = executor.get_run(result["run_id"])
    assert [step.step_id for step in run.step_results] == [
        "dynamic_plan_1", "dynamic_step_1", "dynamic_plan_2", "dynamic_final",
    ]
    assert "动态结果" in coordinator.calls[-1]


@pytest.mark.asyncio
async def test_dynamic_invalid_plan_falls_back_and_marks_partial():
    coordinator = ScriptedAgent(
        "coordinator", AgentRole.COORDINATOR,
        ["不是 JSON", '{"done": true}', "最终答案"],
    )
    worker = ScriptedAgent("worker_1", AgentRole.WORKER, ["兜底结果"])
    executor = build_executor(WorkflowPattern.DYNAMIC, [coordinator, worker], max_iterations=2)

    result = await executor.execute("task")

    assert result["status"] == "partial"
    run = executor.get_run(result["run_id"])
    assert run.step_results[-1].output_text == "最终答案"
    assert any(step.agent_name == "worker_1" for step in run.step_results)


@pytest.mark.asyncio
async def test_debate_rejects_too_few_agents():
    agents = [
        ScriptedAgent("debater_1", AgentRole.WORKER, ["A"]),
        ScriptedAgent("judge", AgentRole.REVIEWER, ["J"]),
    ]
    executor = build_executor(WorkflowPattern.DEBATE, agents)

    with pytest.raises(ValueError, match="at least 3"):
        await executor.execute("task")
