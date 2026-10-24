# -*- coding: utf-8 -*-
"""实验运行器离线测试：使用 tmp 目录与确定性假适配器，不调用真实模型、不联网。

覆盖：
- runner v2 的 CLI/配置/limit/judge 选择；
- 数据集答案隔离、评分失败 vs 缺失评分分别记录；
- rubric v2 的 critical 校准；
- 后端 v3 的 trace_id / attempts / error_type 映射字段；
- 默认不调用真实模型、LLM judge 显式门禁。
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
RUNNER_PATH = BACKEND_DIR / "scripts" / "run_experiment.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("agentflow_run_experiment", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_runner()


DEFAULT_CASE_ID = "test-001"
DEFAULT_TASK = "请复述关键词：alpha"


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _default_answers() -> dict:
    return {
        "dataset_id": "test-dataset",
        "dataset_version": "1.0.0",
        "scorer_version": runner.SCORER_VERSION,
        "answers": [
            {
                "case_id": DEFAULT_CASE_ID,
                "reference_answer": "alpha",
                "pass_threshold": 0.75,
                "calibration_note": "单条目 rubric：命中 alpha 即通过。",
                "rubric": [
                    {
                        "item_id": "r1",
                        "description": "复述关键词 alpha",
                        "any_of": ["alpha"],
                        "weight": 1,
                        "critical": True,
                    }
                ],
            }
        ],
    }


def _configs_document() -> dict:
    return {
        "config_version": "1.0.0",
        "configs": {
            "single": {
                "pattern": "single",
                "engine_pattern": "sequential",
                "steps": [
                    {
                        "step_id": "answer",
                        "agent_name": "solver",
                        "system_prompt": "你是测试助手。",
                    }
                ],
            },
            "sequential": {
                "pattern": "sequential",
                "engine_pattern": "sequential",
                "steps": [
                    {
                        "step_id": "draft",
                        "agent_name": "drafter",
                        "system_prompt": "你是起草员。",
                    },
                    {
                        "step_id": "review",
                        "agent_name": "reviewer",
                        "system_prompt": "你是复核员。",
                    },
                ],
            },
            "parallel": {
                "pattern": "parallel",
                "engine_pattern": "parallel",
                "steps": [
                    {
                        "step_id": "answer_a",
                        "agent_name": "solver_a",
                        "system_prompt": "你是答题助手 A。",
                    },
                    {
                        "step_id": "answer_b",
                        "agent_name": "solver_b",
                        "system_prompt": "你是答题助手 B。",
                    },
                ],
            },
        },
    }


def _write_experiment_files(tmp_path: Path, answers=None, cases=None, configs=None):
    dataset = {
        "dataset_id": "test-dataset",
        "dataset_version": "1.0.0",
        "answers_file": "expected_answers.json",
        "cases": cases or [{"case_id": DEFAULT_CASE_ID, "task": DEFAULT_TASK}],
    }
    dataset_path = _write_json(tmp_path / "dataset.json", dataset)
    answers_path = _write_json(
        tmp_path / "expected_answers.json",
        _default_answers() if answers is None else answers,
    )
    configs_path = _write_json(
        tmp_path / "configs.json",
        _configs_document() if configs is None else configs,
    )
    return dataset_path, answers_path, configs_path


def _run(tmp_path: Path, configs="single", judge=None, tracing=False, **kwargs):
    dataset_path, answers_path, configs_path = _write_experiment_files(tmp_path, **kwargs)
    run_kwargs = {
        "configs": configs,
        "dataset_path": dataset_path,
        "answers_path": answers_path,
        "configs_path": configs_path,
        "adapter_mode": "fake",
    }
    if judge is not None:
        run_kwargs["judge"] = judge
    if tracing:
        run_kwargs["tracing"] = True
    return runner.run_experiment(**run_kwargs)


# ---------------------------------------------------------------------------
# 基础执行与结果结构
# ---------------------------------------------------------------------------

def test_single_config_runs_and_records_required_fields(tmp_path):
    result = _run(tmp_path)

    assert result["adapter"]["mode"] == "fake"
    assert result["adapter"]["network"] is False
    assert result["dataset"]["dataset_version"] == "1.0.0"
    assert result["configs"]["config_version"] == "1.0.0"
    assert result["scorer"]["version"] == runner.SCORER_VERSION
    assert result["judge"]["mode"] == "deterministic"
    assert result["judge"]["network"] is False
    assert result["tracing"]["enabled"] is False

    assert len(result["experiments"]) == 1
    experiment = result["experiments"][0]
    assert experiment["config_name"] == "single"
    assert experiment["engine_pattern"] == "sequential"
    assert experiment["metrics"]["case_count"] == 1

    case = experiment["cases"][0]
    required_fields = {
        "case_id",
        "config",
        "status",
        "run_id",
        "trace_id",
        "trace_id_source",
        "tracing_enabled",
        "elapsed_seconds",
        "total_tokens",
        "usage_type",
        "output",
        "step_results",
        "score",
        "score_status",
        "scoring_error",
        "missing_score",
        "record_schema_version",
        "unknown_usage_step_count",
    }
    assert required_fields <= set(case)
    assert case["case_id"] == DEFAULT_CASE_ID
    assert case["status"] == "completed"
    assert case["failure_reason"] is None
    assert isinstance(case["run_id"], str) and case["run_id"]
    assert case["trace_id"] is None  # 默认不开启追踪
    assert case["trace_id_source"] is None
    assert case["tracing_enabled"] is False
    assert case["elapsed_seconds"] >= 0
    assert case["total_tokens"] > 0
    assert case["record_schema_version"] >= 2
    assert case["unknown_usage_step_count"] == 0
    assert case["usage_type"] in {"actual", "estimated", "partial", "unknown", "mixed"}
    assert "alpha" in case["output"]
    assert case["scoring_error"] is None
    assert case["missing_score"] is False
    assert case["score_status"] == "scored"
    assert case["score"] is not None
    assert case["score"]["passed"] is True
    assert case["score"]["score"] == 1.0
    assert case["score"]["method"] == "deterministic-rubric-v2"

    step = case["step_results"][0]
    required_step_fields = {
        "step_id",
        "step_index",
        "attempts",
        "error_type",
        "model",
        "finish_reason",
        "usage_type",
        "output_excerpt",
    }
    assert required_step_fields <= set(step)
    assert step["status"] == "completed"
    assert step["model"] == runner.ScriptedFakeAdapter.ADAPTER_ID
    assert "alpha" in step["output_excerpt"]
    # 后端 v3 契约：attempts 为 >=1 的整数，error_type 成功时为 None。
    assert isinstance(step["attempts"], int) and step["attempts"] >= 1
    assert step["error_type"] is None

    metrics = experiment["metrics"]
    assert metrics["execution"]["completed_count"] == 1
    assert metrics["execution"]["execution_success_rate"] == 1.0
    assert metrics["execution"]["trace_id_present_count"] == 0
    assert metrics["quality"]["scored_count"] == 1
    assert metrics["quality"]["pass_rate_scored"] == 1.0
    assert metrics["quality"]["pass_rate_all_cases"] == 1.0
    assert metrics["quality"]["judge_disabled_count"] == 0
    assert metrics["timing"]["total_seconds"] >= 0
    assert metrics["tokens"]["total"] > 0
    assert metrics["tokens"]["usage_type_counts"]


@pytest.mark.parametrize("config_name", ["single", "sequential", "parallel"])
def test_each_config_can_run(tmp_path, config_name):
    result = _run(tmp_path, configs=config_name)
    experiment = result["experiments"][0]

    assert experiment["config_name"] == config_name
    case = experiment["cases"][0]
    assert case["status"] == "completed"
    assert case["score"] is not None and case["score"]["passed"] is True
    assert len(case["step_results"]) == len(experiment["steps"])


def test_all_configs_can_run_together(tmp_path):
    result = _run(tmp_path, configs="all")
    assert [experiment["config_name"] for experiment in result["experiments"]] == [
        "single",
        "sequential",
        "parallel",
    ]
    for experiment in result["experiments"]:
        assert experiment["metrics"]["quality"]["pass_rate_all_cases"] == 1.0


def test_limit_only_runs_first_cases(tmp_path):
    cases = [
        {"case_id": "test-001", "task": DEFAULT_TASK},
        {"case_id": "test-002", "task": "请复述关键词：beta"},
    ]
    answers = _default_answers()
    answers["answers"].append(
        {
            "case_id": "test-002",
            "reference_answer": "beta",
            "pass_threshold": 0.75,
            "rubric": [{"item_id": "r1", "any_of": ["beta"], "weight": 1}],
        }
    )
    dataset_path, answers_path, configs_path = _write_experiment_files(
        tmp_path / "limited", cases=cases, answers=answers
    )
    limited = runner.run_experiment(
        configs="single",
        dataset_path=dataset_path,
        answers_path=answers_path,
        configs_path=configs_path,
        limit=1,
        adapter_mode="fake",
    )
    assert limited["dataset"]["case_count"] == 1
    assert limited["dataset"]["full_case_count"] == 2
    assert limited["dataset"]["limit"] == 1
    assert limited["experiments"][0]["metrics"]["case_count"] == 1
    assert limited["experiments"][0]["cases"][0]["case_id"] == "test-001"


def test_fake_adapter_is_deterministic(tmp_path):
    first = _run(tmp_path)
    second = _run(tmp_path)

    first_case = first["experiments"][0]["cases"][0]
    second_case = second["experiments"][0]["cases"][0]
    assert first_case["output"] == second_case["output"]
    assert first_case["total_tokens"] == second_case["total_tokens"]
    assert first_case["score"] == second_case["score"]


# ---------------------------------------------------------------------------
# 评分缺失 / 评分失败 / 结果缺失
# ---------------------------------------------------------------------------

def test_missing_score_is_recorded_separately(tmp_path):
    answers = {
        "dataset_id": "test-dataset",
        "dataset_version": "1.0.0",
        "scorer_version": runner.SCORER_VERSION,
        "answers": [],
    }
    result = _run(tmp_path, answers=answers)
    case = result["experiments"][0]["cases"][0]
    quality = result["experiments"][0]["metrics"]["quality"]

    assert case["missing_score"] is True
    assert case["scoring_error"] is None
    assert case["score"] is None
    assert case["score_status"] == "missing_score"
    assert quality["missing_score_count"] == 1
    assert quality["scoring_error_count"] == 0
    assert quality["judge_disabled_count"] == 0
    assert quality["scored_count"] == 0
    assert quality["passed_count"] == 0
    assert quality["pass_rate_scored"] is None
    assert quality["pass_rate_all_cases"] == 0.0
    assert quality["missing_score_case_ids"] == [DEFAULT_CASE_ID]


def test_scoring_error_is_recorded_separately(tmp_path):
    answers = {
        "dataset_id": "test-dataset",
        "dataset_version": "1.0.0",
        "scorer_version": runner.SCORER_VERSION,
        "answers": [
            {
                "case_id": DEFAULT_CASE_ID,
                "rubric": [{"item_id": "bad", "any_of": []}],
            }
        ],
    }
    result = _run(tmp_path, answers=answers)
    case = result["experiments"][0]["cases"][0]
    quality = result["experiments"][0]["metrics"]["quality"]

    assert case["missing_score"] is False
    assert case["scoring_error"]  # 非空字符串
    assert case["scoring_error_type"] == "deterministic_rubric"
    assert case["score"] is None
    assert case["score_status"] == "scoring_error"
    assert quality["scoring_error_count"] == 1
    assert quality["missing_score_count"] == 0
    assert quality["scored_count"] == 0
    assert quality["pass_rate_scored"] is None
    assert quality["pass_rate_all_cases"] == 0.0
    assert quality["scoring_error_case_ids"] == [DEFAULT_CASE_ID]


def test_missing_final_result_is_marked_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "_extract_output", lambda exec_result, run: ("", None))
    result = _run(tmp_path)
    case = result["experiments"][0]["cases"][0]
    metrics = result["experiments"][0]["metrics"]

    assert case["status"] == "failed"
    assert case["failure_reason"] == "missing_final_result"
    assert case["score"] is None
    assert case["score_status"] == "execution_failed"
    assert metrics["execution"]["failed_count"] == 1
    assert metrics["execution"]["execution_success_rate"] == 0.0
    assert metrics["quality"]["pass_rate_all_cases"] == 0.0
    assert metrics["execution"]["failed_case_ids"] == [DEFAULT_CASE_ID]


def test_failed_execution_is_not_scored_with_fallback_text(tmp_path, monkeypatch):
    """执行失败（引擎回退输出为原始 task）时不能拿回退文本当答案评分。"""

    class FailingAdapter:
        ADAPTER_ID = "failing-fake-v1"
        call_count = 0

        async def complete(self, messages, model, temperature=0.7, max_tokens=2000, **kwargs):
            self.call_count += 1
            raise RuntimeError("simulated provider failure")

        async def stream_complete(self, messages, model, temperature=0.7, max_tokens=2000, **kwargs):
            raise RuntimeError("simulated provider failure")
            yield ""  # pragma: no cover

    monkeypatch.setattr(runner, "ScriptedFakeAdapter", FailingAdapter)
    result = _run(tmp_path)
    case = result["experiments"][0]["cases"][0]
    metrics = result["experiments"][0]["metrics"]

    assert case["status"] == "failed"
    assert case["failure_reason"] == "workflow_failed"
    assert case["score"] is None
    assert case["score_note"] == "execution_failed_no_score"
    assert case["score_status"] == "execution_failed"
    assert case["missing_score"] is False
    assert case["scoring_error"] is None
    assert case["usage_type"] == "unknown"
    assert case["unknown_usage_step_count"] == 1
    assert metrics["execution"]["failed_count"] == 1
    assert metrics["quality"]["scored_count"] == 0
    assert metrics["quality"]["pass_rate_all_cases"] == 0.0
    assert metrics["tokens"]["unknown_usage_step_count"] == 1
    # v3 契约：失败步骤也记录 attempts；error_type 允许为 None 或已分类值。
    assert case["step_results"][0]["attempts"] >= 1
    assert "error_type" in case["step_results"][0]


def test_absent_answers_file_marks_missing_score(tmp_path):
    dataset_path, _, configs_path = _write_experiment_files(tmp_path)
    missing_answers_path = tmp_path / "does-not-exist.json"
    result = runner.run_experiment(
        configs="single",
        dataset_path=dataset_path,
        answers_path=missing_answers_path,
        configs_path=configs_path,
        adapter_mode="fake",
    )
    case = result["experiments"][0]["cases"][0]
    assert result["dataset"]["answers"]["present"] is False
    assert case["missing_score"] is True
    assert case["scoring_error"] is None
    assert case["score"] is None
    assert case["score_status"] == "missing_score"


def test_config_with_unsupported_engine_pattern_is_rejected(tmp_path):
    configs = _configs_document()
    configs["configs"]["single"]["engine_pattern"] = "parallel"
    with pytest.raises(runner.ExperimentConfigError):
        _run(tmp_path, configs=configs)


def test_failed_case_is_included_in_denominator(tmp_path):
    cases = [
        {"case_id": "test-001", "task": DEFAULT_TASK},
        {"case_id": "test-002", "task": "请复述关键词：beta"},
    ]
    answers = _default_answers()
    # test-002 没有预期答案 -> missing_score，不能计入通过
    result = _run(tmp_path, cases=cases, answers=answers)
    metrics = result["experiments"][0]["metrics"]

    assert metrics["case_count"] == 2
    assert metrics["quality"]["scored_count"] == 1
    assert metrics["quality"]["passed_count"] == 1
    assert metrics["quality"]["pass_rate_scored"] == 1.0
    assert metrics["quality"]["pass_rate_all_cases"] == 0.5
    assert metrics["quality"]["missing_score_case_ids"] == ["test-002"]


# ---------------------------------------------------------------------------
# rubric v2 校准（critical 条目）
# ---------------------------------------------------------------------------

def test_critical_item_rule_blocks_high_score_when_missing(tmp_path):
    """score 达到阈值但 critical 条目缺失时仍判不通过。"""
    answers = _default_answers()
    answers["answers"][0]["rubric"] = [
        {"item_id": "r1", "any_of": ["alpha"], "weight": 3, "critical": False},
        {"item_id": "r2", "any_of": ["beta"], "weight": 1, "critical": True},
    ]
    result = _run(tmp_path, answers=answers)
    case = result["experiments"][0]["cases"][0]

    assert case["score"]["score"] == 0.75
    assert case["score"]["passed_score_only"] is True
    assert case["score"]["passed"] is False
    assert case["score"]["critical_missed_items"] == ["r2"]
    assert result["experiments"][0]["metrics"]["quality"]["passed_count"] == 0
    assert result["experiments"][0]["metrics"]["quality"]["critical_missed_case_ids"] == [
        DEFAULT_CASE_ID
    ]


def test_critical_item_rule_passes_when_critical_hit(tmp_path):
    answers = _default_answers()
    answers["answers"][0]["rubric"] = [
        {"item_id": "r1", "any_of": ["alpha"], "weight": 3, "critical": True},
        {"item_id": "r2", "any_of": ["beta"], "weight": 1, "critical": False},
    ]
    result = _run(tmp_path, answers=answers)
    case = result["experiments"][0]["cases"][0]
    assert case["score"]["score"] == 0.75
    assert case["score"]["passed"] is True
    assert case["score"]["critical_missed_items"] == []


# ---------------------------------------------------------------------------
# judge 选择：deterministic / none / llm（显式门禁）
# ---------------------------------------------------------------------------

def test_judge_none_disables_scoring_without_missing_or_error(tmp_path):
    result = _run(tmp_path, judge="none")
    case = result["experiments"][0]["cases"][0]
    quality = result["experiments"][0]["metrics"]["quality"]

    assert result["judge"]["mode"] == "none"
    assert case["status"] == "completed"
    assert case["score"] is None
    assert case["score_status"] == "judge_disabled"
    assert case["score_note"] == "judge_disabled_by_flag"
    assert case["missing_score"] is False
    assert case["scoring_error"] is None
    assert quality["judge_disabled_count"] == 1
    assert quality["missing_score_count"] == 0
    assert quality["scoring_error_count"] == 0
    assert quality["scored_count"] == 0
    assert quality["pass_rate_scored"] is None
    assert quality["pass_rate_all_cases"] == 0.0


def test_judge_llm_requires_explicit_env_flag(tmp_path, monkeypatch):
    monkeypatch.delenv(runner.LLM_JUDGE_ENABLED_ENV, raising=False)
    with pytest.raises(runner.ExperimentConfigError):
        _run(tmp_path, judge="llm")


def test_judge_llm_fake_judge_runs_offline_and_records_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv(runner.LLM_JUDGE_ENABLED_ENV, "1")
    result = _run(tmp_path, judge="llm")
    case = result["experiments"][0]["cases"][0]

    assert result["judge"]["mode"] == "llm"
    assert result["judge"]["fake_judge"] is True
    assert result["judge"]["network"] is False
    assert result["judge"]["adapter"] == runner.ScriptedFakeJudge.ADAPTER_ID
    assert case["status"] == "completed"
    assert case["score_status"] == "scored"
    assert case["score"] is not None
    assert case["score"]["method"] == "llm-judge"
    assert case["score"]["judge_adapter"] == runner.ScriptedFakeJudge.ADAPTER_ID
    assert case["score"]["judge_network"] is False
    assert case["score"]["passed"] is True

    # 同一输入两次运行结果一致（fake judge 确定性）
    second = _run(tmp_path / "second", judge="llm")
    assert second["experiments"][0]["cases"][0]["score"]["score"] == case["score"]["score"]


def test_judge_llm_unparsable_output_is_scoring_error(tmp_path, monkeypatch):
    class BadJudge:
        ADAPTER_ID = "bad-fake-judge"

        def raw_verdict(self, spec, output):
            return "这不是 JSON"

    monkeypatch.setattr(runner, "ScriptedFakeJudge", BadJudge)
    monkeypatch.setenv(runner.LLM_JUDGE_ENABLED_ENV, "1")
    result = _run(tmp_path, judge="llm")
    case = result["experiments"][0]["cases"][0]
    quality = result["experiments"][0]["metrics"]["quality"]

    assert case["status"] == "completed"
    assert case["score"] is None
    assert case["missing_score"] is False
    assert case["score_status"] == "scoring_error"
    assert case["scoring_error_type"] == "llm_judge"
    assert case["scoring_error"]
    assert quality["scoring_error_count"] == 1
    assert quality["missing_score_count"] == 0


def test_unsupported_judge_mode_is_rejected(tmp_path):
    with pytest.raises(runner.ExperimentConfigError):
        _run(tmp_path, judge="magic")


# ---------------------------------------------------------------------------
# 后端 v3 契约：trace_id / attempts / error_type
# ---------------------------------------------------------------------------

def test_trace_id_mapping_reads_run_detail_and_exec_result():
    class FakeRun:
        trace_id = "a" * 32

        def to_dict(self):
            return {"trace_id": self.trace_id}

    assert runner.resolve_trace_id({}, FakeRun()) == ("a" * 32, "run.trace_id")
    assert runner.resolve_trace_id({"trace_id": "b" * 32}, FakeRun()) == (
        "b" * 32,
        "exec_result",
    )

    class DictOnlyRun:
        def to_dict(self):
            return {"trace_id": "c" * 32}

    assert runner.resolve_trace_id({}, DictOnlyRun()) == ("c" * 32, "run.to_dict")
    assert runner.resolve_trace_id({}, None) == (None, None)
    assert runner.resolve_trace_id({"trace_id": ""}, None) == (None, None)


def test_case_records_trace_id_field_even_when_tracing_disabled(tmp_path):
    result = _run(tmp_path)
    for case in result["experiments"][0]["cases"]:
        assert "trace_id" in case
        assert case["trace_id"] is None
        assert case["trace_id_source"] is None
        assert case["tracing_enabled"] is False
    assert result["experiments"][0]["metrics"]["execution"]["trace_id_present_count"] == 0


def test_record_schema_version_is_current_backend_version(tmp_path):
    """记录 schema 版本必须来自后端实际 run，而不是 runner 硬编码。"""
    from agentflow.core.run import RECORD_SCHEMA_VERSION

    result = _run(tmp_path)
    case = result["experiments"][0]["cases"][0]
    assert case["record_schema_version"] == RECORD_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# 数据集隔离与真实模型开关
# ---------------------------------------------------------------------------

def test_dataset_with_embedded_expected_answer_is_rejected(tmp_path):
    cases = [
        {
            "case_id": DEFAULT_CASE_ID,
            "task": DEFAULT_TASK,
            "reference_answer": "alpha",
        }
    ]
    with pytest.raises(runner.ExperimentConfigError):
        _run(tmp_path, cases=cases)


def test_dataset_with_nested_answer_fields_is_rejected(tmp_path):
    cases = [
        {
            "case_id": DEFAULT_CASE_ID,
            "task": DEFAULT_TASK,
            "tags": ["test"],
            "meta": {"expected_answer": "alpha"},
        }
    ]
    with pytest.raises(runner.ExperimentConfigError):
        _run(tmp_path, cases=cases)


def test_dataset_with_unknown_case_field_is_rejected(tmp_path):
    cases = [
        {
            "case_id": DEFAULT_CASE_ID,
            "task": DEFAULT_TASK,
            "hint": "alpha",
        }
    ]
    with pytest.raises(runner.ExperimentConfigError):
        _run(tmp_path, cases=cases)


def test_generated_prompts_exclude_expected_answers(tmp_path, monkeypatch):
    """答案隔离：发送给生成模型的消息里不能出现参考要点/rubric 内容。"""
    created = []

    class RecordingAdapter:
        ADAPTER_ID = "recording-fake-v1"

        def __init__(self):
            self.calls = []
            created.append(self)

        async def complete(self, messages, model, temperature=0.7, max_tokens=2000, **kwargs):
            self.calls.append(list(messages))
            return {
                "content": "alpha",
                "model": model,
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
                "finish_reason": "stop",
            }

        async def stream_complete(self, messages, model, temperature=0.7, max_tokens=2000, **kwargs):
            result = await self.complete(messages, model, temperature, max_tokens, **kwargs)
            yield result["content"]

    monkeypatch.setattr(runner, "ScriptedFakeAdapter", RecordingAdapter)
    answers = _default_answers()
    answers["answers"][0]["reference_answer"] = "ALPHA-REFERENCE-SECRET"
    result = _run(tmp_path, answers=answers)

    assert result["experiments"][0]["cases"][0]["status"] == "completed"
    assert created, "假适配器应被实际调用"
    serialized = json.dumps(created[0].calls, ensure_ascii=False)
    assert "ALPHA-REFERENCE-SECRET" not in serialized
    assert "rubric" not in serialized.lower()
    assert "pass_threshold" not in serialized.lower()
    assert "critical" not in serialized.lower()
    assert DEFAULT_TASK in serialized


def test_default_mode_never_calls_real_model(tmp_path, monkeypatch):
    monkeypatch.delenv(runner.REAL_ENABLED_ENV, raising=False)

    result = _run(tmp_path)
    assert result["adapter"]["mode"] == "fake"
    assert result["adapter"]["network"] is False
    assert result["adapter"]["deterministic"] is True

    dataset_path, answers_path, configs_path = _write_experiment_files(
        tmp_path / "real-gate"
    )
    with pytest.raises(runner.ExperimentConfigError):
        runner.run_experiment(
            configs="single",
            dataset_path=dataset_path,
            answers_path=answers_path,
            configs_path=configs_path,
            adapter_mode="real",
        )


def test_real_mode_requires_env_flag_even_with_key(tmp_path, monkeypatch):
    monkeypatch.delenv(runner.REAL_ENABLED_ENV, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")

    dataset_path, answers_path, configs_path = _write_experiment_files(
        tmp_path / "real-gate-key"
    )
    with pytest.raises(runner.ExperimentConfigError):
        runner.run_experiment(
            configs="single",
            dataset_path=dataset_path,
            answers_path=answers_path,
            configs_path=configs_path,
            adapter_mode="real",
            real_model="fake-model-name",
        )


def test_unknown_config_name_is_rejected(tmp_path):
    with pytest.raises(runner.ExperimentConfigError):
        _run(tmp_path, configs="not-a-config")


def test_unsupported_engine_pattern_name_is_rejected(tmp_path):
    with pytest.raises(runner.ExperimentConfigError):
        _run(tmp_path, configs="debate")


# ---------------------------------------------------------------------------
# CLI 与真实数据集
# ---------------------------------------------------------------------------

def test_cli_output_and_judge_none(tmp_path):
    dataset_path, answers_path, configs_path = _write_experiment_files(tmp_path / "cli")
    output_path = tmp_path / "cli" / "result.json"
    exit_code = runner.main(
        [
            "--config",
            "single",
            "--dataset",
            str(dataset_path),
            "--answers",
            str(answers_path),
            "--configs",
            str(configs_path),
            "--judge",
            "none",
            "--output",
            str(output_path),
        ]
    )
    assert exit_code == 0
    document = json.loads(output_path.read_text(encoding="utf-8"))
    assert document["judge"]["mode"] == "none"
    assert document["experiments"][0]["cases"][0]["score_status"] == "judge_disabled"


def test_default_dataset_is_v2_with_stable_case_ids():
    dataset = runner.load_dataset()
    assert dataset["dataset_id"] == "agentflow-fixed-v2"
    assert dataset["dataset_version"] == "2.0.0"
    assert dataset["case_count"] == 10
    assert [case["case_id"] for case in dataset["cases"]] == [
        f"case-{index:03d}" for index in range(1, 11)
    ]
    # 数据集文件只允许输入字段
    raw = json.loads(runner.DEFAULT_DATASET_PATH.read_text(encoding="utf-8"))
    for case in raw["cases"]:
        assert set(case) <= {"case_id", "task", "tags"}

    answers_index, meta = runner.load_answers(runner.DEFAULT_ANSWERS_PATH, dataset)
    assert meta["present"] is True
    assert meta["scorer_version"] == runner.SCORER_VERSION
    assert meta["answer_case_count"] == 10
    assert meta["missing_case_ids"] == []
    assert meta["unused_case_ids"] == []
    assert meta["calibration"]["pass_threshold_default"] == 0.75
    assert "critical_rule_rationale" in meta["calibration"]
    for case_id in [case["case_id"] for case in dataset["cases"]]:
        spec = answers_index[case_id]
        assert spec["rubric"], f"{case_id} 缺少 rubric"
        assert "reference_answer" in spec, f"{case_id} 缺少 reference_answer"


# ---------------------------------------------------------------------------
# Harness²-lite（本批新增：实验/候选/指纹落库；证据默认关闭、显式开启）
# ---------------------------------------------------------------------------

def test_harness2_default_run_persists_experiment_and_candidates(tmp_path, monkeypatch):
    monkeypatch.delenv(runner.EVIDENCE_ENABLED_ENV, raising=False)
    result = _run(tmp_path)
    harness2 = result["harness2"]

    assert harness2["persisted"] is True
    assert harness2["experiment_id"].startswith("harness2-")
    assert len(harness2["candidates"]) == 1
    entry = harness2["candidates"][0]
    assert entry["config_name"] == "single"
    assert entry["candidate_id"] == f"{harness2['experiment_id']}-single"
    assert len(entry["fingerprint"]) == 16
    case = result["experiments"][0]["cases"][0]
    assert case["experiment_id"] == harness2["experiment_id"]
    assert case["candidate_id"] == entry["candidate_id"]
    assert case["fingerprint"] == entry["fingerprint"]
    assert case["score_source"] == "deterministic"
    assert harness2["evidence"]["enabled"] is False
    assert harness2["evidence"]["written_count"] == 0
    assert case["evidence_ref"] is None


def test_harness2_evidence_flag_writes_bundles(tmp_path, monkeypatch):
    evidence_dir = tmp_path / "evidence"
    monkeypatch.setenv(runner.EVIDENCE_DIR_ENV, str(evidence_dir))
    dataset_path, answers_path, configs_path = _write_experiment_files(tmp_path)

    result = runner.run_experiment(
        configs="single",
        dataset_path=dataset_path,
        answers_path=answers_path,
        configs_path=configs_path,
        adapter_mode="fake",
        evidence=True,
    )
    case = result["experiments"][0]["cases"][0]
    assert result["harness2"]["evidence"]["enabled"] is True
    assert result["harness2"]["evidence"]["written_count"] == 1
    assert case["evidence_ref"]
    assert (evidence_dir / case["evidence_ref"]).is_file()

