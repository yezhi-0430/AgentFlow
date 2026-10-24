"""
记录脱敏工具：写入本地运行记录前，把疑似密钥替换掉。

只做保守的常见模式匹配，不改变错误语义；用于避免把密钥/Token 写进 SQLite。
"""
import re
from typing import Optional

REDACTED = "[REDACTED]"

_PATTERNS = [
    re.compile(r"sk-(?:or-v1|proj|ant|lf)?-?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"pk-lf-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9_\-\.=]{8,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|secret[_-]?key|access[_-]?key|token|password)\s*[:=]\s*['\"]?([^\s'\",;]{6,})"),
]


def redact_text(value: Optional[str], limit: int = 4000) -> Optional[str]:
    """脱敏并截断文本；None 原样返回。"""
    if value is None:
        return None
    text = str(value)
    for pattern in _PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda match: re.sub(r"[^\s:=]+$", REDACTED, match.group(0)), text)
        else:
            text = pattern.sub(REDACTED, text)
    if limit > 0 and len(text) > limit:
        text = text[:limit] + "...[truncated]"
    return text
