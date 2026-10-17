"""
工作流相关 API 路由
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import Dict, Any, Optional
from pydantic import BaseModel

from agentflow.core.workflow import WorkflowExecutor, WorkflowConfig, WorkflowPattern, WorkflowStep
from agentflow.core.agent import AgentConfig, AgentRole
from agentflow.agents.llm_agent import LLMAgent
from agentflow.adapters.factory import AdapterFactory

router = APIRouter()

# 临时存储（生产环境应使用数据库）
workflows: Dict[str, WorkflowExecutor] = {}


@router.get("/providers")
async def get_providers():
    """获取支持的 LLM 提供商列表"""
    return {
        "providers": AdapterFactory.get_provider_info()
    }


class WorkflowCreateRequest(BaseModel):
    """创建工作流请求"""
    name: str
    description: Optional[str] = ""
    pattern: str
    config: Dict[str, Any]


class WorkflowExecuteRequest(BaseModel):
    """执行工作流请求"""
    task: str
    context: Optional[Dict[str, Any]] = {}


@router.post("")
async def create_workflow(request: WorkflowCreateRequest):
    """创建工作流"""
    try:
        # 从 config 中提取参数
        agent_count = request.config.get("agent_count", 3)
        llm_provider = request.config.get("llm_provider", "openai")
        api_key = request.config.get("api_key", "")
        base_url = request.config.get("base_url")
        model = request.config.get("model", "gpt-4")  # 获取选择的模型

        if not api_key:
            raise HTTPException(status_code=400, detail="API key is required")

        # 使用适配器工厂创建适配器
        try:
            adapter = AdapterFactory.create_adapter(
                provider=llm_provider,
                api_key=api_key,
                base_url=base_url,
                site_url=request.config.get("site_url"),
                app_name=request.config.get("app_name", "AgentFlow")
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # 根据模式和数量自动创建 agents
        agent_configs = []
        workflow_steps = []

        pattern = WorkflowPattern(request.pattern)

        if pattern == WorkflowPattern.SEQUENTIAL:
            # 顺序执行：创建一系列 worker agents
            for i in range(agent_count):
                agent_config = AgentConfig(
                    name=f"worker_{i+1}",
                    role=AgentRole.WORKER,
                    system_prompt=f"You are worker {i+1}. Complete the task assigned to you.",
                    model=model,  # 使用选择的模型
                    temperature=0.7,
                    max_tokens=2000,
                )
                agent_configs.append(agent_config)

                # 创建步骤
                step = WorkflowStep(
                    id=f"step_{i+1}",
                    agent_name=f"worker_{i+1}",
                    input_from=f"step_{i}" if i > 0 else None,
                )
                workflow_steps.append(step)

        elif pattern == WorkflowPattern.PARALLEL:
            # 并行执行：创建多个 worker agents
            for i in range(agent_count):
                agent_config = AgentConfig(
                    name=f"worker_{i+1}",
                    role=AgentRole.WORKER,
                    system_prompt=f"You are worker {i+1}. Work on your assigned part of the task.",
                    model=model,  # 使用选择的模型
                    temperature=0.7,
                    max_tokens=2000,
                )
                agent_configs.append(agent_config)

                step = WorkflowStep(
                    id=f"step_{i+1}",
                    agent_name=f"worker_{i+1}",
                    input_from=None,  # 并行执行
                )
                workflow_steps.append(step)

        elif pattern == WorkflowPattern.HIERARCHICAL:
            # 层次协作：1个协调者 + N个工作者
            coordinator = AgentConfig(
                name="coordinator",
                role=AgentRole.COORDINATOR,
                system_prompt="You are the coordinator. Break down tasks and coordinate workers.",
                model=model,  # 使用选择的模型
                temperature=0.7,
                max_tokens=2000,
            )
            agent_configs.append(coordinator)

            for i in range(agent_count - 1):
                worker = AgentConfig(
                    name=f"worker_{i+1}",
                    role=AgentRole.WORKER,
                    system_prompt=f"You are worker {i+1}. Follow coordinator instructions.",
                    model=model,  # 使用选择的模型
                    temperature=0.7,
                    max_tokens=2000,
                )
                agent_configs.append(worker)

        elif pattern == WorkflowPattern.DEBATE:
            # 辩论模式：创建多个专家 agents
            for i in range(agent_count):
                expert = AgentConfig(
                    name=f"expert_{i+1}",
                    role=AgentRole.SPECIALIST,
                    system_prompt=f"You are expert {i+1}. Provide your perspective and engage in constructive debate.",
                    model="gpt-4",
                    temperature=0.8,
                    max_tokens=2000,
                )
                agent_configs.append(expert)

        # 创建工作流配置
        workflow_config = WorkflowConfig(
            name=request.name,
            pattern=pattern,
            steps=workflow_steps if workflow_steps else [],
            agents=agent_configs,
            max_iterations=10,
        )

        # 创建执行器
        executor = WorkflowExecutor(workflow_config)

        # 创建并注册 agents
        for agent_config in agent_configs:
            agent = LLMAgent(agent_config, adapter)
            executor.register_agent(agent)

        # 保存
        workflow_id = executor.workflow_id
        workflows[workflow_id] = executor

        return {
            "workflow_id": workflow_id,
            "name": request.name,
            "description": request.description,
            "pattern": request.pattern,
            "agents": [
                {
                    "name": ac.name,
                    "role": ac.role.value,
                    "model": ac.model,
                }
                for ac in agent_configs
            ],
            "status": "created",
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def execute_workflow_background(executor: WorkflowExecutor, task: str):
    """后台执行工作流"""
    from agentflow.api.websocket import manager

    try:
        # 通知开始执行
        await manager.notify_workflow_event(
            executor.workflow_id,
            "execution_started",
            {"task": task}
        )

        # 执行工作流
        result = await executor.execute(task)

        # 通知执行完成
        await manager.notify_workflow_event(
            executor.workflow_id,
            "execution_completed",
            {"result": result}
        )

    except Exception as e:
        # 通知执行失败
        await manager.notify_workflow_event(
            executor.workflow_id,
            "execution_failed",
            {"error": str(e)}
        )


@router.post("/{workflow_id}/execute")
async def execute_workflow(
    workflow_id: str,
    request: WorkflowExecuteRequest,
    background_tasks: BackgroundTasks
):
    """执行工作流（异步）"""
    if workflow_id not in workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")

    executor = workflows[workflow_id]

    # 添加后台任务
    background_tasks.add_task(execute_workflow_background, executor, request.task)

    return {
        "workflow_id": workflow_id,
        "status": "executing",
        "message": "Workflow execution started in background"
    }


@router.post("/{workflow_id}/stop")
async def stop_workflow(workflow_id: str):
    """停止工作流执行"""
    if workflow_id not in workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")

    executor = workflows[workflow_id]
    executor.stop()

    from agentflow.api.websocket import manager
    await manager.notify_workflow_event(
        workflow_id,
        "execution_stopped",
        {"message": "Workflow execution stopped by user"}
    )

    return {"message": "Workflow stopped"}


@router.get("/{workflow_id}/status")
async def get_workflow_status(workflow_id: str):
    """获取工作流状态"""
    if workflow_id not in workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")

    executor = workflows[workflow_id]
    return executor.get_status()


@router.get("")
async def list_workflows():
    """列出所有工作流"""
    return {
        "workflows": [
            {
                "workflow_id": wf_id,
                "name": executor.config.name,
                "pattern": executor.config.pattern.value,
                "status": executor.status,
                "agents": [
                    {
                        "name": agent.name,
                        "role": agent.role.value,
                    }
                    for agent in executor.agents.values()
                ],
            }
            for wf_id, executor in workflows.items()
        ]
    }


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str):
    """获取工作流详情"""
    if workflow_id not in workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")

    executor = workflows[workflow_id]

    return {
        "workflow_id": workflow_id,
        "name": executor.config.name,
        "pattern": executor.config.pattern.value,
        "status": executor.status,
        "agents": [
            {
                **agent.config.to_dict(),
                "status": agent.state.status,
                "messages_sent": sum(msg.sender == agent.name for msg in executor.message_history),
                "messages_received": sum(msg.receiver == agent.name for msg in executor.message_history),
                "tokens_used": agent.state.total_tokens,
            }
            for agent in executor.agents.values()
        ],
        "message_count": len(executor.message_history),
        "current_step": executor.current_step,
        "max_iterations": executor.config.max_iterations,
    }


@router.delete("/{workflow_id}")
async def delete_workflow(workflow_id: str):
    """删除工作流"""
    if workflow_id not in workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")

    del workflows[workflow_id]
    return {"message": "Workflow deleted"}
