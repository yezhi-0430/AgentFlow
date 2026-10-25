"""group_chat 群聊模式：Lead、轮询、@点名与边界测试（假 Agent，离线）。"""
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
    def __init__(self, name, role, responses):
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


def build_executor(agents, max_iterations=12):
    config = WorkflowConfig(
        name="group-chat-test",
        pattern=WorkflowPattern.GROUP_CHAT,
        steps=[WorkflowStep(id="group_chat", agent_name=agents[0].name)],
        agents=[agent.config for agent in agents],
        max_iterations=max_iterations,
    )
    executor = WorkflowExecutor(config, enable_persistence=False, enable_tracing=False)
    for agent in agents:
        executor.register_agent(agent)
    return executor


@pytest.mark.asyncio
async def test_group_chat_with_lead_dispatches_and_summarizes():
    lead = ScriptedAgent("lead", AgentRole.COORDINATOR, [
        '{"done": false, "next": "member_1", "task": "先分析问题"}',
        '{"done": true, "summary": "最终结论由 Lead 汇总"}',
    ])
    member = ScriptedAgent("member_1", AgentRole.WORKER, ["成员分析"])
    executor = build_executor([lead, member], max_iterations=4)

    result = await executor.execute("task")

    assert result["status"] == "completed"
    assert result["result"]["final_result"] == "最终结论由 Lead 汇总"
    assert "先分析问题" in member.calls[0]
    run = executor.get_run(result["run_id"])
    assert any("成员分析" in (step.input_text or "") for step in run.step_results)
    # 群聊消息记录：lead/成员都应出现在消息历史中
    senders = [msg.sender for msg in executor.message_history]
    assert "lead" in senders and "member_1" in senders


@pytest.mark.asyncio
async def test_group_chat_without_lead_round_robin():
    first = ScriptedAgent("member_1", AgentRole.WORKER, ["第一轮"])
    second = ScriptedAgent("member_2", AgentRole.WORKER, ["第二轮"])
    third = ScriptedAgent("member_3", AgentRole.WORKER, ["第三轮"])
    executor = build_executor([first, second, third], max_iterations=3)

    result = await executor.execute("task")

    assert result["status"] == "completed"
    assert result["result"]["final_result"] == "第三轮"
    assert len(result["result"]["transcript"]) == 3
    assert [row[0] for row in result["result"]["transcript"]] == ["member_1", "member_2", "member_3"]


@pytest.mark.asyncio
async def test_group_chat_mention_routes_next_speaker():
    first = ScriptedAgent("member_1", AgentRole.WORKER, ["我建议 @member_3 补充"])
    second = ScriptedAgent("member_2", AgentRole.WORKER, ["我不该被选中"])
    third = ScriptedAgent("member_3", AgentRole.WORKER, ["我来补充"])
    executor = build_executor([first, second, third], max_iterations=2)

    result = await executor.execute("task")

    assert result["status"] == "completed"
    assert [row[0] for row in result["result"]["transcript"]] == ["member_1", "member_3"]


@pytest.mark.asyncio
async def test_group_chat_respects_max_turns_and_summarizes():
    lead = ScriptedAgent("lead", AgentRole.COORDINATOR, [
        '{"done": false, "next": "member_1", "task": "继续"}',
        "最终总结",
    ])
    member = ScriptedAgent("member_1", AgentRole.WORKER, ["继续分析"])
    executor = build_executor([lead, member], max_iterations=1)

    result = await executor.execute("task")

    assert result["status"] == "completed"
    assert result["result"]["final_result"] == "最终总结"
    assert len(result["result"]["transcript"]) == 2  # lead 指令 + member 回复
    run = executor.get_run(result["run_id"])
    assert "群聊记录" in (run.step_results[-1].input_text or "")


@pytest.mark.asyncio
async def test_group_chat_structured_handoff_routes_and_carries_task():
    first = ScriptedAgent("member_1", AgentRole.WORKER, [
        '{"handoff": "member_3", "task": "请补充风险部分"}'
    ])
    second = ScriptedAgent("member_2", AgentRole.WORKER, ["不该被选中"])
    third = ScriptedAgent("member_3", AgentRole.WORKER, ["补充风险分析"])
    executor = build_executor([first, second, third], max_iterations=2)

    result = await executor.execute("task")

    assert result["status"] == "completed"
    assert [row[0] for row in result["result"]["transcript"]] == ["member_1", "member_3"]
    run = executor.get_run(result["run_id"])
    assert "请补充风险部分" in (run.step_results[-1].input_text or "")


@pytest.mark.asyncio
async def test_group_chat_requires_at_least_two_agents():
    only = ScriptedAgent("member_1", AgentRole.WORKER, ["x"])
    executor = build_executor([only])

    with pytest.raises(ValueError, match="at least 2"):
        await executor.execute("task")
