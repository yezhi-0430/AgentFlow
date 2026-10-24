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
):
    """获取消息历史（只读内存；历史回看不触发模型调用）"""
    from agentflow.api.routes.workflow import workflows

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
        raise HTTPException(status_code=404, detail="Run messages not found")

    if workflow_id:
        # 获取特定工作流的消息（当前/最近一次运行）
        if workflow_id not in workflows:
            raise HTTPException(status_code=404, detail="Workflow not found")

        executor = workflows[workflow_id]
        messages = [msg.to_dict() for msg in executor.message_history]

        return {
            "workflow_id": workflow_id,
            "run_id": executor.current_run.run_id if executor.current_run else None,
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
