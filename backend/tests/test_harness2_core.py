"""
Harness²-lite 核心：配置指纹 / 证据包 / 独立评分 / 实验 API 的离线测试。
"""
import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agentflow.adapters.base import LLMAdapter
from agentflow.agents.llm_agent import LLMAgent
from agentflow.api.app import app
from agentflow.api.routes import workflow as workflow_routes
from agentflow.core.agent import AgentConfig, AgentRole
from agentflow.core.evidence import (
    build_evidence,
    evidence_root,
    prune_evidence,
    read_evidence,
    write_evidence,
)
from agentflow.core.fingerprint import compute_fingerprint
from agentflow.core.judge import JudgeBudget, judge_case
from agentflow.core.workflow import WorkflowConfig, WorkflowExecutor, WorkflowPattern, WorkflowStep
from agentflow.storage import (
    ExperimentRepository,
    RunRepository,
    get_db,
)


class FakeAdapter(LLMAdapter):
    async def complete(self, messages, model, temperature=0.7, max_tokens=2000, **kwargs):
        return {
            "content": "answer " + str(messages[-1]["content"])[:30],
            "model": model,
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        }

    async def stream_complete(self, messages, model, temperature=0.7, max_tokens=2000, **kwargs):
        yield "x"


def build_executor():
    config = WorkflowConfig(
        name="harness candidate",
        pattern=WorkflowPattern.SEQUENTIAL,
        steps=[WorkflowStep(id="step_1", agent_name="worker_1")],
        agents=[AgentConfig(name="worker_1", role=AgentRole.WORKER,
                            system_prompt="you are worker", model="test-model")],
    )
    executor = WorkflowExecutor(config, enable_persistence=True, enable_tracing=False)
    executor.register_agent(LLMAgent(config.agents[0], FakeAdapter()))
    return executor


# ----------------------------------------------------------------- fingerprint
def test_fingerprint_is_stable_and_sensitive():
    dataset = {"dataset_id": "ds", "dataset_version": "1.0"}
    snapshot = {
        "pattern": "sequential",
        "max_iterations": 10,
        "agents": [{"name": "a", "model": "m", "system_prompt": "p", "temperature": 0.7}],
        "steps": [{"id": "s", "agent_name": "a"}],
        "execution_policy": {"max_attempts": 1},
    }
    scorer = {"scorer_id": "rubric", "scorer_version": "2.0"}

    first = compute_fingerprint(dataset=dataset, config_snapshot=snapshot, scorer=scorer)
    second = compute_fingerprint(dataset=dataset, config_snapshot=snapshot, scorer=scorer)
    assert first == second and len(first) == 16


def test_fingerprint_changes_with_prompt_changes_but_not_secrets():
    dataset = {"dataset_id": "ds", "dataset_version": "1.0"}
    base = {
        "pattern": "sequential",
        "agents": [{"name": "a", "model": "m", "system_prompt": "p"}],
        "steps": [{"id": "s", "agent_name": "a"}],
    }
    fp1 = compute_fingerprint(dataset=dataset, config_snapshot=base)
    reordered = dict(base, steps=list(reversed(base["steps"])))
    assert compute_fingerprint(dataset=dataset, config_snapshot=reordered) == fp1

    changed = json.loads(json.dumps(base))
    changed["agents"][0]["system_prompt"] = "p2"
    assert compute_fingerprint(dataset=dataset, config_snapshot=changed) != fp1

    with_key = json.loads(json.dumps(base))
    with_key["agents"][0]["api_key"] = "sk-secret"
    with_key["base_url"] = "https://example.com"
    assert compute_fingerprint(dataset=dataset, config_snapshot=with_key) == fp1


# -------------------------------------------------------------------- evidence
@pytest.fixture
def evidence_dir(monkeypatch):
    path = tempfile.mkdtemp(prefix="agentflow-evidence-")
    monkeypatch.setenv("AGENTFLOW_EVIDENCE_ENABLED", "true")
    monkeypatch.setenv("AGENTFLOW_EVIDENCE_DIR", path)
    monkeypatch.setenv("AGENTFLOW_EVIDENCE_RETENTION_DAYS", "90")
    yield Path(path)


@pytest.mark.asyncio
async def test_evidence_roundtrip_is_redacted(evidence_dir):
    executor = build_executor()
    result = await executor.execute("task", experiment_id="exp-1",
                                    candidate_id="cand-1", case_id="case-1",
                                    fingerprint="f" * 16)
    run = executor.get_run(result["run_id"])
    run.error = "boom sk-abcdefghijklmnop1234567890"
    evidence = build_evidence(
        experiment_id="exp-1", candidate_id="cand-1", case_id="case-1",
        fingerprint="f" * 16, run=run,
        scoring={"score": 0.8, "passed": True, "status": "scored"},
        judge={"status": "scored", "score": 0.9},
    )
    ref = write_evidence(evidence)
    assert ref == "exp-1/cand-1/case-1.json"
    loaded = read_evidence(ref)
    text = json.dumps(loaded, ensure_ascii=False)
    assert "sk-abcdefghijklmnop1234567890" not in text
    assert loaded["experiment_id"] == "exp-1"
    assert loaded["run"]["fingerprint"] == "f" * 16


def test_evidence_disabled_and_path_safety(monkeypatch):
    monkeypatch.setenv("AGENTFLOW_EVIDENCE_ENABLED", "false")
    with pytest.raises(RuntimeError):
        write_evidence({"experiment_id": "e", "candidate_id": "c", "case_id": "x"})

    monkeypatch.setenv("AGENTFLOW_EVIDENCE_ENABLED", "true")
    path = tempfile.mkdtemp(prefix="agentflow-evidence-")
    monkeypatch.setenv("AGENTFLOW_EVIDENCE_DIR", path)
    with pytest.raises(ValueError):
        read_evidence("../outside.json")


def test_evidence_size_cap_and_prune(evidence_dir):
    huge = "x" * 100000
    evidence = {
        "experiment_id": "e", "candidate_id": "c", "case_id": "big",
        "fingerprint": "f" * 16, "run": {"task_input": huge, "step_results": []},
    }
    ref = write_evidence(evidence, max_bytes=5000)
    target = evidence_root() / ref
    assert target.stat().st_size <= 5000

    old = time.time() - 200 * 86400
    os.utime(target, (old, old))
    assert prune_evidence(retention_days=90) >= 1
    assert not target.exists()


# ----------------------------------------------------------------------- judge
@pytest.mark.asyncio
async def test_judge_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AGENTFLOW_EXPERIMENT_LLM_JUDGE", raising=False)
    result = await judge_case(task="t", answer="a", reference_answer="r")
    assert result["status"] == "judge_disabled"


@pytest.mark.asyncio
async def test_judge_scored_normalized_and_budget(monkeypatch):
    monkeypatch.setenv("AGENTFLOW_EXPERIMENT_LLM_JUDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content=json.dumps({"score": 90, "reasoning": "good"})))]
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    budget = JudgeBudget(max_calls=2)

    result = await judge_case(task="t", answer="a", reference_answer="r",
                              rubric={"pass_threshold": 0.75}, client=client, budget=budget)
    assert result["status"] == "scored"
    assert result["score"] == 0.9
    assert result["passed"] is True
    assert budget.used == 1

    second = await judge_case(task="t", answer="a", reference_answer="r",
                              rubric={"pass_threshold": 0.75}, client=client, budget=budget)
    assert second["status"] == "scored"
    third = await judge_case(task="t", answer="a", reference_answer="r", client=client, budget=budget)
    assert third["status"] == "budget_exhausted"


@pytest.mark.asyncio
async def test_judge_error_and_missing_answer(monkeypatch):
    monkeypatch.setenv("AGENTFLOW_EXPERIMENT_LLM_JUDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    async def boom(**kwargs):
        raise RuntimeError("judge unavailable")

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=boom)))
    error = await judge_case(task="t", answer="a", client=client)
    assert error["status"] == "scoring_error"

    missing = await judge_case(task="t", answer="", client=client)
    assert missing["status"] == "missing_score"


# ------------------------------------------------------------------------- API
@pytest.fixture
def client(monkeypatch):
    workflow_routes.workflows.clear()
    monkeypatch.setenv("AGENTFLOW_EVIDENCE_ENABLED", "true")
    with TestClient(app) as test_client:
        yield test_client
    workflow_routes.workflows.clear()


def test_experiment_api_and_evidence_endpoint(client):
    with get_db() as db:
        ExperimentRepository.save_experiment(
            db, experiment_id="exp-api", name="API experiment",
            dataset_id="ds", dataset_version="2.0",
            scorer_id="rubric", scorer_version="2.0",
        )
        ExperimentRepository.save_candidate(
            db, candidate_id="cand-a", experiment_id="exp-api", name="single",
            fingerprint="a" * 16, config_json={"pattern": "sequential"},
        )
        ExperimentRepository.save_candidate(
            db, candidate_id="cand-b", experiment_id="exp-api", name="parallel",
            fingerprint="b" * 16, config_json={"pattern": "parallel"},
        )

    executor = build_executor()
    evidence_refs = {}
    run_ids = []
    for candidate in ("cand-a", "cand-b"):
        result = asyncio.run(executor.execute(
            "task", experiment_id="exp-api", candidate_id=candidate,
            case_id="case-1", fingerprint=candidate[-1] * 16,
        ))
        run_ids.append(result["run_id"])
        with get_db() as db:
            RunRepository.update_scoring(
                db, result["run_id"], score=0.8, passed=True,
                score_status="scored", score_source="deterministic",
            )

    # 给第一条运行写证据并回填引用
    run = executor.get_run(run_ids[0])
    evidence = build_evidence(
        experiment_id="exp-api", candidate_id="cand-a", case_id="case-1",
        fingerprint="a" * 16, run=run,
        scoring={"score": 0.8, "status": "scored"},
    )
    ref = write_evidence(evidence)
    with get_db() as db:
        RunRepository.set_evidence_ref(db, run_ids[0], ref)

    listing = client.get("/api/experiments").json()["experiments"]
    item = next(experiment for experiment in listing if experiment["experiment_id"] == "exp-api")
    assert item["candidate_count"] == 2
    assert item["run_count"] >= 2

    detail = client.get("/api/experiments/exp-api").json()
    assert len(detail["candidates"]) == 2
    metrics = detail["candidates"][0]["metrics"]
    assert metrics["cases"] == 1
    assert metrics["pass_rate_all_cases"] == 1.0
    assert detail["cases"][0]["case_id"] == "case-1"
    assert detail["cases"][0]["candidates"]["cand-a"]["run_id"] == run_ids[0]

    report = client.get("/api/experiments/exp-api/report")
    assert report.status_code == 200
    assert report.json()["experiment"]["experiment_id"] == "exp-api"

    evidence_response = client.get(f"/api/evidence/{run_ids[0]}")
    assert evidence_response.status_code == 200
    assert evidence_response.json()["experiment_id"] == "exp-api"
    assert client.get(f"/api/evidence/{run_ids[1]}").status_code == 404

    filtered = client.get("/api/runs", params={"experiment_id": "exp-api", "candidate_id": "cand-a"})
    assert filtered.status_code == 200
    assert all(run["candidate_id"] == "cand-a" for run in filtered.json()["runs"])

    assert client.get("/api/experiments/missing").status_code == 404


def test_metrics_do_not_count_partial_as_passed():
    from agentflow.api.routes.experiments import _metrics

    partial_run = SimpleNamespace(
        status=SimpleNamespace(value="partial"),
        score=0.9,
        passed=True,
        total_tokens=10,
        total_duration=0.5,
        trace_id=None,
        score_status="scored",
        step_results=[],
    )
    completed_run = SimpleNamespace(
        status=SimpleNamespace(value="completed"),
        score=0.8,
        passed=True,
        total_tokens=10,
        total_duration=0.5,
        trace_id="t" * 32,
        score_status="scored",
        step_results=[],
    )
    metrics = _metrics([partial_run, completed_run])
    assert metrics["completed"] == 1
    assert metrics["partial"] == 1
    assert metrics["passed"] == 1, "partial 运行即使 passed=True 也不能计入通过率"
    assert metrics["pass_rate_all_cases"] == 0.5
