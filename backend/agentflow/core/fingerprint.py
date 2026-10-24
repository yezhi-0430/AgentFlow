"""
配置指纹（Harness²-lite）

指纹回答"两次运行是不是同一套配置"。参与计算的只有会影响结果的配置：
数据集、工作流结构/Agent 配置、执行策略、评分器、模型连接类型；不包含
密钥、base_url、时间戳、run_id、显示名称等。

同配置 → 同指纹；改提示词/参数/模型/步骤 → 指纹变化；换密钥 → 指纹不变。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional

FINGERPRINT_VERSION = 1


def _strip_display_fields(value: Any) -> Any:
    """递归清理不参与指纹的展示字段与敏感字段。"""
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in {
                "api_key", "apikey", "api-key", "secret", "secret_key",
                "access_key", "access_token", "token", "password", "authorization",
                "base_url", "host", "site_url", "app_name", "created_at", "updated_at",
                "description", "workflow_name", "name", "run_id", "trace_id",
            }:
                continue
            if normalized.endswith("_key") or normalized.endswith("_secret") or normalized.endswith("_token"):
                continue
            cleaned[str(key)] = _strip_display_fields(item)
        return cleaned
    if isinstance(value, list):
        return [_strip_display_fields(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def fingerprint_payload(
    *,
    dataset: Optional[Dict[str, Any]] = None,
    config_snapshot: Optional[Dict[str, Any]] = None,
    scorer: Optional[Dict[str, Any]] = None,
    connection: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构造参与指纹的规范化 payload（可用于调试/展示）。"""
    dataset_meta = {}
    if isinstance(dataset, dict):
        dataset_meta = {
            "id": dataset.get("dataset_id") or dataset.get("id"),
            "version": dataset.get("dataset_version") or dataset.get("version"),
        }

    snapshot = config_snapshot or {}
    config = {
        "pattern": snapshot.get("pattern"),
        "max_iterations": snapshot.get("max_iterations"),
        "agents": snapshot.get("agents") or [],
        "steps": snapshot.get("steps") or [],
        "execution_policy": snapshot.get("execution_policy") or {},
    }

    scorer_meta = {}
    if isinstance(scorer, dict):
        scorer_meta = {
            "id": scorer.get("scorer_id") or scorer.get("id") or scorer.get("method"),
            "version": scorer.get("scorer_version") or scorer.get("version"),
            "mode": scorer.get("mode") or scorer.get("judge_mode"),
        }

    connection_meta = {}
    if isinstance(connection, dict):
        connection_meta = {
            "provider": connection.get("provider"),
        }

    return {
        "fingerprint_version": FINGERPRINT_VERSION,
        "dataset": dataset_meta,
        "config": _strip_display_fields(config),
        "scorer": _strip_display_fields(scorer_meta),
        "connection": _strip_display_fields(connection_meta),
    }


def compute_fingerprint(
    *,
    dataset: Optional[Dict[str, Any]] = None,
    config_snapshot: Optional[Dict[str, Any]] = None,
    scorer: Optional[Dict[str, Any]] = None,
    connection: Optional[Dict[str, Any]] = None,
    length: int = 16,
) -> str:
    payload = fingerprint_payload(
        dataset=dataset,
        config_snapshot=config_snapshot,
        scorer=scorer,
        connection=connection,
    )
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return digest[: max(8, min(length, 64))]


def short_fingerprint(fingerprint: Optional[str], length: int = 8) -> str:
    if not fingerprint:
        return "—"
    return fingerprint[: max(4, min(length, 32))]
