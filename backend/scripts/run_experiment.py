# -*- coding: utf-8 -*-
"""AgentFlow 质量实验运行器 v2.1（默认假适配器，离线、确定性）。

功能：
- 读取冻结的数据集 / 配置 / 预期答案（三者版本号独立）；
- 数据集 case 只含输入字段；答案/评分要点单独存放，加载时拒绝任何答案字段进入数据集；
- 按 single / sequential / parallel 三种配置调用 WorkflowExecutor 执行固定任务；
- 每个 case 记录 run_id、trace_id（追踪启用时，来自 run 记录 / execute 返回值）、
  执行状态、耗时、token、usage_type、score 或 scoring_error / missing_score；
- 评分器 v2：确定性 rubric + critical 条目校准；scoring_error（评分失败）与
  missing_score（缺失评分）分别记录，执行失败的结果绝不拿去评分或冒充成功；
- 可选 LLM judge：--judge deterministic|llm|none，默认 deterministic；
  llm 需要显式设置 AGENTFLOW_EXPERIMENT_LLM_JUDGE=1；假适配器模式下用确定性
  fake judge 只验证链路（不联网），真实 LLM judge 只在真实模型门禁下才可能调用；
- 汇总质量、耗时、token、成功率（分母始终是全部 case，不会只统计成功案例）；
- 真实模型仅供显式开启：需要 AGENTFLOW_EXPERIMENT_REAL=1 + --real + 对应密钥，
  默认关闭；本脚本不会打印任何密钥。

Harness²-lite（复用 agentflow.core，不重写）：
- 每次运行创建 experiment_id（harness2-<hex>）与三个候选记录（single/sequential/parallel），
  候选 ID 为 `<experiment_id>-<config>`（数据库 candidate_id 全局唯一，避免覆盖历史实验）；
- 候选指纹由 agentflow.core.fingerprint 计算（dataset + config snapshot + scorer +
  connection(provider)；不含密钥/base_url）；执行时把 experiment_id / candidate_id /
  case_id / fingerprint 传给 WorkflowExecutor.execute 并落库；
- deterministic rubric 分数归一化到 0-1 并写入 run 记录（score/passed/score_status/
  score_source）；可选独立 judge（AGENTFLOW_EXPERIMENT_LLM_JUDGE=1 + --judge llm，
  预算 --judge-budget 默认 50，失败/超预算/缺失分别记录，绝不拿 judge 失败冒充通过）；
- 可选证据包：--evidence（或 AGENTFLOW_EVIDENCE_ENABLED=true）开启，默认关闭；
  每 case 写脱敏证据并回填 run.evidence_ref，每个实验结束按 90 天保留期清理一次；
- 运行结果新增 harness2 段（experiment/candidates/fingerprints/evidence 统计），
  供 experiments/build_harness2_report.py 生成 docs/HARNESS2_COMPARISON.md 与
  docs/harness2_results.json。

用法：
    cd backend
    python scripts/run_experiment.py --config all
    python scripts/run_experiment.py --config single --limit 2 --judge deterministic \
        --output ../experiments/results_single.json
    python scripts/run_experiment.py --config all --judge none
    python scripts/run_experiment.py --config all --judge llm   # 需 AGENTFLOW_EXPERIMENT_LLM_JUDGE=1
    python scripts/run_experiment.py --config all --experiment-name "harness2 fake" \
        --evidence --output ../docs/harness2_results.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
import unicodedata
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

try:  # Windows 管道下保证中文输出可写
    for _stream in (sys.stdout, sys.stderr):
        _stream.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover - 仅环境兼容
    pass

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

try:
    from agentflow.adapters.base import LLMAdapter
except Exception:  # pragma: no cover - 仅在核心代码暂时不完整时给出清晰错误
    LLMAdapter = None  # type: ignore[assignment]

# Harness²-lite 核心（指纹 / 证据 / 独立评分 / 实验存储）。核心已由 Lead 落地，
# 这里只组合调用，不重复实现；导入失败时降级为旧行为并在结果里显式记录。
try:
    from agentflow.core.evidence import (
        EVIDENCE_DIR_ENV,
        EVIDENCE_ENABLED_ENV,
        EVIDENCE_RETENTION_DAYS_ENV,
        build_evidence,
        evidence_enabled,
        prune_evidence,
        write_evidence,
    )
    from agentflow.core.fingerprint import compute_fingerprint
    from agentflow.core.judge import JudgeBudget, judge_case
    from agentflow.storage import (
        ExperimentRepository,
        RunRepository,
        get_db,
        init_db,
    )

    HARNESS2_AVAILABLE = True
except Exception:  # pragma: no cover - 仅核心代码不完整时降级
    EVIDENCE_DIR_ENV = "AGENTFLOW_EVIDENCE_DIR"
    EVIDENCE_ENABLED_ENV = "AGENTFLOW_EVIDENCE_ENABLED"
    EVIDENCE_RETENTION_DAYS_ENV = "AGENTFLOW_EVIDENCE_RETENTION_DAYS"
    HARNESS2_AVAILABLE = False

EXPERIMENTS_DIR = PROJECT_ROOT / "experiments"
DEFAULT_DATASET_PATH = EXPERIMENTS_DIR / "dataset_v2.json"
DEFAULT_CONFIGS_PATH = EXPERIMENTS_DIR / "configs_v1.json"
DEFAULT_ANSWERS_PATH = EXPERIMENTS_DIR / "expected_answers_v2.json"

RUNNER_VERSION = "2.1.0"
SCORER_VERSION = "2.0.0"
SCORER_ID = "deterministic-rubric-v2"
DEFAULT_PASS_THRESHOLD = 0.75
SUPPORTED_CONFIGS = ("single", "sequential", "parallel")
JUDGE_MODES = ("deterministic", "llm", "none")
DEFAULT_JUDGE = "deterministic"
DEFAULT_JUDGE_BUDGET = 50
EXPERIMENT_ID_PREFIX = "harness2-"
EVIDENCE_RETENTION_DAYS_DEFAULT = 90

REAL_ENABLED_ENV = "AGENTFLOW_EXPERIMENT_REAL"
REAL_PROVIDER_ENV = "AGENTFLOW_EXPERIMENT_PROVIDER"
REAL_MODEL_ENV = "AGENTFLOW_EXPERIMENT_MODEL"
REAL_BASE_URL_ENV = "AGENTFLOW_EXPERIMENT_BASE_URL"
LLM_JUDGE_ENABLED_ENV = "AGENTFLOW_EXPERIMENT_LLM_JUDGE"

# 只记录环境变量名；任何情况下都不打印密钥值。
PROVIDER_KEY_ENVS: Dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}

# 数据集 case 中禁止出现的字段（预期答案/评分要点必须单独存放）。
FORBIDDEN_DATASET_CASE_KEYS = {
    "answer",
    "answers",
    "expected",
    "expected_answer",
    "reference_answer",
    "rubric",
    "scoring",
    "labels",
}

# 递归扫描 case 时，键名包含以下词根即视为疑似答案/评分字段（例如 reference_answers）。
ANSWER_LIKE_KEY_TOKENS = (
    "answer",
    "rubric",
    "expected",
    "reference",
    "scoring",
    "grading",
    "solution",
    "label",
)

# 数据集 case 允许出现的输入字段（其它字段会被拒绝，防止答案夹带）。
ALLOWED_CASE_KEYS = {"case_id", "task", "tags"}

NORMALIZATION_DESCRIPTION = "NFKC + casefold + 连续空白折叠为单个空格，再做子串匹配"

PathLike = Union[str, Path]


class ExperimentConfigError(RuntimeError):
    """实验输入/配置错误（不涉及模型调用）。"""


class ScoringError(RuntimeError):
    """确定性评分器无法完成评分（例如 rubric 结构非法）。"""


class JudgeError(RuntimeError):
    """LLM judge 无法完成评分（调用异常、输出不可解析等）。"""


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _round(value: Optional[float], digits: int = 4) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), digits)


def _read_json(path: PathLike) -> Dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise ExperimentConfigError(f"文件不存在：{path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ExperimentConfigError(f"JSON 解析失败：{path}（{exc}）") from exc
    if not isinstance(data, dict):
        raise ExperimentConfigError(f"JSON 顶层必须是对象：{path}")
    return data


def _display_path(path: Optional[PathLike]) -> Optional[str]:
    """把路径转成便于写入报告的形式：仓库内用相对路径（posix），否则原样。"""
    if path is None:
        return None
    try:
        resolved = Path(path).resolve()
        return resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except (ValueError, OSError):
        return str(path)


def _secret_values() -> List[str]:
    values: List[str] = []
    for env_name in set(PROVIDER_KEY_ENVS.values()):
        value = os.getenv(env_name)
        if value and len(value) >= 8:
            values.append(value)
    return values


def scrub_secrets(text: Any) -> str:
    """把可能出现在异常信息里的密钥值替换掉（只用于安全输出）。"""
    result = str(text)
    for secret in _secret_values():
        if secret in result:
            result = result.replace(secret, "<redacted>")
    return result


def _normalize_text(value: Any) -> str:
    """评分/匹配用的文本规范化：NFKC + casefold + 空白折叠。"""
    text = unicodedata.normalize("NFKC", str(value))
    text = text.casefold()
    return re.sub(r"\s+", " ", text).strip()


def _normalized_contains(normalized_text: str, phrase: Any) -> bool:
    phrase_norm = _normalize_text(phrase)
    return bool(phrase_norm) and phrase_norm in normalized_text


def _enum_value(value: Any) -> Optional[str]:
    """把 Enum/字符串等统一成字符串（None 原样返回）。"""
    if value is None:
        return None
    raw = getattr(value, "value", value)
    if raw is None:
        return None
    return str(raw)


def _coerce_attempts(value: Any) -> Optional[int]:
    """attempts 必须是不小于 1 的整数；旧记录/缺失记为 None，不伪装成 1。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 1:
        return value
    return None


# ---------------------------------------------------------------------------
# 假适配器（确定性脚本模型；不联网、不会产生费用）
# ---------------------------------------------------------------------------

# 按固定任务的独特片段返回预先编写的回答。回答内容是脚本文本，不是真实模型输出；
# 其中 case-003 与 case-009 故意答错，用于验证评分器能记录失败、且报告不会只统计成功案例。
SCRIPTED_FAKE_ANSWERS: Tuple[Tuple[str, str], ...] = (
    (
        "list 与 tuple",
        "list 是可变的，可以随时增删改元素；tuple 是不可变的，适合存放固定记录。",
    ),
    (
        "17 × 23",
        "17 × 23 = 391，计算过程是 17 乘以 23，最终结果为 391。",
    ),
    (
        "HTTP 404",
        "HTTP 404 和 HTTP 500 都是网络错误，主要区别在于颜色不同。",
    ),
    (
        "quick brown fox",
        "敏捷的棕色狐狸跳过了那只懒狗。",
    ),
    (
        "[3, 1, 2]",
        "sorted([3, 1, 2]) 会返回新列表 [1, 2, 3]，不会原地修改原列表。",
    ),
    (
        "== 与 is",
        "== 比较值是否相等，is 比较是否为同一个对象（身份）；例如 [1, 2] == [1, 2] 为 True，"
        "而两个独立列表 is 为 False。",
    ),
    (
        "144 ÷ 12",
        "144 ÷ 12 = 12，可以通过 12 × 12 = 144 验证。",
    ),
    (
        "Actions speak louder than words",
        "行动胜于雄辩。",
    ),
    (
        "'AgentFlow' 反转",
        "可以使用 reverse() 方法原地反转字符串。",
    ),
    (
        "HTTP 301",
        "HTTP 301 和 HTTP 302 的区别是：301 是永久重定向，302 是临时重定向。",
    ),
)


def _last_user_content(messages: List[Dict[str, Any]]) -> str:
    for message in reversed(messages or []):
        if isinstance(message, dict) and message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def _scripted_response(prompt: str) -> str:
    normalized = _normalize_text(prompt)
    for key, answer in SCRIPTED_FAKE_ANSWERS:
        if _normalized_contains(normalized, key):
            return answer
    # 未知任务使用确定性的回显式回答（保留原文，便于测试断言）。
    return f"[fake-adapter] {prompt.strip()}"


class ScriptedFakeAdapter(LLMAdapter if LLMAdapter is not None else object):  # type: ignore[misc]
    """确定性假适配器：同一输入永远得到同一输出与同一 token 计数。"""

    ADAPTER_ID = "scripted-fake-v1"

    def __init__(self) -> None:
        self.call_count = 0

    async def complete(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        self.call_count += 1
        prompt = _last_user_content(messages)  # type: ignore[arg-type]
        content = _scripted_response(prompt)
        prompt_tokens = 8 + len(prompt) // 4
        completion_tokens = 4 + len(content) // 4
        return {
            "content": content,
            "model": model or self.ADAPTER_ID,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "finish_reason": "stop",
        }

    async def stream_complete(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs: Any,
    ):
        result = await self.complete(messages, model, temperature, max_tokens, **kwargs)
        yield result["content"]


# ---------------------------------------------------------------------------
# 数据/配置加载与校验
# ---------------------------------------------------------------------------

def _find_answer_like_fields(value: Any, path: str = "") -> List[str]:
    """递归查找疑似答案/评分字段的键路径（用于数据集防泄漏校验）。"""
    found: List[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            key_path = f"{path}.{key_text}" if path else key_text
            lowered = key_text.casefold()
            if key_text in FORBIDDEN_DATASET_CASE_KEYS or any(
                token in lowered for token in ANSWER_LIKE_KEY_TOKENS
            ):
                found.append(key_path)
                continue
            found.extend(_find_answer_like_fields(child, key_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_find_answer_like_fields(item, f"{path}[{index}]"))
    return found


def load_dataset(path: PathLike = DEFAULT_DATASET_PATH) -> Dict[str, Any]:
    """加载数据集并执行防泄漏校验；返回归一化后的数据集信息。"""
    path = Path(path).resolve()
    document = _read_json(path)

    dataset_id = document.get("dataset_id")
    dataset_version = document.get("dataset_version")
    if not isinstance(dataset_id, str) or not dataset_id.strip():
        raise ExperimentConfigError(f"数据集缺少 dataset_id：{path}")
    if not isinstance(dataset_version, str) or not dataset_version.strip():
        raise ExperimentConfigError(f"数据集缺少 dataset_version：{path}")

    raw_cases = document.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ExperimentConfigError(f"数据集 cases 必须是非空列表：{path}")

    cases: List[Dict[str, Any]] = []
    seen_ids: set = set()
    for index, case in enumerate(raw_cases):
        label = f"cases[{index}]"
        if not isinstance(case, dict):
            raise ExperimentConfigError(f"数据集 {label} 必须是对象：{path}")
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ExperimentConfigError(f"数据集 {label} 缺少非空 case_id：{path}")
        if case_id in seen_ids:
            raise ExperimentConfigError(f"数据集 case_id 重复：{case_id}")
        task = case.get("task")
        if not isinstance(task, str) or not task.strip():
            raise ExperimentConfigError(f"数据集 case {case_id} 缺少非空 task：{path}")
        leaked = _find_answer_like_fields(case)
        if leaked:
            raise ExperimentConfigError(
                f"数据集 case {case_id} 含预期答案/评分字段 {leaked}；"
                "预期答案必须单独存放，禁止进入发送给生成模型的消息"
            )
        extra_keys = sorted(set(case) - ALLOWED_CASE_KEYS)
        if extra_keys:
            raise ExperimentConfigError(
                f"数据集 case {case_id} 含未允许的输入字段 {extra_keys}；"
                f"case 只允许 {sorted(ALLOWED_CASE_KEYS)}，避免答案/评分类内容夹带"
            )
        tags = case.get("tags") or []
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ExperimentConfigError(f"数据集 case {case_id} 的 tags 必须是字符串列表")
        seen_ids.add(case_id)
        cases.append(
            {
                "case_id": case_id,
                "task": task,
                "tags": list(tags),
            }
        )

    answers_file = document.get("answers_file")
    if answers_file is not None and not isinstance(answers_file, str):
        raise ExperimentConfigError(f"数据集 answers_file 必须是字符串：{path}")
    return {
        "path": str(path),
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "answers_file": answers_file,
        "cases": cases,
        "case_count": len(cases),
    }


def load_configs(path: PathLike = DEFAULT_CONFIGS_PATH) -> Dict[str, Any]:
    """加载三种冻结配置；只允许已支持配置名，避免拼写错误悄悄生效。"""
    path = Path(path).resolve()
    document = _read_json(path)

    config_version = document.get("config_version")
    if not isinstance(config_version, str) or not config_version.strip():
        raise ExperimentConfigError(f"配置缺少 config_version：{path}")

    defaults = document.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ExperimentConfigError(f"配置 defaults 必须是对象：{path}")
    default_model = defaults.get("fake_model") or ScriptedFakeAdapter.ADAPTER_ID

    raw_configs = document.get("configs")
    if not isinstance(raw_configs, dict) or not raw_configs:
        raise ExperimentConfigError(f"配置 configs 必须是非空对象：{path}")

    configs: Dict[str, Dict[str, Any]] = {}
    for name, raw in raw_configs.items():
        if name not in SUPPORTED_CONFIGS:
            raise ExperimentConfigError(f"不支持的配置名：{name}（支持 {SUPPORTED_CONFIGS}）")
        if not isinstance(raw, dict):
            raise ExperimentConfigError(f"配置 {name} 必须是对象：{path}")
        pattern = raw.get("pattern")
        if pattern != name:
            raise ExperimentConfigError(f"配置 {name} 的 pattern 必须是 {name!r}，实际为 {pattern!r}")
        # 实验层名称（single/sequential/parallel）≠ 引擎模式；引擎只支持 sequential/parallel。
        engine_pattern = raw.get("engine_pattern")
        if engine_pattern not in ("sequential", "parallel"):
            raise ExperimentConfigError(
                f"配置 {name} 的 engine_pattern 必须是 'sequential' 或 'parallel'，"
                f"实际为 {engine_pattern!r}（引擎不支持其它模式）"
            )
        expected_engine_pattern = "parallel" if name == "parallel" else "sequential"
        if engine_pattern != expected_engine_pattern:
            raise ExperimentConfigError(
                f"配置 {name} 的 engine_pattern 必须是 {expected_engine_pattern!r}，"
                f"实际为 {engine_pattern!r}"
            )
        steps = raw.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ExperimentConfigError(f"配置 {name} 的 steps 必须是非空列表")
        if name == "single" and len(steps) != 1:
            raise ExperimentConfigError("single 配置必须恰好有 1 个步骤")
        if name in ("sequential", "parallel") and len(steps) < 2:
            raise ExperimentConfigError(f"{name} 配置至少需要 2 个步骤")

        clean_steps: List[Dict[str, str]] = []
        seen_step_ids: set = set()
        for step_index, step in enumerate(steps):
            if not isinstance(step, dict):
                raise ExperimentConfigError(f"配置 {name} steps[{step_index}] 必须是对象")
            step_id = step.get("step_id")
            agent_name = step.get("agent_name")
            system_prompt = step.get("system_prompt")
            if not isinstance(step_id, str) or not step_id.strip():
                raise ExperimentConfigError(f"配置 {name} steps[{step_index}] 缺少 step_id")
            if step_id in seen_step_ids:
                raise ExperimentConfigError(f"配置 {name} 的 step_id 重复：{step_id}")
            if not isinstance(agent_name, str) or not agent_name.strip():
                raise ExperimentConfigError(f"配置 {name} 的步骤 {step_id} 缺少 agent_name")
            if not isinstance(system_prompt, str) or not system_prompt.strip():
                raise ExperimentConfigError(f"配置 {name} 的步骤 {step_id} 缺少 system_prompt")
            seen_step_ids.add(step_id)
            clean_steps.append(
                {
                    "step_id": step_id,
                    "agent_name": agent_name,
                    "system_prompt": system_prompt,
                }
            )

        temperature = raw.get("temperature", defaults.get("temperature", 0.0))
        max_tokens = raw.get("max_tokens", defaults.get("max_tokens", 512))
        configs[name] = {
            "name": name,
            "pattern": name,
            "engine_pattern": engine_pattern,
            "description": raw.get("description") or "",
            "model": raw.get("model") or default_model,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
            "steps": clean_steps,
        }

    return {
        "path": str(path),
        "config_version": config_version,
        "defaults": defaults,
        "configs": configs,
    }


def load_answers(
    path: Optional[PathLike],
    dataset: Dict[str, Any],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """读取预期答案，返回 case_id -> 评分规则 的索引与元信息。

    文件缺失不算评分错误：对应 case 会以 missing_score=True 记录；
    文档级版本不匹配才是配置错误，直接拒绝运行。
    """
    meta: Dict[str, Any] = {
        "path": str(path) if path is not None else None,
        "present": False,
        "scorer_version": None,
        "answer_case_count": 0,
        "missing_case_ids": [case["case_id"] for case in dataset["cases"]],
        "unused_case_ids": [],
        "calibration": {},
        "error": None,
    }
    if path is None or not Path(path).is_file():
        meta["error"] = "预期答案文件不存在；所有 case 将记录 missing_score"
        return {}, meta

    path = Path(path).resolve()
    document = _read_json(path)
    meta["path"] = str(path)

    for field, actual in (
        ("dataset_id", dataset["dataset_id"]),
        ("dataset_version", dataset["dataset_version"]),
    ):
        expected = document.get(field)
        if isinstance(expected, str) and expected != actual:
            raise ExperimentConfigError(
                f"预期答案文件 {field}={expected!r} 与数据集 {actual!r} 不一致"
            )

    scorer_version = document.get("scorer_version")
    if scorer_version is not None:
        if not isinstance(scorer_version, str) or not scorer_version.strip():
            raise ExperimentConfigError(f"预期答案文件 scorer_version 非法：{scorer_version!r}")
        meta["scorer_version"] = scorer_version
        if scorer_version != SCORER_VERSION:
            raise ExperimentConfigError(
                f"评分器版本不匹配：文件为 {scorer_version}，运行器为 {SCORER_VERSION}"
            )

    calibration = document.get("calibration") or {}
    if not isinstance(calibration, dict):
        raise ExperimentConfigError(f"预期答案文件 calibration 必须是对象：{path}")
    meta["calibration"] = calibration

    raw_answers = document.get("answers")
    if not isinstance(raw_answers, list):
        raise ExperimentConfigError("预期答案文件 answers 必须是列表")

    index: Dict[str, Dict[str, Any]] = {}
    for answer_index, spec in enumerate(raw_answers):
        if not isinstance(spec, dict):
            raise ExperimentConfigError(f"answers[{answer_index}] 必须是对象")
        case_id = spec.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ExperimentConfigError(f"answers[{answer_index}] 缺少非空 case_id")
        if case_id in index:
            index[case_id] = {"_scoring_error": f"预期答案中 case_id 重复：{case_id}"}
            continue
        index[case_id] = spec

    dataset_case_ids = {case["case_id"] for case in dataset["cases"]}
    meta["present"] = True
    meta["answer_case_count"] = len(index)
    meta["missing_case_ids"] = sorted(dataset_case_ids - set(index))
    meta["unused_case_ids"] = sorted(set(index) - dataset_case_ids)
    return index, meta


# ---------------------------------------------------------------------------
# 评分器 v2（确定性 rubric + critical 校准；评分失败与缺失评分分开表达）
# ---------------------------------------------------------------------------

def _resolve_threshold(spec: Dict[str, Any]) -> float:
    threshold = spec.get("pass_threshold", DEFAULT_PASS_THRESHOLD)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ScoringError(f"pass_threshold 非法：{threshold!r}")
    if not 0 <= float(threshold) <= 1:
        raise ScoringError(f"pass_threshold 必须在 [0, 1]：{threshold!r}")
    return float(threshold)


def score_output(output: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    """对一条输出按 rubric v2 打分；结构非法时抛 ScoringError。

    通过标准（写入 expected_answers_v2.json 的 calibration）：
    - score = 命中条目权重和 / 全部条目权重和；
    - passed = score >= pass_threshold 且所有 critical 条目命中。
    """
    rubric = spec.get("rubric")
    if not isinstance(rubric, list) or not rubric:
        raise ScoringError("预期答案缺少非空 rubric")

    threshold = _resolve_threshold(spec)
    normalized = _normalize_text(output)
    matched_items: List[str] = []
    missed_items: List[str] = []
    critical_items: List[str] = []
    total_weight = 0.0
    matched_weight = 0.0

    for item_index, item in enumerate(rubric):
        if not isinstance(item, dict):
            raise ScoringError(f"rubric[{item_index}] 必须是对象")
        item_id = item.get("item_id") or f"item-{item_index + 1}"
        item_id = str(item_id)
        weight = item.get("weight", 1)
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight <= 0:
            raise ScoringError(f"rubric 条目 {item_id} 的 weight 必须是正数")
        all_of = item.get("all_of") or []
        any_of = item.get("any_of") or []
        if not isinstance(all_of, list) or not isinstance(any_of, list):
            raise ScoringError(f"rubric 条目 {item_id} 的 all_of/any_of 必须是列表")
        if not all_of and not any_of:
            raise ScoringError(f"rubric 条目 {item_id} 至少需要 all_of 或 any_of 之一")
        critical = item.get("critical", False)
        if not isinstance(critical, bool):
            raise ScoringError(f"rubric 条目 {item_id} 的 critical 必须是布尔值")

        hit = all(_normalized_contains(normalized, phrase) for phrase in all_of) and (
            not any_of or any(_normalized_contains(normalized, phrase) for phrase in any_of)
        )
        total_weight += float(weight)
        if critical:
            critical_items.append(item_id)
        if hit:
            matched_weight += float(weight)
            matched_items.append(item_id)
        else:
            missed_items.append(item_id)

    if total_weight <= 0:
        raise ScoringError("rubric 权重总和必须为正")

    score = round(matched_weight / total_weight, 4)
    passed_score_only = score >= threshold
    critical_missed_items = [item_id for item_id in missed_items if item_id in set(critical_items)]
    passed = passed_score_only and not critical_missed_items
    reason = (
        f"命中 {len(matched_items)}/{len(rubric)} 个评分点"
        f"（权重 {_round(matched_weight)}/{_round(total_weight)}，score={score}）；"
        f"阈值 {threshold}；critical 缺失：{critical_missed_items or '无'} → "
        f"{'通过' if passed else '不通过'}"
    )
    return {
        "method": "deterministic-rubric-v2",
        "score": score,
        "passed": passed,
        "passed_score_only": passed_score_only,
        "pass_threshold": threshold,
        "matched_items": matched_items,
        "missed_items": missed_items,
        "critical_items": critical_items,
        "critical_missed_items": critical_missed_items,
        "rubric_item_count": len(rubric),
        "weight_total": _round(total_weight),
        "weight_matched": _round(matched_weight),
        "normalization": NORMALIZATION_DESCRIPTION,
        "scorer_version": SCORER_VERSION,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Judge：确定性 rubric（默认）/ 可选 LLM judge（显式开关）
# ---------------------------------------------------------------------------

class DeterministicJudge:
    """默认 judge：直接调用确定性 rubric v2，不联网、可复现。"""

    ADAPTER_ID = "deterministic-rubric-v2"

    async def evaluate(
        self,
        task: str,
        spec: Dict[str, Any],
        output: str,
    ) -> Dict[str, Any]:
        verdict = score_output(output, spec)
        verdict.update(
            {
                "judge_mode": "deterministic",
                "judge_adapter": self.ADAPTER_ID,
                "judge_model": None,
                "judge_network": False,
            }
        )
        return verdict


class ScriptedFakeJudge:
    """假适配器模式下的确定性 judge：返回固定格式 JSON，仅用于验证 LLM judge 链路。

    它不是真实 LLM，不联网、不产生费用；其分数由确定性 rubric 生成，
    因此不能代表真实 LLM 评审质量。
    """

    ADAPTER_ID = "scripted-fake-judge-v1"

    def __init__(self) -> None:
        self.call_count = 0

    def raw_verdict(self, spec: Dict[str, Any], output: str) -> str:
        self.call_count += 1
        deterministic = score_output(output, spec)
        payload = {
            "score": deterministic["score"],
            "critical_missed_items": deterministic["critical_missed_items"],
            "reason": f"[scripted-fake-judge] {deterministic['reason']}",
        }
        return json.dumps(payload, ensure_ascii=False)


def build_judge_messages(task: str, spec: Dict[str, Any], output: str) -> List[Dict[str, str]]:
    """构造 LLM judge 消息。

    注意：这里包含参考要点，但只在执行结束后的评分阶段使用，绝不会进入生成模型上下文。
    """
    rubric_lines: List[str] = []
    rubric = spec.get("rubric")
    if isinstance(rubric, list):
        for index, item in enumerate(rubric):
            if not isinstance(item, dict):
                continue
            item_id = item.get("item_id") or f"item-{index + 1}"
            critical = "（critical）" if item.get("critical") else ""
            rubric_lines.append(
                f"- {item_id}{critical}：{item.get('description') or ''}；"
                f"all_of={item.get('all_of') or []}；any_of={item.get('any_of') or []}；"
                f"weight={item.get('weight', 1)}"
            )
    threshold = spec.get("pass_threshold", DEFAULT_PASS_THRESHOLD)
    system_prompt = (
        "你是严格的评测员。请依据任务、参考要点与 rubric 评估候选答案。"
        "只输出一个 JSON 对象，不要输出 Markdown 或其它文字；字段为："
        '{"score": 0 到 1 的数字, "critical_missed_items": [未命中的 critical 条目 id], '
        '"reason": "简短中文理由"}。'
    )
    user_prompt = "\n".join(
        [
            f"任务：{task}",
            "",
            "候选答案：",
            output,
            "",
            f"参考要点：{spec.get('reference_answer') or '（未提供）'}",
            "",
            f"通过阈值：{threshold}（score >= 阈值且 critical 条目全部命中才算通过）",
            "rubric：",
            "\n".join(rubric_lines) or "（未提供）",
        ]
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _parse_judge_verdict(raw: Any, spec: Dict[str, Any]) -> Dict[str, Any]:
    """解析 LLM judge 的 JSON 输出；任何问题都抛 JudgeError（记录为 scoring_error）。"""
    if not isinstance(raw, str) or not raw.strip():
        raise JudgeError("judge 返回为空")
    threshold = _resolve_threshold(spec)
    text = raw.strip()
    if "```" in text:
        # 去掉 Markdown 代码围栏，保留其中内容
        parts = [part for part in text.split("```") if part.strip()]
        if parts:
            text = parts[0].strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise JudgeError("judge 输出中没有 JSON 对象")
    payload_text = text[start : end + 1]
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise JudgeError(f"judge 输出不是合法 JSON：{exc}") from exc
    if not isinstance(payload, dict):
        raise JudgeError("judge 输出的 JSON 顶层必须是对象")

    score = payload.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise JudgeError(f"judge score 必须是 0-1 的数字，实际为 {score!r}")
    score = float(score)
    if not 0 <= score <= 1:
        raise JudgeError(f"judge score 必须在 [0, 1]，实际为 {score!r}")

    critical_missed = payload.get("critical_missed_items") or []
    if not isinstance(critical_missed, list):
        raise JudgeError("judge critical_missed_items 必须是列表")
    critical_missed_items = [str(item_id) for item_id in critical_missed]
    reason = payload.get("reason") or ""
    if not isinstance(reason, str):
        reason = str(reason)

    score = round(score, 4)
    passed_score_only = score >= threshold
    passed = passed_score_only and not critical_missed_items
    return {
        "method": "llm-judge",
        "score": score,
        "passed": passed,
        "passed_score_only": passed_score_only,
        "pass_threshold": threshold,
        "matched_items": None,
        "missed_items": None,
        "critical_items": [
            str(item.get("item_id") or f"item-{index + 1}")
            for index, item in enumerate(spec.get("rubric") or [])
            if isinstance(item, dict) and item.get("critical")
        ],
        "critical_missed_items": critical_missed_items,
        "rubric_item_count": len(spec.get("rubric") or []),
        "normalization": "由 LLM judge 自行判断（不保证确定性）",
        "scorer_version": SCORER_VERSION,
        "judge_reason": reason[:500],
        "judge_raw_excerpt": scrub_secrets(text[:500]),
        "reason": reason[:500] or "judge 未提供理由",
    }


class LLMJudge:
    """可选 LLM judge：真实模式调用模型；假适配器模式使用确定性 fake judge 验证链路。"""

    def __init__(
        self,
        adapter: Any = None,
        model: Optional[str] = None,
        adapter_id: Optional[str] = None,
        fake_judge: Optional[ScriptedFakeJudge] = None,
    ) -> None:
        self.adapter = adapter
        self.model = model
        self.adapter_id = adapter_id
        self.fake_judge = fake_judge

    async def evaluate(
        self,
        task: str,
        spec: Dict[str, Any],
        output: str,
    ) -> Dict[str, Any]:
        if self.fake_judge is not None:
            raw = self.fake_judge.raw_verdict(spec, output)
            extra = {
                "judge_mode": "llm",
                "judge_adapter": ScriptedFakeJudge.ADAPTER_ID,
                "judge_model": None,
                "judge_network": False,
            }
        else:
            messages = build_judge_messages(task, spec, output)
            try:
                response = await self.adapter.complete(
                    messages,
                    self.model or "",
                    temperature=0.0,
                    max_tokens=512,
                )
            except Exception as exc:  # noqa: BLE001 - judge 调用失败要显式记录
                raise JudgeError(
                    f"judge 调用失败（{type(exc).__name__}: {scrub_secrets(exc)}）"
                ) from exc
            content = response.get("content") if isinstance(response, dict) else getattr(
                response, "content", None
            )
            raw = content if isinstance(content, str) else ""
            extra = {
                "judge_mode": "llm",
                "judge_adapter": self.adapter_id,
                "judge_model": self.model,
                "judge_network": True,
            }
        verdict = _parse_judge_verdict(raw, spec)
        verdict.update(extra)
        return verdict


def _create_judge(
    judge_mode: str,
    adapter_mode: str,
    adapter: Any,
    adapter_info: Dict[str, Any],
) -> Tuple[Any, Dict[str, Any]]:
    """按 --judge 创建 judge 并返回可写入结果的元信息。"""
    if judge_mode not in JUDGE_MODES:
        raise ExperimentConfigError(f"未知 judge 模式：{judge_mode!r}（支持 {JUDGE_MODES}）")

    if judge_mode == "deterministic":
        return DeterministicJudge(), {
            "mode": "deterministic",
            "adapter": DeterministicJudge.ADAPTER_ID,
            "model": None,
            "network": False,
            "deterministic": True,
            "version": SCORER_VERSION,
            "pass_threshold_default": DEFAULT_PASS_THRESHOLD,
            "note": (
                "确定性 rubric 评分（默认）：不联网、可复现；阈值与 critical 规则来自 "
                "expected_answers 的 calibration。"
            ),
        }

    if judge_mode == "none":
        return None, {
            "mode": "none",
            "adapter": None,
            "model": None,
            "network": False,
            "deterministic": True,
            "version": SCORER_VERSION,
            "note": (
                "评分被显式关闭：所有 case 记录 score_status=judge_disabled，"
                "不计入 missing_score / scoring_error，也不计入通过数。"
            ),
        }

    # judge == "llm"：必须显式打开门禁，默认不联网、不产生费用。
    if os.getenv(LLM_JUDGE_ENABLED_ENV) != "1":
        raise ExperimentConfigError(
            f"LLM judge 已禁用：需显式设置 {LLM_JUDGE_ENABLED_ENV}=1（默认关闭，"
            "避免误调付费模型；真实 judge 还会产生额外费用）"
        )

    if adapter_mode == "real":
        model = adapter_info.get("model")
        provider = adapter_info.get("provider")
        judge = LLMJudge(
            adapter=adapter,
            model=model,
            adapter_id=f"real:{provider}:{model}",
        )
        return judge, {
            "mode": "llm",
            "adapter": f"real:{provider}",
            "model": model,
            "network": True,
            "deterministic": False,
            "fake_judge": False,
            "version": SCORER_VERSION,
            "note": (
                "真实 LLM judge：会额外调用付费模型；仅在 --real + 真实模型门禁 + "
                f"{LLM_JUDGE_ENABLED_ENV}=1 同时满足时运行。"
            ),
        }

    fake_judge = ScriptedFakeJudge()
    judge = LLMJudge(fake_judge=fake_judge)
    return judge, {
        "mode": "llm",
        "adapter": ScriptedFakeJudge.ADAPTER_ID,
        "model": None,
        "network": False,
        "deterministic": True,
        "fake_judge": True,
        "version": SCORER_VERSION,
        "note": (
            "假适配器模式下的确定性 fake judge：只验证 judge 调用/解析/记录链路，"
            "不联网、不产生费用；它不是真实 LLM 评审，分数不代表真实评审质量。"
        ),
    }


# ---------------------------------------------------------------------------
# 执行引擎装配
# ---------------------------------------------------------------------------

def _workflow_pattern(engine_pattern: str):
    from agentflow.core.workflow import WorkflowPattern

    if engine_pattern == "parallel":
        return WorkflowPattern.PARALLEL
    if engine_pattern == "sequential":
        return WorkflowPattern.SEQUENTIAL
    raise ExperimentConfigError(
        f"引擎不支持的模式：{engine_pattern!r}（只支持 sequential / parallel）"
    )


def build_workflow_config(
    config_name: str,
    config_def: Dict[str, Any],
    model_override: Optional[str] = None,
):
    """把冻结配置转换成 WorkflowConfig；消息中只包含 system prompt + case.task。"""
    from agentflow.core.agent import AgentConfig, AgentRole
    from agentflow.core.workflow import WorkflowConfig, WorkflowStep

    model = model_override or config_def["model"]
    agents = []
    steps = []
    for step in config_def["steps"]:
        agents.append(
            AgentConfig(
                name=step["agent_name"],
                role=AgentRole.WORKER,
                system_prompt=step["system_prompt"],
                model=model,
                temperature=config_def["temperature"],
                max_tokens=config_def["max_tokens"],
            )
        )
        steps.append(WorkflowStep(id=step["step_id"], agent_name=step["agent_name"]))

    return WorkflowConfig(
        name=f"experiment-{config_name}",
        pattern=_workflow_pattern(config_def["engine_pattern"]),
        steps=steps,
        agents=agents,
        max_iterations=1,
    )


def _aggregate_usage_type(run: Any) -> str:
    if run is None:
        return "unknown"
    types = [
        _enum_value(step.usage_type)
        for step in run.step_results
        if getattr(step, "usage_type", None) is not None
    ]
    types = [value for value in types if value]
    if not types:
        return "unknown"
    unique = set(types)
    if len(unique) == 1:
        return types[0]
    return "mixed"


def _extract_output(exec_result: Dict[str, Any], run: Any) -> Tuple[str, Optional[str]]:
    payload = exec_result.get("result")
    if isinstance(payload, dict):
        final_result = payload.get("final_result")
        if isinstance(final_result, str) and final_result.strip():
            return final_result, "final_result"
        aggregated = payload.get("aggregated")
        if isinstance(aggregated, str) and aggregated.strip():
            return aggregated, "aggregated"
    if run is not None and isinstance(run.final_result, str) and run.final_result.strip():
        return run.final_result, "run.final_result"
    return "", None


def resolve_trace_id(
    exec_result: Optional[Dict[str, Any]] = None,
    run: Any = None,
) -> Tuple[Optional[str], Optional[str]]:
    """从执行结果/run 记录读取 trace_id（兼容 v3 字段与不同调用路径）。

    顺序：execute() 返回值 -> run.trace_id -> run.to_dict()["trace_id"]。
    未启用追踪或追踪初始化失败时返回 (None, None)，绝不伪造 trace_id。
    """
    candidates: List[Tuple[str, Any]] = []
    if isinstance(exec_result, dict):
        candidates.append(("exec_result", exec_result.get("trace_id")))
    if run is not None:
        candidates.append(("run.trace_id", getattr(run, "trace_id", None)))
        to_dict = getattr(run, "to_dict", None)
        if callable(to_dict):
            try:
                candidates.append(("run.to_dict", to_dict().get("trace_id")))
            except Exception:  # noqa: BLE001 - 读取详情失败不能影响主流程
                pass
    for source, value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip(), source
    return None, None


def _step_records(run: Any, message_history: Sequence[Any]) -> List[Dict[str, Any]]:
    """把 run.step_results 转成可追溯步骤记录（含 v3 的 attempts/error_type）。"""
    message_outputs = {
        getattr(message, "id", None): getattr(message, "content", "")
        for message in message_history
    }
    records: List[Dict[str, Any]] = []
    if run is None:
        return records
    for step in run.step_results:
        input_text = getattr(step, "input_text", None)
        output_text = getattr(step, "output_text", None)
        if output_text is None:
            output_text = message_outputs.get(step.output_message_id) or ""
        output_excerpt = output_text if len(output_text) <= 300 else output_text[:300] + "..."
        usage = step.usage or {}
        usage_type = _enum_value(step.usage_type)
        records.append(
            {
                "step_id": step.step_id,
                "step_index": getattr(step, "step_index", None),
                "agent_name": step.agent_name,
                "status": _enum_value(step.status),
                "attempts": _coerce_attempts(getattr(step, "attempts", None)),
                "error_type": _enum_value(getattr(step, "error_type", None)),
                "model": getattr(step, "model", None),
                "finish_reason": getattr(step, "finish_reason", None),
                "duration_seconds": _round(step.duration),
                "total_tokens": int(usage.get("total_tokens") or 0),
                "usage_type": usage_type,
                "usage_unknown": usage_type == "unknown",
                "error": scrub_secrets(step.error) if step.error else None,
                "input_chars": len(input_text or ""),
                "output_excerpt": output_excerpt,
            }
        )
    return records


# ---------------------------------------------------------------------------
# Harness²-lite：实验/候选/指纹/评分持久化/独立 judge/证据
# ---------------------------------------------------------------------------

def build_config_snapshot(
    config_name: str,
    config_def: Dict[str, Any],
    model_override: Optional[str] = None,
) -> Dict[str, Any]:
    """构造参与指纹的配置快照。

    复用引擎的配置快照（pattern / steps / execution_policy / agents 参数），并显式补上
    system prompt——提示词是影响输出的关键配置，必须参与指纹。密钥/base_url 不在此处出现，
    且 compute_fingerprint 会再次剔除敏感字段。
    """
    workflow_config = build_workflow_config(config_name, config_def, model_override=model_override)
    prompts = [step["system_prompt"] for step in config_def["steps"]]
    try:
        from agentflow.core.workflow import WorkflowExecutor

        snapshot = WorkflowExecutor(
            workflow_config, enable_persistence=False, enable_tracing=False
        )._config_snapshot()
        for agent_entry, prompt in zip(snapshot.get("agents") or [], prompts):
            agent_entry["system_prompt"] = prompt
        return snapshot
    except Exception:  # pragma: no cover - 引擎异常时使用等价手工快照
        model = model_override or config_def["model"]
        return {
            "name": f"experiment-{config_name}",
            "pattern": config_def["engine_pattern"],
            "max_iterations": 1,
            "execution_policy": {
                "step_timeout_seconds": 0.0,
                "max_attempts": 1,
                "record_text_limit": 20000,
            },
            "steps": [
                {"id": step["step_id"], "agent_name": step["agent_name"], "input_from": None}
                for step in config_def["steps"]
            ],
            "agents": [
                {
                    "name": step["agent_name"],
                    "role": "worker",
                    "system_prompt": step["system_prompt"],
                    "model": model,
                    "temperature": config_def["temperature"],
                    "max_tokens": config_def["max_tokens"],
                }
                for step in config_def["steps"]
            ],
        }


def build_candidate_fingerprint(
    config_name: str,
    config_def: Dict[str, Any],
    *,
    dataset: Dict[str, Any],
    scorer: Dict[str, Any],
    connection: Dict[str, Any],
    model_override: Optional[str] = None,
) -> str:
    """候选指纹：dataset + 配置快照 + scorer + 模型连接（仅 provider），不含密钥。"""
    snapshot = build_config_snapshot(config_name, config_def, model_override=model_override)
    return compute_fingerprint(
        dataset=dataset,
        config_snapshot=snapshot,
        scorer=scorer,
        connection=connection,
    )


def _candidate_config_json(
    config_name: str,
    config_def: Dict[str, Any],
    model_override: Optional[str] = None,
) -> Dict[str, Any]:
    """候选配置（落库/报告用，无密钥）。"""
    return {
        "config_name": config_name,
        "pattern": config_def["pattern"],
        "engine_pattern": config_def["engine_pattern"],
        "model": model_override or config_def["model"],
        "temperature": config_def["temperature"],
        "max_tokens": config_def["max_tokens"],
        "steps": [
            {
                "step_id": step["step_id"],
                "agent_name": step["agent_name"],
                "system_prompt": step["system_prompt"],
            }
            for step in config_def["steps"]
        ],
    }


class _ScriptedFakeJudgeClient:
    """假适配器模式下的离线 judge client。

    只用于验证 core.judge 的调用/解析/记录链路（不联网、无费用），其分数由本次
    确定性 rubric 分数换算，绝不代表真实 LLM 评审质量。
    """

    def __init__(self, score_100: float) -> None:
        self.score_100 = max(0.0, min(100.0, float(score_100)))
        self.calls = 0
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    async def _create(self, **kwargs: Any) -> Any:
        self.calls += 1
        payload = {
            "score": self.score_100,
            "reasoning": "[scripted-fake-judge] 离线确定性 judge；只验证链路，不代表真实评审质量。",
        }
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))
                )
            ]
        )


def _new_experiment_id() -> str:
    return f"{EXPERIMENT_ID_PREFIX}{uuid.uuid4().hex[:12]}"


def _create_harness2_context(
    *,
    dataset: Dict[str, Any],
    selected_case_count: int,
    configs_document: Dict[str, Any],
    config_names: Sequence[str],
    dataset_path: PathLike,
    answers_path: Optional[PathLike],
    configs_path: PathLike,
    adapter_mode: str,
    adapter_info: Dict[str, Any],
    judge_mode: str,
    judge_info: Dict[str, Any],
    tracing: bool,
    evidence_enabled_flag: bool,
    experiment_name: Optional[str],
    judge_budget: Optional[int],
    model_override: Optional[str],
    persist: bool = True,
) -> Dict[str, Any]:
    """创建实验上下文：experiment_id、候选 ID/指纹、可选落库、judge 预算。"""
    experiment_id = _new_experiment_id()
    connection = {
        "provider": "fake" if adapter_mode == "fake" else (adapter_info.get("provider") or "real"),
    }
    scorer = {
        "scorer_id": SCORER_ID,
        "scorer_version": SCORER_VERSION,
        "mode": judge_mode,
    }
    context: Dict[str, Any] = {
        "enabled": HARNESS2_AVAILABLE,
        "experiment_id": experiment_id,
        "experiment_name": (experiment_name or "").strip()
        or f"Harness²-lite {adapter_mode} 候选对比 {_now_iso()}",
        "persist": False,
        "db_error": None,
        "dataset": {
            "dataset_id": dataset["dataset_id"],
            "dataset_version": dataset["dataset_version"],
            "case_count": selected_case_count,
        },
        "scorer": scorer,
        "connection": connection,
        "configs_document": configs_document,
        "candidates": {},
        "judge_mode": judge_mode,
        "independent_judge_enabled": judge_mode == "llm",
        "judge_budget": None,
        "judge_model": (adapter_info.get("model") if adapter_mode == "real" else None),
        "adapter_mode": adapter_mode,
        "adapter_info": adapter_info,
        "judge_info": judge_info,
        "tracing": bool(tracing),
        "evidence_enabled": bool(evidence_enabled_flag),
        "evidence_written": 0,
        "evidence_pruned": 0,
        "evidence_retention_days": EVIDENCE_RETENTION_DAYS_DEFAULT,
    }

    if not HARNESS2_AVAILABLE:
        context["db_error"] = "agentflow.core Harness²-lite 模块不可用，已降级为旧行为"
        return context

    try:
        context["judge_budget"] = JudgeBudget(
            max_calls=judge_budget if judge_budget is not None else DEFAULT_JUDGE_BUDGET
        )
    except Exception as exc:  # pragma: no cover - 参数校验已在入口完成
        context["db_error"] = f"judge 预算初始化失败：{type(exc).__name__}"

    for config_name in config_names:
        config_def = configs_document["configs"][config_name]
        try:
            fingerprint = build_candidate_fingerprint(
                config_name,
                config_def,
                dataset=context["dataset"],
                scorer=scorer,
                connection=connection,
                model_override=model_override,
            )
        except Exception as exc:  # pragma: no cover - 指纹异常不阻断执行，但显式记录
            fingerprint = None
            context["db_error"] = (
                context["db_error"]
                or f"候选 {config_name} 指纹计算失败：{type(exc).__name__}"
            )
        context["candidates"][config_name] = {
            "candidate_id": f"{experiment_id}-{config_name}",
            "name": config_name,
            "fingerprint": fingerprint,
            "config": _candidate_config_json(config_name, config_def, model_override),
        }

    metadata = {
        "harness2_runner_version": RUNNER_VERSION,
        "created_at": _now_iso(),
        "adapter": adapter_info,
        "judge": judge_info,
        "tracing": {"enabled": bool(tracing)},
        "evidence": {
            "enabled": bool(evidence_enabled_flag),
            "retention_days": EVIDENCE_RETENTION_DAYS_DEFAULT,
            "directory_env": EVIDENCE_DIR_ENV,
        },
        "dataset": {
            "path": _display_path(dataset_path),
            "dataset_id": dataset["dataset_id"],
            "dataset_version": dataset["dataset_version"],
            "case_count": selected_case_count,
            "full_case_count": dataset["case_count"],
        },
        "configs": {
            "path": _display_path(configs_path),
            "config_version": configs_document["config_version"],
        },
        "answers": {"path": _display_path(answers_path)},
        "candidates": {
            name: {
                "candidate_id": entry["candidate_id"],
                "fingerprint": entry["fingerprint"],
                "name": entry["name"],
            }
            for name, entry in context["candidates"].items()
        },
    }
    try:
        if not persist:
            raise RuntimeError("persistence disabled by runner option")
        init_db()
        with get_db() as db:
            ExperimentRepository.save_experiment(
                db,
                experiment_id=experiment_id,
                name=context["experiment_name"],
                dataset_id=dataset["dataset_id"],
                dataset_version=dataset["dataset_version"],
                scorer_id=SCORER_ID,
                scorer_version=SCORER_VERSION,
                notes=json.dumps(metadata, ensure_ascii=False),
            )
            for config_name in config_names:
                entry = context["candidates"][config_name]
                ExperimentRepository.save_candidate(
                    db,
                    candidate_id=entry["candidate_id"],
                    experiment_id=experiment_id,
                    name=entry["name"],
                    fingerprint=entry["fingerprint"] or "",
                    config_json=entry["config"],
                )
        context["persist"] = True
    except Exception as exc:  # noqa: BLE001 - 数据库不可用时降级，但仍可离线执行
        context["persist"] = False
        if persist:
            context["db_error"] = scrub_secrets(f"{type(exc).__name__}: {exc}")
    return context


def _score_source_for(record: Dict[str, Any], judge_mode: str) -> Optional[str]:
    """主分数（score/passed）始终来自 deterministic rubric。

    独立 judge 是增量记录（见 independent_judge / judge_status），不覆盖主分数，
    因此主分数来源固定为 deterministic；judge 的失败/超预算不能把 case 标成通过。
    """
    if record.get("score_status") != "scored":
        return None
    return "deterministic"


def _persist_scoring(record: Dict[str, Any], harness2: Dict[str, Any]) -> None:
    """把 deterministic rubric 分数/passed 写回 run 记录（schema v4 字段）。"""
    if not harness2.get("persist") or not record.get("run_id"):
        return
    score_payload = record.get("score")
    score = score_payload.get("score") if isinstance(score_payload, dict) else None
    passed = bool(score_payload.get("passed")) if isinstance(score_payload, dict) else None
    try:
        with get_db() as db:
            RunRepository.update_scoring(
                db,
                record["run_id"],
                score=score,
                passed=passed,
                score_status=record.get("score_status"),
                score_source=record.get("score_source"),
            )
    except Exception as exc:  # noqa: BLE001 - 持久化失败不影响执行结果
        record["persistence_error"] = scrub_secrets(f"{type(exc).__name__}: {exc}")


async def _run_independent_judge(
    record: Dict[str, Any],
    case: Dict[str, Any],
    spec: Optional[Dict[str, Any]],
    harness2: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """调用 core.judge 的独立评分器；失败/禁用/超预算都显式记录，绝不影响 passed。"""
    if not harness2.get("independent_judge_enabled"):
        return None
    if not HARNESS2_AVAILABLE:
        return {"status": "unavailable", "reason": "core.judge 不可用"}
    if record.get("status") not in ("completed", "partial") or not (record.get("output") or "").strip():
        return {"status": "not_run", "reason": "case 没有可用输出，未调用独立 judge"}
    if not isinstance(spec, dict) or not isinstance(spec.get("rubric"), list):
        return {"status": "not_run", "reason": "case 没有预期答案/rubric，未调用独立 judge"}

    client = None
    if harness2.get("adapter_mode") == "fake":
        score_payload = record.get("score")
        score_100 = (
            round(float(score_payload["score"]) * 100.0)
            if isinstance(score_payload, dict) and score_payload.get("score") is not None
            else 50.0
        )
        client = _ScriptedFakeJudgeClient(score_100)

    reference = ""
    threshold = DEFAULT_PASS_THRESHOLD
    if isinstance(spec, dict):
        reference = str(spec.get("reference_answer") or "")
        threshold = spec.get("pass_threshold", DEFAULT_PASS_THRESHOLD)
    try:
        result = await judge_case(
            task=case["task"],
            answer=record["output"],
            reference_answer=reference,
            rubric={"pass_threshold": threshold},
            model=harness2.get("judge_model"),
            budget=harness2.get("judge_budget"),
            client=client,
        )
    except Exception as exc:  # noqa: BLE001 - judge 自身异常也要可记录
        result = {"status": "scoring_error", "error": scrub_secrets(f"{type(exc).__name__}: {exc}")}
    result = dict(result or {})
    if result.get("status") == "scored" and isinstance(record.get("score"), dict):
        result["agreement_with_deterministic"] = bool(result.get("passed")) == bool(
            record["score"].get("passed")
        )
    return result


def _score_payload_for_record(record: Dict[str, Any]) -> Dict[str, Any]:
    payload = record.get("score")
    if not isinstance(payload, dict):
        return {}
    keys = (
        "method",
        "score",
        "passed",
        "passed_score_only",
        "pass_threshold",
        "critical_missed_items",
        "scorer_version",
    )
    return {key: payload.get(key) for key in keys if key in payload}


def _build_run_payload_from_record(record: Dict[str, Any], case: Dict[str, Any]) -> Dict[str, Any]:
    """持久化不可用时，用 case 记录构造等价 run 载荷（证据仍可写入）。"""
    score_payload = record.get("score")
    return {
        "run_id": record.get("run_id"),
        "workflow_id": None,
        "task_input": case["task"],
        "status": record.get("workflow_status"),
        "trace_id": record.get("trace_id"),
        "experiment_id": record.get("experiment_id"),
        "candidate_id": record.get("candidate_id"),
        "case_id": record.get("case_id"),
        "fingerprint": record.get("fingerprint"),
        "evidence_ref": None,
        "score": score_payload.get("score") if isinstance(score_payload, dict) else None,
        "passed": score_payload.get("passed") if isinstance(score_payload, dict) else None,
        "score_status": record.get("score_status"),
        "score_source": record.get("score_source"),
        "final_result": record.get("output"),
        "error": record.get("error") or record.get("workflow_error"),
        "step_results": record.get("step_results") or [],
        "total_tokens": int(record.get("total_tokens") or 0),
        "total_duration": float(record.get("elapsed_seconds") or 0.0),
    }


def _capture_evidence(
    record: Dict[str, Any],
    run: Any,
    case: Dict[str, Any],
    harness2: Dict[str, Any],
) -> None:
    """写入脱敏证据并回填 run.evidence_ref；任何失败只记录，不阻断实验。"""
    if not harness2.get("evidence_enabled") or not HARNESS2_AVAILABLE:
        return
    run_payload = run
    if run_payload is None and harness2.get("persist") and record.get("run_id"):
        try:
            with get_db() as db:
                run_payload = RunRepository.get_run(db, record["run_id"])
        except Exception:  # noqa: BLE001 - 读取失败时退回记录载荷
            run_payload = None
    if run_payload is None:
        run_payload = _build_run_payload_from_record(record, case)

    judge_payload = record.get("independent_judge")
    evidence = build_evidence(
        experiment_id=harness2["experiment_id"],
        candidate_id=record.get("candidate_id") or "",
        case_id=record.get("case_id") or case["case_id"],
        fingerprint=record.get("fingerprint"),
        run=run_payload,
        dataset=harness2.get("dataset"),
        scorer=harness2.get("scorer"),
        scoring={
            "score": (record.get("score") or {}).get("score")
            if isinstance(record.get("score"), dict)
            else None,
            "passed": (record.get("score") or {}).get("passed")
            if isinstance(record.get("score"), dict)
            else None,
            "score_status": record.get("score_status"),
            "score_source": record.get("score_source"),
            "detail": _score_payload_for_record(record),
        },
        judge=judge_payload if isinstance(judge_payload, dict) else {},
        extra={
            "adapter_mode": harness2.get("adapter_mode"),
            "judge_mode": harness2.get("judge_mode"),
        },
    )
    try:
        ref = write_evidence(evidence)
    except Exception as exc:  # noqa: BLE001 - 证据失败不影响执行/评分
        record["evidence_error"] = scrub_secrets(f"{type(exc).__name__}: {exc}")
        return
    record["evidence_ref"] = ref
    harness2["evidence_written"] = int(harness2.get("evidence_written") or 0) + 1
    if harness2.get("persist") and record.get("run_id"):
        try:
            with get_db() as db:
                RunRepository.set_evidence_ref(db, record["run_id"], ref)
        except Exception as exc:  # noqa: BLE001
            record["evidence_error"] = scrub_secrets(f"{type(exc).__name__}: {exc}")


async def _finalize_case(
    record: Dict[str, Any],
    run: Any,
    case: Dict[str, Any],
    spec: Optional[Dict[str, Any]],
    harness2: Optional[Dict[str, Any]],
) -> None:
    """Harness²-lite 收尾：候选/指纹关联、评分持久化、独立 judge、证据。"""
    if harness2 is None:
        record["score_source"] = None
        return
    config_name = record.get("config")
    candidate = (harness2.get("candidates") or {}).get(config_name) or {}
    record["experiment_id"] = harness2.get("experiment_id")
    record["candidate_id"] = candidate.get("candidate_id")
    record["fingerprint"] = candidate.get("fingerprint")
    record["score_source"] = _score_source_for(record, harness2.get("judge_mode") or DEFAULT_JUDGE)
    _persist_scoring(record, harness2)
    judge_result = await _run_independent_judge(record, case, spec, harness2)
    if judge_result is not None:
        record["independent_judge"] = judge_result
        record["judge_status"] = judge_result.get("status")
    _capture_evidence(record, run, case, harness2)


def _prune_evidence_once(harness2: Optional[Dict[str, Any]]) -> None:
    """每个实验结束按保留期（默认 90 天，环境变量可配）清理一次证据。"""
    if not harness2 or not harness2.get("evidence_enabled") or not HARNESS2_AVAILABLE:
        return
    try:
        harness2["evidence_pruned"] = int(prune_evidence() or 0)
    except Exception as exc:  # noqa: BLE001 - 清理失败只记录
        harness2["prune_error"] = scrub_secrets(f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# 单 case 执行
# ---------------------------------------------------------------------------

def _new_case_record(case_id: str, config_name: str, tracing: bool) -> Dict[str, Any]:
    return {
        "case_id": case_id,
        "config": config_name,
        # Harness²-lite 关联（执行后回填）
        "experiment_id": None,
        "candidate_id": None,
        "fingerprint": None,
        "status": "failed",
        "workflow_status": None,
        "workflow_name": None,
        "record_schema_version": None,
        "workflow_error": None,
        "stop_requested": False,
        "failure_reason": None,
        "error": None,
        "run_id": None,
        "trace_id": None,
        "trace_id_source": None,
        "tracing_enabled": bool(tracing),
        "elapsed_seconds": 0.0,
        "workflow_duration_seconds": None,
        "total_tokens": 0,
        "unknown_usage_step_count": 0,
        "usage_type": "unknown",
        "output": "",
        "output_source": None,
        "step_results": [],
        "score": None,
        "score_status": "not_scored",
        "score_source": None,
        "scoring_error": None,
        "scoring_error_type": None,
        "missing_score": False,
        "score_note": None,
        # 独立 judge（仅 --judge llm 且门禁开启时调用 core.judge）
        "independent_judge": None,
        "judge_status": None,
        # 证据（默认关闭；--evidence / 环境变量开启时写入并回填）
        "evidence_ref": None,
        "evidence_error": None,
        # 持久化异常（不应中断实验）
        "persistence_error": None,
    }


async def _execute_case(
    case: Dict[str, Any],
    config_name: str,
    config_def: Dict[str, Any],
    adapter: Any,
    answers_index: Dict[str, Dict[str, Any]],
    model_override: Optional[str],
    judge: Any = None,
    judge_mode: str = DEFAULT_JUDGE,
    tracing: bool = False,
    harness2: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Any, Optional[Dict[str, Any]]]:
    """执行 + 既有评分逻辑；返回 (case 记录, run 对象, 预期答案 spec)。

    Harness²-lite 关联（experiment/candidate/case/指纹）在执行开始前传入执行器，
    运行记录由 WorkflowExecutor 持久化；评分/证据在 _finalize_case 中回填。
    """
    from agentflow.agents.llm_agent import LLMAgent
    from agentflow.core.workflow import WorkflowExecutor

    case_id = case["case_id"]
    record = _new_case_record(case_id, config_name, tracing)
    candidate = ((harness2 or {}).get("candidates") or {}).get(config_name) or {}
    persist = bool((harness2 or {}).get("persist"))
    run_kwargs: Dict[str, Any] = {}
    if harness2 is not None and candidate.get("candidate_id"):
        run_kwargs = {
            "experiment_id": harness2.get("experiment_id"),
            "candidate_id": candidate.get("candidate_id"),
            "case_id": case_id,
            "fingerprint": candidate.get("fingerprint"),
        }

    run = None
    spec: Optional[Dict[str, Any]] = None
    exec_result: Dict[str, Any] = {}
    try:
        workflow_config = build_workflow_config(config_name, config_def, model_override=model_override)
        executor = WorkflowExecutor(
            workflow_config,
            enable_persistence=persist,
            enable_tracing=tracing,
        )
        for agent_config in workflow_config.agents:
            executor.register_agent(LLMAgent(agent_config, adapter))

        started_at = time.perf_counter()
        exec_result = await executor.execute(case["task"], **run_kwargs)
        elapsed = time.perf_counter() - started_at
        record["elapsed_seconds"] = _round(elapsed)

        run_id = exec_result.get("run_id")
        record["run_id"] = run_id
        if run_id:
            run = executor.get_run(run_id)
        record["workflow_status"] = exec_result.get("status") or (
            _enum_value(run.status) if run is not None else None
        )
        record["workflow_name"] = getattr(run, "workflow_name", None) if run is not None else None
        record["record_schema_version"] = (
            getattr(run, "schema_version", None) if run is not None else None
        )
        workflow_error = exec_result.get("error")
        if not workflow_error and run is not None:
            workflow_error = getattr(run, "error", None)
        record["workflow_error"] = scrub_secrets(workflow_error) if workflow_error else None
        record["stop_requested"] = (
            bool(getattr(run, "stop_requested", False)) if run is not None else False
        )
        record["workflow_duration_seconds"] = _round(run.total_duration) if run is not None else None
        record["total_tokens"] = int(
            exec_result.get("total_tokens")
            or (run.total_tokens if run is not None else 0)
            or 0
        )
        record["usage_type"] = _aggregate_usage_type(run)
        record["step_results"] = _step_records(run, executor.message_history)
        record["unknown_usage_step_count"] = sum(
            1 for step_record in record["step_results"] if step_record.get("usage_unknown")
        )
        trace_id, trace_source = resolve_trace_id(exec_result, run)
        record["trace_id"] = trace_id
        record["trace_id_source"] = trace_source
        record["tracing_enabled"] = bool(getattr(executor, "enable_tracing", tracing))

        output, output_source = _extract_output(exec_result, run)
        record["output"] = output
        record["output_source"] = output_source
        workflow_status = record["workflow_status"] or "unknown"
        if output.strip():
            if workflow_status == "completed":
                record["status"] = "completed"
            elif workflow_status == "partial":
                record["status"] = "partial"
            else:
                record["status"] = "failed"
                record["failure_reason"] = f"workflow_{workflow_status}"
        else:
            record["status"] = "failed"
            record["failure_reason"] = (
                "missing_final_result"
                if workflow_status in ("completed", "partial")
                else f"workflow_{workflow_status}"
            )
    except Exception as exc:  # 引擎/适配器异常：显式失败，不中断整个配置
        record["elapsed_seconds"] = _round(record["elapsed_seconds"])
        record["status"] = "failed"
        record["failure_reason"] = "runner_exception"
        record["error"] = scrub_secrets(f"{type(exc).__name__}: {exc}")
        record["score_note"] = "execution_failed_no_output"
        record["score_status"] = "execution_failed"
        return record, None, None

    # 评分与执行状态解耦：先判断“是否允许评分”，再判断“是否有评分材料”。
    if judge_mode == "none":
        record["score_note"] = "judge_disabled_by_flag"
        record["score_status"] = "judge_disabled"
        return record, run, None
    if record["status"] not in ("completed", "partial"):
        # 失败执行不把引擎回退文本（如原始 task）当答案，显式记录未评分原因。
        record["score_note"] = "execution_failed_no_score"
        record["score_status"] = "execution_failed"
        return record, run, None
    if not record["output"].strip():
        record["score_note"] = "execution_failed_no_output"
        record["score_status"] = "execution_failed"
        return record, run, None

    spec = answers_index.get(case_id)
    if spec is None:
        record["missing_score"] = True
        record["score_note"] = "expected_answer_missing"
        record["score_status"] = "missing_score"
        return record, run, None
    if "_scoring_error" in spec:
        record["scoring_error"] = scrub_secrets(spec["_scoring_error"])
        record["scoring_error_type"] = "answer_spec"
        record["score_note"] = "scoring_error_answer_spec"
        record["score_status"] = "scoring_error"
        return record, run, spec

    try:
        if judge_mode == "deterministic":
            verdict = await judge.evaluate(case["task"], spec, record["output"])
        elif judge_mode == "llm":
            verdict = await judge.evaluate(case["task"], spec, record["output"])
        else:  # pragma: no cover - 上面已提前返回
            raise ExperimentConfigError(f"未知 judge 模式：{judge_mode!r}")
        record["score"] = verdict
        record["score_status"] = "scored"
        record["score_note"] = None
    except ScoringError as exc:
        record["scoring_error"] = scrub_secrets(str(exc))
        record["scoring_error_type"] = "deterministic_rubric"
        record["score_note"] = "scoring_error_deterministic_rubric"
        record["score_status"] = "scoring_error"
    except JudgeError as exc:
        record["scoring_error"] = scrub_secrets(str(exc))
        record["scoring_error_type"] = "llm_judge"
        record["score_note"] = "scoring_error_llm_judge"
        record["score_status"] = "scoring_error"
    except Exception as exc:  # 评分器自身异常也单独记录，不影响执行结果
        record["scoring_error"] = scrub_secrets(f"{type(exc).__name__}: {exc}")
        record["scoring_error_type"] = "unknown"
        record["score_note"] = "scoring_error_unknown"
        record["score_status"] = "scoring_error"
    return record, run, spec


async def _run_case(
    case: Dict[str, Any],
    config_name: str,
    config_def: Dict[str, Any],
    adapter: Any,
    answers_index: Dict[str, Dict[str, Any]],
    model_override: Optional[str],
    judge: Any = None,
    judge_mode: str = DEFAULT_JUDGE,
    tracing: bool = False,
    harness2: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """执行 + 评分 + Harness²-lite 收尾（持久化/独立 judge/证据）。"""
    record, run, spec = await _execute_case(
        case,
        config_name,
        config_def,
        adapter,
        answers_index,
        model_override,
        judge=judge,
        judge_mode=judge_mode,
        tracing=tracing,
        harness2=harness2,
    )
    await _finalize_case(record, run, case, spec, harness2)
    return record


# ---------------------------------------------------------------------------
# 指标汇总
# ---------------------------------------------------------------------------

def summarize_cases(cases: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """汇总一个配置下的所有 case；分母始终为全部 case。"""
    total = len(cases)
    status_counts = Counter(case["status"] for case in cases)
    completed = status_counts.get("completed", 0)
    partial = status_counts.get("partial", 0)
    failed = status_counts.get("failed", 0)

    elapsed_values = [float(case["elapsed_seconds"]) for case in cases]
    token_values = [int(case["total_tokens"]) for case in cases]
    usage_counts = Counter(case["usage_type"] for case in cases)
    score_status_counts = Counter(case.get("score_status") or "unknown" for case in cases)

    scored_cases = [case for case in cases if case.get("score") is not None]
    passed_cases = [case for case in scored_cases if case["score"].get("passed")]
    missing_cases = [case for case in cases if case.get("missing_score")]
    scoring_error_cases = [case for case in cases if case.get("scoring_error")]
    judge_disabled_cases = [case for case in cases if case.get("score_status") == "judge_disabled"]
    unscored_cases = [case for case in cases if case.get("score") is None]
    trace_id_cases = [case for case in cases if case.get("trace_id")]

    def _ratio(numerator: int, denominator: int) -> Optional[float]:
        return round(numerator / denominator, 4) if denominator else None

    quality = {
        "scored_count": len(scored_cases),
        "unscored_count": len(unscored_cases),
        "passed_count": len(passed_cases),
        "missing_score_count": len(missing_cases),
        "scoring_error_count": len(scoring_error_cases),
        "judge_disabled_count": len(judge_disabled_cases),
        "score_status_counts": dict(sorted(score_status_counts.items())),
        "pass_rate_scored": _ratio(len(passed_cases), len(scored_cases)),
        "pass_rate_all_cases": _ratio(len(passed_cases), total),
        "mean_score_scored": (
            _round(statistics.fmean(float(case["score"]["score"]) for case in scored_cases))
            if scored_cases
            else None
        ),
        "mean_score_all_cases": (
            _round(sum(float(case["score"]["score"]) for case in scored_cases) / total)
            if total
            else None
        ),
        "passed_case_ids": [case["case_id"] for case in passed_cases],
        "scored_case_ids": [case["case_id"] for case in scored_cases],
        "unscored_case_ids": [case["case_id"] for case in unscored_cases],
        "missing_score_case_ids": [case["case_id"] for case in missing_cases],
        "scoring_error_case_ids": [case["case_id"] for case in scoring_error_cases],
        "judge_disabled_case_ids": [case["case_id"] for case in judge_disabled_cases],
        "critical_missed_case_ids": [
            case["case_id"]
            for case in scored_cases
            if case["score"].get("critical_missed_items")
        ],
    }

    timing = {
        "total_seconds": _round(sum(elapsed_values)),
        "mean_seconds": _round(statistics.fmean(elapsed_values)) if elapsed_values else None,
        "median_seconds": _round(statistics.median(elapsed_values)) if elapsed_values else None,
        "max_seconds": _round(max(elapsed_values)) if elapsed_values else None,
    }

    tokens = {
        "total": sum(token_values),
        "mean_per_case": _round(statistics.fmean(token_values)) if token_values else None,
        "usage_type_counts": dict(sorted(usage_counts.items())),
        # 未知用量不能被当成 0 真实成本：显式统计哪些步骤/case 的用量不可信。
        "unknown_usage_step_count": sum(
            int(case.get("unknown_usage_step_count") or 0) for case in cases
        ),
        "unknown_usage_case_ids": [
            case["case_id"]
            for case in cases
            if case["usage_type"] in ("unknown", "mixed")
        ],
    }

    judge_status_counts = Counter(
        case.get("judge_status") for case in cases if case.get("judge_status")
    )
    harness2_metrics = {
        "judge_status_counts": dict(sorted(judge_status_counts.items())),
        "judge_scored_count": sum(
            1 for case in cases if case.get("judge_status") == "scored"
        ),
        "judge_failure_count": sum(
            1
            for case in cases
            if case.get("judge_status")
            in ("scoring_error", "budget_exhausted", "missing_score", "unavailable")
        ),
        "judge_agreement_count": sum(
            1
            for case in cases
            if (case.get("independent_judge") or {}).get("agreement_with_deterministic")
            is True
        ),
        "judge_disagreement_count": sum(
            1
            for case in cases
            if (case.get("independent_judge") or {}).get("agreement_with_deterministic")
            is False
        ),
        "evidence_ref_count": sum(1 for case in cases if case.get("evidence_ref")),
        "evidence_error_count": sum(1 for case in cases if case.get("evidence_error")),
        "persistence_error_count": sum(1 for case in cases if case.get("persistence_error")),
    }

    return {
        "case_count": total,
        "status_counts": dict(sorted(status_counts.items())),
        "execution": {
            "completed_count": completed,
            "partial_count": partial,
            "failed_count": failed,
            "execution_success_rate": _ratio(completed, total),
            "failed_case_ids": [
                case["case_id"] for case in cases if case["status"] == "failed"
            ],
            "partial_case_ids": [
                case["case_id"] for case in cases if case["status"] == "partial"
            ],
            "trace_id_present_count": len(trace_id_cases),
            "trace_id_case_ids": [case["case_id"] for case in trace_id_cases],
        },
        "timing": timing,
        "tokens": tokens,
        "quality": quality,
        "harness2": harness2_metrics,
    }


# ---------------------------------------------------------------------------
# 适配器创建（真实模型必须显式开启）
# ---------------------------------------------------------------------------

def _create_adapter(
    adapter_mode: str,
    real_model: Optional[str] = None,
) -> Tuple[Any, Dict[str, Any]]:
    if adapter_mode == "fake":
        adapter = ScriptedFakeAdapter()
        return adapter, {
            "mode": "fake",
            "adapter_id": ScriptedFakeAdapter.ADAPTER_ID,
            "network": False,
            "deterministic": True,
            "usage_note": (
                "假适配器自报的 token 计数由确定性规则生成，仅用于验证计量机制，"
                "不代表真实计费。"
            ),
            "note": "脚本化确定性假模型；不调用任何网络或付费模型。",
        }

    if adapter_mode != "real":
        raise ExperimentConfigError(f"未知适配器模式：{adapter_mode!r}")

    if os.getenv(REAL_ENABLED_ENV) != "1":
        raise ExperimentConfigError(
            f"真实模型模式已禁用：需显式设置 {REAL_ENABLED_ENV}=1（默认关闭，避免误调付费模型）"
        )

    provider = (os.getenv(REAL_PROVIDER_ENV) or "openai").strip().lower()
    key_env = PROVIDER_KEY_ENVS.get(provider)
    if key_env is None:
        raise ExperimentConfigError(
            f"不支持的 provider：{provider!r}"
            f"（支持 {sorted(set(PROVIDER_KEY_ENVS.values()))} 对应的 provider）"
        )
    api_key = os.getenv(key_env)
    if not api_key:
        raise ExperimentConfigError(
            f"缺少密钥环境变量 {key_env}（未设置则不会调用真实模型；密钥不会被打印）"
        )

    model = (real_model or os.getenv(REAL_MODEL_ENV) or "").strip()
    if not model:
        raise ExperimentConfigError(
            f"真实模型模式需要显式指定模型：--real-model 或 {REAL_MODEL_ENV}"
        )

    base_url = os.getenv(REAL_BASE_URL_ENV) or None
    try:
        from agentflow.adapters.factory import AdapterFactory

        adapter = AdapterFactory.create_adapter(provider, api_key, base_url=base_url)
    except Exception as exc:  # 不打印异常原文，避免潜在密钥泄漏
        raise ExperimentConfigError(
            f"真实适配器创建失败（{type(exc).__name__}），请检查 provider/依赖配置"
        ) from exc

    return adapter, {
        "mode": "real",
        "provider": provider,
        "model": model,
        "network": True,
        "deterministic": False,
        "key_env": key_env,
        "key_present": True,
        "note": "真实模型实验会产生费用；密钥值不会被记录或打印。",
    }


# ---------------------------------------------------------------------------
# 配置级与实验级运行
# ---------------------------------------------------------------------------

async def _run_config_async(
    config_name: str,
    config_def: Dict[str, Any],
    cases: Sequence[Dict[str, Any]],
    answers_index: Dict[str, Dict[str, Any]],
    adapter: Any,
    adapter_info: Dict[str, Any],
    model_override: Optional[str],
    config_version: str,
    judge: Any,
    judge_info: Dict[str, Any],
    judge_mode: str,
    tracing: bool,
    harness2: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    case_records = [
        await _run_case(
            case,
            config_name,
            config_def,
            adapter,
            answers_index,
            model_override,
            judge=judge,
            judge_mode=judge_mode,
            tracing=tracing,
            harness2=harness2,
        )
        for case in cases
    ]
    metrics = summarize_cases(case_records)
    candidate = ((harness2 or {}).get("candidates") or {}).get(config_name) or {}
    return {
        "config_name": config_name,
        "candidate_id": candidate.get("candidate_id"),
        "candidate_name": candidate.get("name") or config_name,
        "fingerprint": candidate.get("fingerprint"),
        "config_version": config_version,
        "pattern": config_def["pattern"],
        "engine_pattern": config_def["engine_pattern"],
        "description": config_def.get("description", ""),
        "model": model_override or config_def["model"],
        "steps": [
            {"step_id": step["step_id"], "agent_name": step["agent_name"]}
            for step in config_def["steps"]
        ],
        "adapter": adapter_info,
        "judge": judge_info,
        "tracing": {"enabled": bool(tracing)},
        "metrics": metrics,
        "cases": case_records,
    }


def run_experiment(
    configs: Optional[Union[str, Sequence[str]]] = None,
    dataset_path: PathLike = DEFAULT_DATASET_PATH,
    answers_path: Optional[PathLike] = None,
    configs_path: PathLike = DEFAULT_CONFIGS_PATH,
    limit: Optional[int] = None,
    adapter_mode: str = "fake",
    real_model: Optional[str] = None,
    judge: str = DEFAULT_JUDGE,
    tracing: bool = False,
    experiment_name: Optional[str] = None,
    evidence: bool = False,
    judge_budget: Optional[int] = None,
    persist: bool = True,
) -> Dict[str, Any]:
    """同步执行一个或多个配置的实验，返回完整的 JSON 可序列化结果。

    Harness²-lite：默认创建实验/候选记录并把 case 运行、评分关联落库；
    `evidence=True`（或 AGENTFLOW_EVIDENCE_ENABLED=true）时才写证据包。
    """
    if judge not in JUDGE_MODES:
        raise ExperimentConfigError(f"未知 judge 模式：{judge!r}（支持 {JUDGE_MODES}）")
    if limit is not None and (not isinstance(limit, int) or limit < 1):
        raise ExperimentConfigError(f"limit 必须是正整数，实际为 {limit!r}")
    if judge_budget is not None and (not isinstance(judge_budget, int) or judge_budget < 1):
        raise ExperimentConfigError(f"judge 预算必须是正整数，实际为 {judge_budget!r}")

    if configs is None or configs == "all":
        config_names = list(SUPPORTED_CONFIGS)
    elif isinstance(configs, str):
        config_names = [configs]
    else:
        config_names = list(configs)
    if not config_names:
        raise ExperimentConfigError("至少需要指定一个配置")
    unknown = [name for name in config_names if name not in SUPPORTED_CONFIGS]
    if unknown:
        raise ExperimentConfigError(f"不支持的配置名：{unknown}（支持 {SUPPORTED_CONFIGS}）")
    # 去重且保持顺序
    config_names = list(dict.fromkeys(config_names))

    dataset = load_dataset(dataset_path)
    configs_document = load_configs(configs_path)
    missing_configs = [name for name in config_names if name not in configs_document["configs"]]
    if missing_configs:
        raise ExperimentConfigError(f"配置文件中缺少配置：{missing_configs}")

    if answers_path is None:
        answers_file = dataset.get("answers_file")
        if isinstance(answers_file, str) and answers_file.strip():
            answers_path = Path(dataset_path).resolve().parent / answers_file
        else:
            answers_path = DEFAULT_ANSWERS_PATH
    answers_index, answers_meta = load_answers(answers_path, dataset)

    adapter, adapter_info = _create_adapter(adapter_mode, real_model=real_model)
    model_override = real_model if adapter_mode == "real" else None
    if adapter_mode == "real" and not model_override:
        model_override = adapter_info.get("model")

    judge_object, judge_info = _create_judge(judge, adapter_mode, adapter, adapter_info)

    all_cases = dataset["cases"]
    selected_cases = all_cases[:limit] if limit is not None else all_cases

    # 实验运行强制关闭自动评估，避免任何隐式评审模型调用。
    os.environ["AUTO_EVALUATE"] = "false"

    # 证据开关：--evidence 显式开启；环境变量同样可开启；默认关闭。
    original_evidence_env = os.environ.get(EVIDENCE_ENABLED_ENV)
    evidence_env_changed = False
    if evidence and HARNESS2_AVAILABLE and not evidence_enabled():
        os.environ[EVIDENCE_ENABLED_ENV] = "true"
        evidence_env_changed = True
    evidence_on = bool(HARNESS2_AVAILABLE and (evidence or evidence_enabled()))

    harness2 = _create_harness2_context(
        dataset=dataset,
        selected_case_count=len(selected_cases),
        configs_document=configs_document,
        config_names=config_names,
        dataset_path=dataset_path,
        answers_path=answers_path,
        configs_path=configs_path,
        adapter_mode=adapter_mode,
        adapter_info=adapter_info,
        judge_mode=judge,
        judge_info=judge_info,
        tracing=tracing,
        evidence_enabled_flag=evidence_on,
        experiment_name=experiment_name,
        judge_budget=judge_budget,
        model_override=model_override,
        persist=persist,
    )

    async def _run_all() -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for name in config_names:
            results.append(
                await _run_config_async(
                    config_name=name,
                    config_def=configs_document["configs"][name],
                    cases=selected_cases,
                    answers_index=answers_index,
                    adapter=adapter,
                    adapter_info=adapter_info,
                    model_override=model_override,
                    config_version=configs_document["config_version"],
                    judge=judge_object,
                    judge_info=judge_info,
                    judge_mode=judge,
                    tracing=tracing,
                    harness2=harness2,
                )
            )
        return results

    try:
        experiments = asyncio.run(_run_all())
    finally:
        # 每个实验结束按保留期（默认 90 天）清理一次证据（仅证据开启时）。
        _prune_evidence_once(harness2)
        if evidence_env_changed:
            if original_evidence_env is None:
                os.environ.pop(EVIDENCE_ENABLED_ENV, None)
            else:
                os.environ[EVIDENCE_ENABLED_ENV] = original_evidence_env

    judge_budget_obj = harness2.get("judge_budget")
    return {
        "experiment_id": harness2["experiment_id"],
        "created_at": _now_iso(),
        "runner": {"name": "run_experiment.py", "version": RUNNER_VERSION},
        "adapter": adapter_info,
        "judge": judge_info,
        "tracing": {
            "enabled": bool(tracing),
            "provider": "langfuse",
            "note": (
                "追踪显式开启时，case.trace_id 从 run 记录 / execute() 返回值读取；"
                "未配置 Langfuse 或未启用追踪时 trace_id=null，不会伪造。"
            ),
        },
        "dataset": {
            "path": _display_path(dataset["path"]),
            "dataset_id": dataset["dataset_id"],
            "dataset_version": dataset["dataset_version"],
            "full_case_count": dataset["case_count"],
            "case_count": len(selected_cases),
            "case_ids": [case["case_id"] for case in selected_cases],
            "limit": limit,
            "answers": dict(answers_meta, path=_display_path(answers_meta.get("path"))),
        },
        "configs": {
            "path": _display_path(configs_document["path"]),
            "config_version": configs_document["config_version"],
            "names": config_names,
        },
        "scorer": {
            "id": SCORER_ID,
            "version": SCORER_VERSION,
            "method": "deterministic-rubric-v2",
            "pass_threshold_default": DEFAULT_PASS_THRESHOLD,
            "normalization": NORMALIZATION_DESCRIPTION,
            "pass_rule": "score >= pass_threshold 且所有 critical 条目命中",
            "calibration": answers_meta.get("calibration") or {},
        },
        "harness2": {
            "experiment_id": harness2["experiment_id"],
            "experiment_name": harness2["experiment_name"],
            "persisted": bool(harness2.get("persist")),
            "db_error": harness2.get("db_error"),
            "candidates": [
                {
                    "config_name": name,
                    "candidate_id": entry["candidate_id"],
                    "name": entry["name"],
                    "fingerprint": entry["fingerprint"],
                }
                for name, entry in (harness2.get("candidates") or {}).items()
            ],
            "judge": {
                "mode": judge,
                "independent_judge_enabled": bool(harness2.get("independent_judge_enabled")),
                "budget": judge_budget_obj.to_dict() if judge_budget_obj is not None else None,
            },
            "evidence": {
                "enabled": bool(evidence_on),
                "directory_env": EVIDENCE_DIR_ENV,
                "retention_days": harness2.get("evidence_retention_days"),
                "written_count": int(harness2.get("evidence_written") or 0),
                "pruned_count": int(harness2.get("evidence_pruned") or 0),
                "prune_error": harness2.get("prune_error"),
            },
        },
        "experiments": experiments,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "AgentFlow 质量实验运行器 v2.1（默认确定性假适配器，不调用付费模型；"
            "Harness²-lite 实验/指纹/证据/独立 judge/候选对比）"
        )
    )
    parser.add_argument(
        "--config",
        choices=list(SUPPORTED_CONFIGS) + ["all"],
        default="all",
        help="要运行的配置（默认 all）",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET_PATH,
        help="数据集 JSON 路径（默认 experiments/dataset_v2.json）",
    )
    parser.add_argument(
        "--answers",
        type=Path,
        default=None,
        help="预期答案 JSON 路径（默认按数据集 answers_file 推导）",
    )
    parser.add_argument(
        "--configs",
        type=Path,
        default=DEFAULT_CONFIGS_PATH,
        help="配置定义 JSON 路径（默认 experiments/configs_v1.json）",
    )
    parser.add_argument("--limit", type=int, default=None, help="只运行前 N 个 case")
    parser.add_argument(
        "--judge",
        choices=list(JUDGE_MODES),
        default=DEFAULT_JUDGE,
        help=(
            "评分方式（默认 deterministic；llm 需额外设置 "
            f"{LLM_JUDGE_ENABLED_ENV}=1；none 表示显式关闭评分）"
        ),
    )
    parser.add_argument(
        "--judge-budget",
        type=int,
        default=None,
        help=(
            "独立 judge 调用预算（默认 50，也可用环境变量 AGENTFLOW_JUDGE_MAX_CALLS；"
            "仅在 --judge llm 且门禁开启时生效，超预算记录 budget_exhausted，不会静默通过）"
        ),
    )
    parser.add_argument(
        "--experiment-name",
        type=str,
        default=None,
        help="实验显示名称（写入 experiments 表与报告；默认自动生成，不含密钥）",
    )
    parser.add_argument(
        "--evidence",
        action="store_true",
        help=(
            "显式开启执行证据包（默认关闭；也可用环境变量 "
            f"{EVIDENCE_ENABLED_ENV}=true 开启；目录/保留期用环境变量配置）"
        ),
    )
    parser.add_argument(
        "--tracing",
        action="store_true",
        help="启用 Langfuse 追踪（需 Langfuse 环境配置；默认关闭，trace_id 默认 null）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="把 JSON 结果写入文件（默认输出到 stdout）",
    )
    parser.add_argument(
        "--real",
        action="store_true",
        help=f"启用真实模型（还需 {REAL_ENABLED_ENV}=1、provider 密钥和模型名）",
    )
    parser.add_argument(
        "--real-model",
        type=str,
        default=None,
        help=f"真实模型名（也可用 {REAL_MODEL_ENV}）",
    )
    return parser


def _summary_lines(document: Dict[str, Any]) -> List[str]:
    lines = []
    judge_mode = (document.get("judge") or {}).get("mode")
    harness2 = document.get("harness2") or {}
    evidence = harness2.get("evidence") or {}
    lines.append(
        "[harness2] experiment_id={eid} persisted={persisted} judge={judge} "
        "evidence={evidence} candidates={candidates} evidence_written={written} "
        "evidence_pruned={pruned}".format(
            eid=harness2.get("experiment_id"),
            persisted=harness2.get("persisted"),
            judge=judge_mode,
            evidence=evidence.get("enabled"),
            candidates=len(harness2.get("candidates") or []),
            written=evidence.get("written_count"),
            pruned=evidence.get("pruned_count"),
        )
    )
    for experiment in document["experiments"]:
        metrics = experiment["metrics"]
        quality = metrics["quality"]
        lines.append(
            "[{name}] cases={total} completed={completed} failed={failed} "
            "scored={scored} passed={passed} pass_rate_scored={prs} pass_rate_all={pra} "
            "missing={missing} scoring_error={serr} judge_disabled={jdisabled} "
            "judge={judge} trace_ids={traces} tokens={tokens} elapsed={elapsed}s "
            "candidate={candidate} fingerprint={fingerprint}".format(
                name=experiment["config_name"],
                total=metrics["case_count"],
                completed=metrics["execution"]["completed_count"],
                failed=metrics["execution"]["failed_count"],
                scored=quality["scored_count"],
                passed=quality["passed_count"],
                prs=quality["pass_rate_scored"],
                pra=quality["pass_rate_all_cases"],
                missing=quality["missing_score_count"],
                serr=quality["scoring_error_count"],
                jdisabled=quality["judge_disabled_count"],
                judge=judge_mode,
                traces=metrics["execution"]["trace_id_present_count"],
                tokens=metrics["tokens"]["total"],
                elapsed=metrics["timing"]["total_seconds"],
                candidate=experiment.get("candidate_id"),
                fingerprint=experiment.get("fingerprint"),
            )
        )
    return lines


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.limit is not None and args.limit < 1:
        print("错误：--limit 必须是正整数", file=sys.stderr)
        return 2
    if args.judge_budget is not None and args.judge_budget < 1:
        print("错误：--judge-budget 必须是正整数", file=sys.stderr)
        return 2

    try:
        document = run_experiment(
            configs=args.config,
            dataset_path=args.dataset,
            answers_path=args.answers,
            configs_path=args.configs,
            limit=args.limit,
            adapter_mode="real" if args.real else "fake",
            real_model=args.real_model,
            judge=args.judge,
            tracing=bool(args.tracing),
            experiment_name=args.experiment_name,
            evidence=bool(args.evidence),
            judge_budget=args.judge_budget,
        )
    except ExperimentConfigError as exc:
        print(f"实验配置错误：{scrub_secrets(exc)}", file=sys.stderr)
        return 2

    payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload, encoding="utf-8")
        print(f"结果已写入：{output_path}")
        for line in _summary_lines(document):
            print(line, file=sys.stderr)
    else:
        for line in _summary_lines(document):
            print(line, file=sys.stderr)
        print(payload, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
