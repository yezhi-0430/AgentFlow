"""
独立评分器（Harness²-lite）

真实 LLM judge 作为独立评分来源，与生成链路/模型/提示词分离：
- 默认关闭，需要显式门禁 AGENTFLOW_EXPERIMENT_LLM_JUDGE=1 且存在密钥；
- 有调用预算（默认 50 次），超预算返回 budget_exhausted，不静默失败；
- 返回 scored / judge_disabled / budget_exhausted / scoring_error / missing_score；
- 评分只输出 0-100 分与理由，由调用方归一化；密钥不打印。
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from agentflow.core.redaction import redact_text

JUDGE_GATE_ENV = "AGENTFLOW_EXPERIMENT_LLM_JUDGE"
JUDGE_MODEL_ENV = "AGENTFLOW_JUDGE_MODEL"
JUDGE_BASE_URL_ENV = "AGENTFLOW_JUDGE_BASE_URL"
JUDGE_API_KEY_ENV = "AGENTFLOW_JUDGE_API_KEY"
JUDGE_BUDGET_ENV = "AGENTFLOW_JUDGE_MAX_CALLS"
JUDGE_SCORE_NAME = "independent-judge"
JUDGE_PROMPT_VERSION = "judge-v1"

DEFAULT_BUDGET = 50
DEFAULT_THRESHOLD = 75.0


def judge_gate_enabled() -> bool:
    return os.getenv(JUDGE_GATE_ENV, "0") == "1"


def judge_configured() -> bool:
    return judge_gate_enabled() and bool(
        os.getenv(JUDGE_API_KEY_ENV) or os.getenv("OPENAI_API_KEY")
    )


class JudgeBudget:
    """简单的调用预算计数器（顺序调用场景）。"""

    def __init__(self, max_calls: Optional[int] = None):
        if max_calls is None:
            try:
                max_calls = int(os.getenv(JUDGE_BUDGET_ENV, DEFAULT_BUDGET))
            except (TypeError, ValueError):
                max_calls = DEFAULT_BUDGET
        self.max_calls = max(1, max_calls)
        self.used = 0

    def can_call(self) -> bool:
        return self.used < self.max_calls

    def consume(self) -> None:
        self.used += 1

    def to_dict(self) -> Dict[str, Any]:
        return {"max_calls": self.max_calls, "used": self.used, "remaining": self.max_calls - self.used}


_JUDGE_PROMPT = """你是独立的答案质量评审。请只根据任务、参考答案/评分要点和回答内容评分。

任务：
{task}

参考答案/评分要点：
{reference}

待评审回答：
{answer}

请返回 JSON（不要输出其他内容）：
{{"score": 0-100 的整数, "reasoning": "不超过 200 字的理由"}}

评分标准：完全满足任务与要点 90-100；基本满足但缺少细节 75-89；部分满足 50-74；偏离或错误 0-49。
"""


async def judge_case(
    *,
    task: str,
    answer: str,
    reference_answer: str = "",
    rubric: Optional[Dict[str, Any]] = None,
    model: Optional[str] = None,
    budget: Optional[JudgeBudget] = None,
    client: Any = None,
    timeout: float = 60.0,
) -> Dict[str, Any]:
    """独立评审一个 case；失败/禁用/超预算都返回明确状态，不抛异常。"""
    if not judge_configured():
        return {
            "status": "judge_disabled",
            "reason": "LLM judge 未启用（需要 AGENTFLOW_EXPERIMENT_LLM_JUDGE=1 与密钥）",
            "prompt_version": JUDGE_PROMPT_VERSION,
        }

    if budget is not None and not budget.can_call():
        return {
            "status": "budget_exhausted",
            "reason": "judge 调用预算已用尽",
            "prompt_version": JUDGE_PROMPT_VERSION,
            "budget": budget.to_dict(),
        }

    if not answer or not str(answer).strip():
        return {"status": "missing_score", "reason": "没有可评审的回答", "prompt_version": JUDGE_PROMPT_VERSION}

    reference = reference_answer or json.dumps(rubric or {}, ensure_ascii=False)
    prompt = _JUDGE_PROMPT.format(task=task, reference=reference, answer=answer)
    model = model or os.getenv(JUDGE_MODEL_ENV, os.getenv("EVAL_MODEL", "openai/gpt-4o-mini"))
    base_url = os.getenv(JUDGE_BASE_URL_ENV) or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    api_key = os.getenv(JUDGE_API_KEY_ENV) or os.getenv("OPENAI_API_KEY")

    try:
        if client is None:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        if budget is not None:
            budget.consume()
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
            timeout=timeout,
        )
        payload = json.loads(response.choices[0].message.content)
        raw_score = float(payload.get("score"))
        score = max(0.0, min(100.0, raw_score))
        threshold = float((rubric or {}).get("pass_threshold", DEFAULT_THRESHOLD) or DEFAULT_THRESHOLD)
        # rubric 可能是 0-1 分制，阈值也按 0-1 处理
        if threshold <= 1.0:
            threshold *= 100.0
        return {
            "status": "scored",
            "score": round(score / 100.0, 6),
            "score_100": score,
            "passed": score >= threshold,
            "reasoning": str(payload.get("reasoning", ""))[:500],
            "model": model,
            "prompt_version": JUDGE_PROMPT_VERSION,
            "score_name": JUDGE_SCORE_NAME,
            "budget": budget.to_dict() if budget else None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "scoring_error",
            "error": redact_text(f"{type(exc).__name__}: {exc}") or "judge failed",
            "model": model,
            "prompt_version": JUDGE_PROMPT_VERSION,
        }
