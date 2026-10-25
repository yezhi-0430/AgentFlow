"""
工作流相关 API 路由

工作流定义持久化（不含密钥）：
- 创建/导入时把定义写入本地 SQLite；
- 后端启动时从数据库恢复定义（执行器先以"需要密钥"状态存在）；
- 导出/导入使用版本化定义 JSON，导入总是分配新的 workflow_id；
- 恢复的工作流在执行时必须显式提供 api_key（不落库、只驻留内存）。
"""
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

# 确保环境变量已加载
load_dotenv()

from agentflow.adapters.factory import AdapterFactory
from agentflow.agents.llm_agent import LLMAgent
from agentflow.core.agent import AgentConfig, AgentRole
from agentflow.core.definition import DefinitionValidationError, WorkflowDefinition
from agentflow.core.workflow import (
    RunAlreadyRunningError,
    UnsupportedPatternError,
    WorkflowConfig,
    WorkflowExecutor,
    WorkflowPattern,
    WorkflowStep,
    ensure_supported_pattern,
    validate_pattern_agents,
)

try:  # 定义持久化是可选的：缺少依赖时不影响内存工作流
    from agentflow.storage import WorkflowDefinitionRepository, get_db
    DEFINITION_STORAGE_AVAILABLE = True
except ImportError:
    WorkflowDefinitionRepository = None  # type: ignore[assignment]
    get_db = None  # type: ignore[assignment]
    DEFINITION_STORAGE_AVAILABLE = False

router = APIRouter()

# 内存中的工作流执行器（定义持久化在 SQLite，密钥只在内存）
workflows: Dict[str, WorkflowExecutor] = {}


def _is_tracing_enabled() -> bool:
    """检查是否启用 Langfuse 追踪"""
    return os.getenv("ENABLE_LANGFUSE_TRACING", "false").lower() in ("true", "1", "yes")


# --------------------------------------------------------------- persistence
def _persist_definition(executor: WorkflowExecutor) -> None:
    """保存定义（不含密钥）；失败只告警，不影响内存工作流"""
    if not DEFINITION_STORAGE_AVAILABLE:
        return
    try:
        with get_db() as db:
            WorkflowDefinitionRepository.save(db, executor.to_definition())
    except Exception as e:  # noqa: BLE001
        print(f"Failed to persist workflow definition {executor.workflow_id}: {e}")


def _load_definition(workflow_id: str) -> Optional[WorkflowDefinition]:
    if not DEFINITION_STORAGE_AVAILABLE:
        return None
    try:
        with get_db() as db:
            return WorkflowDefinitionRepository.get(db, workflow_id)
    except Exception as e:  # noqa: BLE001
        print(f"Failed to load workflow definition {workflow_id}: {e}")
        return None


def _delete_definition(workflow_id: str) -> None:
    if not DEFINITION_STORAGE_AVAILABLE:
        return
    try:
        with get_db() as db:
            WorkflowDefinitionRepository.delete(db, workflow_id)
    except Exception as e:  # noqa: BLE001
        print(f"Failed to delete workflow definition {workflow_id}: {e}")


def restore_workflows() -> int:
    """从数据库恢复工作流定义（在应用启动时调用）。

    恢复的执行器没有 Agent/适配器，`requires_credentials=True`；
    执行时需要显式提供 api_key。
    """
    if not DEFINITION_STORAGE_AVAILABLE:
        return 0
    try:
        with get_db() as db:
            definitions = WorkflowDefinitionRepository.list_all(db)
    except Exception as e:  # noqa: BLE001
        print(f"Workflow definition restore skipped: {e}")
        return 0

    restored = 0
    for definition in definitions:
        if definition.workflow_id in workflows:
            continue
        try:
            executor = WorkflowExecutor(
                definition.to_workflow_config(),
                enable_persistence=True,
                enable_tracing=_is_tracing_enabled(),
                workflow_id=definition.workflow_id,
            )
        except Exception as e:  # noqa: BLE001
            print(f"Skip invalid workflow definition {definition.workflow_id}: {e}")
            continue
        executor.description = definition.description
        executor.connection = dict(definition.connection)
        workflows[definition.workflow_id] = executor
        restored += 1

    if restored:
        print(f"Restored {restored} workflow definition(s) from database")
    return restored


# ------------------------------------------------------------------- helpers
def _attach_agents(executor: WorkflowExecutor, api_key: str) -> None:
    """用显式提供的密钥为恢复的工作流构建适配器与 Agent（只驻留内存）"""
    connection = executor.connection or {}
    provider = connection.get("provider") or "openai"
    try:
        adapter = AdapterFactory.create_adapter(
            provider=provider,
            api_key=api_key,
            base_url=connection.get("base_url"),
            site_url=connection.get("site_url"),
            app_name=connection.get("app_name", "AgentFlow"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    executor.agents.clear()
    for agent_config in executor.config.agents:
        executor.register_agent(LLMAgent(agent_config, adapter))


def _agent_summaries(executor: WorkflowExecutor) -> List[Dict[str, Any]]:
    """优先使用已注册的 Agent；恢复的工作流回退到配置快照"""
    if executor.agents:
        return [
            {"name": agent.name, "role": agent.role.value, "model": agent.config.model}
            for agent in executor.agents.values()
        ]
    return [
        {
            "name": config.name,
            "role": config.role.value if hasattr(config.role, "value") else str(config.role),
            "model": config.model,
        }
        for config in executor.config.agents
    ]


def _workflow_summary(workflow_id: str, executor: WorkflowExecutor) -> Dict[str, Any]:
    return {
        "workflow_id": workflow_id,
        "name": executor.config.name,
        "description": executor.description,
        "pattern": executor.config.pattern.value,
        "status": executor.status,
        "requires_credentials": executor.requires_credentials,
        "agents": _agent_summaries(executor),
    }


# -------------------------------------------------------------------- models
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
    # 恢复的工作流（服务重启后）需要重新提供密钥；密钥只驻留内存
    api_key: Optional[str] = None


# -------------------------------------------------------------------- routes
@router.get("/providers")
async def get_providers():
    """获取支持的 LLM 提供商列表"""
    return {"providers": AdapterFactory.get_provider_info()}


def _group_chat_specs(
    config: Dict[str, Any], agent_count: int, default_model: str
) -> tuple[Optional[str], List[Dict[str, str]]]:
    """解析群聊多模型配置；旧配置没有 members 时返回 (None, [])。"""
    group_chat = config.get("group_chat")
    if not isinstance(group_chat, dict) or "members" not in group_chat:
        return None, []

    if str(config.get("llm_provider", "openai")).lower() != "openrouter":
        raise HTTPException(status_code=400, detail="group_chat requires OpenRouter when members are configured")

    raw_members = group_chat.get("members")
    if not isinstance(raw_members, list):
        raise HTTPException(status_code=400, detail="group_chat.members must be a list")

    enable_lead = bool(group_chat.get("enable_lead", True))
    minimum = 1 if enable_lead else 2
    maximum = 5 if enable_lead else 6
    if not minimum <= len(raw_members) <= maximum:
        raise HTTPException(
            status_code=400,
            detail=f"group_chat.members must contain {minimum}-{maximum} members",
        )

    members: List[Dict[str, str]] = []
    seen = set()
    for index, item in enumerate(raw_members):
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail=f"group_chat.members[{index}] must be an object")
        name = str(item.get("name") or "").strip()
        member_model = str(item.get("model") or "").strip()
        if not name or not member_model:
            raise HTTPException(status_code=400, detail=f"group_chat.members[{index}] requires name and model")
        if name.casefold() in {"lead", "system", "group", "human"}:
            raise HTTPException(status_code=400, detail=f"group_chat member name is reserved: {name}")
        if name in seen:
            raise HTTPException(status_code=400, detail=f"duplicate group_chat member name: {name}")
        seen.add(name)
        members.append({"name": name, "model": member_model})

    lead_model = None
    if enable_lead:
        lead_model = str(group_chat.get("lead_model") or "").strip()
        if not lead_model:
            raise HTTPException(status_code=400, detail="group_chat.lead_model is required when enable_lead is true")

    return lead_model, members


def _build_pattern_agents(
    pattern: WorkflowPattern,
    agent_count: int,
    model: str,
    *,
    group_chat_lead: bool = True,
    group_chat_config: Optional[Dict[str, Any]] = None,
    llm_provider: str = "openai",
) -> tuple[List[AgentConfig], List[WorkflowStep]]:
    """按协作模式生成 Agent 配置与展示用步骤（密钥不进入配置）。"""
    agents: List[AgentConfig] = []
    steps: List[WorkflowStep] = []

    def agent(name: str, role: AgentRole, prompt: str, model_override: Optional[str] = None) -> AgentConfig:
        return AgentConfig(
            name=name, role=role, system_prompt=prompt, model=model_override or model,
            temperature=0.7, max_tokens=2000,
        )

    if pattern in (WorkflowPattern.SEQUENTIAL, WorkflowPattern.PARALLEL):
        for index in range(agent_count):
            name = f"worker_{index + 1}"
            agents.append(agent(
                name, AgentRole.WORKER,
                f"You are worker {index + 1}. Complete the task assigned to you.",
            ))
            steps.append(WorkflowStep(
                id=f"step_{index + 1}", agent_name=name,
                input_from=f"step_{index}" if pattern == WorkflowPattern.SEQUENTIAL and index > 0 else None,
            ))
        return agents, steps

    if pattern == WorkflowPattern.GROUP_CHAT:
        lead_model, member_specs = _group_chat_specs(
            {"group_chat": group_chat_config or {}, "llm_provider": llm_provider},
            agent_count,
            model,
        )
        if member_specs:
            if group_chat_lead:
                agents.append(agent(
                    "lead", AgentRole.COORDINATOR,
                    "You are the lead of a group chat. The user's ORIGINAL TASK is the only goal; "
                    "never invent projects, people, or unrelated topics. You MUST reply with a single "
                    "JSON object only, no prose: {\"done\": false, \"next\": \"member_1\", \"task\": \"...\"} "
                    "to assign the next member (next must be from the provided member list), or "
                    "{\"done\": true, \"summary\": \"...\"} to finish. Produce the final summary.",
                    model_override=lead_model,
                ))
            for index, spec in enumerate(member_specs, start=1):
                agents.append(agent(
                    spec["name"], AgentRole.WORKER,
                    f"You are group member {index}. Contribute from your role, react to others, "
                    "and help complete the task.",
                    model_override=spec["model"],
                ))
            steps.append(WorkflowStep(
                id="group_chat",
                agent_name="lead" if group_chat_lead else member_specs[0]["name"],
            ))
            return agents, steps

        if group_chat_lead:
            agents.append(agent(
                "lead", AgentRole.COORDINATOR,
                "You are the lead of a group chat. The user's ORIGINAL TASK is the only goal; "
                "never invent projects, people, or unrelated topics. You MUST reply with a single "
                "JSON object only, no prose: {\"done\": false, \"next\": \"member_1\", \"task\": \"...\"} "
                "to assign the next member (next must be from the provided member list), or "
                "{\"done\": true, \"summary\": \"...\"} to finish. Produce the final summary.",
            ))
            for index in range(agent_count - 1):
                name = f"member_{index + 1}"
                agents.append(agent(
                    name, AgentRole.WORKER,
                    f"You are group member {index + 1}. Contribute from your role, react to others, "
                    "and help complete the task.",
                ))
            steps.append(WorkflowStep(id="group_chat", agent_name="lead"))
        else:
            for index in range(agent_count):
                name = f"member_{index + 1}"
                agents.append(agent(
                    name, AgentRole.WORKER,
                    f"You are group member {index + 1}. Contribute from your role, react to others, "
                    "and help complete the task.",
                ))
            steps.append(WorkflowStep(id="group_chat", agent_name="member_1"))
        return agents, steps

    if pattern in (WorkflowPattern.HIERARCHICAL, WorkflowPattern.DYNAMIC):
        agents.append(agent(
            "coordinator", AgentRole.COORDINATOR,
            "You are the coordinator. Break the task into subtasks, assign work, "
            "and synthesize the final answer.",
        ))
        for index in range(agent_count - 1):
            name = f"worker_{index + 1}"
            agents.append(agent(
                name, AgentRole.WORKER,
                f"You are worker {index + 1}. Complete the subtask assigned by the coordinator.",
            ))
            steps.append(WorkflowStep(id=f"worker_{index + 1}", agent_name=name))
        if pattern == WorkflowPattern.HIERARCHICAL:
            steps.insert(0, WorkflowStep(id="plan", agent_name="coordinator"))
            steps.append(WorkflowStep(id="synthesis", agent_name="coordinator"))
        else:
            steps.insert(0, WorkflowStep(id="dynamic_orchestration", agent_name="coordinator"))
        return agents, steps

    # debate / voting：前 n-1 个是辩手/候选，最后一个是裁判
    judge_name = "judge"
    if pattern == WorkflowPattern.DEBATE:
        for index in range(agent_count - 1):
            name = f"debater_{index + 1}"
            agents.append(agent(
                name, AgentRole.WORKER,
                f"You are debater {index + 1}. State your position, respond to others, "
                "and revise toward a correct answer.",
            ))
            steps.append(WorkflowStep(id=f"debate_r1_{name}", agent_name=name))
            steps.append(WorkflowStep(id=f"debate_r2_{name}", agent_name=name))
    else:
        for index in range(agent_count - 1):
            name = f"candidate_{index + 1}"
            agents.append(agent(
                name, AgentRole.WORKER,
                f"You are candidate {index + 1}. Solve the task independently.",
            ))
            steps.append(WorkflowStep(id=f"candidate_{name}", agent_name=name))

    agents.append(agent(
        judge_name, AgentRole.REVIEWER,
        "You are the judge. Compare the answers and give the final answer.",
    ))
    steps.append(WorkflowStep(id="judge", agent_name=judge_name))
    return agents, steps


@router.post("")
async def create_workflow(request: WorkflowCreateRequest):
    """创建工作流（定义持久化，密钥不落库）"""
    try:
        agent_count = request.config.get("agent_count", 3)
        try:
            agent_count = int(agent_count)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="agent_count must be an integer")
        llm_provider = request.config.get("llm_provider", "openai")
        api_key = request.config.get("api_key", "")
        base_url = request.config.get("base_url")
        model = request.config.get("model", "gpt-4")

        if not api_key:
            raise HTTPException(status_code=400, detail="API key is required")

        try:
            adapter = AdapterFactory.create_adapter(
                provider=llm_provider,
                api_key=api_key,
                base_url=base_url,
                site_url=request.config.get("site_url"),
                app_name=request.config.get("app_name", "AgentFlow"),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # 明确拒绝未支持的模式：避免创建后执行到一半才失败
        try:
            pattern = WorkflowPattern(request.pattern)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown workflow pattern: {request.pattern}",
            )
        try:
            ensure_supported_pattern(pattern)
        except UnsupportedPatternError as e:
            raise HTTPException(status_code=400, detail=str(e))

        group_chat_lead = True
        group_chat_config = request.config.get("group_chat")
        max_iterations = 10
        if pattern == WorkflowPattern.GROUP_CHAT:
            if isinstance(group_chat_config, dict):
                group_chat_lead = bool(group_chat_config.get("enable_lead", True))
                try:
                    max_turns = int(group_chat_config.get("max_turns", 12))
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400, detail="group_chat.max_turns must be an integer")
                max_iterations = max(1, min(20, max_turns))

        agent_configs, workflow_steps = _build_pattern_agents(
            pattern,
            agent_count,
            model,
            group_chat_lead=group_chat_lead,
            group_chat_config=group_chat_config,
            llm_provider=llm_provider,
        )
        try:
            validate_pattern_agents(pattern, len(agent_configs))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        workflow_config = WorkflowConfig(
            name=request.name,
            pattern=pattern,
            steps=workflow_steps,
            agents=agent_configs,
            max_iterations=max_iterations,
        )

        executor = WorkflowExecutor(
            workflow_config,
            enable_persistence=True,
            enable_tracing=_is_tracing_enabled(),
        )
        executor.description = request.description or ""
        executor.connection = {
            key: value
            for key, value in {
                "provider": llm_provider,
                "base_url": base_url,
                "site_url": request.config.get("site_url"),
                "app_name": request.config.get("app_name", "AgentFlow"),
            }.items()
            if value
        }

        for agent_config in agent_configs:
            executor.register_agent(LLMAgent(agent_config, adapter))

        workflow_id = executor.workflow_id
        workflows[workflow_id] = executor
        _persist_definition(executor)

        return {
            "workflow_id": workflow_id,
            "name": request.name,
            "description": request.description,
            "pattern": request.pattern,
            "agents": _agent_summaries(executor),
            "requires_credentials": False,
            "status": "created",
        }

    except HTTPException:
        raise
    except UnsupportedPatternError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/import")
async def import_workflow(payload: Dict[str, Any]):
    """导入工作流定义（总是分配新 workflow_id；不会导入密钥）"""
    try:
        definition = WorkflowDefinition.from_dict(payload)
    except DefinitionValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    definition.workflow_id = str(uuid.uuid4())
    definition.created_at = time.time()
    definition.updated_at = time.time()

    try:
        executor = WorkflowExecutor(
            definition.to_workflow_config(),
            enable_persistence=True,
            enable_tracing=_is_tracing_enabled(),
            workflow_id=definition.workflow_id,
        )
    except (UnsupportedPatternError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    executor.description = definition.description
    executor.connection = dict(definition.connection)
    workflows[definition.workflow_id] = executor
    _persist_definition(executor)

    return {
        "workflow_id": definition.workflow_id,
        "name": definition.name,
        "description": definition.description,
        "pattern": definition.pattern,
        "agents": _agent_summaries(executor),
        "requires_credentials": True,
        "status": "imported",
    }


async def execute_workflow_background(executor: WorkflowExecutor, task: str, run_id: str):
    """后台执行工作流（run_id 由 API 提前生成，前端可立即用于查询/追踪）"""
    from agentflow.api.websocket import manager

    try:
        await manager.notify_workflow_event(
            executor.workflow_id,
            "execution_started",
            {"task": task, "run_id": run_id},
        )

        result = await executor.execute(task, run_id=run_id)

        await manager.notify_workflow_event(
            executor.workflow_id,
            "execution_completed",
            {"result": result, "run_id": run_id, "status": result.get("status")},
        )

    except RunAlreadyRunningError as e:
        await manager.notify_workflow_event(
            executor.workflow_id, "execution_failed",
            {"error": str(e), "run_id": run_id},
        )
    except Exception as e:
        await manager.notify_workflow_event(
            executor.workflow_id, "execution_failed",
            {"error": str(e), "run_id": run_id},
        )


@router.post("/{workflow_id}/execute")
async def execute_workflow(
    workflow_id: str,
    request: WorkflowExecuteRequest,
    background_tasks: BackgroundTasks,
):
    """执行工作流（异步；恢复的工作流可用 api_key 重新提供密钥）"""
    if workflow_id not in workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")

    executor = workflows[workflow_id]

    if executor.is_busy():
        raise HTTPException(
            status_code=409,
            detail="A run is already executing for this workflow; concurrent runs are not supported",
        )

    # 服务重启后恢复的工作流没有密钥：必须显式提供，且不落库
    if executor.requires_credentials:
        if not request.api_key:
            raise HTTPException(
                status_code=400,
                detail=(
                    "This workflow was restored after restart and needs an API key. "
                    "Provide 'api_key' in the execute request (it is kept in memory only)."
                ),
            )
        _attach_agents(executor, request.api_key)

    run_id = str(uuid.uuid4())
    background_tasks.add_task(execute_workflow_background, executor, request.task, run_id)

    return {
        "workflow_id": workflow_id,
        "run_id": run_id,
        "status": "executing",
        "message": "Workflow execution started in background",
    }


@router.post("/{workflow_id}/stop")
async def stop_workflow(workflow_id: str):
    """停止工作流执行（真实执行控制：阻止后续步骤/取消未完成调用）"""
    if workflow_id not in workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")

    executor = workflows[workflow_id]
    stopped = executor.stop()
    if not stopped:
        raise HTTPException(status_code=409, detail="No active run to stop")

    from agentflow.api.websocket import manager
    await manager.notify_workflow_event(
        workflow_id,
        "execution_stopping",
        {"message": "Stop requested; finishing current calls"},
    )

    return {"message": "Stop requested", "status": "stopping"}


@router.get("/{workflow_id}/definition")
async def export_workflow_definition(workflow_id: str):
    """导出工作流定义（版本化 JSON，不含任何密钥）"""
    if workflow_id not in workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")

    executor = workflows[workflow_id]
    stored = _load_definition(workflow_id)
    definition = stored or executor.to_definition()
    payload = definition.to_dict()
    payload["exported_at"] = time.time()
    return payload


@router.get("/{workflow_id}/status")
async def get_workflow_status(workflow_id: str):
    """获取工作流状态"""
    if workflow_id not in workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")

    executor = workflows[workflow_id]
    status = executor.get_status()
    status["requires_credentials"] = executor.requires_credentials
    status["description"] = executor.description
    return status


@router.get("")
async def list_workflows():
    """列出所有工作流（含服务重启后恢复的定义）"""
    return {
        "workflows": [
            _workflow_summary(workflow_id, executor)
            for workflow_id, executor in workflows.items()
        ]
    }


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str):
    """获取工作流详情"""
    if workflow_id not in workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")

    executor = workflows[workflow_id]

    if executor.agents:
        agents_payload = [
            {
                **agent.config.to_dict(),
                "status": agent.state.status,
                "messages_sent": sum(msg.sender == agent.name for msg in executor.message_history),
                "messages_received": sum(msg.receiver == agent.name for msg in executor.message_history),
                "tokens_used": agent.state.total_tokens,
            }
            for agent in executor.agents.values()
        ]
    else:
        agents_payload = [
            {
                **config.to_dict(),
                "status": "unavailable",
                "messages_sent": 0,
                "messages_received": 0,
                "tokens_used": 0,
            }
            for config in executor.config.agents
        ]

    return {
        "workflow_id": workflow_id,
        "name": executor.config.name,
        "description": executor.description,
        "pattern": executor.config.pattern.value,
        "status": executor.status,
        "requires_credentials": executor.requires_credentials,
        "connection": {"provider": executor.connection.get("provider")},
        "agents": agents_payload,
        "message_count": len(executor.message_history),
        "current_step": executor.current_step,
        "max_iterations": executor.config.max_iterations,
    }


@router.delete("/{workflow_id}")
async def delete_workflow(workflow_id: str):
    """删除工作流（同时删除持久化的定义；历史运行记录保留）"""
    if workflow_id not in workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")

    del workflows[workflow_id]
    _delete_definition(workflow_id)
    return {"message": "Workflow deleted"}
