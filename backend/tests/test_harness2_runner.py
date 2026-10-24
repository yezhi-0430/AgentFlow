# -*- coding: utf-8 -*-
"""Harness²-lite 实验 runner + 候选对比报告的离线测试。

覆盖（全部使用 tmp 目录 / 确定性假适配器，不联网、不调用付费模型）：
- 实验/候选/运行记录落库，候选指纹稳定且与密钥无关；
- deterministic rubric 分数与 passed 持久化（分母为全部 case）；
- 独立 judge 默认零调用、显式门禁、预算与失败/缺失记录（不冒充通过）；
- 证据默认关闭；--evidence / 环境变量开启时写入并回填 evidence_ref、按保留期清理一次；
- 报告字段、候选表、case×候选矩阵、分母口径、样本限制、无密钥/base_url；
- 真实模型门禁默认拒绝。
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
RUNNER_PATH = BACKEND_DIR / "scripts" / "run_experiment.py"
REPORT_BUILDER_PATH = PROJECT_ROOT / "experiments" / "build_harness2_report.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_module("agentflow_run_experiment_h2", RUNNER_PATH)
report_builder = _load_module("agentflow_build_harness2_report", REPORT_BUILDER_PATH)

DATASET_ID = "test-dataset"
DATASET_VERSION = "1.0.0"
DEFAULT_TASKS = {
    "case-001": "请复述关键词：alpha",
    "case-002": "请复述关键词：beta",
    "case-003": "请复述关键词：gamma",
}


# ---------------------------------------------------------------------------
# 测试数据 / 工具
# ---------------------------------------------------------------------------

def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _answers_for(case_ids=("case-001", "case-002")) -> dict:
    answers = []
    for case_id in case_ids:
        keyword = {"case-001": "alpha", "case-002": "beta", "case-003": "gamma"}[case_id]
        answers.append(
            {
                "case_id": case_id,
                "reference_answer": keyword,
                "pass_threshold": 0.75,
                "rubric": [
                    {
                        "item_id": "r1",
                        "description": f"复述关键词 {keyword}",
                        "any_of": [keyword],
                        "weight": 1,
                        "critical": True,
                    }
                ],
            }
        )
    return {
        "dataset_id": DATASET_ID,
        "dataset_version": DATASET_VERSION,
        "scorer_version": runner.SCORER_VERSION,
        "answers": answers,
    }


def _configs_document() -> dict:
    return {
        "config_version": "1.0.0",
        "configs": {
            "single": {
                "pattern": "single",
                "engine_pattern": "sequential",
                "steps": [
                    {"step_id": "answer", "agent_name": "solver", "system_prompt": "你是测试助手。"}
                ],
            },
            "sequential": {
                "pattern": "sequential",
                "engine_pattern": "sequential",
                "steps": [
                    {"step_id": "draft", "agent_name": "drafter", "system_prompt": "你是起草员。"},
                    {"step_id": "review", "agent_name": "reviewer", "system_prompt": "你是复核员。"},
                ],
            },
            "parallel": {
                "pattern": "parallel",
                "engine_pattern": "parallel",
                "steps": [
                    {"step_id": "answer_a", "agent_name": "solver_a", "system_prompt": "助手 A。"},
                    {"step_id": "answer_b", "agent_name": "solver_b", "system_prompt": "助手 B。"},
                ],
            },
        },
    }


def _write_experiment_files(
    tmp_path: Path,
    *,
    cases=None,
    answers=None,
    configs=None,
):
    dataset_cases = cases or [
        {"case_id": case_id, "task": task} for case_id, task in DEFAULT_TASKS.items()
    ]
    case_ids = [case["case_id"] for case in dataset_cases]
    default_answer_ids = tuple(case_ids[:2] if len(case_ids) > 2 else case_ids)
    dataset = {
        "dataset_id": DATASET_ID,
        "dataset_version": DATASET_VERSION,
        "answers_file": "expected_answers.json",
        "cases": dataset_cases,
    }
    dataset_path = _write_json(tmp_path / "dataset.json", dataset)
    answers_path = _write_json(
        tmp_path / "expected_answers.json",
        answers if answers is not None else _answers_for(default_answer_ids),
    )
    configs_path = _write_json(
        tmp_path / "configs.json", configs if configs is not None else _configs_document()
    )
    return dataset_path, answers_path, configs_path


def _run(tmp_path: Path, *, configs="single", judge=None, evidence=False, judge_budget=None,
         experiment_name=None, persist=True, cases=None, answers=None, limit=None):
    dataset_path, answers_path, configs_path = _write_experiment_files(
        tmp_path, cases=cases, answers=answers
    )
    kwargs = dict(
        configs=configs,
        dataset_path=dataset_path,
        answers_path=answers_path,
        configs_path=configs_path,
        adapter_mode="fake",
        evidence=evidence,
        persist=persist,
    )
    if judge is not None:
        kwargs["judge"] = judge
    if judge_budget is not None:
        kwargs["judge_budget"] = judge_budget
    if experiment_name is not None:
        kwargs["experiment_name"] = experiment_name
    if limit is not None:
        kwargs["limit"] = limit
    return runner.run_experiment(**kwargs)


def _db_runs(experiment_id: str):
    from agentflow.storage import RunRepository, get_db

    with get_db() as db:
        return RunRepository.list_runs(db, experiment_id=experiment_id, limit=500, offset=0)


def _db_experiment(experiment_id: str):
    from agentflow.storage import ExperimentRepository, get_db

    with get_db() as db:
        model = ExperimentRepository.get_experiment(db, experiment_id)
        if model is None:
            return None
        # 在 session 内取值，避免 ORM 实例 detach 后属性过期
        return {
            "experiment_id": model.experiment_id,
            "name": model.name,
            "dataset_id": model.dataset_id,
            "dataset_version": model.dataset_version,
            "scorer_id": model.scorer_id,
            "scorer_version": model.scorer_version,
            "notes": model.notes,
        }


def _db_candidates(experiment_id: str):
    from agentflow.storage import ExperimentRepository, get_db

    with get_db() as db:
        models = ExperimentRepository.list_candidates(db, experiment_id)
        return [
            {
                "candidate_id": model.candidate_id,
                "experiment_id": model.experiment_id,
                "name": model.name,
                "fingerprint": model.fingerprint,
                "config_json": model.config_json,
            }
            for model in models
        ]


def _case(doc, case_id="case-001", config_name=None):
    experiments = doc["experiments"]
    if config_name is not None:
        experiments = [exp for exp in experiments if exp["config_name"] == config_name]
    for case in experiments[0]["cases"]:
        if case["case_id"] == case_id:
            return case
    raise AssertionError(f"case {case_id} 不存在")


@pytest.fixture(autouse=True)
def _offline_env(monkeypatch, tmp_path):
    """默认离线：无证据、无 judge 门禁、无真实模型密钥。"""
    monkeypatch.setenv(runner.EVIDENCE_ENABLED_ENV, "false")
    monkeypatch.delenv(runner.EVIDENCE_DIR_ENV, raising=False)
    monkeypatch.delenv(runner.LLM_JUDGE_ENABLED_ENV, raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AGENTFLOW_JUDGE_MAX_CALLS", raising=False)
    monkeypatch.delenv(runner.REAL_ENABLED_ENV, raising=False)
    yield


# ---------------------------------------------------------------------------
# 实验/候选/运行记录持久化
# ---------------------------------------------------------------------------

def test_default_run_persists_experiment_candidates_and_runs(tmp_path):
    doc = _run(tmp_path, configs="all")
    harness2 = doc["harness2"]

    assert harness2["persisted"] is True
    assert harness2["experiment_id"].startswith("harness2-")
    assert len(harness2["candidates"]) == 3
    fingerprints = {entry["config_name"]: entry["fingerprint"] for entry in harness2["candidates"]}
    assert set(fingerprints) == {"single", "sequential", "parallel"}
    assert len(set(fingerprints.values())) == 3
    for fingerprint in fingerprints.values():
        assert len(fingerprint) == 16
        int(fingerprint, 16)  # 合法 hex

    experiment = _db_experiment(harness2["experiment_id"])
    assert experiment is not None
    assert experiment["name"] == harness2["experiment_name"]
    assert experiment["dataset_id"] == DATASET_ID
    assert experiment["dataset_version"] == DATASET_VERSION
    assert experiment["scorer_id"] == runner.SCORER_ID
    assert experiment["scorer_version"] == runner.SCORER_VERSION

    candidates = _db_candidates(harness2["experiment_id"])
    assert len(candidates) == 3
    assert {candidate["name"] for candidate in candidates} == {"single", "sequential", "parallel"}
    by_name = {candidate["name"]: candidate for candidate in candidates}
    for name, candidate in by_name.items():
        assert candidate["fingerprint"] == fingerprints[name]
        config_text = json.dumps(candidate["config_json"], ensure_ascii=False)
        assert "api_key" not in config_text and "base_url" not in config_text

    runs = _db_runs(harness2["experiment_id"])
    assert len(runs) == 3 * 3  # 3 候选 × 3 case
    for run in runs:
        assert run.experiment_id == harness2["experiment_id"]
        assert run.case_id in DEFAULT_TASKS
        assert run.candidate_id in {entry["candidate_id"] for entry in harness2["candidates"]}
        assert run.fingerprint in set(fingerprints.values())

    # 每个候选的 case 记录都带 fingerprint / candidate_id
    for experiment_payload in doc["experiments"]:
        assert experiment_payload["candidate_id"]
        assert experiment_payload["fingerprint"] in set(fingerprints.values())
        for case in experiment_payload["cases"]:
            assert case["experiment_id"] == harness2["experiment_id"]
            assert case["candidate_id"] == experiment_payload["candidate_id"]
            assert case["fingerprint"] == experiment_payload["fingerprint"]


def test_fingerprint_is_stable_and_independent_of_secrets(tmp_path):
    dataset = {"dataset_id": DATASET_ID, "dataset_version": DATASET_VERSION}
    scorer = {
        "scorer_id": runner.SCORER_ID,
        "scorer_version": runner.SCORER_VERSION,
        "mode": "deterministic",
    }
    configs = runner.load_configs(_write_experiment_files(tmp_path)[2])
    config_def = configs["configs"]["single"]

    base = runner.build_candidate_fingerprint(
        "single", config_def, dataset=dataset, scorer=scorer,
        connection={"provider": "fake"},
    )
    assert len(base) == 16
    assert base == runner.build_candidate_fingerprint(
        "single", config_def, dataset=dataset, scorer=scorer,
        connection={"provider": "fake"},
    )
    # 密钥/base_url 不参与指纹
    with_secrets = runner.build_candidate_fingerprint(
        "single", config_def, dataset=dataset, scorer=scorer,
        connection={
            "provider": "fake",
            "api_key": "sk-test-not-a-real-key-123456",
            "base_url": "https://example.invalid/v1",
        },
    )
    assert with_secrets == base

    # 提示词改动会改变指纹
    changed = json.loads(json.dumps(config_def))
    changed["steps"][0]["system_prompt"] = changed["steps"][0]["system_prompt"] + "只输出结论。"
    assert runner.build_candidate_fingerprint(
        "single", changed, dataset=dataset, scorer=scorer, connection={"provider": "fake"}
    ) != base

    # 两次运行同一配置的候选指纹一致（实验 id 不同）
    first = _run(tmp_path / "run1")
    second = _run(tmp_path / "run2")
    first_fp = {(entry["config_name"]): entry["fingerprint"] for entry in first["harness2"]["candidates"]}
    second_fp = {(entry["config_name"]): entry["fingerprint"] for entry in second["harness2"]["candidates"]}
    assert first["harness2"]["experiment_id"] != second["harness2"]["experiment_id"]
    assert first_fp == second_fp


def test_scoring_and_passed_are_persisted(tmp_path):
    doc = _run(tmp_path)  # 3 case：前两个有答案，第三个 missing_score
    experiment_id = doc["harness2"]["experiment_id"]
    runs = {run.case_id: run for run in _db_runs(experiment_id)}
    assert set(runs) == set(DEFAULT_TASKS)

    for case_id in ("case-001", "case-002"):
        run = runs[case_id]
        assert run.score == 1.0
        assert run.passed is True
        assert run.score_status == "scored"
        assert run.score_source == "deterministic"

    missing = runs["case-003"]
    assert missing.score is None
    assert missing.passed is None
    assert missing.score_status == "missing_score"
    assert missing.evidence_ref is None

    metrics = doc["experiments"][0]["metrics"]["quality"]
    assert metrics["passed_count"] == 2
    assert metrics["pass_rate_all_cases"] == round(2 / 3, 4)
    assert metrics["missing_score_count"] == 1


def test_persistence_can_be_disabled(tmp_path):
    doc = _run(tmp_path, persist=False)
    assert doc["harness2"]["persisted"] is False
    assert _db_experiment(doc["harness2"]["experiment_id"]) is None
    case = _case(doc)
    assert case["candidate_id"]
    assert case["fingerprint"]
    assert case["score_status"] == "scored"
    assert case["score_source"] == "deterministic"


# ---------------------------------------------------------------------------
# 独立 judge：默认关闭 / 门禁 / 预算 / 失败
# ---------------------------------------------------------------------------

def test_judge_not_called_by_default(tmp_path, monkeypatch):
    calls = []

    async def _should_not_be_called(**kwargs):
        calls.append(kwargs)
        raise AssertionError("deterministic 模式不应调用独立 judge")

    monkeypatch.setattr(runner, "judge_case", _should_not_be_called)
    doc = _run(tmp_path)
    assert calls == []
    assert doc["harness2"]["judge"]["independent_judge_enabled"] is False
    assert all(case["judge_status"] is None for case in doc["experiments"][0]["cases"])


def test_judge_llm_scored_and_budget_exhausted(tmp_path, monkeypatch):
    monkeypatch.setenv(runner.LLM_JUDGE_ENABLED_ENV, "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-a-real-key")
    cases = [
        {"case_id": "case-001", "task": DEFAULT_TASKS["case-001"]},
        {"case_id": "case-002", "task": DEFAULT_TASKS["case-002"]},
    ]
    doc = _run(tmp_path, judge="llm", judge_budget=1, cases=cases)
    experiment = doc["experiments"][0]
    case_records = {case["case_id"]: case for case in experiment["cases"]}

    first = case_records["case-001"]
    second = case_records["case-002"]
    assert first["independent_judge"]["status"] == "scored"
    assert first["independent_judge"]["score"] == 1.0
    assert first["independent_judge"]["agreement_with_deterministic"] is True
    assert second["independent_judge"]["status"] == "budget_exhausted"
    # 主评分（deterministic rubric）不受 judge 预算影响
    assert first["score_status"] == "scored" and first["score"]["passed"] is True
    assert second["score_status"] == "scored" and second["score"]["passed"] is True
    assert doc["harness2"]["judge"]["budget"]["max_calls"] == 1
    assert doc["harness2"]["judge"]["budget"]["used"] == 1
    assert experiment["metrics"]["harness2"]["judge_failure_count"] == 1


def test_judge_failure_cannot_fake_pass(tmp_path, monkeypatch):
    monkeypatch.setenv(runner.LLM_JUDGE_ENABLED_ENV, "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-a-real-key")

    async def _failed_judge(**kwargs):
        return {"status": "scoring_error", "error": "judge unavailable"}

    monkeypatch.setattr(runner, "judge_case", _failed_judge)
    answers = _answers_for(("case-001",))
    # rubric 要求不存在的短语 → 主评分判不通过
    answers["answers"][0]["rubric"][0]["any_of"] = ["不存在的短语-zzz"]
    doc = _run(tmp_path, judge="llm", answers=answers)
    case = _case(doc)

    assert case["status"] == "completed"
    assert case["score_status"] == "scored"
    assert case["score"]["passed"] is False
    assert case["independent_judge"]["status"] == "scoring_error"
    assert case["judge_status"] == "scoring_error"
    assert doc["experiments"][0]["metrics"]["quality"]["passed_count"] == 0
    assert doc["experiments"][0]["metrics"]["harness2"]["judge_failure_count"] == 1


def test_judge_llm_requires_explicit_gate_in_harness2_runner(tmp_path):
    with pytest.raises(runner.ExperimentConfigError):
        _run(tmp_path, judge="llm")


# ---------------------------------------------------------------------------
# 证据包：默认关闭 / 开启写入 / 脱敏 / 保留期清理
# ---------------------------------------------------------------------------

def test_evidence_disabled_by_default(tmp_path, monkeypatch):
    evidence_dir = tmp_path / "evidence"
    monkeypatch.setenv(runner.EVIDENCE_DIR_ENV, str(evidence_dir))
    calls = []
    monkeypatch.setattr(runner, "prune_evidence", lambda *a, **k: calls.append(1) or 0)

    doc = _run(tmp_path)
    assert doc["harness2"]["evidence"]["enabled"] is False
    assert doc["harness2"]["evidence"]["written_count"] == 0
    assert _case(doc)["evidence_ref"] is None
    assert not evidence_dir.exists() or not list(evidence_dir.rglob("*.json"))
    assert calls == []  # 未开启证据不触发清理


def test_evidence_enabled_writes_redacted_bundle_and_links_run(tmp_path, monkeypatch):
    from agentflow.core.evidence import read_evidence

    evidence_dir = tmp_path / "evidence"
    monkeypatch.setenv(runner.EVIDENCE_DIR_ENV, str(evidence_dir))
    prune_calls = []
    real_prune = runner.prune_evidence

    def _counting_prune(*args, **kwargs):
        prune_calls.append(1)
        return real_prune(*args, **kwargs)

    monkeypatch.setattr(runner, "prune_evidence", _counting_prune)

    doc = _run(tmp_path, evidence=True)
    harness2 = doc["harness2"]
    assert harness2["evidence"]["enabled"] is True
    assert harness2["evidence"]["written_count"] == 3
    assert harness2["evidence"]["retention_days"] == 90
    assert len(prune_calls) == 1  # 每个实验结束清理一次

    case = _case(doc)
    ref = case["evidence_ref"]
    assert ref == f"{harness2['experiment_id']}/{case['candidate_id']}/case-001.json"
    evidence = read_evidence(ref)
    assert evidence["experiment_id"] == harness2["experiment_id"]
    assert evidence["candidate_id"] == case["candidate_id"]
    assert evidence["fingerprint"] == case["fingerprint"]
    assert evidence["run"]["fingerprint"] == case["fingerprint"]
    assert evidence["scoring"]["score_status"] == "scored"

    text = json.dumps(evidence, ensure_ascii=False)
    for forbidden in ("api_key", "base_url", "sk-", "Bearer "):
        assert forbidden not in text

    runs = {run.case_id: run for run in _db_runs(harness2["experiment_id"])}
    assert runs["case-001"].evidence_ref == ref


def test_evidence_env_can_enable_without_flag(tmp_path, monkeypatch):
    evidence_dir = tmp_path / "evidence"
    monkeypatch.setenv(runner.EVIDENCE_ENABLED_ENV, "true")
    monkeypatch.setenv(runner.EVIDENCE_DIR_ENV, str(evidence_dir))

    doc = _run(tmp_path, evidence=False)
    assert doc["harness2"]["evidence"]["enabled"] is True
    assert doc["harness2"]["evidence"]["written_count"] == 3
    assert _case(doc)["evidence_ref"]


# ---------------------------------------------------------------------------
# 报告：字段 / 分母 / 矩阵 / 限制 / 无密钥
# ---------------------------------------------------------------------------

def test_report_fields_and_denominator(tmp_path):
    doc = _run(tmp_path, configs="all")
    report = report_builder.build_report(doc)

    experiment = report["experiment"]
    assert experiment["experiment_id"] == doc["harness2"]["experiment_id"]
    assert experiment["dataset"]["id"] == DATASET_ID
    assert experiment["dataset"]["version"] == DATASET_VERSION
    assert experiment["scorer"]["version"] == runner.SCORER_VERSION
    assert experiment["adapter"]["mode"] == "fake"
    assert experiment["adapter"]["network"] is False
    assert experiment["judge"]["mode"] == "deterministic"
    assert experiment["tracing"]["enabled"] is False
    assert experiment["evidence"]["enabled"] is False

    candidates = report["candidates"]
    assert len(candidates) == 3
    for candidate in candidates:
        assert candidate["cases"] == 3
        assert candidate["completed"] == 3
        assert candidate["failed"] == 0
        assert candidate["passed"] == 2
        assert candidate["pass_rate_all_cases"] == round(2 / 3, 6)
        assert candidate["mean_score"] == 1.0
        assert candidate["mean_score_all_cases"] == round(2 / 3, 6)
        assert candidate["total_tokens"] > 0
        assert candidate["total_seconds"] >= 0
        assert candidate["trace_id_present"] == 0
        assert candidate["fingerprint"] and len(candidate["fingerprint"]) == 16
        assert candidate["score_sources"] == ["deterministic"]

    matrix = report["case_matrix"]
    assert [row["case_id"] for row in matrix] == ["case-001", "case-002", "case-003"]
    for row in matrix:
        assert set(row["candidates"]) == {"single", "sequential", "parallel"}
        for cell in row["candidates"].values():
            assert {"status", "score", "score_status", "trace_id", "evidence_ref"} <= set(cell)
    assert matrix[0]["candidates"]["single"]["score"] == 1.0
    assert matrix[2]["candidates"]["single"]["score"] is None
    assert matrix[2]["candidates"]["single"]["score_status"] == "missing_score"

    limitations = "\n".join(report["limitations"])
    assert "3 个固定 case" in limitations
    assert "单轮执行" in limitations
    assert "分母始终是全部 case" in limitations
    assert report["scoring"]["denominator"].startswith("全部 case")
    assert report["verification"]["fake_only"] is True
    assert report["verification"]["secret_scan"] == "passed"


def test_report_markdown_no_secrets(tmp_path, monkeypatch):
    evidence_dir = tmp_path / "evidence"
    monkeypatch.setenv(runner.EVIDENCE_DIR_ENV, str(evidence_dir))
    doc = _run(tmp_path, evidence=True)
    results_path = _write_json(tmp_path / "results.json", doc)
    markdown_path = tmp_path / "HARNESS2_COMPARISON.md"
    report_builder.write_report(results_path, markdown_path)

    assert results_path.is_file() and markdown_path.is_file()
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "# Harness²-lite 候选对比报告" in markdown
    assert "候选对比表" in markdown
    assert "case × 候选矩阵" in markdown
    assert "样本限制" in markdown
    assert "复现命令" in markdown
    for forbidden in ("api_key", "base_url", "sk-", "Bearer "):
        assert forbidden not in markdown
    enriched = json.loads(results_path.read_text(encoding="utf-8"))
    assert "report" in enriched
    assert enriched["report"]["experiment"]["experiment_id"] == doc["harness2"]["experiment_id"]
    assert evidence_dir.exists()


def test_report_rejects_non_fake_results_and_secrets():
    clean_doc = {
        "adapter": {"mode": "fake", "network": False, "deterministic": True},
        "experiments": [
            {
                "config_name": "single",
                "cases": [
                    {
                        "case_id": "c1",
                        "status": "completed",
                        "score": {"score": 1.0, "passed": True},
                        "score_status": "scored",
                        "score_source": "deterministic",
                    }
                ],
            }
        ],
        "harness2": {
            "experiment_id": "harness2-test",
            "evidence": {"enabled": False},
            "judge": {"mode": "deterministic"},
        },
    }
    report = report_builder.build_report(clean_doc)
    assert report["candidates"][0]["pass_rate_all_cases"] == 1.0

    real_doc = json.loads(json.dumps(clean_doc))
    real_doc["adapter"].update({"mode": "real", "network": True, "deterministic": False})
    with pytest.raises(report_builder.ReportError):
        report_builder.build_report(real_doc)
    assert report_builder.build_report(real_doc, allow_real=True)["verification"]["fake_only"] is False

    leaky_doc = json.loads(json.dumps(clean_doc))
    leaky_doc["adapter"]["api_key"] = "sk-test-not-a-real-key-123456"
    with pytest.raises(report_builder.ReportError):
        report_builder.build_report(leaky_doc)


# ---------------------------------------------------------------------------
# CLI / 真实模型门禁
# ---------------------------------------------------------------------------

def test_cli_harness2_flags(tmp_path, monkeypatch):
    evidence_dir = tmp_path / "evidence"
    monkeypatch.setenv(runner.EVIDENCE_DIR_ENV, str(evidence_dir))
    dataset_path, answers_path, configs_path = _write_experiment_files(tmp_path)
    output_path = tmp_path / "out" / "result.json"

    exit_code = runner.main(
        [
            "--config",
            "single",
            "--limit",
            "1",
            "--dataset",
            str(dataset_path),
            "--answers",
            str(answers_path),
            "--configs",
            str(configs_path),
            "--experiment-name",
            "cli harness2",
            "--evidence",
            "--judge-budget",
            "3",
            "--output",
            str(output_path),
        ]
    )
    assert exit_code == 0
    document = json.loads(output_path.read_text(encoding="utf-8"))
    assert document["harness2"]["experiment_name"] == "cli harness2"
    assert document["harness2"]["evidence"]["enabled"] is True
    assert document["harness2"]["judge"]["budget"]["max_calls"] == 3
    assert document["dataset"]["case_count"] == 1


def test_real_model_requires_gate(tmp_path, monkeypatch):
    monkeypatch.delenv(runner.REAL_ENABLED_ENV, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    dataset_path, answers_path, configs_path = _write_experiment_files(tmp_path)
    with pytest.raises(runner.ExperimentConfigError):
        runner.run_experiment(
            configs="single",
            dataset_path=dataset_path,
            answers_path=answers_path,
            configs_path=configs_path,
            adapter_mode="real",
            real_model="fake-model-name",
        )
