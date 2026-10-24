# -*- coding: utf-8 -*-
"""生成 Harness²-lite 候选对比报告（离线、确定性、只读本次实跑结果）。

输入：backend/scripts/run_experiment.py 写出的结果 JSON（默认 docs/harness2_results.json）。
输出：
- docs/harness2_results.json：在原始结果上追加 report 段（实验元数据、候选表、case×候选矩阵、
  评分口径、样本限制、复现命令），数字全部来自本次实际运行；
- docs/HARNESS2_COMPARISON.md：人类可读的候选对比报告。

安全约束：
- 默认只接受 fake 适配器结果（认为报告里的 fake 数据不代表真实模型质量）；真实模型结果需
  显式 --allow-real，并会在报告里标注 adapter=real；
- 报告只使用白名单字段，不含密钥 / base_url；写盘前会递归扫描敏感键与 sk- 形态密钥。

用法：
    cd backend
    python scripts/run_experiment.py --config all --experiment-name "Harness²-lite fake baseline" \
        --evidence --output ../docs/harness2_results.json
    cd ..
    python experiments/build_harness2_report.py
    # 或指定文件：
    python experiments/build_harness2_report.py --results docs/harness2_results.json \
        --markdown docs/HARNESS2_COMPARISON.md
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

try:  # Windows 管道下保证中文输出可写
    for _stream in (sys.stdout, sys.stderr):
        _stream.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

EXPERIMENTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = EXPERIMENTS_DIR.parent
DOCS_DIR = PROJECT_ROOT / "docs"
DEFAULT_RESULTS_PATH = DOCS_DIR / "harness2_results.json"
DEFAULT_MARKDOWN_PATH = DOCS_DIR / "HARNESS2_COMPARISON.md"

REPORT_VERSION = "1.0.0"
REPORT_SCHEMA_VERSION = 1
SUPPORTED_CONFIGS = ("single", "sequential", "parallel")

_SECRET_KEY_NAMES = {
    "api_key",
    "apikey",
    "api-key",
    "secret",
    "secret_key",
    "access_key",
    "access_token",
    "token",
    "password",
    "authorization",
    "base_url",
    "host",
}
_SECRET_VALUE_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{10,}"),
)
_SECRET_KEY_SUFFIXES = ("_key", "_secret", "_token")


class ReportError(RuntimeError):
    """输入结果不可用于生成报告（非 fake 结果、敏感信息、结构非法等）。"""


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise ReportError(f"结果文件不存在：{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReportError(f"结果 JSON 解析失败：{path}（{exc}）") from exc
    if not isinstance(payload, dict):
        raise ReportError(f"结果 JSON 顶层必须是对象：{path}")
    return payload


def _sha256_document(document: Dict[str, Any]) -> str:
    """对去除 report 段后的规范 JSON 求哈希（重建报告时保持稳定）。"""
    source = {key: value for key, value in document.items() if key != "report"}
    payload = json.dumps(
        source, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _fmt_rate(value: Optional[float]) -> str:
    return "—" if value is None else f"{float(value) * 100:.1f}%"


def _fmt_number(value: Optional[float], digits: int = 4) -> str:
    if value is None:
        return "—"
    number = float(value)
    if number == int(number):
        return str(int(number))
    return f"{number:.{digits}f}".rstrip("0").rstrip(".")


def _fmt_seconds(value: Optional[float]) -> str:
    return "—" if value is None else f"{float(value):.4f}"


def _md_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_md_cell(cell) for cell in row) + " |")
    return "\n".join(lines)


def _short_fingerprint(value: Optional[str], length: int = 8) -> str:
    if not value:
        return "—"
    return str(value)[:length]


def _whitelist(mapping: Any, keys: Sequence[str]) -> Dict[str, Any]:
    if not isinstance(mapping, dict):
        return {}
    return {key: mapping.get(key) for key in keys if key in mapping}


# ---------------------------------------------------------------------------
# 安全扫描 / fake-only 校验
# ---------------------------------------------------------------------------

def secret_findings(value: Any, path: str = "") -> List[str]:
    """递归查找敏感键名与密钥形态字符串（只返回路径/类型，不回显值）。"""
    findings: List[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            key_path = f"{path}.{key_text}" if path else key_text
            normalized = key_text.strip().lower()
            if normalized in _SECRET_KEY_NAMES or normalized.endswith(_SECRET_KEY_SUFFIXES):
                findings.append(f"敏感键名：{key_path}")
            findings.extend(secret_findings(item, key_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(secret_findings(item, f"{path}[{index}]"))
    elif isinstance(value, str):
        for pattern in _SECRET_VALUE_PATTERNS:
            if pattern.search(value):
                findings.append(f"疑似密钥值：{path or '<root>'}")
                break
    return findings


def assert_fake_only(document: Dict[str, Any], allow_real: bool = False) -> None:
    """默认只允许 fake 适配器结果生成报告，防止把假数据误当真实模型结论。"""
    adapter = document.get("adapter") or {}
    mode = adapter.get("mode")
    if allow_real:
        return
    if mode != "fake":
        raise ReportError(
            f"只接受 fake 适配器结果（实际 adapter.mode={mode!r}）；"
            "真实模型报告需显式加 --allow-real 并在报告中标注"
        )
    if adapter.get("network") is not False or adapter.get("deterministic") is not True:
        raise ReportError("fake 结果必须满足 network=false 且 deterministic=true")


# ---------------------------------------------------------------------------
# 指标计算（全部来自本次实际运行结果）
# ---------------------------------------------------------------------------

def _case_score(case: Dict[str, Any]) -> Optional[float]:
    payload = case.get("score")
    if not isinstance(payload, dict):
        return None
    value = payload.get("score")
    return float(value) if isinstance(value, (int, float)) else None


def _case_passed(case: Dict[str, Any]) -> bool:
    payload = case.get("score")
    return bool(payload.get("passed")) if isinstance(payload, dict) else False


def _case_failure_type(case: Dict[str, Any]) -> Optional[str]:
    for step in case.get("step_results") or []:
        if isinstance(step, dict) and step.get("error_type"):
            return str(step["error_type"])
    if case.get("failure_reason"):
        return str(case["failure_reason"])
    if case.get("scoring_error_type"):
        return f"scoring:{case['scoring_error_type']}"
    if case.get("status") == "failed":
        return "failed"
    if case.get("status") == "partial":
        return "partial"
    return None


def candidate_metrics(experiment: Dict[str, Any]) -> Dict[str, Any]:
    """一个候选的汇总指标；通过率分母始终是全部 case。"""
    cases = [case for case in (experiment.get("cases") or []) if isinstance(case, dict)]
    total = len(cases)
    status_counts = Counter(str(case.get("status") or "unknown") for case in cases)
    scored = [case for case in cases if _case_score(case) is not None]
    passed = [case for case in scored if _case_passed(case)]
    scores = [float(_case_score(case)) for case in scored]  # type: ignore[arg-type]
    score_status_counts = Counter(
        str(case.get("score_status") or "unknown") for case in cases
    )
    failure_types: Counter = Counter()
    for case in cases:
        failure = _case_failure_type(case)
        if failure:
            failure_types[failure] += 1
    judge_status_counts = Counter(
        str(case["judge_status"]) for case in cases if case.get("judge_status")
    )
    evidence_refs = [case.get("evidence_ref") for case in cases if case.get("evidence_ref")]
    trace_ids = [case.get("trace_id") for case in cases if case.get("trace_id")]

    def _ratio(numerator: int, denominator: int) -> Optional[float]:
        return round(numerator / denominator, 6) if denominator else None

    return {
        "config_name": experiment.get("config_name"),
        "candidate_id": experiment.get("candidate_id"),
        "candidate_name": experiment.get("candidate_name") or experiment.get("config_name"),
        "fingerprint": experiment.get("fingerprint"),
        "short_fingerprint": _short_fingerprint(experiment.get("fingerprint")),
        "cases": total,
        "completed": status_counts.get("completed", 0),
        "partial": status_counts.get("partial", 0),
        "failed": status_counts.get("failed", 0),
        "passed": len(passed),
        "pass_rate_all_cases": _ratio(len(passed), total),
        "scored": len(scored),
        "pass_rate_scored": _ratio(len(passed), len(scored)),
        "mean_score": round(sum(scores) / len(scores), 6) if scores else None,
        "mean_score_all_cases": round(sum(scores) / total, 6) if total else None,
        "total_tokens": sum(int(case.get("total_tokens") or 0) for case in cases),
        "total_seconds": round(
            sum(float(case.get("elapsed_seconds") or 0.0) for case in cases), 6
        ),
        "trace_id_present": len(trace_ids),
        "evidence_ref_present": len(evidence_refs),
        "failure_types": dict(sorted(failure_types.items())),
        "score_status_counts": dict(sorted(score_status_counts.items())),
        "judge_status_counts": dict(sorted(judge_status_counts.items())),
        "score_sources": sorted(
            {str(case["score_source"]) for case in cases if case.get("score_source")}
        ),
    }


def build_case_matrix(experiments: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """case × 候选矩阵；每个格子包含 status/score/score_status/trace_id/evidence_ref 等。"""
    by_config: Dict[str, Dict[str, Dict[str, Any]]] = {}
    case_ids: List[str] = []
    for experiment in experiments:
        config_name = str(experiment.get("config_name") or "")
        by_config[config_name] = {}
        for case in experiment.get("cases") or []:
            if not isinstance(case, dict):
                continue
            case_id = str(case.get("case_id") or "")
            if not case_id:
                continue
            if case_id not in case_ids:
                case_ids.append(case_id)
            by_config[config_name][case_id] = {
                "status": case.get("status"),
                "score": _case_score(case),
                "passed": _case_passed(case) if case.get("score") is not None else None,
                "score_status": case.get("score_status"),
                "score_source": case.get("score_source"),
                "trace_id": case.get("trace_id"),
                "evidence_ref": case.get("evidence_ref"),
                "judge_status": case.get("judge_status"),
                "tokens": int(case.get("total_tokens") or 0),
                "error_type": _case_failure_type(case),
            }
    matrix = []
    for case_id in case_ids:
        matrix.append(
            {
                "case_id": case_id,
                "candidates": {
                    config_name: cells.get(case_id)
                    for config_name, cells in by_config.items()
                },
            }
        )
    return matrix


# ---------------------------------------------------------------------------
# 报告构造
# ---------------------------------------------------------------------------

def _limitations(experiment: Dict[str, Any], candidate_count: int, case_count: int) -> List[str]:
    judge_mode = (experiment.get("judge") or {}).get("mode")
    evidence = experiment.get("evidence") or {}
    tracing = experiment.get("tracing") or {}
    return [
        f"样本量：{case_count} 个固定 case × {candidate_count} 个候选，单轮执行"
        "（无重复 seed、无统计显著性检验/置信区间）；结论仅描述本次运行，不外推总体质量。",
        "适配器：fake 脚本化确定性假模型，回答是预置脚本文本；通过/失败只证明执行、评分、"
        "指纹、证据与报告机制可用，不代表任何真实模型的能力或质量。",
        "token：假适配器自报的确定性计数，仅用于验证计量链路，不代表真实 token/费用。",
        "评分来源：确定性 rubric v2 归一化到 0-1；passed = score >= 阈值且 critical 条目全部命中；"
        "分母始终是全部 case（缺失评分、评分错误、执行失败均按未通过计入），不只统计成功案例。",
        f"独立 judge：本次 judge 模式为 {judge_mode}；judge 失败/超预算/缺失分别记录，"
        "不会被计为通过，也不会改写 deterministic 分数。",
        f"证据：本报告证据开启状态为 {evidence.get('enabled')}（默认关闭）；"
        "证据文件仅本地保存并按保留期清理。",
        f"追踪：tracing.enabled={tracing.get('enabled')}；未启用时 trace_id 为 null，不伪造。",
        "不宣称某个候选最优；真实模型对比必须 --real + 环境门禁 + 受控预算单独执行，"
        "本报告不含真实模型数据。",
    ]


def _experiment_metadata(document: Dict[str, Any]) -> Dict[str, Any]:
    harness2 = document.get("harness2") or {}
    dataset = document.get("dataset") or {}
    configs = document.get("configs") or {}
    scorer = document.get("scorer") or {}
    adapter = _whitelist(
        document.get("adapter"),
        ("mode", "adapter_id", "provider", "model", "network", "deterministic", "note"),
    )
    judge = _whitelist(
        document.get("judge"),
        ("mode", "adapter", "model", "network", "deterministic", "fake_judge", "version", "note"),
    )
    tracing = _whitelist(document.get("tracing"), ("enabled", "provider", "note"))
    evidence = _whitelist(
        (harness2.get("evidence") or {}),
        (
            "enabled",
            "directory_env",
            "retention_days",
            "written_count",
            "pruned_count",
            "prune_error",
        ),
    )
    return {
        "experiment_id": harness2.get("experiment_id"),
        "name": harness2.get("experiment_name"),
        "created_at": document.get("created_at"),
        "runner": _whitelist(document.get("runner"), ("name", "version")),
        "dataset": {
            "id": dataset.get("dataset_id"),
            "version": dataset.get("dataset_version"),
            "path": dataset.get("path"),
            "case_count": dataset.get("case_count"),
            "full_case_count": dataset.get("full_case_count"),
        },
        "config": {
            "version": configs.get("config_version"),
            "path": configs.get("path"),
            "names": configs.get("names"),
        },
        "scorer": {
            "id": scorer.get("id"),
            "version": scorer.get("version"),
            "method": scorer.get("method"),
            "pass_threshold_default": scorer.get("pass_threshold_default"),
            "normalization": scorer.get("normalization"),
            "pass_rule": scorer.get("pass_rule"),
        },
        "adapter": adapter,
        "judge": dict(judge, **(harness2.get("judge") or {})),
        "tracing": tracing,
        "evidence": evidence,
        "persisted": harness2.get("persisted"),
    }


def _sum_judge_status(candidates: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """汇总所有候选的独立 judge 状态计数。"""
    total: Counter = Counter()
    for candidate in candidates:
        for status, count in (candidate.get("judge_status_counts") or {}).items():
            total[str(status)] += int(count)
    return dict(sorted(total.items()))


def _observations(
    candidates: Sequence[Dict[str, Any]],
    matrix: Sequence[Dict[str, Any]],
    judge_mode: Any,
) -> Dict[str, Any]:
    """本次运行的机制观察（不宣称质量结论）。"""
    failed_case_ids = sorted(
        {
            str(row.get("case_id"))
            for row in matrix
            if any(
                isinstance(cell, dict) and cell.get("passed") is False
                for cell in (row.get("candidates") or {}).values()
            )
        }
    )
    errored_case_ids = sorted(
        {
            str(row.get("case_id"))
            for row in matrix
            if any(
                isinstance(cell, dict)
                and cell.get("score_status") not in (None, "scored")
                for cell in (row.get("candidates") or {}).values()
            )
        }
    )
    return {
        "all_candidates_completed_all_cases": all(
            candidate.get("failed") == 0 and candidate.get("cases") == candidate.get("completed")
            for candidate in candidates
        ),
        "failed_case_ids": failed_case_ids,
        "unscored_or_error_case_ids": errored_case_ids,
        "judge_mode": judge_mode,
        "note": (
            "以上只是本次 fake 运行中确定性 rubric 的评分结果（含预先设计的错误回答），"
            "用于验证失败可被如实记录；不构成对候选优劣的判断。"
        ),
    }


def build_report(
    document: Dict[str, Any],
    *,
    allow_real: bool = False,
    source_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """把 runner 结果文档转成候选对比报告数据（不含密钥/base_url）。"""
    if not isinstance(document, dict):
        raise ReportError("结果文档必须是 JSON 对象")
    assert_fake_only(document, allow_real=allow_real)
    findings = secret_findings(document)
    if findings:
        raise ReportError("结果文档包含疑似敏感信息，拒绝生成报告：" + "；".join(findings))

    experiments = [item for item in document.get("experiments") or [] if isinstance(item, dict)]
    if not experiments:
        raise ReportError("结果文档缺少 experiments 数据（先运行 run_experiment.py）")
    experiment_meta = _experiment_metadata(document)
    candidates = [candidate_metrics(experiment) for experiment in experiments]
    matrix = build_case_matrix(experiments)
    case_count = len(matrix)
    judge_mode = (experiment_meta.get("judge") or {}).get("mode")
    evidence_meta = experiment_meta.get("evidence") or {}

    reproduction_results = Path("docs/harness2_results.json").as_posix()
    run_command = "\n".join(
        [
            "cd backend",
            "python scripts/run_experiment.py --config all "
            '--experiment-name "Harness²-lite fake baseline" --evidence '
            f"--output ../{reproduction_results}",
            "cd ..",
            "python experiments/build_harness2_report.py",
        ]
    )
    real_command = "\n".join(
        [
            "cd backend",
            "python scripts/run_experiment.py --config all --real --real-model <model> "
            "--judge llm --judge-budget 50 --evidence "
            "--output ../docs/real_harness2_results.json",
            "# 需 AGENTFLOW_EXPERIMENT_REAL=1（以及 --judge llm 时的 judge 门禁/密钥）；",
            "# 由 Lead 受控执行并复核预算；本报告不含真实模型数据。",
        ]
    )

    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "report_version": REPORT_VERSION,
        "generated_at": _now_iso(),
        "generated_by": "experiments/build_harness2_report.py",
        "experiment": experiment_meta,
        "candidates": candidates,
        "case_matrix": matrix,
        "scoring": {
            "primary_source": "deterministic-rubric-v2（0-1 归一化）",
            "score_source_field": "run.score_source = deterministic",
            "pass_rule": "score >= pass_threshold（默认 0.75）且所有 critical 条目命中",
            "denominator": "全部 case（len(case_matrix)）",
            "pass_rate_all_cases_definition": "passed / 全部 case",
            "mean_score_definition": "已评分 case 的平均分",
            "mean_score_all_cases_definition": "已评分 case 分数之和 / 全部 case（未评分为 0）",
            "total_seconds_definition": "runner 实测每个 case 的 elapsed_seconds 之和（墙钟时间）",
            "independent_judge": {
                "mode": judge_mode,
                "enabled": bool((experiment_meta.get("judge") or {}).get("independent_judge_enabled")),
                "used_for_passed": False,
                "note": "独立 judge 失败/超预算/缺失不会计为通过，也不改写 deterministic 分数。",
            },
            "judge_status_counts": _sum_judge_status(candidates),
        },
        "evidence_summary": {
            "enabled": bool(evidence_meta.get("enabled")),
            "written_count": evidence_meta.get("written_count") or 0,
            "pruned_count": evidence_meta.get("pruned_count") or 0,
            "retention_days": evidence_meta.get("retention_days"),
        },
        "sample": {
            "dataset_id": experiment_meta["dataset"].get("id"),
            "dataset_version": experiment_meta["dataset"].get("version"),
            "case_count": case_count,
            "candidate_count": len(candidates),
            "rounds": 1,
            "adapter_mode": (experiment_meta.get("adapter") or {}).get("mode"),
        },
        "limitations": _limitations(experiment_meta, len(candidates), case_count),
        "observations": _observations(candidates, matrix, judge_mode),
        "reproduction": {
            "run_command": run_command,
            "report_command": "python experiments/build_harness2_report.py",
            "real_model_command": real_command,
            "note": "本报告由 fake 适配器实跑生成；真实模型命令未执行，需 Lead 受控执行。",
        },
        "verification": {
            "fake_only": (experiment_meta.get("adapter") or {}).get("mode") == "fake",
            "secret_scan": "passed",
            "source_results_sha256": source_sha256,
        },
    }


# ---------------------------------------------------------------------------
# Markdown 渲染
# ---------------------------------------------------------------------------

def _cell_text(cell: Optional[Dict[str, Any]]) -> str:
    if not cell:
        return "（无记录）"
    parts = [str(cell.get("status") or "unknown")]
    parts.append(f"score={_fmt_number(cell.get('score'))}")
    parts.append(f"status={cell.get('score_status')}")
    if cell.get("judge_status"):
        parts.append(f"judge={cell.get('judge_status')}")
    trace = cell.get("trace_id")
    parts.append(f"trace={_short_fingerprint(trace, 12) if trace else 'null'}")
    evidence = cell.get("evidence_ref")
    parts.append("evidence=yes" if evidence else "evidence=null")
    if cell.get("error_type"):
        parts.append(f"error={cell.get('error_type')}")
    return " / ".join(parts)


def render_markdown(report: Dict[str, Any]) -> str:
    experiment = report.get("experiment") or {}
    adapter = experiment.get("adapter") or {}
    judge = experiment.get("judge") or {}
    tracing = experiment.get("tracing") or {}
    evidence = experiment.get("evidence") or {}
    dataset = experiment.get("dataset") or {}
    scorer = experiment.get("scorer") or {}
    candidates = report.get("candidates") or []
    matrix = report.get("case_matrix") or []

    lines: List[str] = []
    lines.append("# Harness²-lite 候选对比报告")
    lines.append("")
    lines.append(
        "> 状态：由 fake 适配器实跑生成（不联网、无付费模型调用）；"
        f"生成时间 {report.get('generated_at')}；报告版本 {report.get('report_version')}。"
    )
    lines.append(
        "> 数字全部来自本次运行，可由文末命令复现；**假模型结果只证明机制，不代表真实模型质量**。"
    )
    lines.append("")

    # 1. 实验元数据
    lines.append("## 1. 实验元数据")
    lines.append("")
    judge_budget = judge.get("budget")
    if isinstance(judge_budget, (dict, list)):
        judge_budget_text = json.dumps(judge_budget, ensure_ascii=False)
    else:
        judge_budget_text = judge_budget
    metadata_rows = [
        ("experiment_id", experiment.get("experiment_id")),
        ("实验名称", experiment.get("name")),
        ("创建时间", experiment.get("created_at")),
        ("数据集", f"{dataset.get('id')}@{dataset.get('version')}"),
        (
            "数据文件 / case 数",
            f"{dataset.get('path')}（本次 {dataset.get('case_count')} / 全量 "
            f"{dataset.get('full_case_count')}）",
        ),
        ("配置版本", (experiment.get("config") or {}).get("version")),
        ("运行器", f"{(experiment.get('runner') or {}).get('name')} "
                   f"{(experiment.get('runner') or {}).get('version')}"),
        ("适配器", f"{(adapter.get('mode'))} / {adapter.get('adapter_id') or '—'}；"
                   f"network={adapter.get('network')}，deterministic={adapter.get('deterministic')}"),
        ("评分器", f"{scorer.get('id')}@{scorer.get('version')}（{scorer.get('method')}）"),
        ("judge", f"mode={judge.get('mode')}；network={judge.get('network')}；"
                  f"独立 judge 启用={judge.get('independent_judge_enabled')}；"
                  f"预算={judge_budget_text}"),
        ("tracing", f"enabled={tracing.get('enabled')}；trace_id 缺失记为 null，不伪造"),
        ("evidence", f"enabled={evidence.get('enabled')}；写入 {evidence.get('written_count')} 份；"
                     f"清理 {evidence.get('pruned_count')} 份；保留 {evidence.get('retention_days')} 天；"
                     f"目录由 {evidence.get('directory_env')} 控制"),
        ("数据库持久化", f"persisted={experiment.get('persisted')}（experiments/candidates/runs 已关联）"),
    ]
    lines.append(_table(["字段", "值"], metadata_rows))
    lines.append("")

    # 2. 候选对比表
    lines.append("## 2. 候选对比表（通过率分母 = 全部 case）")
    lines.append("")
    candidate_rows = []
    for candidate in candidates:
        candidate_rows.append(
            [
                candidate.get("candidate_name"),
                candidate.get("candidate_id"),
                _short_fingerprint(candidate.get("fingerprint")),
                candidate.get("fingerprint"),
                candidate.get("cases"),
                candidate.get("completed"),
                candidate.get("failed"),
                candidate.get("passed"),
                _fmt_rate(candidate.get("pass_rate_all_cases")),
                _fmt_number(candidate.get("mean_score")),
                candidate.get("total_tokens"),
                _fmt_seconds(candidate.get("total_seconds")),
                candidate.get("trace_id_present"),
                "、".join(
                    f"{key}×{value}" for key, value in (candidate.get("failure_types") or {}).items()
                )
                or "无",
            ]
        )
    lines.append(
        _table(
            [
                "候选",
                "candidate_id",
                "指纹(短)",
                "指纹(完整)",
                "cases",
                "completed",
                "failed",
                "passed",
                "pass_rate_all_cases",
                "mean_score",
                "total_tokens",
                "total_seconds",
                "trace_id_present",
                "failure_types",
            ],
            candidate_rows,
        )
    )
    lines.append("")
    lines.append(
        "> `mean_score` 为已评分 case 的平均分；`total_seconds` 为 runner 实测墙钟耗时之和；"
        "`failure_types` 统计执行失败/评分失败原因（来自本次运行的 case 记录）。"
    )
    lines.append("")

    # 3. 矩阵
    lines.append("## 3. case × 候选矩阵")
    lines.append("")
    config_names = [str(candidate.get("candidate_name")) for candidate in candidates]
    matrix_rows = []
    for row in matrix:
        cells = row.get("candidates") or {}
        matrix_rows.append(
            [row.get("case_id")] + [_cell_text(cells.get(name)) for name in config_names]
        )
    lines.append(_table(["case_id"] + config_names, matrix_rows))
    lines.append("")
    lines.append(
        "> 单元格格式：`status / score / score_status / judge / trace / evidence / error`；"
        "`score` 为 0-1；`trace` 未开启追踪时为 `null`；`evidence` 默认关闭。"
    )
    lines.append("")

    # 4. 每个候选的评分状态
    lines.append("## 4. 评分状态分布（每个候选）")
    lines.append("")
    status_rows = []
    for candidate in candidates:
        status_rows.append(
            [
                candidate.get("candidate_name"),
                candidate.get("fingerprint"),
                "、".join(
                    f"{key}×{value}"
                    for key, value in (candidate.get("score_status_counts") or {}).items()
                )
                or "—",
                "、".join(
                    f"{key}×{value}"
                    for key, value in (candidate.get("judge_status_counts") or {}).items()
                )
                or "—",
                "、".join(candidate.get("score_sources") or []) or "—",
            ]
        )
    lines.append(
        _table(
            ["候选", "指纹(完整)", "score_status", "judge_status", "score_source"],
            status_rows,
        )
    )
    lines.append("")

    # 5. 评分口径
    scoring = report.get("scoring") or {}
    lines.append("## 5. 评分口径")
    lines.append("")
    for bullet in (
        f"主评分来源：{scoring.get('primary_source')}",
        f"通过规则：{scoring.get('pass_rule')}",
        f"通过率分母：{scoring.get('denominator')}",
        f"累计通过率：{scoring.get('pass_rate_all_cases_definition')}",
        f"平均分：{scoring.get('mean_score_definition')}；全 case 平均分："
        f"{scoring.get('mean_score_all_cases_definition')}",
        f"耗时：{scoring.get('total_seconds_definition')}",
        f"独立 judge 是否用于 passed：{scoring.get('independent_judge', {}).get('used_for_passed')}"
        "（否；judge 失败/超预算/缺失不会冒充通过）",
    ):
        lines.append(f"- {bullet}")
    lines.append("")

    # 6. 本次运行观察
    observations = report.get("observations") or {}
    lines.append("## 6. 本次运行观察（仅机制验证）")
    lines.append("")
    lines.append(
        f"- 所有候选是否全部完成全部 case：{observations.get('all_candidates_completed_all_cases')}"
    )
    lines.append(
        "- deterministic rubric 判为未通过的 case："
        + ("、".join(observations.get("failed_case_ids") or []) or "无")
    )
    lines.append(
        "- 未评分/评分错误/执行失败的 case："
        + ("、".join(observations.get("unscored_or_error_case_ids") or []) or "无")
    )
    lines.append(f"- {observations.get('note')}")
    lines.append("")

    # 7. 样本限制
    lines.append("## 7. 样本限制与不宣称结论")
    lines.append("")
    for limitation in report.get("limitations") or []:
        lines.append(f"- {limitation}")
    lines.append("")

    # 8. 复现
    reproduction = report.get("reproduction") or {}
    lines.append("## 8. 复现命令")
    lines.append("")
    lines.append("```powershell")
    lines.append("# fake 全量运行 + 生成报告（离线、无费用）：")
    lines.append(reproduction.get("run_command") or "")
    lines.append("")
    lines.append("# 真实模型（未执行；仅命令模板，需门禁/预算，由 Lead 受控执行）：")
    lines.append(reproduction.get("real_model_command") or "")
    lines.append("```")
    lines.append("")
    lines.append(
        f"JSON 数据：`docs/harness2_results.json`（`report` 段；"
        f"源结果 sha256={report.get('verification', {}).get('source_results_sha256')}）。"
    )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 写盘 / CLI
# ---------------------------------------------------------------------------

def write_report(
    results_path: Path,
    markdown_path: Path,
    *,
    allow_real: bool = False,
) -> Dict[str, Any]:
    """读取 runner 结果 → 追加 report 段写回 JSON → 渲染 Markdown。"""
    results_path = Path(results_path)
    markdown_path = Path(markdown_path)
    document = _read_json(results_path)
    source_sha = _sha256_document(document)
    report = build_report(document, allow_real=allow_real, source_sha256=source_sha)

    enriched = dict(document)
    enriched["report"] = report
    json_payload = json.dumps(enriched, ensure_ascii=False, indent=2) + "\n"
    markdown = render_markdown(report)

    findings = secret_findings(enriched) + secret_findings(markdown)
    if findings:
        raise ReportError("生成内容包含疑似敏感信息，拒绝写盘：" + "；".join(findings))

    results_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json_payload, encoding="utf-8")
    markdown_path.write_text(markdown, encoding="utf-8")
    return report


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="生成 Harness²-lite 候选对比报告（默认只接受 fake 适配器实跑结果）"
    )
    parser.add_argument(
        "--results",
        type=Path,
        default=DEFAULT_RESULTS_PATH,
        help=f"runner 结果 JSON（默认 {DEFAULT_RESULTS_PATH}）",
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=DEFAULT_MARKDOWN_PATH,
        help=f"Markdown 报告输出路径（默认 {DEFAULT_MARKDOWN_PATH}）",
    )
    parser.add_argument(
        "--allow-real",
        action="store_true",
        help="允许真实模型结果生成报告（默认拒绝，避免把 fake/真实数据混用）",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    try:
        report = write_report(args.results, args.markdown, allow_real=args.allow_real)
    except ReportError as exc:
        print(f"报告生成失败：{exc}", file=sys.stderr)
        return 2
    print(f"报告已写入：{args.markdown}")
    print(f"报告数据已写入：{args.results}（report 段）")
    for candidate in report.get("candidates") or []:
        print(
            "[{name}] cases={cases} passed={passed} pass_rate_all={rate} "
            "mean_score={mean} tokens={tokens} seconds={seconds} fingerprint={fp}".format(
                name=candidate.get("candidate_name"),
                cases=candidate.get("cases"),
                passed=candidate.get("passed"),
                rate=_fmt_rate(candidate.get("pass_rate_all_cases")),
                mean=_fmt_number(candidate.get("mean_score")),
                tokens=candidate.get("total_tokens"),
                seconds=_fmt_seconds(candidate.get("total_seconds")),
                fp=candidate.get("fingerprint"),
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
