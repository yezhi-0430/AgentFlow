"""
工作流定义的序列化、校验与版本化

定义只包含可恢复工作流所需的结构信息（名称、模式、Agent 配置、步骤、非敏感连接信息）；
**永远不包含 API Key / secret / token**。导入导出与本地持久化都走这里。

定义格式版本：1
"""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

DEFINITION_SCHEMA_VERSION = 1

# 递归剔除的敏感字段名（定义中不应出现；导入/导出/持久化前统一清洗）
_SECRET_FIELD_NAMES = {
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
    "auth",
}

# 连接信息中允许保存的字段（本地配置，不含密钥）
_ALLOWED_CONNECTION_KEYS = ("provider", "base_url", "site_url", "app_name")

_MAX_AGENTS = 100
_MAX_STEPS = 100
_MAX_TEXT = 20000


class DefinitionValidationError(ValueError):
    """定义格式非法（导入/恢复时使用）"""


def _strip_secrets(value: Any) -> Any:
    """递归清洗敏感字段，返回新对象。"""
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            normalized = str(key).strip().lower().replace(" ", "_")
            if (
                normalized in _SECRET_FIELD_NAMES
                or normalized.endswith("_key")
                or normalized.endswith("_secret")
                or normalized.endswith("_token")
            ):
                continue
            cleaned[key] = _strip_secrets(item)
        return cleaned
    if isinstance(value, list):
        return [_strip_secrets(item) for item in value]
    return value


def clean_connection(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """只保留允许落库的连接字段。"""
    if not isinstance(raw, dict):
        return {}
    return {key: raw[key] for key in _ALLOWED_CONNECTION_KEYS if raw.get(key)}


def _text(value: Any, limit: int = _MAX_TEXT) -> str:
    if value is None:
        return ""
    return str(value)[:limit]


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class WorkflowDefinition:
    """一次工作流定义的完整快照（不含密钥）"""

    workflow_id: str
    name: str
    pattern: str = "sequential"
    description: str = ""
    agents: List[Dict[str, Any]] = field(default_factory=list)
    steps: List[Dict[str, Any]] = field(default_factory=list)
    max_iterations: int = 10
    connection: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    schema_version: int = DEFINITION_SCHEMA_VERSION
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    # ------------------------------------------------------------------ output
    def to_dict(self) -> Dict[str, Any]:
        """导出/持久化格式（已清洗敏感字段）"""
        return {
            "schema_version": self.schema_version,
            "workflow_id": self.workflow_id,
            "name": self.name,
            "description": self.description,
            "pattern": self.pattern,
            "agents": _strip_secrets(copy.deepcopy(self.agents)),
            "steps": _strip_secrets(copy.deepcopy(self.steps)),
            "max_iterations": self.max_iterations,
            "connection": clean_connection(self.connection),
            "metadata": _strip_secrets(copy.deepcopy(self.metadata)),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_workflow_config(self):
        """转换为引擎可用的 WorkflowConfig（延迟导入避免循环）"""
        from agentflow.core.agent import AgentConfig, AgentRole
        from agentflow.core.workflow import (
            WorkflowConfig,
            WorkflowPattern,
            WorkflowStep,
            ensure_supported_pattern,
        )

        pattern = WorkflowPattern(self.pattern)
        ensure_supported_pattern(pattern)

        agents = []
        for raw in self.agents:
            try:
                role = AgentRole(raw.get("role", "worker"))
            except ValueError:
                role = AgentRole.WORKER
            agents.append(
                AgentConfig(
                    name=str(raw["name"]),
                    role=role,
                    system_prompt=str(raw.get("system_prompt", "")),
                    model=str(raw.get("model", "gpt-4")),
                    temperature=_number(raw.get("temperature"), 0.7),
                    max_tokens=int(_number(raw.get("max_tokens"), 2000)),
                    tools=raw.get("tools"),
                    capabilities=raw.get("capabilities"),
                    metadata=raw.get("metadata") or {},
                )
            )

        steps = [
            WorkflowStep(
                id=str(raw["id"]),
                agent_name=str(raw["agent_name"]),
                input_from=raw.get("input_from"),
            )
            for raw in self.steps
        ]

        return WorkflowConfig(
            name=self.name,
            pattern=pattern,
            steps=steps,
            agents=agents,
            max_iterations=int(self.max_iterations or 10),
        )

    # ------------------------------------------------------------------ input
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowDefinition":
        """校验并构造定义；非法时抛 DefinitionValidationError。"""
        from agentflow.core.workflow import (
            UnsupportedPatternError,
            WorkflowPattern,
            ensure_supported_pattern,
        )

        if not isinstance(data, dict):
            raise DefinitionValidationError("definition must be a JSON object")
        if isinstance(data.get("definition"), dict):
            data = data["definition"]

        # 导入内容先清洗，避免把密钥写进内存/数据库
        data = _strip_secrets(data)

        version = data.get("schema_version", DEFINITION_SCHEMA_VERSION)
        try:
            version = int(version)
        except (TypeError, ValueError):
            raise DefinitionValidationError("schema_version must be an integer")
        if version != DEFINITION_SCHEMA_VERSION:
            raise DefinitionValidationError(
                f"unsupported definition schema_version: {version}; "
                f"supported: {DEFINITION_SCHEMA_VERSION}"
            )

        workflow_id = _text(data.get("workflow_id"), 64).strip()
        if not workflow_id:
            raise DefinitionValidationError("workflow_id is required")

        name = _text(data.get("name"), 200).strip()
        if not name:
            raise DefinitionValidationError("name is required")

        pattern = (_text(data.get("pattern"), 32).strip() or "sequential")
        try:
            ensure_supported_pattern(WorkflowPattern(pattern))
        except (ValueError, UnsupportedPatternError) as e:
            raise DefinitionValidationError(str(e))

        agents_raw = data.get("agents")
        steps_raw = data.get("steps")
        if not isinstance(agents_raw, list) or not agents_raw:
            raise DefinitionValidationError("agents must be a non-empty list")
        if not isinstance(steps_raw, list) or not steps_raw:
            raise DefinitionValidationError("steps must be a non-empty list")
        if len(agents_raw) > _MAX_AGENTS:
            raise DefinitionValidationError(f"too many agents (>{_MAX_AGENTS})")
        if len(steps_raw) > _MAX_STEPS:
            raise DefinitionValidationError(f"too many steps (>{_MAX_STEPS})")

        agents: List[Dict[str, Any]] = []
        agent_names = set()
        for raw in agents_raw:
            if not isinstance(raw, dict):
                raise DefinitionValidationError("each agent must be an object")
            agent_name = _text(raw.get("name"), 100).strip()
            if not agent_name:
                raise DefinitionValidationError("agent name is required")
            if agent_name in agent_names:
                raise DefinitionValidationError(f"duplicate agent name: {agent_name}")
            agent_names.add(agent_name)
            agents.append(
                {
                    "name": agent_name,
                    "role": _text(raw.get("role") or "worker", 32),
                    "system_prompt": _text(raw.get("system_prompt")),
                    "model": _text(raw.get("model") or "gpt-4", 100),
                    "temperature": _number(raw.get("temperature"), 0.7),
                    "max_tokens": int(_number(raw.get("max_tokens"), 2000)),
                    "tools": raw.get("tools"),
                    "capabilities": raw.get("capabilities"),
                    "metadata": raw.get("metadata") or {},
                }
            )

        steps: List[Dict[str, Any]] = []
        step_ids = set()
        for raw in steps_raw:
            if not isinstance(raw, dict):
                raise DefinitionValidationError("each step must be an object")
            step_id = _text(raw.get("id"), 100).strip()
            agent_name = _text(raw.get("agent_name"), 100).strip()
            if not step_id:
                raise DefinitionValidationError("step id is required")
            if step_id in step_ids:
                raise DefinitionValidationError(f"duplicate step id: {step_id}")
            if agent_name not in agent_names:
                raise DefinitionValidationError(
                    f"step '{step_id}' references unknown agent: {agent_name}"
                )
            step_ids.add(step_id)
            input_from = raw.get("input_from")
            steps.append(
                {
                    "id": step_id,
                    "agent_name": agent_name,
                    "input_from": _text(input_from, 100) if input_from else None,
                }
            )

        for step in steps:
            if step["input_from"] and step["input_from"] not in step_ids:
                raise DefinitionValidationError(
                    f"step '{step['id']}' references unknown input_from: {step['input_from']}"
                )

        max_iterations = int(_number(data.get("max_iterations"), 10))
        if not 1 <= max_iterations <= 100:
            max_iterations = 10

        return cls(
            workflow_id=workflow_id,
            name=name,
            description=_text(data.get("description"), 1000),
            pattern=pattern,
            agents=agents,
            steps=steps,
            max_iterations=max_iterations,
            connection=clean_connection(data.get("connection")),
            metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
            schema_version=version,
            created_at=_number(data.get("created_at"), time.time()),
            updated_at=time.time(),
        )
