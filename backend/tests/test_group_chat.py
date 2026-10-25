"""group_chat 群聊模式：Lead、轮询、@点名与边界测试（假 Agent，离线）。"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from agentflow.adapters.base import LLMAdapter
from agentflow.agents.llm_agent import LLMAgent
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


def build_executor(agents, max_iterations=12, *, persist=False):
    config = WorkflowConfig(
        name="group-chat-test",
        pattern=WorkflowPattern.GROUP_CHAT,
        steps=[WorkflowStep(id="group_chat", agent_name=agents[0].name)],
        agents=[agent.config for agent in agents],
        max_iterations=max_iterations,
    )
    executor = WorkflowExecutor(
        config, enable_persistence=persist, enable_tracing=False
    )
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
async def test_group_chat_messages_are_persisted_for_replay():
    lead = ScriptedAgent("lead", AgentRole.COORDINATOR, [
        '{"done": false, "next": "member_1", "task": "先分析"}',
        '{"done": true, "summary": "总结"}',
    ])
    member = ScriptedAgent("member_1", AgentRole.WORKER, ["成员回复"])
    executor = build_executor([lead, member], max_iterations=2, persist=True)

    result = await executor.execute("task")

    from agentflow.storage import MessageRepository, get_db

    with get_db() as db:
        rows = MessageRepository.list_by_run(db, result["run_id"])
    assert rows
    assert {row["sender"] for row in rows} >= {"lead", "member_1"}
    assert all("workflow_id" in row and "content" in row for row in rows)


@pytest.mark.asyncio
async def test_group_chat_invalid_lead_json_falls_back_to_original_task():
    lead = ScriptedAgent("lead", AgentRole.COORDINATOR, [
        "我先安排一下大家发言",
        '{"done": true, "summary": "总结"}',
    ])
    member = ScriptedAgent("member_1", AgentRole.WORKER, ["处理原始任务"])
    executor = build_executor([lead, member], max_iterations=2)

    result = await executor.execute("原始任务：解释 list 与 tuple")

    assert result["status"] == "partial"
    run = executor.get_run(result["run_id"])
    member_step = next(step for step in run.step_results if step.agent_name == "member_1")
    assert "请直接完成原始任务" in (member_step.input_text or "")
    assert "list 与 tuple" in (member_step.input_text or "")


@pytest.mark.asyncio
async def test_group_chat_tool_ask_agent_returns_result_to_caller():
    first = ScriptedAgent("member_1", AgentRole.WORKER, [
        '{"tool": "ask_agent", "agent": "member_2", "task": "请核对事实"}',
        "综合答案",
    ])
    second = ScriptedAgent("member_2", AgentRole.WORKER, ["核对后的结果"])
    executor = build_executor([first, second], max_iterations=2)

    result = await executor.execute("task")

    assert result["status"] == "completed"
    speakers = [row[0] for row in result["result"]["transcript"]]
    assert "member_2" in speakers
    assert speakers[-1] == "member_1"
    run = executor.get_run(result["run_id"])
    tool_step = next(step for step in run.step_results if step.agent_name == "member_2")
    assert "请核对事实" in (tool_step.input_text or "")
    followup = run.step_results[-1]
    assert followup.agent_name == "member_1" and "工具结果" in (followup.input_text or "")


@pytest.mark.asyncio
async def test_group_chat_tool_invalid_target_marks_partial():
    first = ScriptedAgent("member_1", AgentRole.WORKER, [
        '{"tool": "ask_agent", "agent": "ghost", "task": "核对事实"}'
    ])
    second = ScriptedAgent("member_2", AgentRole.WORKER, ["不应被调用"])
    executor = build_executor([first, second], max_iterations=2)

    result = await executor.execute("task")

    assert result["status"] == "partial"
    run = executor.get_run(result["run_id"])
    assert not any(step.step_id.startswith("tool_") for step in run.step_results)
    assert second.calls == []


@pytest.mark.asyncio
async def test_group_chat_tool_missing_arguments_marks_partial():
    first = ScriptedAgent("member_1", AgentRole.WORKER, [
        '{"tool": "ask_agent", "agent": "member_2"}'
    ])
    second = ScriptedAgent("member_2", AgentRole.WORKER, ["不应被调用"])
    executor = build_executor([first, second], max_iterations=2)

    result = await executor.execute("task")

    assert result["status"] == "partial"
    assert second.calls == []


class SlowAgent(ScriptedAgent):
    async def process(self, message):
        await asyncio.sleep(0.05)
        return await super().process(message)


@pytest.mark.asyncio
async def test_group_chat_timeout_reports_step_error(monkeypatch):
    monkeypatch.setenv("AGENTFLOW_STEP_TIMEOUT_SECONDS", "0.01")
    slow = SlowAgent("member_1", AgentRole.WORKER, ["太慢"])
    second = ScriptedAgent("member_2", AgentRole.WORKER, ["正常"])
    executor = build_executor([slow, second], max_iterations=1)

    result = await executor.execute("task")

    assert result["status"] == "failed"
    run = executor.get_run(result["run_id"])
    assert "timed out" in (run.error or "")


class FakeToolAdapter(LLMAdapter):
    """第一次返回原生 tool_calls，第二次返回最终答案。"""

    def __init__(self):
        self.calls = 0

    async def complete(self, messages, model="fake", temperature=0.7, max_tokens=2000, **kwargs):
        self.calls += 1
        if self.calls == 1 and kwargs.get("tools"):
            return {
                "content": None,
                "model": "fake-tool",
                "finish_reason": "tool_calls",
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "ask_agent",
                        "arguments": json.dumps({"agent": "member_2", "task": "核对事实"}),
                    },
                }],
            }
        return {
            "content": "基于工具结果的最终答案",
            "model": "fake-tool",
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        }

    async def stream_complete(self, messages, model="fake", **kwargs):
        yield "x"


@pytest.mark.asyncio
async def test_group_chat_native_tool_calls_are_executed():
    adapter = FakeToolAdapter()
    caller = LLMAgent(AgentConfig(name="member_1", role=AgentRole.WORKER, model="fake",
                                  system_prompt="you are member_1"), adapter)
    target = ScriptedAgent("member_2", AgentRole.WORKER, ["核对结果"])
    executor = build_executor([caller, target], max_iterations=1)

    result = await executor.execute("task")

    assert result["status"] == "completed"
    assert adapter.calls == 2
    assert target.calls
    run = executor.get_run(result["run_id"])
    assert any(step.step_id.startswith("native_tool_") for step in run.step_results)
    assert "基于工具结果的最终答案" in (result["result"]["final_result"] or "")


@pytest.mark.asyncio
async def test_group_chat_requires_at_least_two_agents():
    only = ScriptedAgent("member_1", AgentRole.WORKER, ["x"])
    executor = build_executor([only])

    with pytest.raises(ValueError, match="at least 2"):
        await executor.execute("task")
