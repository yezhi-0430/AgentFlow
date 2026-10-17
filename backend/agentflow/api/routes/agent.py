"""
Agent 相关 API 路由
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, List

router = APIRouter()


@router.get("")
async def list_agents():
    """列出所有 agents（从所有工作流中）"""
    from agentflow.api.routes.workflow import workflows

    all_agents = []
    for workflow_id, executor in workflows.items():
        for agent_name, agent in executor.agents.items():
            all_agents.append({
                "workflow_id": workflow_id,
                "name": agent.name,
                "role": agent.role.value,
                "status": agent.state.status,
                "messages_processed": agent.state.messages_processed,
                "total_tokens": agent.state.total_tokens,
            })

    return {"agents": all_agents}


@router.get("/{agent_name}/memory")
async def get_agent_memory(agent_name: str, workflow_id: str):
    """获取 agent 的记忆"""
    from agentflow.api.routes.workflow import workflows

    if workflow_id not in workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")

    executor = workflows[workflow_id]
    agent = executor.agents.get(agent_name)

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    return {
        "agent": agent_name,
        "memory": [msg.to_dict() for msg in agent.memory],
        "memory_size": len(agent.memory),
    }


@router.get("/{agent_name}/state")
async def get_agent_state(agent_name: str, workflow_id: str):
    """获取 agent 状态"""
    from agentflow.api.routes.workflow import workflows

    if workflow_id not in workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")

    executor = workflows[workflow_id]
    agent = executor.agents.get(agent_name)

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    return agent.get_state()
