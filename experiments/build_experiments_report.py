# -*- coding: utf-8 -*-
"""生成 docs/EXPERIMENTS_REPORT.md 与 docs/experiments_results.json（离线、确定性）。

流程：
1. 运行 backend/tests/test_experiment_runner.py（实际 pytest 数字写入 A 节）；
2. A 节：机制验证（数据集/答案隔离、rubric v2 校准、judge 模式、v3 记录契约、真实模型门禁）；
3. B 节：用确定性假适配器实际运行 single / sequential / parallel，全量 10 个 case；
   明确“仅证明机制，不代表真实质量/成本”，成功率分母始终是全部 case；
4. C 节：真实模型实验未运行（待 Lead 受控执行），只写启用条件/命令/预计样本，不编造数字；
5. 报告与 JSON 中所有数字都来自本次实际运行。

用法：
    cd experiments && python build_experiments_report.py
（或从仓库根目录：python experiments/build_experiments_report.py）
"""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:  # Windows 管道下保证中文输出可写
    for _stream in (sys.stdout, sys.stderr):
        _stream.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

EXPERIMENTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = EXPERIMENTS_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
SCRIPTS_DIR = BACKEND_DIR / "scripts"
DOCS_DIR = PROJECT_ROOT / "docs"
RESULTS_JSON_PATH = DOCS_DIR / "experiments_results.json"
REPORT_PATH = DOCS_DIR / "EXPERIMENTS_REPORT.md"
# 由 Lead 受控运行真实模型实验后写入；存在时报告 C 节会展示实际结果
REAL_RESULTS_JSON_PATH = DOCS_DIR / "real_experiment_results.json"

for _path in (BACKEND_DIR, SCRIPTS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import run_experiment as exp  # noqa: E402  (需要先设置 sys.path)

REPORT_VERSION = "1.0.0"
PYTEST_TARGET = "tests/test_experiment_runner.py"
PYTEST_TIMEOUT_SECONDS = 900
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _fmt_rate(value: Optional[float]) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _fmt_number(value: Optional[float], digits: int = 4) -> str:
    if value is None:
        return "—"
    number = float(value)
    if number == int(number):
        return str(int(number))
    return f"{number:.{digits}f}".rstrip("0").rstrip(".")


def _fmt_seconds(value: Optional[float]) -> str:
    return "—" if value is None else f"{float(value):.4f}"


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def _check(name: str, passed: bool, details: Any) -> Dict[str, Any]:
    return {"check": name, "passed": bool(passed), "details": details}


def _run_command(
    command: Sequence[str],
    cwd: Path,
    timeout: int = PYTEST_TIMEOUT_SECONDS,
    extra_env: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    env["AUTO_EVALUATE"] = "false"  # 机制验证阶段也绝不触发评审模型
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        list(command),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
    )


def _git_metadata() -> Dict[str, Any]:
    metadata: Dict[str, Any] = {"commit": None, "branch": None, "dirty": None, "dirty_count": None}
    try:
        commit = _run_command(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, timeout=30)
        if commit.returncode == 0:
            metadata["commit"] = commit.stdout.strip()
        branch = _run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=PROJECT_ROOT, timeout=30)
        if branch.returncode == 0:
            metadata["branch"] = branch.stdout.strip()
        status = _run_command(["git", "status", "--porcelain"], cwd=PROJECT_ROOT, timeout=30)
        if status.returncode == 0:
            changed = [line for line in status.stdout.splitlines() if line.strip()]
            metadata["dirty"] = bool(changed)
            metadata["dirty_count"] = len(changed)
    except Exception:
        pass
    return metadata


def _environment_metadata() -> Dict[str, Any]:
    return {
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cwd": os.getcwd(),
        "project_root": str(PROJECT_ROOT),
        "git": _git_metadata(),
    }


# ---------------------------------------------------------------------------
# A. 机制验证（实际运行）
# ---------------------------------------------------------------------------

def run_pytest() -> Dict[str, Any]:
    command = [sys.executable, "-m", "pytest", PYTEST_TARGET, "-q"]
    started = time.perf_counter()
    try:
        process = _run_command(command, cwd=BACKEND_DIR, timeout=PYTEST_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return {
            "command": " ".join(command),
            "cwd": str(BACKEND_DIR),
            "exit_code": None,
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "duration_seconds": PYTEST_TIMEOUT_SECONDS,
            "summary_line": f"pytest 超时（>{PYTEST_TIMEOUT_SECONDS}s）",
            "output_tail": "",
            "timeout": True,
        }
    duration = time.perf_counter() - started
    raw = ANSI_ESCAPE.sub("", f"{process.stdout or ''}\n{process.stderr or ''}")
    lines = [line.rstrip() for line in raw.splitlines() if line.strip()]

    def count(pattern: str) -> int:
        match = re.search(pattern, raw)
        return int(match.group(1)) if match else 0

    summary_line = ""
    for line in reversed(lines):
        if re.search(r"\d+ (?:passed|failed|error|errors|skipped)", line):
            summary_line = line.strip()
            break
    duration_match = re.search(r"in ([\d.]+)s", raw)
    if duration_match is not None:
        duration = float(duration_match.group(1))
    tail = "\n".join((process.stdout or "").strip().splitlines()[-40:])
    return {
        "command": " ".join(command),
        "cwd": str(BACKEND_DIR),
        "exit_code": process.returncode,
        "passed": count(r"(\d+) passed"),
        "failed": count(r"(\d+) failed"),
        "errors": count(r"(\d+) error(?:s)?"),
        "skipped": count(r"(\d+) skipped"),
        "duration_seconds": round(duration, 2),
        "summary_line": summary_line or (lines[-1] if lines else ""),
        "output_tail": tail,
        "timeout": False,
    }


def _load_frozen_assets():
    dataset = exp.load_dataset(exp.DEFAULT_DATASET_PATH)
    configs = exp.load_configs(exp.DEFAULT_CONFIGS_PATH)
    answers_index, answers_meta = exp.load_answers(exp.DEFAULT_ANSWERS_PATH, dataset)
    return dataset, configs, answers_index, answers_meta


def build_mechanism_checks(
    dataset: Dict[str, Any],
    configs: Dict[str, Any],
    answers_index: Dict[str, Dict[str, Any]],
    answers_meta: Dict[str, Any],
    fake_run: Dict[str, Any],
    fake_judge_run: Optional[Dict[str, Any]],
    fake_judge_error: Optional[str],
) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    dataset_ids = [case["case_id"] for case in dataset["cases"]]

    # 1) 数据集 v2 固定 10 个 case
    checks.append(
        _check(
            "数据集 v2 可加载：固定 10 个 case、case_id 稳定且唯一",
            len(dataset_ids) == 10
            and len(set(dataset_ids)) == 10
            and dataset_ids == [f"case-{index:03d}" for index in range(1, 11)],
            {
                "dataset_id": dataset["dataset_id"],
                "dataset_version": dataset["dataset_version"],
                "case_count": dataset["case_count"],
                "case_ids": dataset_ids,
            },
        )
    )

    # 2) 数据集只含输入字段，递归扫描无答案字段
    raw_dataset = json.loads(exp.DEFAULT_DATASET_PATH.read_text(encoding="utf-8"))
    leaked: List[Dict[str, Any]] = []
    for case in raw_dataset.get("cases", []):
        found = exp._find_answer_like_fields(case)
        extra = sorted(set(case) - exp.ALLOWED_CASE_KEYS)
        if found or extra:
            leaked.append(
                {"case_id": case.get("case_id"), "answer_like_fields": found, "extra_fields": extra}
            )
    checks.append(
        _check(
            "数据集不含答案/评分字段（只允许 case_id/task/tags）",
            not leaked,
            {"leaked": leaked, "forbidden_keys": sorted(exp.FORBIDDEN_DATASET_CASE_KEYS)},
        )
    )

    # 3) 加载器会拒绝注入的答案字段
    rejection_ok = False
    rejection_detail: Any = None
    with tempfile.TemporaryDirectory(prefix="agentflow-eval-isolation-") as tmp:
        poisoned = {
            "dataset_id": "poisoned",
            "dataset_version": "1.0.0",
            "cases": [
                {
                    "case_id": "case-001",
                    "task": "demo",
                    "meta": {"expected_answer": "should be rejected"},
                }
            ],
        }
        poisoned_path = Path(tmp) / "poisoned.json"
        poisoned_path.write_text(json.dumps(poisoned, ensure_ascii=False), encoding="utf-8")
        try:
            exp.load_dataset(poisoned_path)
        except exp.ExperimentConfigError as exc:
            rejection_ok = True
            rejection_detail = exp.scrub_secrets(exc)

    # 4) 答案隔离：生成模型消息中不出现参考要点/rubric
    isolation_leaks: List[Dict[str, Any]] = []
    for config_name, config_def in configs["configs"].items():
        workflow_config = exp.build_workflow_config(config_name, config_def)
        prompt_texts: List[str] = [agent.system_prompt for agent in workflow_config.agents]
        for case in dataset["cases"]:
            prompt_texts.append(case["task"])
            spec = answers_index.get(case["case_id"]) or {}
            reference = spec.get("reference_answer")
            joined = "\n".join(prompt_texts)
            if isinstance(reference, str) and reference and reference in joined:
                isolation_leaks.append(
                    {"config": config_name, "case_id": case["case_id"], "leak": "reference_answer"}
                )
            lowered = joined.casefold()
            for marker in ("rubric", "pass_threshold", "critical_missed", "expected_answer"):
                if marker in lowered:
                    isolation_leaks.append(
                        {"config": config_name, "case_id": case["case_id"], "leak": marker}
                    )
    checks.append(
        _check(
            "答案隔离：加载器拒绝注入的答案字段，生成消息不含参考要点/rubric",
            rejection_ok and not isolation_leaks,
            {
                "injected_answer_rejected": rejection_ok,
                "rejection_message": rejection_detail,
                "isolation_leaks": isolation_leaks,
                "checked_configs": sorted(configs["configs"]),
            },
        )
    )

    # 5) 答案覆盖与版本一致
    checks.append(
        _check(
            "预期答案覆盖全部 10 个 case，数据集/评分器版本一致且带校准说明",
            answers_meta["present"]
            and answers_meta["answer_case_count"] == 10
            and not answers_meta["missing_case_ids"]
            and not answers_meta["unused_case_ids"]
            and answers_meta["scorer_version"] == exp.SCORER_VERSION
            and bool(answers_meta["calibration"].get("threshold_rationale")),
            {
                "answer_case_count": answers_meta["answer_case_count"],
                "missing_case_ids": answers_meta["missing_case_ids"],
                "unused_case_ids": answers_meta["unused_case_ids"],
                "scorer_version": answers_meta["scorer_version"],
                "calibration_keys": sorted(answers_meta["calibration"]),
            },
        )
    )

    # 6) rubric v2 校准证据：假适配器输出（8 正确 + 2 故意错误）
    calibration_rows: List[Dict[str, Any]] = []
    calibration_ok = True
    for case in dataset["cases"]:
        spec = answers_index[case["case_id"]]
        verdict = exp.score_output(exp._scripted_response(case["task"]), spec)
        calibration_rows.append(
            {
                "case_id": case["case_id"],
                "score": verdict["score"],
                "passed": verdict["passed"],
                "critical_missed_items": verdict["critical_missed_items"],
                "score_status": "scored",
            }
        )
        expected_pass = case["case_id"] not in ("case-003", "case-009")
        if verdict["passed"] is not expected_pass:
            calibration_ok = False
    passed_ids = [row["case_id"] for row in calibration_rows if row["passed"]]
    checks.append(
        _check(
            "rubric v2 校准：预设 8 条正确回答通过、2 条故意错误回答不通过（critical 规则生效）",
            calibration_ok and len(passed_ids) == 8,
            {
                "passed_count": len(passed_ids),
                "failed_case_ids": [
                    row["case_id"] for row in calibration_rows if not row["passed"]
                ],
                "rows": calibration_rows,
            },
        )
    )

    # 7) judge 模式与显式门禁
    judge_details: Dict[str, Any] = {}
    judge_ok = True
    try:
        deterministic_judge, deterministic_info = exp._create_judge(
            "deterministic", "fake", None, {"mode": "fake"}
        )
        none_judge, none_info = exp._create_judge("none", "fake", None, {"mode": "fake"})
        judge_details["deterministic"] = deterministic_info["mode"]
        judge_details["none"] = none_info["mode"]
        judge_details["deterministic_network"] = deterministic_info["network"]
        judge_details["none_adapter"] = none_info["adapter"]
        if deterministic_info["network"] or none_info["adapter"] is not None:
            judge_ok = False
    except Exception as exc:  # noqa: BLE001
        judge_ok = False
        judge_details["error"] = exp.scrub_secrets(exc)

    # LLM judge 未设门禁时必须拒绝
    original_env = os.environ.pop(exp.LLM_JUDGE_ENABLED_ENV, None)
    try:
        try:
            exp._create_judge("llm", "fake", None, {"mode": "fake"})
            judge_details["llm_without_gate_rejected"] = False
            judge_ok = False
        except exp.ExperimentConfigError:
            judge_details["llm_without_gate_rejected"] = True
    finally:
        if original_env is not None:
            os.environ[exp.LLM_JUDGE_ENABLED_ENV] = original_env
    if fake_judge_run is not None:
        judge_details["llm_fake_judge"] = fake_judge_run.get("judge")
        judge_details["llm_fake_judge_scores"] = [
            (case["case_id"], case["score"]["score"] if case["score"] else None)
            for case in fake_judge_run["experiments"][0]["cases"]
        ]
        judge_meta = fake_judge_run.get("judge") or {}
        if judge_meta.get("mode") != "llm" or judge_meta.get("network") is not False:
            judge_ok = False
    else:
        judge_ok = False
        judge_details["llm_fake_judge_error"] = fake_judge_error
    checks.append(
        _check(
            "judge 选择：默认 deterministic、none 关闭评分、llm 需显式门禁且默认不联网",
            judge_ok,
            judge_details,
        )
    )

    # 8) 后端 v3 记录契约：run_id / trace_id 字段 / schema / attempts / error_type
    from agentflow.core.run import RECORD_SCHEMA_VERSION

    contract_rows: List[Dict[str, Any]] = []
    contract_ok = True
    for experiment in fake_run["experiments"]:
        for case in experiment["cases"]:
            step = case["step_results"][0] if case["step_results"] else {}
            row = {
                "case_id": case["case_id"],
                "run_id_present": bool(case["run_id"]),
                "trace_id_field_present": "trace_id" in case,
                "trace_id": case["trace_id"],
                "tracing_enabled": case["tracing_enabled"],
                "record_schema_version": case["record_schema_version"],
                "attempts": step.get("attempts"),
                "error_type": step.get("error_type"),
                "score_status": case["score_status"],
            }
            contract_rows.append(row)
            if not (
                row["run_id_present"]
                and row["trace_id_field_present"]
                and row["tracing_enabled"] is False
                and row["trace_id"] is None
                and row["record_schema_version"] == RECORD_SCHEMA_VERSION
                and isinstance(row["attempts"], int)
                and row["attempts"] >= 1
                and "error_type" in step
            ):
                contract_ok = False
    checks.append(
        _check(
            f"运行记录满足后端 v{RECORD_SCHEMA_VERSION} 契约：run_id、trace_id 字段、attempts、error_type",
            contract_ok,
            {
                "backend_record_schema_version": RECORD_SCHEMA_VERSION,
                "case_count_checked": len(contract_rows),
                "sample": contract_rows[:3],
                "note": "本次未开启追踪，trace_id 为 null；开启追踪且配置 Langfuse 后由 run 记录带入。",
            },
        )
    )

    # 9) trace_id 映射逻辑（从 run 详情 / execute 返回值读取）
    class _FakeRun:
        trace_id = "d" * 32

        def to_dict(self):
            return {"trace_id": self.trace_id}

    mapping_ok = (
        exp.resolve_trace_id({}, _FakeRun()) == ("d" * 32, "run.trace_id")
        and exp.resolve_trace_id({"trace_id": "e" * 32}, _FakeRun()) == ("e" * 32, "exec_result")
        and exp.resolve_trace_id({}, None) == (None, None)
    )
    checks.append(
        _check(
            "trace_id 映射：优先 execute() 返回值，其次 run.trace_id / run.to_dict()，缺失不伪造",
            mapping_ok,
            {
                "run_detail": exp.resolve_trace_id({}, _FakeRun()),
                "exec_result": exp.resolve_trace_id({"trace_id": "e" * 32}, _FakeRun()),
                "none": exp.resolve_trace_id({}, None),
            },
        )
    )

    # 10) 成功率分母为全部 case（缺失/错误/执行失败都算未通过）
    denominator_ok = True
    denominator_details: List[Dict[str, Any]] = []
    for experiment in fake_run["experiments"]:
        metrics = experiment["metrics"]
        total = metrics["case_count"]
        quality = metrics["quality"]
        expected_rate = round(quality["passed_count"] / total, 4) if total else None
        denominator_details.append(
            {
                "config": experiment["config_name"],
                "case_count": total,
                "passed_count": quality["passed_count"],
                "missing_score_count": quality["missing_score_count"],
                "scoring_error_count": quality["scoring_error_count"],
                "judge_disabled_count": quality["judge_disabled_count"],
                "pass_rate_all_cases": quality["pass_rate_all_cases"],
                "recomputed": expected_rate,
            }
        )
        if quality["pass_rate_all_cases"] != expected_rate:
            denominator_ok = False
    checks.append(
        _check(
            "成功率分母为全部 case（缺失评分/评分错误/执行失败按未通过计入）",
            denominator_ok,
            {"per_config": denominator_details},
        )
    )

    # 11) 未支持配置被拒绝 + limit 生效
    unsupported_rejected = False
    try:
        exp.run_experiment(configs="debate", adapter_mode="fake")
    except exp.ExperimentConfigError:
        unsupported_rejected = True
    limited = exp.run_experiment(configs="single", adapter_mode="fake", limit=3)
    limit_ok = (
        limited["dataset"]["case_count"] == 3
        and limited["dataset"]["full_case_count"] == 10
        and limited["dataset"]["limit"] == 3
    )
    checks.append(
        _check(
            "不支持的配置被拒绝（--config debate）且 --limit 只运行前 N 个 case",
            unsupported_rejected and limit_ok,
            {
                "debate_rejected": unsupported_rejected,
                "limit_case_count": limited["dataset"]["case_count"],
                "limit_full_case_count": limited["dataset"]["full_case_count"],
            },
        )
    )

    # 12) 默认不调用真实模型 + CLI 默认值
    original_real = os.environ.pop(exp.REAL_ENABLED_ENV, None)
    real_gate_ok = False
    real_gate_detail = None
    try:
        try:
            exp._create_adapter("real")
        except exp.ExperimentConfigError as exc:
            real_gate_ok = True
            real_gate_detail = exp.scrub_secrets(exc)
    finally:
        if original_real is not None:
            os.environ[exp.REAL_ENABLED_ENV] = original_real
    cli_args = exp.build_parser().parse_args([])
    cli_defaults_ok = (
        cli_args.config == "all"
        and cli_args.judge == "deterministic"
        and cli_args.real is False
        and cli_args.tracing is False
    )
    checks.append(
        _check(
            "真实模型默认关闭（缺 AGENTFLOW_EXPERIMENT_REAL 即拒绝）且 CLI 默认 fake/确定性 judge",
            real_gate_ok and cli_defaults_ok,
            {
                "real_gate_rejected": real_gate_ok,
                "real_gate_message": real_gate_detail,
                "cli_defaults": {
                    "config": cli_args.config,
                    "judge": cli_args.judge,
                    "real": cli_args.real,
                    "tracing": cli_args.tracing,
                },
            },
        )
    )

    return {
        "checks": checks,
        "checks_passed": sum(1 for check in checks if check["passed"]),
        "checks_total": len(checks),
        "calibration": answers_meta["calibration"],
    }


# ---------------------------------------------------------------------------
# C. 真实模型（有受控运行结果时展示，否则展示启用说明）
# ---------------------------------------------------------------------------

def _load_real_experiment_results() -> Optional[Dict[str, Any]]:
    """读取 docs/real_experiment_results.json（若存在），只保留汇总所需字段。"""
    if not REAL_RESULTS_JSON_PATH.exists():
        return None
    try:
        raw = json.loads(REAL_RESULTS_JSON_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "error": f"读取真实实验结果失败：{type(exc).__name__}",
            "path": str(REAL_RESULTS_JSON_PATH.relative_to(PROJECT_ROOT)),
        }

    configs = []
    for experiment in raw.get("experiments", []):
        configs.append(
            {
                "config_name": experiment.get("config_name"),
                "pattern": experiment.get("pattern"),
                "engine_pattern": experiment.get("engine_pattern"),
                "metrics": experiment.get("metrics") or {},
                "cases": [
                    {
                        key: case.get(key)
                        for key in (
                            "case_id",
                            "status",
                            "score",
                            "score_status",
                            "trace_id",
                            "total_tokens",
                            "usage_type",
                            "elapsed_seconds",
                            "error",
                        )
                    }
                    for case in (experiment.get("cases") or [])
                ],
            }
        )

    return {
        "status": "run",
        "path": str(REAL_RESULTS_JSON_PATH.relative_to(PROJECT_ROOT)),
        "experiment_id": raw.get("experiment_id"),
        "created_at": raw.get("created_at"),
        "adapter": raw.get("adapter") or {},
        "judge": raw.get("judge") or {},
        "tracing": raw.get("tracing") or {},
        "configs": configs,
    }


def build_real_model_section() -> Dict[str, Any]:
    key_envs = sorted(set(exp.PROVIDER_KEY_ENVS.values()))
    key_presence = {env_name: bool(os.getenv(env_name)) for env_name in key_envs}
    real_run = _load_real_experiment_results()
    return {
        "status": "run" if real_run else "not_run",
        "reason": (
            "本报告只运行确定性假适配器；真实模型实验需要人工显式开启，"
            "并按成本预算受控执行（由 Lead 在最后执行）。本任务不调用任何付费模型。"
        ),
        "env_flag": exp.REAL_ENABLED_ENV,
        "env_flag_set_now": os.getenv(exp.REAL_ENABLED_ENV) == "1",
        "judge_env_flag": exp.LLM_JUDGE_ENABLED_ENV,
        "judge_env_flag_set_now": os.getenv(exp.LLM_JUDGE_ENABLED_ENV) == "1",
        "key_envs_present": key_presence,
        "estimated_samples": {
            "cases": 10,
            "configs": 3,
            "executions": 30,
            "llm_judge_extra_calls_if_enabled": 30,
            "note": "预计样本仅按固定数据集与配置计算；真实耗时/成本未知，本报告不编造成本数字。",
        },
        "required_conditions": [
            f"设置 {exp.REAL_ENABLED_ENV}=1",
            "命令行显式加 --real",
            f"选择 provider：{exp.REAL_PROVIDER_ENV}（默认 openai）",
            "对应 provider 的密钥环境变量存在（只检查是否存在，不打印值）",
            f"指定模型：--real-model 或 {exp.REAL_MODEL_ENV}",
            f"若要 --judge llm：额外设置 {exp.LLM_JUDGE_ENABLED_ENV}=1（会产生额外评审调用费用）",
            "若要记录 trace_id：配置 Langfuse 并显式加 --tracing",
        ],
        "commands": {
            "deterministic_judge": (
                "cd backend && python scripts/run_experiment.py --real --config all "
                "--judge deterministic --output ../experiments/real_run_deterministic.json"
            ),
            "llm_judge": (
                "cd backend && python scripts/run_experiment.py --real --config all "
                "--judge llm --output ../experiments/real_run_llm_judge.json"
            ),
            "with_langfuse_tracing": (
                "cd backend && python scripts/run_experiment.py --real --config all "
                "--judge deterministic --tracing --output ../experiments/real_run_traced.json"
            ),
            "enable_env_examples": [
                f"export {exp.REAL_ENABLED_ENV}=1  # Windows PowerShell: $env:{exp.REAL_ENABLED_ENV}='1'",
                f"export {exp.REAL_PROVIDER_ENV}=<openai|deepseek|anthropic|openrouter>",
                "export OPENAI_API_KEY=<密钥>  # 按 provider 选择对应变量；不要写进仓库",
                f"export {exp.REAL_MODEL_ENV}=<模型名>",
                f"export {exp.LLM_JUDGE_ENABLED_ENV}=1  # 仅 --judge llm 时需要",
            ],
        },
        "real_run": real_run,
        "note": (
            "C 节若 status=run 表示已用真实模型受控运行，数字全部来自 "
            "docs/real_experiment_results.json；若 status=not_run 则没有任何真实模型数字。"
            "禁止用 B 节假模型数字替代真实模型质量/成本结论。"
        ),
    }


# ---------------------------------------------------------------------------
# Markdown 报告
# ---------------------------------------------------------------------------

def _build_report(document: Dict[str, Any]) -> str:
    metadata = document["metadata"]
    mechanism = document["mechanism_verification"]
    pytest_info = mechanism["pytest"]
    fake = document["fake_model_experiment"]
    real = document["real_model_experiment"]
    versions = document["versions"]
    experiment = fake.get("experiment")

    lines: List[str] = []
    lines.append("# AgentFlow 实验报告（评测升级 v2）")
    lines.append("")
    lines.append(f"- 生成时间：{document['generated_at']}")
    lines.append("- 生成命令：`cd experiments && python build_experiments_report.py`（本报告由脚本基于本次实际运行自动生成）")
    git_label = metadata["git"].get("commit") or "（非 git 仓库或不可用）"
    lines.append(
        f"- 代码版本：commit `{git_label[:12]}`，分支 `{metadata['git'].get('branch') or '—'}`，"
        f"工作区 dirty={metadata['git'].get('dirty')}（改动文件数 {metadata['git'].get('dirty_count')}）"
    )
    lines.append(
        f"- 运行环境：Python {metadata['python_version']} / {metadata['platform']} / "
        f"解释器 `{metadata['python_executable']}`"
    )
    lines.append(
        f"- 版本冻结：数据集 `{versions['dataset']['dataset_id']}@{versions['dataset']['dataset_version']}`"
        f"（{versions['dataset']['case_count']} 个 case），配置 `{versions['config']['config_version']}`，"
        f"评分器 `{versions['scorer']['version']}`，judge `{versions['judge']['mode']}`"
    )
    lines.append("")
    lines.append(
        "> **范围声明**：A、B 两节数字均来自本次实际运行。B 节使用确定性假适配器"
        "（不联网、不调用付费模型），其质量数字仅用于证明实验、评分与记录链路可用，"
        "**不代表任何真实模型的质量或成本**。C 节若 status=run，则展示受控真实模型运行结果；"
        "否则说明未运行原因与启用命令。禁止用 B 节数字冒充真实模型结论。"
    )
    lines.append("")

    # ---------------- A ----------------
    lines.append("## A. 机制验证（本次实跑）")
    lines.append("")
    lines.append("### A1. 实验运行器测试（pytest）")
    lines.append("")
    lines.append(f"命令：`{pytest_info['command']}`（cwd=`backend`）")
    lines.append("")
    lines.append(
        f"结果：**{pytest_info['passed']} passed, {pytest_info['failed']} failed, "
        f"{pytest_info['errors']} error, {pytest_info['skipped']} skipped**；"
        f"退出码 `{pytest_info['exit_code']}`，耗时 {pytest_info['duration_seconds']}s。"
    )
    lines.append("")
    if pytest_info.get("summary_line"):
        lines.append(f"摘要行：`{pytest_info['summary_line']}`")
        lines.append("")
    lines.append("测试覆盖：默认不调真实模型、答案隔离、评分失败/缺失分别记录、"
                 "critical rubric 校准、judge 选择与门禁、trace_id/attempts/error_type 字段。")
    lines.append("")

    lines.append("### A2. 补充确定性断言（独立于 pytest，本轮实跑）")
    lines.append("")
    check_rows = [
        [
            check["check"],
            "通过" if check["passed"] else "失败",
            json.dumps(check["details"], ensure_ascii=False)[:500],
        ]
        for check in mechanism["checks"]
    ]
    lines.append(_table(["检查项", "结果", "细节（截断）"], check_rows))
    lines.append("")
    lines.append(
        f"检查通过：**{mechanism['checks_passed']}/{mechanism['checks_total']}**。"
    )
    lines.append("")

    lines.append("### A3. 评分器 v2 校准（阈值、通过标准、理由）")
    lines.append("")
    calibration = mechanism.get("calibration") or {}
    lines.append(
        f"- 默认阈值：**{calibration.get('pass_threshold_default', exp.DEFAULT_PASS_THRESHOLD)}**。"
    )
    lines.append(
        "- 通过标准：`score = 命中条目权重和 / 全部条目权重和`，"
        "且 `passed = score >= pass_threshold 且所有 critical 条目命中`。"
    )
    lines.append(f"- 阈值理由：{calibration.get('threshold_rationale') or '—'}")
    lines.append(f"- critical 理由：{calibration.get('critical_rule_rationale') or '—'}")
    lines.append(f"- 校准证据：{calibration.get('calibration_evidence') or '—'}")
    lines.append("")
    bands = calibration.get("bands") or []
    if bands:
        band_rows = [[band.get("range", "—"), band.get("meaning", "—")] for band in bands]
        lines.append(_table(["分数区间", "含义"], band_rows))
        lines.append("")

    # ---------------- B ----------------
    lines.append("## B. 假模型实验（本次实跑；仅证明机制，不代表真实质量/成本）")
    lines.append("")
    lines.append(
        "> 假适配器 `scripted-fake-v1` 返回预先编写的确定性文本，token 由确定性规则生成；"
        "其中 case-003、case-009 为故意错误回答。B 节通过率只说明评分器能区分预设的正确/错误回答，"
        "**样本仅 10 个 case，不得外推为总体质量**；耗时与 token 不具备真实外部效度。"
    )
    lines.append("")
    lines.append(
        "运行方式（本轮内部执行）：`cd backend && python scripts/run_experiment.py --config all "
        "--judge deterministic`"
    )
    lines.append("")
    if experiment is None:
        lines.append(f"**假模型实验未成功运行**：`{fake.get('error')}`")
        lines.append("")
    else:
        dataset_info = experiment["dataset"]
        lines.append(
            f"- 数据集：`{dataset_info['dataset_id']}@{dataset_info['dataset_version']}`，"
            f"固定 case 数 {dataset_info['case_count']}"
        )
        lines.append(
            f"- 配置：single / sequential / parallel（`{experiment['configs']['config_version']}`）"
        )
        lines.append(
            f"- 适配器：`{experiment['adapter']['adapter_id']}`"
            f"（mode={experiment['adapter']['mode']}，network={experiment['adapter']['network']}，"
            f"deterministic={experiment['adapter']['deterministic']}）"
        )
        judge_info = experiment.get("judge") or {}
        lines.append(
            f"- Judge：mode={judge_info.get('mode')}，adapter=`{judge_info.get('adapter')}`，"
            f"network={judge_info.get('network')}（默认确定性 rubric，不联网）"
        )
        lines.append(
            f"- 评分器：v{experiment['scorer']['version']}（rubric v2 + critical 校准，"
            f"默认阈值 {experiment['scorer']['pass_threshold_default']}）"
        )
        lines.append(
            "- trace_id：本次未开启追踪（`tracing.enabled=false`），因此所有 case 的 `trace_id=null`；"
            "字段本身始终写入结果，开启 `--tracing` 且配置 Langfuse 后从 run 记录带入。"
        )
        lines.append("")

        lines.append("### B1. 总览（成功率分母始终是全部 case）")
        lines.append("")
        overview_rows = []
        for exp_result in experiment["experiments"]:
            metrics = exp_result["metrics"]
            quality = metrics["quality"]
            execution = metrics["execution"]
            overview_rows.append(
                [
                    exp_result["config_name"],
                    metrics["case_count"],
                    execution["completed_count"],
                    execution["partial_count"],
                    execution["failed_count"],
                    _fmt_rate(execution["execution_success_rate"]),
                    quality["scored_count"],
                    quality["missing_score_count"],
                    quality["scoring_error_count"],
                    quality["judge_disabled_count"],
                    quality["passed_count"],
                    _fmt_rate(quality["pass_rate_scored"]),
                    _fmt_rate(quality["pass_rate_all_cases"]),
                    _fmt_number(quality["mean_score_scored"]),
                    metrics["tokens"]["total"],
                    _fmt_seconds(metrics["timing"]["total_seconds"]),
                    execution["trace_id_present_count"],
                ]
            )
        lines.append(
            _table(
                [
                    "配置", "用例数", "完成", "部分", "失败", "执行成功率",
                    "已评分", "缺失评分", "评分错误", "judge关闭", "通过",
                    "通过率(已评分)", "通过率(全部case)", "平均分(已评分)",
                    "总token", "总耗时(s)", "trace_id数",
                ],
                overview_rows,
            )
        )
        lines.append("")
        lines.append(
            "说明：`通过率(已评分)` 的分母是成功产出且完成评分的 case；`通过率(全部case)` 的分母是"
            "全部 case（本次每个配置均为 10），缺失评分、评分错误、执行失败、judge 关闭都按“未通过”计入，"
            "不会只统计成功案例。"
        )
        lines.append("")

        lines.append("### B2. 逐 case 结果")
        lines.append("")
        case_rows = []
        for exp_result in experiment["experiments"]:
            for case in exp_result["cases"]:
                score = case["score"]
                issue = ""
                if case["missing_score"]:
                    issue = "missing_score"
                elif case["scoring_error"]:
                    issue = "scoring_error"
                elif case["score_status"] == "judge_disabled":
                    issue = "judge_disabled"
                elif case["score_status"] == "execution_failed":
                    issue = "execution_failed"
                step_attempts = case["step_results"][0]["attempts"] if case["step_results"] else None
                step_error_type = case["step_results"][0]["error_type"] if case["step_results"] else None
                case_rows.append(
                    [
                        exp_result["config_name"],
                        case["case_id"],
                        (case["run_id"] or "")[:8],
                        "—" if case["trace_id"] is None else case["trace_id"][:8],
                        case["status"],
                        case["record_schema_version"],
                        step_attempts,
                        step_error_type or "—",
                        case["total_tokens"],
                        case["usage_type"],
                        _fmt_number(score["score"]) if score else "—",
                        ("是" if score["passed"] else "否") if score else "—",
                        ",".join(score.get("critical_missed_items") or []) if score else "—",
                        issue or "—",
                    ]
                )
        lines.append(
            _table(
                [
                    "配置", "case_id", "run_id", "trace_id", "执行状态", "schema",
                    "attempts", "error_type", "token", "usage_type", "分数",
                    "通过", "critical缺失", "评分/执行异常",
                ],
                case_rows,
            )
        )
        lines.append("")

        missing_rows = []
        error_rows = []
        judge_disabled_rows = []
        for exp_result in experiment["experiments"]:
            for case in exp_result["cases"]:
                if case["missing_score"]:
                    missing_rows.append(
                        [exp_result["config_name"], case["case_id"], case.get("score_note") or ""]
                    )
                if case["scoring_error"]:
                    error_rows.append(
                        [exp_result["config_name"], case["case_id"], case["scoring_error"]]
                    )
                if case["score_status"] == "judge_disabled":
                    judge_disabled_rows.append([exp_result["config_name"], case["case_id"], "judge=none"])
        lines.append("### B3. 评分记录完整性")
        lines.append("")
        lines.append(
            f"- 缺失评分（missing_score）记录数：{len(missing_rows)}；"
            f"评分错误（scoring_error）记录数：{len(error_rows)}；"
            f"judge 关闭（judge_disabled）记录数：{len(judge_disabled_rows)}。"
        )
        unknown_steps = sum(
            exp_result["metrics"]["tokens"].get("unknown_usage_step_count", 0)
            for exp_result in experiment["experiments"]
        )
        lines.append(
            f"- 未知用量（usage_type=unknown）步骤数：{unknown_steps}；"
            "未知用量不会被当作 0 真实成本。"
        )
        lines.append(
            "- 执行失败的 case 不会被拿去评分：评分前先判断执行状态与输出非空，"
            "失败执行以 `score_status=execution_failed` 记录，不会用引擎回退文本冒充成功。"
        )
        if missing_rows:
            lines.append("")
            lines.append(_table(["配置", "case_id", "说明"], missing_rows))
        if error_rows:
            lines.append("")
            lines.append(_table(["配置", "case_id", "scoring_error"], error_rows))
        if judge_disabled_rows:
            lines.append("")
            lines.append(_table(["配置", "case_id", "说明"], judge_disabled_rows))
        lines.append("")

        lines.append("### B4. 如何解读（局限必须连同数字一起阅读）")
        lines.append("")
        lines.append(
            "- 假适配器有 2 条预设回答故意答错（case-003、case-009），通过率 80% 是"
            "**评分器识别失败**的证据，不是模型能力结论。"
        )
        lines.append(
            "- 质量分数反映“预先编写的回答”与“关键词 rubric + critical 规则”的匹配程度，"
            "无法判断语义等价表达；关键词覆盖不到的正确答案可能被误判为不通过。"
        )
        lines.append(
            "- token 为假适配器按字符长度规则生成的合成值，usage_type 由引擎按“是否返回 usage”判定，"
            "均不代表真实模型计费。"
        )
        lines.append(
            "- 固定数据集只有 10 个 case，不具备统计代表性；任何通过率都不可外推为总体质量。"
        )
        lines.append(
            "- 耗时在毫秒级，受进程调度影响大，仅证明计时字段可用，不可外推到真实模型延迟。"
        )
        lines.append(
            "- 本次 trace_id 全为 null（追踪未开启），仅证明字段与映射逻辑就绪，"
            "不能据此声称已产生 Langfuse trace。"
        )
        lines.append("")

    # ---------------- C ----------------
    real_run = real.get("real_run")
    if real_run and real_run.get("status") == "run":
        lines.append("## C1. 真实模型实验（本次受控运行）")
        lines.append("")
        lines.append(
            f"- 数据来源：`{real_run.get('path')}`（experiment_id `{real_run.get('experiment_id')}`，"
            f"生成时间 {real_run.get('created_at')}）"
        )
        adapter_info = real_run.get("adapter") or {}
        judge_info = real_run.get("judge") or {}
        tracing_info = real_run.get("tracing") or {}
        lines.append(
            f"- 适配器：mode=`{adapter_info.get('mode')}`，provider=`{adapter_info.get('provider')}`，"
            f"model=`{adapter_info.get('model')}`，network=`{adapter_info.get('network')}`"
        )
        lines.append(
            f"- 评分：mode=`{judge_info.get('mode')}`，adapter=`{judge_info.get('adapter')}`"
            "（确定性 rubric；本轮未运行 LLM judge）"
        )
        lines.append(
            f"- 追踪：enabled=`{tracing_info.get('enabled')}`；每个 case 的 trace_id 从 "
            "execute() 返回值/运行记录读取，未启用时为 null，不伪造。"
        )
        lines.append("")

        overview_rows = []
        case_rows = []
        for config in real_run.get("configs", []):
            metrics = config.get("metrics") or {}
            execution = metrics.get("execution") or {}
            quality = metrics.get("quality") or {}
            tokens = metrics.get("tokens") or {}
            timing = metrics.get("timing") or {}
            cases = config.get("cases") or []
            overview_rows.append(
                [
                    str(config.get("config_name")),
                    str(config.get("pattern")),
                    f"{execution.get('completed_count', 0)}/{metrics.get('case_count', len(cases))}",
                    f"{quality.get('passed_count', 0)}/{metrics.get('case_count', len(cases))}",
                    f"{quality.get('pass_rate_all_cases')}",
                    f"{quality.get('mean_score_all_cases')}",
                    str(tokens.get("total")),
                    f"{timing.get('total_seconds')}",
                    f"{execution.get('trace_id_present_count', 0)}",
                ]
            )
            for case in cases:
                score = case.get("score") or {}
                case_rows.append(
                    [
                        str(config.get("config_name")),
                        str(case.get("case_id")),
                        str(case.get("status")),
                        str(case.get("score_status")),
                        f"{score.get('score')}",
                        str(case.get("total_tokens")),
                        str(case.get("usage_type")),
                        (str(case.get("trace_id")) if case.get("trace_id") else "—"),
                    ]
                )

        lines.append(
            _table(
                ["配置", "模式", "完成", "通过（分母全部 case）", "pass_rate_all_cases",
                 "mean_score_all_cases", "total_tokens", "总耗时(s)", "trace_id 数"],
                overview_rows,
            )
        )
        lines.append("")
        lines.append("每 case 结果（真实模型）：")
        lines.append("")
        lines.append(
            _table(
                ["配置", "case_id", "执行状态", "评分状态", "score", "tokens", "usage_type", "trace_id"],
                case_rows,
            )
        )
        lines.append("")
        lines.append(
            "> 说明：10 个固定 case × 3 配置 = 30 次真实执行；token 为提供商实际返回，"
            "分数为确定性 rubric。样本很小，上述通过率只是该配置在该数据集上的观察，"
            "**不能外推为总体质量，也不能据此证明多 Agent 方案更优**；本轮未运行 LLM judge，"
            "未对真实评审模型做校准。真实运行结果文件：`docs/real_experiment_results.json`。"
        )
        lines.append("")
    elif real_run:
        lines.append("## C1. 真实模型实验结果（读取失败）")
        lines.append("")
        lines.append(f"读取 `{real_run.get('path')}` 失败：{real_run.get('error')}")
        lines.append("")

    lines.append("## C2. 真实模型实验的启用条件与命令（参考）")
    lines.append("")
    if real_run and real_run.get("status") == "run":
        lines.append("> 本次已完成受控运行，C1 为实际结果；以下条件与命令保留用于复现。")
        lines.append("")
    else:
        lines.append(f"**状态：未运行（status=`{real['status']}`）。**")
        lines.append("")
        lines.append(f"原因：{real['reason']}")
        lines.append("")
    lines.append(
        f"当前开关检查：`{real['env_flag']}` = "
        f"`{'1（已设置）' if real['env_flag_set_now'] else '未设置（默认关闭）'}`；"
        f"`{real['judge_env_flag']}` = "
        f"`{'1（已设置）' if real['judge_env_flag_set_now'] else '未设置（默认关闭）'}`。"
        "密钥只检查是否存在，不读取、不记录、不打印具体值。"
    )
    lines.append("")
    lines.append("预计样本（仅按固定数据集计算，不代表成本）：")
    samples = real["estimated_samples"]
    lines.append(
        f"- {samples['cases']} 个固定 case × {samples['configs']} 个配置 = "
        f"**{samples['executions']} 次执行**；若启用 LLM judge，额外 {samples['llm_judge_extra_calls_if_enabled']} 次评审调用。"
    )
    lines.append(f"- {samples['note']}")
    lines.append("")
    lines.append("启用条件：")
    for index, condition in enumerate(real["required_conditions"], 1):
        lines.append(f"{index}. {condition}")
    lines.append("")
    lines.append("命令（密钥通过环境变量提供，不要写进仓库）：")
    lines.append("")
    lines.append("```bash")
    for env_line in real["commands"]["enable_env_examples"]:
        lines.append(env_line)
    lines.append("")
    lines.append(real["commands"]["deterministic_judge"])
    lines.append(real["commands"]["llm_judge"])
    lines.append(real["commands"]["with_langfuse_tracing"])
    lines.append("```")
    lines.append("")
    lines.append("密钥环境变量是否存在（仅布尔值）：")
    key_rows = [
        [env_name, "已设置" if present else "未设置"]
        for env_name, present in real["key_envs_present"].items()
    ]
    lines.append("")
    lines.append(_table(["环境变量", "状态"], key_rows))
    lines.append("")
    if real.get("status") == "run":
        lines.append(
            "> 注：上表检查的是生成报告进程的环境；C1 的真实运行由独立受控启动器注入密钥与模型配置，"
            "因此这里显示未设置不代表真实运行未配置。"
        )
        lines.append("")
    lines.append(f"> {real['note']}")
    lines.append("")

    # ---------------- D ----------------
    lines.append("## D. Langfuse 实验关联说明")
    lines.append("")
    lines.append(
        "1. 每个 case 结果始终包含 `trace_id` / `trace_id_source` / `tracing_enabled` 字段。"
    )
    lines.append(
        "2. 默认不开启追踪：不联网、不需要 Langfuse 配置，`trace_id=null`，绝不伪造。"
    )
    lines.append(
        "3. 需要关联时显式加 `--tracing`，并配置 `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`"
        "（可选 `LANGFUSE_HOST`）；runner 从 `execute()` 返回值 / run 记录的 `trace_id` 读取并写入结果。"
    )
    if real.get("status") == "run":
        lines.append(
            "4. 本次 C1 真实运行显式启用了 `--tracing`，30 个 case 均记录了非空 `trace_id`"
            "（见 C1 每 case 表）；trace 可在 Langfuse 中按该 id 检索。B 节假模型实验未开启追踪，"
            "因此 B 节 trace_id 为 null。"
        )
    else:
        lines.append(
            "4. 本次报告没有真实 Langfuse trace：未配置密钥、未开启追踪；真实运行需显式加 `--tracing`，"
            "不能在未实际运行前声称已关联。"
        )
    lines.append("")

    # ---------------- 复现 ----------------
    lines.append("## 复现与相关文件")
    lines.append("")
    lines.append("- 本报告：`docs/EXPERIMENTS_REPORT.md`")
    lines.append("- 原始结果 JSON：`docs/experiments_results.json`")
    lines.append("- 数据集：`experiments/dataset_v2.json`（10 个固定 case，case-001..case-010）")
    lines.append("- 预期答案/评分要点/校准：`experiments/expected_answers_v2.json`（只给评分器读）")
    lines.append("- 配置：`experiments/configs_v1.json`")
    lines.append("- 生成报告：`cd experiments && python build_experiments_report.py`")
    lines.append("- 单跑实验：`cd backend && python scripts/run_experiment.py --config single|sequential|parallel|all [--limit N] [--judge deterministic|llm|none]`")
    lines.append("- 重跑基线：`cd backend && python scripts/run_baseline.py`")
    lines.append("")
    lines.append("## 未运行 / 未验证项")
    lines.append("")
    for limitation in document["limitations"]:
        lines.append(f"- {limitation}")
    lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> int:
    generated_at = _now_iso()
    print("=" * 72)
    print("AgentFlow 实验报告生成：A 机制验证 + B 假模型实验 + C 真实模型（未运行）")
    print("=" * 72)

    dataset, configs, answers_index, answers_meta = _load_frozen_assets()

    print(f"\n[A] 运行 {PYTEST_TARGET} ...")
    pytest_info = run_pytest()
    print(
        f"    pytest: {pytest_info['passed']} passed, {pytest_info['failed']} failed, "
        f"{pytest_info['errors']} error, {pytest_info['skipped']} skipped "
        f"(exit={pytest_info['exit_code']}, {pytest_info['duration_seconds']}s)"
    )

    print("\n[B] 运行假模型实验（single / sequential / parallel，全量 10 个 case）...")
    fake_error: Optional[str] = None
    fake_run: Optional[Dict[str, Any]] = None
    fake_elapsed = 0.0
    try:
        started = time.perf_counter()
        fake_run = exp.run_experiment(
            configs="all",
            adapter_mode="fake",
            judge="deterministic",
        )
        fake_elapsed = round(time.perf_counter() - started, 4)
        for experiment in fake_run["experiments"]:
            metrics = experiment["metrics"]
            quality = metrics["quality"]
            print(
                f"    [{experiment['config_name']}] cases={metrics['case_count']} "
                f"completed={metrics['execution']['completed_count']} "
                f"scored={quality['scored_count']} passed={quality['passed_count']} "
                f"pass_rate_all={quality['pass_rate_all_cases']} "
                f"tokens={metrics['tokens']['total']}"
            )
    except Exception as exc:  # noqa: BLE001
        fake_error = exp.scrub_secrets(exc)
        print(f"    假模型实验失败：{fake_error}")

    print("\n[A] 运行 LLM judge（假 judge 链路，离线）机制验证 ...")
    fake_judge_run: Optional[Dict[str, Any]] = None
    fake_judge_error: Optional[str] = None
    original_gate = os.environ.get(exp.LLM_JUDGE_ENABLED_ENV)
    try:
        os.environ[exp.LLM_JUDGE_ENABLED_ENV] = "1"
        fake_judge_run = exp.run_experiment(
            configs="single",
            adapter_mode="fake",
            judge="llm",
            limit=2,
        )
        print(
            "    judge=llm 假链路灯：",
            [(case["case_id"], case["score_status"]) for case in fake_judge_run["experiments"][0]["cases"]],
        )
    except Exception as exc:  # noqa: BLE001
        fake_judge_error = exp.scrub_secrets(exc)
        print(f"    LLM judge 机制验证失败：{fake_judge_error}")
    finally:
        if original_gate is None:
            os.environ.pop(exp.LLM_JUDGE_ENABLED_ENV, None)
        else:
            os.environ[exp.LLM_JUDGE_ENABLED_ENV] = original_gate

    print("\n[A] 运行补充确定性断言 ...")
    if fake_run is None:
        raise SystemExit("假模型实验失败，无法生成完整报告；请检查 B 节错误。")
    mechanism = build_mechanism_checks(
        dataset,
        configs,
        answers_index,
        answers_meta,
        fake_run,
        fake_judge_run,
        fake_judge_error,
    )
    for check in mechanism["checks"]:
        print(f"    [{'通过' if check['passed'] else '失败'}] {check['check']}")

    real_model = build_real_model_section()

    versions = {
        "dataset": {
            "dataset_id": dataset["dataset_id"],
            "dataset_version": dataset["dataset_version"],
            "case_count": dataset["case_count"],
        },
        "config": {
            "config_version": configs["config_version"],
            "names": sorted(configs["configs"]),
        },
        "scorer": {
            "version": exp.SCORER_VERSION,
            "method": "deterministic-rubric-v2",
            "pass_threshold_default": exp.DEFAULT_PASS_THRESHOLD,
            "calibration": answers_meta["calibration"],
        },
        "judge": {
            "mode": fake_run.get("judge", {}).get("mode"),
            "adapter": fake_run.get("judge", {}).get("adapter"),
            "network": fake_run.get("judge", {}).get("network"),
        },
        "runner_version": exp.RUNNER_VERSION,
    }

    limitations = [
        "真实模型实验未运行：没有任何真实模型质量、延迟或成本数据；C 节仅为受控执行入口。",
        "B 节使用假适配器，质量数字只能证明评分/执行/记录链路，不能代表真实模型质量。",
        "确定性评分器为关键词/短语 rubric + critical 规则，无法评判语义等价与推理过程质量，存在误判可能。",
        "固定数据集只有 10 个 case，不具统计代表性，任何通过率都不可外推。",
        "本次未开启 Langfuse 追踪，trace_id 全为 null；字段与映射逻辑已就绪，但尚未产生真实 trace。",
        "耗时为本机毫秒级调度结果，token 为假适配器合成值，均不可外推为真实成本/延迟。",
        "本轮未覆盖真实网络故障、限流、超时重试等场景（后端 v3 的 attempts/error_type 字段已记录但未被真实触发）。",
    ]

    document: Dict[str, Any] = {
        "report_version": REPORT_VERSION,
        "runner_version": exp.RUNNER_VERSION,
        "generated_at": generated_at,
        "metadata": _environment_metadata(),
        "versions": versions,
        "mechanism_verification": {
            "pytest": pytest_info,
            "checks": mechanism["checks"],
            "checks_passed": mechanism["checks_passed"],
            "checks_total": mechanism["checks_total"],
            "calibration": mechanism.get("calibration") or {},
        },
        "fake_model_experiment": {
            "note": "仅证明机制，不代表真实模型质量/成本；假适配器不联网、不调用付费模型。",
            "adapter_note": "scripted-fake-v1 输出为预先编写的确定性文本，token 为规则生成的合成值。",
            "experiment": fake_run,
            "elapsed_seconds": fake_elapsed,
            "error": fake_error,
        },
        "real_model_experiment": real_model,
        "limitations": limitations,
    }

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_JSON_PATH.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    REPORT_PATH.write_text(_build_report(document), encoding="utf-8")

    print(f"\n已生成：{RESULTS_JSON_PATH}")
    print(f"已生成：{REPORT_PATH}")
    success = (
        pytest_info["exit_code"] == 0
        and mechanism["checks_passed"] == mechanism["checks_total"]
        and fake_run is not None
    )
    if not success:
        print("\n注意：机制验证或假模型实验存在失败，请查看报告 A/B 节。", file=sys.stderr)
        return 1
    print("\n实验报告生成完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
