"""
Harness²-lite 实验 / 候选对比 / 证据 只读 API

数据来源：
- `experiments` / `experiment_candidates` 表（实验与候选元数据，无密钥）；
- `workflow_runs` 中 experiment_id/candidate_id/case_id/fingerprint 关联的运行记录；
- 证据文件（evidence_ref，默认关闭，存在时可读）。

这些接口只读本地数据，不调用任何模型。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from agentflow.core.evidence import read_evidence
from agentflow.storage import (
    ExperimentRepository,
    RunRepository,
    get_db_session,
    init_db,
)

router = APIRouter()

try:
    init_db()
except Exception as e:  # pragma: no cover
    print(f"Database initialization warning: {e}")


def _run_error_types(runs) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for run in runs:
        for step in run.step_results:
            key = step.error_type or ("failed" if step.error else None)
            if key:
                counts[key] = counts.get(key, 0) + 1
    return counts


def _metrics(runs) -> Dict[str, Any]:
    cases = len(runs)
    completed = sum(1 for run in runs if run.status.value == "completed")
    failed = sum(1 for run in runs if run.status.value == "failed")
    partial = sum(1 for run in runs if run.status.value == "partial")
    stopped = sum(1 for run in runs if run.status.value == "stopped")
    scored = [run for run in runs if run.score is not None]
    # 通过率口径：只有 completed 且 passed 才计为通过；partial/stopped/failed 即使带分数也不算
    passed = sum(1 for run in runs if run.status.value == "completed" and run.passed is True)
    missing_score = sum(1 for run in runs if run.score_status in ("missing_score", "scoring_error", "judge_disabled", "budget_exhausted"))
    scores = [float(run.score) for run in scored]
    return {
        "cases": cases,
        "completed": completed,
        "failed": failed,
        "partial": partial,
        "stopped": stopped,
        "passed": passed,
        "pass_rate_all_cases": round(passed / cases, 6) if cases else None,
        "scored": len(scored),
        "mean_score": round(sum(scores) / len(scores), 6) if scores else None,
        "missing_or_failed_score": missing_score,
        "total_tokens": sum(int(run.total_tokens or 0) for run in runs),
        "total_seconds": round(sum(float(run.total_duration or 0.0) for run in runs), 3),
        "trace_id_present": sum(1 for run in runs if run.trace_id),
        "failure_types": _run_error_types(runs),
    }


def _candidate_payload(candidate, runs) -> Dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "name": candidate.name,
        "fingerprint": candidate.fingerprint,
        "config": candidate.config_json or {},
        "created_at": candidate.created_at,
        "metrics": _metrics(runs),
    }


def _experiment_payload(db: Session, experiment) -> Dict[str, Any]:
    candidates = ExperimentRepository.list_candidates(db, experiment.experiment_id)
    runs = RunRepository.list_runs(
        db, experiment_id=experiment.experiment_id, limit=500, offset=0
    )
    runs_by_candidate: Dict[str, List[Any]] = {}
    for run in runs:
        runs_by_candidate.setdefault(run.candidate_id or "unknown", []).append(run)

    candidate_payloads = [
        _candidate_payload(candidate, runs_by_candidate.get(candidate.candidate_id, []))
        for candidate in candidates
    ]

    case_ids = sorted({run.case_id for run in runs if run.case_id})
    matrix = []
    for case_id in case_ids:
        cells = {}
        for candidate in candidates:
            candidate_runs = [
                run for run in runs_by_candidate.get(candidate.candidate_id, [])
                if run.case_id == case_id
            ]
            run = candidate_runs[-1] if candidate_runs else None
            if run is None:
                cells[candidate.candidate_id] = None
                continue
            error_type = next(
                (step.error_type for step in run.step_results if step.error_type and step.error), None
            )
            cells[candidate.candidate_id] = {
                "run_id": run.run_id,
                "status": run.status.value,
                "score": run.score,
                "passed": run.passed,
                "score_status": run.score_status,
                "score_source": run.score_source,
                "trace_id": run.trace_id,
                "evidence_ref": run.evidence_ref,
                "tokens": run.total_tokens,
                "error_type": error_type,
            }
        matrix.append({"case_id": case_id, "candidates": cells})

    return {
        "experiment": {
            "experiment_id": experiment.experiment_id,
            "name": experiment.name,
            "dataset_id": experiment.dataset_id,
            "dataset_version": experiment.dataset_version,
            "scorer_id": experiment.scorer_id,
            "scorer_version": experiment.scorer_version,
            "created_at": experiment.created_at,
            "notes": experiment.notes,
        },
        "candidates": candidate_payloads,
        "cases": matrix,
        "run_count": len(runs),
        "generated_at": time.time(),
    }


@router.get("/experiments")
async def list_experiments(db: Session = Depends(get_db_session)):
    """列出实验及候选/运行数量（只读）"""
    try:
        experiments = ExperimentRepository.list_experiments(db)
        payload = []
        for experiment in experiments:
            candidates = ExperimentRepository.list_candidates(db, experiment.experiment_id)
            runs = RunRepository.list_runs(
                db, experiment_id=experiment.experiment_id, limit=500, offset=0
            )
            payload.append(
                {
                    "experiment_id": experiment.experiment_id,
                    "name": experiment.name,
                    "dataset_id": experiment.dataset_id,
                    "dataset_version": experiment.dataset_version,
                    "scorer_id": experiment.scorer_id,
                    "scorer_version": experiment.scorer_version,
                    "created_at": experiment.created_at,
                    "candidate_count": len(candidates),
                    "run_count": len(runs),
                }
            )
        return {"experiments": payload}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/experiments/{experiment_id}")
async def get_experiment(experiment_id: str, db: Session = Depends(get_db_session)):
    """实验详情：候选对比 + case × 候选矩阵（只读）"""
    try:
        experiment = ExperimentRepository.get_experiment(db, experiment_id)
        if not experiment:
            raise HTTPException(status_code=404, detail="Experiment not found")
        return _experiment_payload(db, experiment)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/experiments/{experiment_id}/report")
async def get_experiment_report(experiment_id: str, db: Session = Depends(get_db_session)):
    """候选对比报告数据（与详情同结构，便于导出）"""
    return await get_experiment(experiment_id, db)


@router.get("/evidence/{run_id}")
async def get_evidence(run_id: str, db: Session = Depends(get_db_session)):
    """读取某次运行的脱敏证据（默认关闭；无证据返回 404）"""
    try:
        run = RunRepository.get_run(db, run_id)
    finally:
        db.close()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not run.evidence_ref:
        raise HTTPException(status_code=404, detail="No evidence captured for this run")
    try:
        return read_evidence(run.evidence_ref)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Evidence file not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
