# -*- coding: utf-8 -*-
"""AgentFlow 基线：机制验证 + 假模型实验，生成 docs/BASELINE_REPORT.md 与 docs/baseline_results.json。

设计原则：
- A 节（机制验证）：本次实际运行后端 pytest（解析 passed/failed 数）+ 补充确定性断言；
- B 节（假模型实验）：本次实际运行 single/sequential/parallel 三种配置，明确"仅证明机制，
  不代表真实模型质量/成本"；
- C 节（真实模型实验）：未运行。只写原因与启用方法，不编造任何数字；
- 报告与 JSON 中的所有数字均来自本次实际运行。

用法：
    cd backend
    python scripts/run_baseline.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import platform
import re
import subprocess
import sys
import sysconfig
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

try:  # Windows 管道下保证中文输出可写
    for _stream in (sys.stdout, sys.stderr):
        _stream.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover - 仅环境兼容
    pass

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
SCRIPTS_DIR = BACKEND_DIR / "scripts"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

try:
    import run_experiment as exp
except ImportError:  # pragma: no cover - 直接按路径加载的兜底
    _spec = importlib.util.spec_from_file_location(
        "agentflow_run_experiment", SCRIPTS_DIR / "run_experiment.py"
    )
    if _spec is None or _spec.loader is None:  # pragma: no cover
        raise
    exp = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = exp
    _spec.loader.exec_module(exp)

DOCS_DIR = PROJECT_ROOT / "docs"
BASELINE_JSON_PATH = DOCS_DIR / "baseline_results.json"
BASELINE_REPORT_PATH = DOCS_DIR / "BASELINE_REPORT.md"

PYTEST_TIMEOUT_SECONDS = 900
PYTEST_TAIL_LINES = 60
REPORT_VERSION = "2.0.0"
MIN_FIXED_CASES = 10

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


# ---------------------------------------------------------------------------
# 实际命令执行与解析
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _run_command(command: Sequence[str], cwd: Path, timeout: int = PYTEST_TIMEOUT_SECONDS):
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    env["AUTO_EVALUATE"] = "false"  # 机制验证阶段也绝不触发评审模型
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


def parse_pytest_output(stdout: str, stderr: str, exit_code: int, duration: float) -> Dict[str, Any]:
    """从 pytest -q 输出解析 passed/failed/error/skipped 数量与摘要行。"""
    raw = ANSI_ESCAPE.sub("", f"{stdout}\n{stderr}")
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

    tail_source = stdout.strip()
    if stderr.strip():
        tail_source = f"{tail_source}\n[stderr]\n{stderr.strip()}"
    tail = "\n".join(tail_source.splitlines()[-PYTEST_TAIL_LINES:])

    return {
        "command": f"{sys.executable} -m pytest tests/ -q",
        "cwd": str(BACKEND_DIR),
        "exit_code": exit_code,
        "passed": count(r"(\d+) passed"),
        "failed": count(r"(\d+) failed"),
        "errors": count(r"(\d+) error(?:s)?"),
        "skipped": count(r"(\d+) skipped"),
        "duration_seconds": round(duration, 2),
        "summary_line": summary_line or (lines[-1] if lines else ""),
        "output_tail": tail,
    }


def run_pytest() -> Dict[str, Any]:
    started = datetime.now()
    try:
        process = _run_command(
            [sys.executable, "-m", "pytest", "tests/", "-q"],
            cwd=BACKEND_DIR,
            timeout=PYTEST_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {
            "command": f"{sys.executable} -m pytest tests/ -q",
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
    duration = (datetime.now() - started).total_seconds()
    result = parse_pytest_output(process.stdout or "", process.stderr or "", process.returncode, duration)
    result["timeout"] = False
    result["started_at"] = started.astimezone().isoformat(timespec="seconds")
    return result


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
        "python_build": sysconfig.get_config_var("BUILD_GNU_TYPE") or "",
    }


# ---------------------------------------------------------------------------
# 补充确定性断言（A 节）
# ---------------------------------------------------------------------------

def _check(name: str, passed: bool, details: Any) -> Dict[str, Any]:
    return {"check": name, "passed": bool(passed), "details": details}


def build_mechanism_checks(
    dataset_path: Path,
    answers_path: Path,
    configs_path: Path,
) -> Dict[str, Any]:
    """不依赖 pytest 的独立确定性断言；全部基于实际加载/实际运行。"""
    checks: List[Dict[str, Any]] = []
    loaded: Dict[str, Any] = {}

    # 1) 数据集可加载，版本字段完整
    try:
        dataset = exp.load_dataset(dataset_path)
        loaded["dataset"] = dataset
        checks.append(
            _check(
                "数据集可加载且版本字段完整",
                bool(dataset["dataset_id"] and dataset["dataset_version"] and dataset["case_count"] > 0),
                {
                    "dataset_id": dataset["dataset_id"],
                    "dataset_version": dataset["dataset_version"],
                    "case_count": dataset["case_count"],
                },
            )
        )
    except Exception as exc:
        checks.append(_check("数据集可加载且版本字段完整", False, exp.scrub_secrets(exc)))
        dataset = None

    # 2) 固定 case 数量与 ID 唯一性
    if dataset is not None:
        case_ids = [case["case_id"] for case in dataset["cases"]]
        checks.append(
            _check(
                f"至少 {MIN_FIXED_CASES} 个固定 case 且 case_id 唯一",
                len(case_ids) >= MIN_FIXED_CASES and len(case_ids) == len(set(case_ids)),
                {
                    "case_count": len(case_ids),
                    "unique": len(set(case_ids)),
                    "min_expected": MIN_FIXED_CASES,
                    "case_ids": case_ids,
                },
            )
        )

        # 3) 数据集中不出现预期答案/评分字段（防泄漏）
        raw_dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
        leaked_fields: List[Dict[str, Any]] = []
        for index, case in enumerate(raw_dataset.get("cases", [])):
            if not isinstance(case, dict):
                leaked_fields.append({"index": index, "fields": ["<非对象>"]})
                continue
            found = sorted(key for key in case if key in exp.FORBIDDEN_DATASET_CASE_KEYS)
            if found:
                leaked_fields.append({"case_id": case.get("case_id"), "fields": found})
        checks.append(
            _check(
                "数据集不含预期答案/评分字段（答案隔离）",
                not leaked_fields,
                {"leaked_fields": leaked_fields, "forbidden_keys": sorted(exp.FORBIDDEN_DATASET_CASE_KEYS)},
            )
        )
    else:
        checks.append(_check(f"至少 {MIN_FIXED_CASES} 个固定 case 且 case_id 唯一", False, "数据集加载失败"))
        checks.append(_check("数据集不含预期答案/评分字段（答案隔离）", False, "数据集加载失败"))

    # 4) 预期答案覆盖全部固定 case
    if dataset is not None:
        try:
            answers_index, answers_meta = exp.load_answers(answers_path, dataset)
            dataset_ids = {case["case_id"] for case in dataset["cases"]}
            missing_ids = sorted(dataset_ids - set(answers_index))
            checks.append(
                _check(
                    "预期答案覆盖全部固定 case 且评分器版本一致",
                    answers_meta["present"] and not missing_ids,
                    {
                        "answers_present": answers_meta["present"],
                        "scorer_version": answers_meta["scorer_version"],
                        "answer_case_count": answers_meta["answer_case_count"],
                        "missing_case_ids": missing_ids,
                        "unused_case_ids": answers_meta["unused_case_ids"],
                    },
                )
            )
            loaded["answers_meta"] = answers_meta
        except Exception as exc:
            checks.append(
                _check(
                    "预期答案覆盖全部固定 case 且评分器版本一致",
                    False,
                    exp.scrub_secrets(exc),
                )
            )
    else:
        checks.append(
            _check("预期答案覆盖全部固定 case 且评分器版本一致", False, "数据集加载失败")
        )

    # 5) 三种配置冻结齐全
    try:
        configs_doc = exp.load_configs(configs_path)
        loaded["configs_doc"] = configs_doc
        names = set(configs_doc["configs"])
        expected_names = set(exp.SUPPORTED_CONFIGS)
        checks.append(
            _check(
                "三种配置（single/sequential/parallel）定义齐全",
                names == expected_names,
                {
                    "config_version": configs_doc["config_version"],
                    "configs": sorted(names),
                    "missing": sorted(expected_names - names),
                    "unexpected": sorted(names - expected_names),
                },
            )
        )
        engine_patterns = {
            name: config["engine_pattern"] for name, config in configs_doc["configs"].items()
        }
        engine_patterns_supported = (
            len(engine_patterns) == len(expected_names)
            and all(value in ("sequential", "parallel") for value in engine_patterns.values())
            and engine_patterns.get("single") == "sequential"
            and engine_patterns.get("sequential") == "sequential"
            and engine_patterns.get("parallel") == "parallel"
        )
        checks.append(
            _check(
                "实验配置只使用引擎支持的 sequential/parallel 模式",
                engine_patterns_supported,
                {
                    "engine_patterns": engine_patterns,
                    "note": "single 是实验层名称，底层为 1 步 sequential；未支持模式不会进入实验配置。",
                },
            )
        )
    except Exception as exc:
        checks.append(
            _check("三种配置（single/sequential/parallel）定义齐全", False, exp.scrub_secrets(exc))
        )
        configs_doc = None

    # 6/7) 引擎冒烟 + 8) 假适配器确定性（实际运行两次）
    smoke: Dict[str, Any] = {"runs": [], "deterministic": None}
    try:
        first = exp.run_experiment(
            configs=["single"], dataset_path=dataset_path, answers_path=answers_path,
            configs_path=configs_path, limit=1, adapter_mode="fake",
        )
        second = exp.run_experiment(
            configs=["single"], dataset_path=dataset_path, answers_path=answers_path,
            configs_path=configs_path, limit=1, adapter_mode="fake",
        )
        smoke["runs"] = [first, second]
        first_experiment = first["experiments"][0]
        first_case = first_experiment["cases"][0]
        smoke_ok = (
            first["adapter"]["mode"] == "fake"
            and first["adapter"]["network"] is False
            and first_case["status"] == "completed"
            and bool(first_case["output"].strip())
            and first_case["score"] is not None
        )
        checks.append(
            _check(
                "引擎冒烟：single 配置可执行、有输出且可评分",
                smoke_ok,
                {
                    "case_id": first_case["case_id"],
                    "status": first_case["status"],
                    "output_chars": len(first_case["output"]),
                    "score": first_case["score"]["score"] if first_case["score"] else None,
                    "elapsed_seconds": first_case["elapsed_seconds"],
                    "total_tokens": first_case["total_tokens"],
                    "adapter": first["adapter"]["adapter_id"],
                },
            )
        )

        second_experiment = second["experiments"][0]
        second_case = second_experiment["cases"][0]
        deterministic = (
            first_case["output"] == second_case["output"]
            and first_case["total_tokens"] == second_case["total_tokens"]
            and first_case["score"] == second_case["score"]
        )
        smoke["deterministic"] = deterministic
        checks.append(
            _check(
                "假适配器确定性：同一输入两次运行输出/token/评分一致",
                deterministic,
                {
                    "output_equal": first_case["output"] == second_case["output"],
                    "tokens": [first_case["total_tokens"], second_case["total_tokens"]],
                    "scores": [
                        first_case["score"]["score"] if first_case["score"] else None,
                        second_case["score"]["score"] if second_case["score"] else None,
                    ],
                },
            )
        )
        checks.append(
            _check(
                "运行器默认不启用真实模型（mode=fake、network=false）",
                first["adapter"]["mode"] == "fake" and first["adapter"]["network"] is False,
                {
                    "mode": first["adapter"]["mode"],
                    "network": first["adapter"]["network"],
                    "real_gate_env": exp.REAL_ENABLED_ENV,
                    "real_gate_set": os.getenv(exp.REAL_ENABLED_ENV) == "1",
                },
            )
        )

        step_records = first_case["step_results"]
        required_step_fields = {
            "step_id",
            "step_index",
            "attempts",
            "error_type",
            "model",
            "finish_reason",
            "usage_type",
            "input_chars",
            "output_excerpt",
        }
        try:
            from agentflow.core.run import RECORD_SCHEMA_VERSION as BACKEND_SCHEMA_VERSION
        except Exception:  # pragma: no cover - 仅在核心代码不可用时
            BACKEND_SCHEMA_VERSION = None
        contract_ok = (
            bool(first_case.get("run_id"))
            and "trace_id" in first_case
            and first_case.get("tracing_enabled") is False
            and first_case.get("trace_id") is None
            and first_case.get("score_status") == "scored"
            and first_case.get("record_schema_version") == BACKEND_SCHEMA_VERSION
            and bool(step_records)
            and required_step_fields <= set(step_records[0])
            and isinstance(step_records[0].get("attempts"), int)
            and step_records[0].get("attempts") >= 1
            and "error_type" in step_records[0]
            and step_records[0].get("usage_type")
            in ("actual", "estimated", "partial", "unknown")
        )
        checks.append(
            _check(
                "运行记录满足版本化契约（schema_version/run_id/trace_id/attempts/error_type/用量类型）",
                contract_ok,
                {
                    "backend_record_schema_version": BACKEND_SCHEMA_VERSION,
                    "record_schema_version": first_case.get("record_schema_version"),
                    "run_id_present": bool(first_case.get("run_id")),
                    "trace_id": first_case.get("trace_id"),
                    "tracing_enabled": first_case.get("tracing_enabled"),
                    "step_fields": sorted(step_records[0]) if step_records else [],
                    "step_usage_type": step_records[0].get("usage_type") if step_records else None,
                    "attempts": step_records[0].get("attempts") if step_records else None,
                    "error_type": step_records[0].get("error_type") if step_records else None,
                },
            )
        )
    except Exception as exc:
        smoke["error"] = exp.scrub_secrets(exc)
        checks.append(
            _check(
                "引擎冒烟：single 配置可执行、有输出且可评分",
                False,
                smoke["error"],
            )
        )
        checks.append(
            _check("假适配器确定性：同一输入两次运行输出/token/评分一致", False, smoke["error"])
        )
        checks.append(
            _check(
                "运行器默认不启用真实模型（mode=fake、network=false）",
                False,
                smoke["error"],
            )
        )

    # 9) 引擎支持全部模式，并拒绝未知模式（实验配置不得误用）
    try:
        from agentflow.core.workflow import (
            SUPPORTED_PATTERNS,
            UnsupportedPatternError,
            WorkflowPattern,
            ensure_supported_pattern,
        )

        supported = all(
            ensure_supported_pattern(pattern) is None for pattern in WorkflowPattern
        )
        rejected = False
        try:
            ensure_supported_pattern("unknown-pattern")
        except UnsupportedPatternError:
            rejected = True
        checks.append(
            _check(
                "引擎支持全部 7 种模式且拒绝未知模式",
                supported and rejected,
                {
                    "patterns": list(SUPPORTED_PATTERNS),
                    "unknown_rejected": rejected,
                },
            )
        )
    except Exception as exc:
        checks.append(
            _check("引擎支持全部 7 种模式且拒绝未知模式", False, exp.scrub_secrets(exc))
        )

    return {
        "checks": checks,
        "checks_passed": sum(1 for check in checks if check["passed"]),
        "checks_total": len(checks),
        "smoke": smoke,
        "loaded": loaded,
    }


# ---------------------------------------------------------------------------
# 真实模型部分（未运行，仅说明）
# ---------------------------------------------------------------------------

def build_real_model_section() -> Dict[str, Any]:
    key_envs = sorted(set(exp.PROVIDER_KEY_ENVS.values()))
    key_presence = {env_name: bool(os.getenv(env_name)) for env_name in key_envs}
    real_results_path = DOCS_DIR / "real_experiment_results.json"
    real_run_elsewhere = None
    if real_results_path.exists():
        try:
            raw = json.loads(real_results_path.read_text(encoding="utf-8"))
            summaries = []
            for experiment in raw.get("experiments", []):
                metrics = experiment.get("metrics") or {}
                quality = metrics.get("quality") or {}
                tokens = metrics.get("tokens") or {}
                timing = metrics.get("timing") or {}
                execution = metrics.get("execution") or {}
                summaries.append(
                    {
                        "config": experiment.get("config_name"),
                        "completed": execution.get("completed_count"),
                        "passed": quality.get("passed_count"),
                        "cases": metrics.get("case_count"),
                        "pass_rate_all_cases": quality.get("pass_rate_all_cases"),
                        "total_tokens": tokens.get("total"),
                        "total_seconds": timing.get("total_seconds"),
                        "trace_id_present_count": execution.get("trace_id_present_count"),
                    }
                )
            real_run_elsewhere = {
                "status": "run",
                "path": str(real_results_path.relative_to(PROJECT_ROOT)),
                "experiment_id": raw.get("experiment_id"),
                "created_at": raw.get("created_at"),
                "adapter": raw.get("adapter") or {},
                "judge": raw.get("judge") or {},
                "configs": summaries,
                "note": "真实模型实验由独立受控运行完成，不在本基线脚本内执行；数字见该文件与 docs/EXPERIMENTS_REPORT.md C1。",
            }
        except Exception as exc:  # noqa: BLE001
            real_run_elsewhere = {
                "status": "error",
                "path": str(real_results_path.relative_to(PROJECT_ROOT)),
                "error": f"{type(exc).__name__}: {exc}",
            }
    return {
        "status": "not_run_in_baseline",
        "real_experiment_done_separately": real_run_elsewhere,
        "reason": (
            "本次基线按设计只运行确定性假适配器；真实模型路径需要人工显式开启，"
            "基线脚本不会自动调用任何付费模型。"
        ),
        "env_flag": exp.REAL_ENABLED_ENV,
        "env_flag_set_now": os.getenv(exp.REAL_ENABLED_ENV) == "1",
        "env_flag_default": "未设置（默认关闭）",
        "judge_env_flag": exp.LLM_JUDGE_ENABLED_ENV,
        "judge_env_flag_set_now": os.getenv(exp.LLM_JUDGE_ENABLED_ENV) == "1",
        "key_envs_present": key_presence,
        "estimated_samples": {
            "cases": MIN_FIXED_CASES,
            "configs": 3,
            "executions": MIN_FIXED_CASES * 3,
            "llm_judge_extra_calls_if_enabled": MIN_FIXED_CASES * 3,
            "note": "预计样本仅按固定数据集与配置计算；真实耗时/成本未知，不编造成本数字。",
        },
        "required_conditions": [
            f"设置 {exp.REAL_ENABLED_ENV}=1",
            "命令行显式加 --real",
            f"选择 provider：{exp.REAL_PROVIDER_ENV}（默认 openai）",
            "对应 provider 的密钥环境变量存在（只检查是否存在，不打印值）",
            f"指定模型：--real-model 或 {exp.REAL_MODEL_ENV}",
            f"若要 --judge llm：额外设置 {exp.LLM_JUDGE_ENABLED_ENV}=1（额外评审调用会产生费用）",
            "若要记录 trace_id：配置 Langfuse 并显式加 --tracing",
        ],
        "enable_steps": [
            f"export {exp.REAL_ENABLED_ENV}=1  # Windows PowerShell: $env:{exp.REAL_ENABLED_ENV}='1'",
            f"export {exp.REAL_PROVIDER_ENV}=openai  # 或 deepseek / anthropic / openrouter",
            "export OPENAI_API_KEY=<密钥>  # 按 provider 选择对应变量；不要写进仓库",
            f"export {exp.REAL_MODEL_ENV}=<模型名>",
            f"export {exp.LLM_JUDGE_ENABLED_ENV}=1  # 仅 --judge llm 时需要",
            "cd backend && python scripts/run_experiment.py --real --config all --judge deterministic "
            "--output ../experiments/real_run_deterministic.json",
            "cd backend && python scripts/run_experiment.py --real --config all --judge llm "
            "--output ../experiments/real_run_llm_judge.json",
            "cd backend && python scripts/run_experiment.py --real --config all --judge deterministic "
            "--tracing --output ../experiments/real_run_traced.json",
        ],
        "command_example": (
            "cd backend && python scripts/run_experiment.py --real --config all "
            "--judge deterministic --output ../experiments/real_run_deterministic.json"
        ),
        "note": (
            "C 节当前没有任何数字。真实模型跑完后需人工审阅结果并单独补充本节，"
            "禁止用 B 节假模型数字替代真实模型质量/成本结论。"
        ),
    }


# ---------------------------------------------------------------------------
# Markdown 报告
# ---------------------------------------------------------------------------

def _fmt_rate(value: Optional[float]) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _fmt_number(value: Optional[float], digits: int = 4) -> str:
    if value is None:
        return "—"
    return f"{float(value):.{digits}f}".rstrip("0").rstrip(".") if float(value) != int(float(value)) else str(int(float(value)))


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


def _build_report(baseline: Dict[str, Any]) -> str:
    metadata = baseline["metadata"]
    versions = baseline["versions"]
    mechanism = baseline["mechanism_verification"]
    pytest_info = mechanism["pytest"]
    fake = baseline["fake_model_experiment"]
    real = baseline["real_model_experiment"]

    lines: List[str] = []
    lines.append("# AgentFlow 基线报告")
    lines.append("")
    lines.append(f"- 生成时间：{baseline['generated_at']}")
    lines.append(f"- 生成命令：`cd backend && python scripts/run_baseline.py`（本报告由脚本基于本次实际运行自动生成）")
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
        f"- 版本冻结：数据集 `{versions['dataset']['dataset_id']}@{versions['dataset']['dataset_version']}`，"
        f"配置 `{versions['config']['config_version']}`，评分器 `{versions['scorer']['version']}`，"
        f"judge `{versions.get('judge', {}).get('mode')}`"
    )
    lines.append("")
    lines.append("> **范围声明**：A、B 两节数字均来自本次实际运行。B 节使用确定性假适配器（不联网、不调用付费模型），"
                 "其质量数字仅用于证明实验、评分与记录链路可用，**不代表任何真实模型的质量或成本**。")
    lines.append("")
    lines.append(f"> v2 升级：数据集扩为 {MIN_FIXED_CASES} 个固定 case，评分器升级为 rubric v2（阈值 + critical 校准），"
                 "记录兼容后端 v3（trace_id / attempts / error_type）；本基线只运行 `--judge deterministic`（默认）。")
    lines.append("")

    # ---- A ----
    lines.append("## A. 机制验证（本次实跑）")
    lines.append("")
    lines.append("### A1. 后端测试套件（pytest）")
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
    lines.append("本次 pytest 输出尾部（截取）：")
    lines.append("")
    lines.append("```text")
    lines.append(pytest_info.get("output_tail") or "（无输出）")
    lines.append("```")
    lines.append("")

    lines.append("### A2. 补充确定性断言（独立于 pytest，本轮实跑）")
    lines.append("")
    check_rows = [
        [
            check["check"],
            "通过" if check["passed"] else "失败",
            json.dumps(check["details"], ensure_ascii=False),
        ]
        for check in mechanism["checks"]
    ]
    lines.append(_table(["检查项", "结果", "细节"], check_rows))
    lines.append("")
    lines.append(
        f"检查通过：**{mechanism['checks_passed']}/{mechanism['checks_total']}**。"
    )
    smoke = mechanism.get("smoke", {})
    if smoke.get("error"):
        lines.append(f"冒烟执行错误：`{smoke['error']}`")
    elif smoke.get("runs"):
        smoke_case = smoke["runs"][0]["experiments"][0]["cases"][0]
        lines.append(
            f"引擎冒烟（single，case={smoke_case['case_id']}）：状态 `{smoke_case['status']}`，"
            f"输出 {len(smoke_case['output'])} 字符，得分 "
            f"{smoke_case['score']['score'] if smoke_case['score'] else '—'}，"
            f"token={smoke_case['total_tokens']}，耗时 {smoke_case['elapsed_seconds']}s，"
            f"记录 schema_version={smoke_case.get('record_schema_version')}；"
            f"假适配器确定性复跑一致={smoke.get('deterministic')}。"
        )
    lines.append("")

    # ---- B ----
    lines.append("## B. 假模型质量实验（本次实跑）")
    lines.append("")
    lines.append("> **仅证明机制，不代表真实模型质量/成本。** 假适配器 `scripted-fake-v1` 返回预先编写的确定性文本，"
                 "token 计数由确定性规则生成；本节的通过率只说明评分器能区分预设的正确/错误回答，"
                 "耗时和 token 都不具备外部效度。样本只有 10 个 case，不得外推整体质量。")
    lines.append("")
    lines.append(
        "运行方式（本轮内部执行）：`cd backend && python scripts/run_experiment.py --config all "
        "--judge deterministic`"
    )
    lines.append("")
    fake_experiment = fake.get("experiment")
    if fake_experiment is None:
        lines.append(f"**假模型实验未成功运行**：`{fake.get('error')}`")
        lines.append("")
    else:
        dataset_info = fake_experiment["dataset"]
        lines.append(
            f"- 数据集：`{dataset_info['dataset_id']}@{dataset_info['dataset_version']}`，"
            f"固定 case 数 {dataset_info['case_count']}"
        )
        lines.append(
            f"- 配置：single / sequential / parallel（`{fake_experiment['configs']['config_version']}`）"
        )
        lines.append(
            f"- 适配器：`{fake_experiment['adapter']['adapter_id']}`"
            f"（mode={fake_experiment['adapter']['mode']}，network={fake_experiment['adapter']['network']}，"
            f"deterministic={fake_experiment['adapter']['deterministic']}）"
        )
        lines.append(
            f"- 评分器：v{fake_experiment['scorer']['version']}（rubric v2 + critical 校准，默认通过阈值 "
            f"{fake_experiment['scorer']['pass_threshold_default']}）"
        )
        judge_info = fake_experiment.get("judge") or {}
        lines.append(
            f"- Judge：mode={judge_info.get('mode')}，adapter=`{judge_info.get('adapter')}`，"
            f"network={judge_info.get('network')}（默认确定性 rubric，不联网）"
        )
        lines.append(
            "- trace_id：本次未开启追踪，所有 case 的 `trace_id=null`；字段/映射逻辑已就绪，"
            "开启 `--tracing` 且配置 Langfuse 后从 run 记录带入，不伪造。"
        )
        lines.append("")

        lines.append("### B1. 总览（成功率分母始终是全部 case）")
        lines.append("")
        overview_rows = []
        for experiment in fake_experiment["experiments"]:
            metrics = experiment["metrics"]
            quality = metrics["quality"]
            execution = metrics["execution"]
            timing = metrics["timing"]
            tokens = metrics["tokens"]
            overview_rows.append(
                [
                    experiment["config_name"],
                    metrics["case_count"],
                    execution["completed_count"],
                    execution["partial_count"],
                    execution["failed_count"],
                    _fmt_rate(execution["execution_success_rate"]),
                    quality["scored_count"],
                    quality["missing_score_count"],
                    quality["scoring_error_count"],
                    quality.get("judge_disabled_count", 0),
                    quality["passed_count"],
                    _fmt_rate(quality["pass_rate_scored"]),
                    _fmt_rate(quality["pass_rate_all_cases"]),
                    _fmt_number(quality["mean_score_scored"]),
                    _fmt_seconds(timing["total_seconds"]),
                    _fmt_seconds(timing["mean_seconds"]),
                    tokens["total"],
                    _fmt_number(tokens["mean_per_case"]),
                    tokens.get("unknown_usage_step_count", 0),
                    execution.get("trace_id_present_count", 0),
                ]
            )
        lines.append(
            _table(
                [
                    "配置", "用例数", "完成", "部分", "失败", "执行成功率",
                    "已评分", "缺失评分", "评分错误", "judge关闭", "通过", "通过率(已评分)",
                    "通过率(全部用例)", "平均分(已评分)", "总耗时(s)", "平均耗时(s)",
                    "总token", "平均token/case", "未知用量step数", "trace_id数",
                ],
                overview_rows,
            )
        )
        lines.append("")
        lines.append(
            "说明：`通过率(已评分)` 的分母是成功产出且评分的 case；`通过率(全部用例)` 的分母是全部 case，"
            "缺失评分、评分错误、执行失败、judge 关闭都按“未通过”计入，不会只统计成功案例。"
        )
        lines.append("")

        lines.append("### B2. 逐 case 结果")
        lines.append("")
        case_rows = []
        for experiment in fake_experiment["experiments"]:
            for case in experiment["cases"]:
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
                step = case["step_results"][0] if case["step_results"] else {}
                case_rows.append(
                    [
                        experiment["config_name"],
                        case["case_id"],
                        (case["run_id"] or "")[:8],
                        "—" if case["trace_id"] is None else case["trace_id"][:8],
                        case["status"],
                        case["workflow_status"],
                        case["record_schema_version"],
                        step.get("attempts"),
                        step.get("error_type") or "—",
                        _fmt_seconds(case["elapsed_seconds"]),
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
                    "配置", "case_id", "run_id", "trace_id", "执行状态", "工作流状态",
                    "schema", "attempts", "error_type", "耗时(s)", "token", "usage_type",
                    "分数", "通过", "critical缺失", "评分异常",
                ],
                case_rows,
            )
        )
        lines.append("")

        missing_rows = []
        error_rows = []
        judge_disabled_rows = []
        for experiment in fake_experiment["experiments"]:
            for case in experiment["cases"]:
                if case["missing_score"]:
                    missing_rows.append(
                        [experiment["config_name"], case["case_id"], case.get("score_note") or ""]
                    )
                if case["scoring_error"]:
                    error_rows.append(
                        [experiment["config_name"], case["case_id"], case["scoring_error"]]
                    )
                if case["score_status"] == "judge_disabled":
                    judge_disabled_rows.append(
                        [experiment["config_name"], case["case_id"], "judge=none"]
                    )
        lines.append("### B3. 评分记录完整性")
        lines.append("")
        lines.append(
            f"- 缺失评分（missing_score）记录数：{len(missing_rows)}；"
            f"评分错误（scoring_error）记录数：{len(error_rows)}；"
            f"judge 关闭（judge_disabled）记录数：{len(judge_disabled_rows)}。"
        )
        unknown_steps = sum(
            experiment["metrics"]["tokens"].get("unknown_usage_step_count", 0)
            for experiment in fake_experiment["experiments"]
        )
        unknown_case_ids = sorted(
            {
                case_id
                for experiment in fake_experiment["experiments"]
                for case_id in experiment["metrics"]["tokens"].get("unknown_usage_case_ids", [])
            }
        )
        lines.append(
            f"- 未知用量（usage_type=unknown）步骤数：{unknown_steps}；"
            f"涉及 case：{', '.join(unknown_case_ids) if unknown_case_ids else '无'}。"
            "未知用量不会被当作 0 真实成本，case 记录中的 usage_type 与 unknown_usage_step_count 会显式体现。"
        )
        trace_id_total = sum(
            experiment["metrics"]["execution"].get("trace_id_present_count", 0)
            for experiment in fake_experiment["experiments"]
        )
        lines.append(
            f"- 本次 trace_id 非空记录数：{trace_id_total}（追踪未开启，全部为 null）；"
            "`trace_id` 字段始终写入结果，开启 `--tracing` 且配置 Langfuse 后由后端 run 记录带入。"
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
        if not missing_rows and not error_rows and not judge_disabled_rows:
            lines.append("")
            lines.append("本次假模型实验中每个 case 都产出了评分结果，无缺失评分、无评分错误、无 judge 关闭。")
        lines.append("")

        lines.append("### B4. 如何解读（局限必须连同数字一起阅读）")
        lines.append("")
        failed_ids = sorted(
            {
                case["case_id"]
                for experiment in fake_experiment["experiments"]
                for case in experiment["cases"]
                if case["score"] is not None and not case["score"]["passed"]
            }
        )
        lines.append(
            f"- 假适配器有 {len(failed_ids)} 条预设回答故意答错（{', '.join(failed_ids) or '无'}），"
            "因此通过率 <100% 是**评分器识别失败**的证据，不是模型能力结论。"
        )
        lines.append("- 质量分数反映“预先编写的回答”与“rubric v2（关键词 + critical）”的匹配程度，"
                     "无法判断语义等价表达；关键词覆盖不到的正确答案可能被误判。")
        lines.append("- 固定数据集只有 10 个 case，不具统计代表性；通过率不可外推为总体质量。")
        lines.append("- token 为假适配器按字符长度规则生成的合成值，usage_type 由引擎按“是否返回 usage”判定，"
                     "均不代表真实模型计费。")
        lines.append("- 若步骤用量未知，记录会显式标记 `usage_type=unknown`（并计入“未知用量step数”），"
                     "不会把 0 当作已统计的真实成本；本次假适配器所有步骤均返回 usage。")
        lines.append("- 耗时在毫秒级，受进程调度影响大，仅证明计时字段可用，不可外推到真实模型延迟。")
        lines.append("")

    # ---- C ----
    lines.append("## C. 真实模型实验")
    lines.append("")
    separate = real.get("real_experiment_done_separately")
    if separate and separate.get("status") == "run":
        lines.append("**本基线脚本不运行真实模型（避免自动产生费用）。** 真实模型实验已由独立的受控运行完成：")
        lines.append("")
        lines.append(
            f"- 数据：`{separate['path']}`（生成时间 {separate.get('created_at')}，"
            f"experiment_id `{separate.get('experiment_id')}`）"
        )
        adapter_info = separate.get("adapter") or {}
        judge_info = separate.get("judge") or {}
        lines.append(
            f"- 适配器：mode=`{adapter_info.get('mode')}`，model=`{adapter_info.get('model')}`；"
            f"评分：mode=`{judge_info.get('mode')}`（确定性 rubric，未跑真实 LLM judge）"
        )
        lines.append("")
        rows = []
        for config in separate.get("configs", []):
            rows.append(
                [
                    str(config.get("config")),
                    f"{config.get('completed')}/{config.get('cases')}",
                    f"{config.get('passed')}/{config.get('cases')}",
                    f"{config.get('pass_rate_all_cases')}",
                    str(config.get("total_tokens")),
                    f"{config.get('total_seconds')}",
                    str(config.get("trace_id_present_count")),
                ]
            )
        lines.append(
            _table(
                ["配置", "完成", "通过", "pass_rate_all_cases", "total_tokens", "总耗时(s)", "trace_id 数"],
                rows,
            )
        )
        lines.append("")
        lines.append(
            "- 逐 case 结果与解读见 `docs/EXPERIMENTS_REPORT.md` C1；样本仅 10 个 case，"
            "不能外推总体质量或证明多 Agent 更优。"
        )
        lines.append("")
    lines.append(f"**基线脚本内状态：未运行（status=`{real['status']}`）。**")
    lines.append("")
    lines.append(f"原因：{real['reason']}")
    lines.append("")
    lines.append(f"当前开关检查：`{real['env_flag']}` = "
                 f"`{'1（已设置）' if real['env_flag_set_now'] else '未设置（默认关闭）'}`；"
                 f"`{real.get('judge_env_flag', exp.LLM_JUDGE_ENABLED_ENV)}` = "
                 f"`{'1（已设置）' if real.get('judge_env_flag_set_now') else '未设置（默认关闭）'}`。"
                 "密钥只检查是否存在，不读取、不记录、不打印具体值。")
    lines.append("")
    samples = real.get("estimated_samples") or {}
    if samples:
        lines.append(
            f"预计样本（仅按固定数据集计算，不代表成本）：{samples.get('cases')} 个 case × "
            f"{samples.get('configs')} 个配置 = **{samples.get('executions')} 次执行**；"
            f"若启用 LLM judge，额外 {samples.get('llm_judge_extra_calls_if_enabled')} 次评审调用。"
        )
        lines.append(f"{samples.get('note')}")
        lines.append("")
    lines.append("启用条件：")
    for index, condition in enumerate(real["required_conditions"], 1):
        lines.append(f"{index}. {condition}")
    lines.append("")
    lines.append("启用步骤（示例，密钥请通过环境变量提供，不要写进仓库）：")
    lines.append("")
    lines.append("```bash")
    for step in real["enable_steps"]:
        lines.append(step)
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
    lines.append(
        f"> {real['note']}"
    )
    lines.append("")

    # ---- 复现 ----
    lines.append("## 复现与相关文件")
    lines.append("")
    lines.append("- 本报告：`docs/BASELINE_REPORT.md`")
    lines.append("- 原始结果 JSON：`docs/baseline_results.json`")
    lines.append("- 实验数据与配置：`experiments/`（dataset / expected_answers / configs，各自带版本号）")
    lines.append("- 重跑基线：`cd backend && python scripts/run_baseline.py`")
    lines.append("- 单独跑某配置：`cd backend && python scripts/run_experiment.py --config single|sequential|parallel`")
    lines.append("")
    lines.append("## 未运行 / 未验证项")
    lines.append("")
    for limitation in baseline["limitations"]:
        lines.append(f"- {limitation}")
    lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> int:
    generated_at = _now_iso()
    metadata = {
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cwd": os.getcwd(),
        "project_root": str(PROJECT_ROOT),
        "git": _git_metadata(),
        "empirical": True,
        "note": "本基线所有数字来自本次实际运行；假适配器实验不代表真实模型质量/成本。",
    }

    print("=" * 72)
    print("AgentFlow 基线生成：A 机制验证 + B 假模型实验 + C 真实模型（未运行）")
    print("=" * 72)

    print("\n[A] 运行后端 pytest ...")
    pytest_info = run_pytest()
    print(
        f"    pytest: {pytest_info['passed']} passed, {pytest_info['failed']} failed, "
        f"{pytest_info['errors']} error, {pytest_info['skipped']} skipped "
        f"(exit={pytest_info['exit_code']}, {pytest_info['duration_seconds']}s)"
    )

    dataset_path = exp.DEFAULT_DATASET_PATH
    answers_path = exp.DEFAULT_ANSWERS_PATH
    configs_path = exp.DEFAULT_CONFIGS_PATH

    print("\n[A] 运行补充确定性断言与引擎冒烟 ...")
    mechanism = build_mechanism_checks(dataset_path, answers_path, configs_path)
    for check in mechanism["checks"]:
        print(f"    [{'通过' if check['passed'] else '失败'}] {check['check']}")

    print("\n[B] 运行假模型实验（single / sequential / parallel，全量 case）...")
    fake_experiment_error: Optional[str] = None
    fake_experiment: Optional[Dict[str, Any]] = None
    try:
        fake_experiment = exp.run_experiment(
            configs="all",
            dataset_path=dataset_path,
            answers_path=answers_path,
            configs_path=configs_path,
            adapter_mode="fake",
            judge="deterministic",
        )
        for experiment in fake_experiment["experiments"]:
            metrics = experiment["metrics"]
            quality = metrics["quality"]
            print(
                f"    [{experiment['config_name']}] cases={metrics['case_count']} "
                f"completed={metrics['execution']['completed_count']} "
                f"scored={quality['scored_count']} passed={quality['passed_count']} "
                f"pass_rate_all={quality['pass_rate_all_cases']} "
                f"tokens={metrics['tokens']['total']} "
                f"elapsed={metrics['timing']['total_seconds']}s"
            )
    except Exception as exc:
        fake_experiment_error = exp.scrub_secrets(exc)
        print(f"    假模型实验失败：{fake_experiment_error}")

    if fake_experiment is not None:
        versions = {
            "dataset": {
                "dataset_id": fake_experiment["dataset"]["dataset_id"],
                "dataset_version": fake_experiment["dataset"]["dataset_version"],
                "case_count": fake_experiment["dataset"]["case_count"],
            },
            "config": {
                "config_version": fake_experiment["configs"]["config_version"],
                "names": fake_experiment["configs"]["names"],
            },
            "scorer": dict(fake_experiment["scorer"]),
            "judge": dict(fake_experiment.get("judge") or {}),
        }
    else:
        versions = {
            "dataset": {"dataset_id": None, "dataset_version": None, "case_count": None},
            "config": {"config_version": None, "names": None},
            "scorer": {"version": exp.SCORER_VERSION, "method": "deterministic-rubric-v2"},
            "judge": {"mode": exp.DEFAULT_JUDGE, "network": False},
        }

    real_model = build_real_model_section()

    limitations = [
        "真实模型实验未运行：没有任何真实模型质量、延迟或成本数据；C 节只是受控执行入口。",
        "假适配器输出为人工编写的脚本文本，B 节质量数字只能证明评分/执行/记录链路，不能代表真实模型质量。",
        "评分器为 rubric v2（关键词/短语 + critical 规则），无法评判语义等价、推理过程正确性等；存在误判可能。",
        f"固定数据集只有 {MIN_FIXED_CASES} 个 case，不具统计代表性；结论不可外推到其他任务。",
        "耗时为本机毫秒级调度结果，不能外推为真实模型延迟；token 为假适配器合成值。",
        "本次未开启 Langfuse 追踪，trace_id 全为 null；字段与映射逻辑就绪，但尚未产生真实 trace。",
        "本轮未覆盖并发/多进程/真实网络故障等场景，成功率不代表生产环境可靠性；"
        "后端 v3 的 attempts/error_type 字段已记录，但真实重试/超时未被触发。",
    ]

    baseline: Dict[str, Any] = {
        "report_version": REPORT_VERSION,
        "runner_version": exp.RUNNER_VERSION,
        "generated_at": generated_at,
        "metadata": metadata,
        "versions": versions,
        "mechanism_verification": {
            "pytest": pytest_info,
            "checks": mechanism["checks"],
            "checks_passed": mechanism["checks_passed"],
            "checks_total": mechanism["checks_total"],
            "smoke": mechanism["smoke"],
        },
        "fake_model_experiment": {
            "note": "仅证明机制，不代表真实模型质量/成本；假适配器不联网、不调用付费模型。",
            "adapter_note": (
                "scripted-fake-v1 的输出为预先编写的确定性文本，token 为规则生成的合成值。"
            ),
            "experiment": fake_experiment,
            "error": fake_experiment_error,
        },
        "real_model_experiment": real_model,
        "limitations": limitations,
    }

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    BASELINE_JSON_PATH.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    BASELINE_REPORT_PATH.write_text(_build_report(baseline), encoding="utf-8")

    print(f"\n已生成：{BASELINE_JSON_PATH}")
    print(f"已生成：{BASELINE_REPORT_PATH}")

    success = (
        pytest_info["exit_code"] == 0
        and mechanism["checks_passed"] == mechanism["checks_total"]
        and fake_experiment is not None
    )
    if not success:
        print("\n注意：机制验证或假模型实验存在失败，请查看报告 A/B 节。", file=sys.stderr)
        return 1
    print("\n基线生成完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
