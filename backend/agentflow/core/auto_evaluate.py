"""
自动评估模块 - LLM-as-a-Judge

工作流执行结束后，用评审模型（默认 OpenRouter 上的 gpt-4o-mini）给本次运行打分，
并把分数写进 Langfuse 的 **评分（Score）**：

- 评分挂在本次运行的真实 trace 上（trace_id 由 run_id 稳定推导，不能用 run_id 当 trace_id）
- Langfuse 5.x 写评分的 API 是 ``client.create_score(...)``，不是 ``client.score(...)``
- 评估失败只打印日志，绝不影响工作流本身

打分数值 0-100，评分名默认 ``auto-quality``（可用 ``EVAL_SCORE_NAME`` 覆盖）。
"""
import json
import os
from typing import Any, Dict, Optional

DEFAULT_SCORE_NAME = "auto-quality"
MAX_OUTPUT_CHARS = 2000

EVAL_PROMPT = """你是专业的内容质量评估专家。请评估以下内容的质量：

评分标准（总分100）:
1. 内容相关性 (0-25分): 是否切题、有用
2. 完整性 (0-25分): 内容是否完整、结构清晰
3. 准确性 (0-25分): 信息是否准确、逻辑清晰
4. 表达质量 (0-25分): 语言流畅、易懂

待评估内容:
{output}

请只返回 JSON 格式:
{{"score": 85, "reasoning": "内容质量很高，但..."}}
"""


def _as_text(value: Any) -> Optional[str]:
    """把任意输出转成可评估的文本（限长）"""
    if value is None:
        return None
    if isinstance(value, dict):
        value = json.dumps(value, ensure_ascii=False, default=str)
    elif not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if not value:
        return None
    if len(value) > MAX_OUTPUT_CHARS:
        value = value[:MAX_OUTPUT_CHARS] + "..."
    return value


def _is_trace_id(value: Any) -> bool:
    """Langfuse trace_id 必须是 32 位十六进制字符串"""
    return (
        isinstance(value, str)
        and len(value) == 32
        and all(ch in "0123456789abcdefABCDEF" for ch in value)
    )


def extract_final_output(run, result: Optional[Dict[str, Any]]) -> Optional[str]:
    """从运行结果里找出"最终输出"（不同 pattern 的返回结构不同）"""
    candidates = []

    if isinstance(result, dict):
        inner = result.get("result")
        if isinstance(inner, dict):
            candidates.extend([
                inner.get("final_result"),
                inner.get("aggregated"),
                inner.get("winner"),
            ])
        candidates.extend([
            result.get("final_result"),
            result.get("output"),
        ])

    if run is not None:
        candidates.append(getattr(run, "final_result", None))
        # 兜底：最后一条没有错误的步骤输出（StepResult 只有 message id，没有 output 字段）
        step_results = getattr(run, "step_results", None) or []
        for step in reversed(step_results):
            if getattr(step, "error", None):
                continue
            candidates.append(getattr(step, "output", None))

    for candidate in candidates:
        text = _as_text(candidate)
        if text:
            return text
    return None


def _parse_score(content: Optional[str]) -> Optional[Dict[str, Any]]:
    if not content:
        return None
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        value = float(payload.get("score"))
    except (TypeError, ValueError):
        return None
    reasoning = payload.get("reasoning")
    return {
        "score": max(0.0, min(100.0, value)),
        "reasoning": str(reasoning or "")[:1000],
    }


async def auto_evaluate_workflow(
    tracer,
    run,
    result: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """评估一次工作流运行，并把分数写入 Langfuse。

    Args:
        tracer: LangfuseTracer（需要 enabled 且 client 可用）
        run: WorkflowRun
        result: execute() 返回的结果字典（用于取最终输出）
        trace_id: 可选的 trace_id；默认由 run.run_id 推导

    Returns:
        {"score": 85.0, "reasoning": "...", "trace_id": "..."}；跳过/失败返回 None
    """
    if tracer is None or not getattr(tracer, "enabled", False):
        return None
    client = getattr(tracer, "client", None)
    if client is None:
        return None

    run_id = getattr(run, "run_id", None)
    if not _is_trace_id(trace_id):
        trace_id = tracer.trace_id_for_run(run_id) if run_id else None
    if not _is_trace_id(trace_id):
        print("[自动评估] 无法确定合法的 trace_id，跳过")
        return None

    output = extract_final_output(run, result)
    if not output:
        print("[自动评估] 没有可评估的输出，跳过")
        return None

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[自动评估] 缺少 OPENAI_API_KEY，跳过")
        return None

    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    eval_model = os.getenv("EVAL_MODEL", "openai/gpt-4o-mini")
    score_name = os.getenv("EVAL_SCORE_NAME", DEFAULT_SCORE_NAME)

    try:
        from openai import AsyncOpenAI

        judge = AsyncOpenAI(api_key=api_key, base_url=base_url)
        response = await judge.chat.completions.create(
            model=eval_model,
            messages=[{"role": "user", "content": EVAL_PROMPT.format(output=output)}],
            response_format={"type": "json_object"},
            temperature=0.3,
            timeout=60,
        )
        evaluation = _parse_score(response.choices[0].message.content)
        if not evaluation:
            print("[自动评估] 评审模型返回内容无法解析，跳过")
            return None

        score = evaluation["score"]
        reasoning = evaluation["reasoning"]

        # 内容采集默认关闭：评论是输出派生文本，只有显式开启才外发
        capture_content = os.getenv("LANGFUSE_CAPTURE_CONTENT", "false").lower() in ("true", "1", "yes")

        # Langfuse 5.x: 用 create_score；trace_id 必须是真实 trace id
        client.create_score(
            name=score_name,
            value=score,
            trace_id=trace_id,
            data_type="NUMERIC",
            comment=reasoning if capture_content else None,
            metadata={"model": eval_model, "run_id": run_id, "scoring": "llm-judge"},
        )

        print(f"[自动评估] 评分 {score:.0f}/100 已写入 Langfuse（score={score_name}, trace_id={trace_id}）")
        if capture_content:
            print(f"[自动评估] 理由: {reasoning[:100]}...")
        return {"score": score, "reasoning": reasoning, "trace_id": trace_id}
    except Exception as e:  # noqa: BLE001 - 评估失败不影响业务
        print(f"[自动评估] 评估失败（不影响工作流）: {e}")
        return None
