"""
消息相关 API 路由
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

router = APIRouter()


@router.get("")
async def get_messages(
    workflow_id: Optional[str] = Query(None, description="过滤特定工作流的消息"),
    run_id: Optional[str] = Query(None, description="过滤某次运行的消息（历史回看不调用模型）"),
    limit: int = Query(50, ge=1, le=200),
    before: Optional[float] = Query(None, description="只返回该时间戳之前的消息"),
    include_internal: bool = Query(False, description="是否返回 Lead 规划等内部消息"),
):
    """获取消息历史（只读内存；历史回看不触发模型调用）"""
    from agentflow.api.routes.workflow import workflows

    try:
        from agentflow.storage import MessageRepository, get_db
    except ImportError:  # pragma: no cover - 存储不可用时只读内存
        MessageRepository = None
        get_db = None

    if run_id:
        # 按运行过滤：优先从执行器内存中取该 run 的消息
        for wf_id, executor in workflows.items():
            messages = executor.get_run_messages(run_id)
            if messages:
                payload = []
                for msg in messages:
                    item = msg.to_dict()
                    item["workflow_id"] = wf_id
                    item["run_id"] = run_id
                    payload.append(item)
                return {"workflow_id": wf_id, "run_id": run_id, "messages": payload, "count": len(payload)}
        # 服务重启后内存消息丢失：从 group messages 表回放
        if MessageRepository is not None and get_db is not None:
            with get_db() as db:
                rows = MessageRepository.list_by_run(db, run_id)
            if rows:
                return {
                    "workflow_id": rows[0].get("workflow_id"),
                    "run_id": run_id,
                    "messages": rows,
                    "count": len(rows),
                }
        raise HTTPException(status_code=404, detail="Run messages not found")

    if workflow_id:
        rows = []
        if MessageRepository is not None and get_db is not None:
            with get_db() as db:
                rows = MessageRepository.list_by_workflow(db, workflow_id)

        if workflow_id in workflows:
            executor = workflows[workflow_id]
            rows = rows + [msg.to_dict() for msg in executor.message_history]
        elif not rows:
            raise HTTPException(status_code=404, detail="Workflow not found")

        deduped = {}
        for item in rows:
            metadata = item.get("metadata") or {}
            item.setdefault("run_id", metadata.get("run_id"))
            if not include_internal and (
                metadata.get("visibility") == "internal"
                or str(metadata.get("step_id") or "").startswith("lead_plan_")
            ):
                continue
            if before is not None and float(item.get("timestamp") or 0) >= before:
                continue
            deduped[str(item.get("id"))] = item

        messages = sorted(deduped.values(), key=lambda item: float(item.get("timestamp") or 0))
        messages = messages[-limit:]
        executor = workflows.get(workflow_id)
        return {
            "workflow_id": workflow_id,
            "run_id": (executor.current_run.run_id if executor and executor.current_run else (
                messages[-1].get("run_id") if messages else None
            )),
            "messages": messages,
            "count": len(messages),
        }
    else:
        # 获取所有消息
        all_messages = []
        for wf_id, executor in workflows.items():
            for msg in executor.message_history:
                msg_dict = msg.to_dict()
                msg_dict["workflow_id"] = wf_id
                all_messages.append(msg_dict)

        return {
            "messages": all_messages,
            "count": len(all_messages),
        }


@router.get("/{message_id}")
async def get_message(message_id: str, workflow_id: str):
    """获取特定消息"""
    from agentflow.api.routes.workflow import workflows

    if workflow_id not in workflows:
        raise HTTPException(status_code=404, detail="Workflow not found")

    executor = workflows[workflow_id]

    for msg in executor.message_history:
        if msg.id == message_id:
            return msg.to_dict()

    raise HTTPException(status_code=404, detail="Message not found")
