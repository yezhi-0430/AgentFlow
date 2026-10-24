"""
执行证据包（Harness²-lite）

每个实验 case 可保存一份脱敏证据：运行记录（含步骤输入输出/错误/用量）、
指纹、trace_id、评分与 judge 结果。默认关闭；开启后只写本地文件。

隐私约束：
- 写入前递归脱敏（API Key/Bearer/连接配置），删除敏感字段；
- 单文件大小受限（默认 200KB），超限逐级截断文本；
- 路径只允许 <experiment>/<candidate>/<case>.json，且读取时校验不越界；
- 提供按保留期清理。
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

from agentflow.core.redaction import redact_text

EVIDENCE_ENABLED_ENV = "AGENTFLOW_EVIDENCE_ENABLED"
EVIDENCE_DIR_ENV = "AGENTFLOW_EVIDENCE_DIR"
EVIDENCE_RETENTION_DAYS_ENV = "AGENTFLOW_EVIDENCE_RETENTION_DAYS"
EVIDENCE_MAX_BYTES_ENV = "AGENTFLOW_EVIDENCE_MAX_BYTES"

DEFAULT_MAX_BYTES = 200_000
DEFAULT_RETENTION_DAYS = 90
EVIDENCE_SCHEMA_VERSION = 1

_SENSITIVE_KEYS = {
    "api_key", "apikey", "api-key", "secret", "secret_key", "access_key",
    "access_token", "token", "password", "authorization",
}
_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9_.-]+")


def evidence_enabled() -> bool:
    return os.getenv(EVIDENCE_ENABLED_ENV, "false").lower() in ("true", "1", "yes")


def evidence_root(directory: Optional[str] = None) -> Path:
    if directory:
        root = Path(directory)
    elif os.getenv(EVIDENCE_DIR_ENV):
        root = Path(os.getenv(EVIDENCE_DIR_ENV))
    else:
        root = Path(__file__).resolve().parents[2] / "evidence"
    return root


def _safe_component(value: str, fallback: str = "unknown") -> str:
    cleaned = _SAFE_COMPONENT.sub("_", str(value or "")).strip("._")
    return cleaned or fallback


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _SENSITIVE_KEYS or normalized.endswith(("_key", "_secret", "_token")):
                continue
            result[str(key)] = _sanitize(item)
        return result
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return redact_text(value, limit=20_000)
    return value


def _truncate_strings(value: Any, limit: int) -> Any:
    if isinstance(value, dict):
        return {key: _truncate_strings(item, limit) for key, item in value.items()}
    if isinstance(value, list):
        return [_truncate_strings(item, limit) for item in value]
    if isinstance(value, str):
        return value[:limit] + ("...[truncated]" if len(value) > limit else "")
    return value


def build_evidence(
    *,
    experiment_id: str,
    candidate_id: str,
    case_id: str,
    fingerprint: Optional[str],
    run,
    dataset: Optional[Dict[str, Any]] = None,
    scorer: Optional[Dict[str, Any]] = None,
    scoring: Optional[Dict[str, Any]] = None,
    judge: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构造脱敏证据字典（尚未落盘）。"""
    evidence = {
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "created_at": time.time(),
        "experiment_id": experiment_id,
        "candidate_id": candidate_id,
        "case_id": case_id,
        "fingerprint": fingerprint,
        "dataset": dataset or {},
        "scorer": scorer or {},
        "run": run.to_dict() if hasattr(run, "to_dict") else run,
        "scoring": scoring or {},
        "judge": judge or {},
        "extra": extra or {},
    }
    return _sanitize(evidence)


def _fit_size(evidence: Dict[str, Any], max_bytes: int) -> Dict[str, Any]:
    for limit in (20_000, 4_000, 1_000, 200):
        candidate = _truncate_strings(evidence, limit)
        payload = json.dumps(candidate, ensure_ascii=False, default=str).encode("utf-8")
        if len(payload) <= max_bytes:
            return candidate
    raise ValueError(f"evidence exceeds max size ({max_bytes} bytes) even after truncation")


def write_evidence(
    evidence: Dict[str, Any],
    *,
    directory: Optional[str] = None,
    max_bytes: Optional[int] = None,
) -> str:
    """写入证据文件，返回相对路径（posix）。"""
    if not evidence_enabled():
        raise RuntimeError("evidence capture is disabled")
    max_bytes = int(max_bytes or os.getenv(EVIDENCE_MAX_BYTES_ENV, DEFAULT_MAX_BYTES))
    fitted = _fit_size(evidence, max_bytes)

    experiment_id = _safe_component(evidence.get("experiment_id", "experiment"))
    candidate_id = _safe_component(evidence.get("candidate_id", "candidate"))
    case_id = _safe_component(evidence.get("case_id", "case"))
    root = evidence_root(directory)
    target = root / experiment_id / candidate_id / f"{case_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(fitted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target.relative_to(root).as_posix()


def read_evidence(ref: str, *, directory: Optional[str] = None) -> Dict[str, Any]:
    """读取证据文件；拒绝路径越界。"""
    root = evidence_root(directory).resolve()
    target = (root / ref).resolve()
    if root not in target.parents and target != root:
        raise ValueError("evidence path escapes root")
    if not target.is_file():
        raise FileNotFoundError(ref)
    return json.loads(target.read_text(encoding="utf-8"))


def prune_evidence(
    *,
    directory: Optional[str] = None,
    retention_days: Optional[float] = None,
) -> int:
    """按保留期删除旧证据文件，返回删除数量。"""
    days = float(
        retention_days if retention_days is not None
        else os.getenv(EVIDENCE_RETENTION_DAYS_ENV, DEFAULT_RETENTION_DAYS)
    )
    if days <= 0:
        return 0
    root = evidence_root(directory)
    if not root.exists():
        return 0
    cutoff = time.time() - days * 86400
    removed = 0
    for path in root.rglob("*.json"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed
