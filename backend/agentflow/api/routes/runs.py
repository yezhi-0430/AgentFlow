"""
运行记录相关 API 路由

只读接口用于历史回看，不触发任何模型调用。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from agentflow.storage import RunRepository, get_db_session, init_db

router = APIRouter()

# 确保数据库已初始化
try:
    init_db()
except Exception as e:
    print(f"Database initialization warning: {e}")


def _limit(limit: int, maximum: int = 200) -> int:
    return max(1, min(limit, maximum))


@router.get("/workflows/{workflow_id}/runs")
async def list_workflow_runs(
    workflow_id: str,
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db_session),
):
    """获取工作流的运行历史"""
    try:
        runs = RunRepository.list_runs(
            db, workflow_id=workflow_id, limit=_limit(limit), offset=max(0, offset)
        )
        return {
            "workflow_id": workflow_id,
            "runs": [run.to_dict() for run in runs],
            "total": RunRepository.count_runs(db, workflow_id=workflow_id),
            "limit": _limit(limit),
            "offset": max(0, offset),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/runs/compare")
async def compare_runs(
    run_ids: str,
    db: Session = Depends(get_db_session),
):
    """对比多个运行记录（必须声明在 /runs/{run_id} 之前，否则会被路径参数吞掉）"""
    try:
        run_id_list = [run_id.strip() for run_id in run_ids.split(",") if run_id.strip()]

        if not run_id_list:
            raise HTTPException(status_code=400, detail="run_ids is required")
        if len(run_id_list) > 5:
            raise HTTPException(status_code=400, detail="Maximum 5 runs can be compared")

        runs = []
        for run_id in run_id_list:
            run = RunRepository.get_run(db, run_id)
            if run:
                runs.append(run.to_dict())

        if not runs:
            raise HTTPException(status_code=404, detail="No runs found")

        return {
            "runs": runs,
            "summary": {
                "total_runs": len(runs),
                "avg_tokens": sum(r["total_tokens"] for r in runs) / len(runs),
                "avg_duration": sum(r["total_duration"] for r in runs) / len(runs),
                "status_distribution": {
                    status: sum(1 for run in runs if run["status"] == status)
                    for status in {run["status"] for run in runs}
                },
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/runs/{run_id}")
async def get_run_detail(run_id: str, db: Session = Depends(get_db_session)):
    """获取运行详情（历史回看，不触发模型调用）"""
    try:
        run = RunRepository.get_run(db, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return run.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/runs")
async def list_all_runs(
    limit: int = 20,
    offset: int = 0,
    experiment_id: str | None = None,
    candidate_id: str | None = None,
    fingerprint: str | None = None,
    case_id: str | None = None,
    db: Session = Depends(get_db_session),
):
    """列出所有运行记录（支持按实验/候选/指纹/case 过滤；只读）"""
    try:
        runs = RunRepository.list_runs(
            db,
            workflow_id=None,
            limit=_limit(limit),
            offset=max(0, offset),
            experiment_id=experiment_id,
            candidate_id=candidate_id,
            fingerprint=fingerprint,
            case_id=case_id,
        )
        return {
            "runs": [run.to_dict() for run in runs],
            "total": len(runs),
            "limit": _limit(limit),
            "offset": max(0, offset),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str, db: Session = Depends(get_db_session)):
    """删除运行记录"""
    try:
        success = RunRepository.delete_run(db, run_id)
        if not success:
            raise HTTPException(status_code=404, detail="Run not found")
        return {"message": "Run deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
