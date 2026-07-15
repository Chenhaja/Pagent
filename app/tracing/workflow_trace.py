from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.security import redact_sensitive_text

WorkflowTraceNodeType = Literal["normal", "agent", "tool", "gate"]
WorkflowTraceStatus = Literal["started", "running", "completed", "failed", "skipped", "waiting"]
WorkflowTraceEventName = Literal[
    "workflow_started",
    "workflow_completed",
    "workflow_failed",
    "node_started",
    "node_completed",
    "node_failed",
    "node_skipped",
    "progress_updated",
    "agent_started",
    "agent_completed",
    "agent_failed",
    "model_call_started",
    "model_call_completed",
    "model_call_failed",
    "agent_step_started",
    "agent_step_completed",
    "agent_step_failed",
    "tool_call_started",
    "tool_call_completed",
    "tool_call_failed",
]

_SENSITIVE_FIELD_NAMES = {"api_key", "token", "secret", "password", "authorization", "credential"}


class WorkflowTraceEvent(BaseModel):
    """标准 workflow trace 事件。

    Args:
        schema_version: trace schema 版本。
        trace_id: 链路追踪 ID。
        span_id: 当前 span ID。
        parent_span_id: 父 span ID。
        workflow_id: workflow 执行实例 ID。
        session_id: 用户会话 ID。
        request_id: 当前 API 请求 ID。
        node_name: workflow 节点名称。
        node_type: 节点类型。
        event: 稳定英文事件名。
        status: 事件状态。
        stage: 面向业务阶段的命名空间。
        agent_name: agent 名称。
        agent_run_id: agent 执行 ID。
        tool_name: 工具名称。
        tool_call_id: 工具调用 ID。
        input_summary: 输入摘要。
        output_summary: 输出摘要。
        duration_ms: 耗时毫秒数。
        error_type: 错误类型。
        error_message: 错误摘要。
        progress: 前端进度投影字段。
        metadata: 附加短字段。
        timestamp: ISO-8601 时间戳。

    Returns:
        可进入 NodeResult.trace_events 的标准事件对象。
    """

    schema_version: str = "1"
    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    workflow_id: str | None = None
    session_id: str | None = None
    request_id: str | None = None
    node_name: str
    node_type: WorkflowTraceNodeType
    event: WorkflowTraceEventName
    status: WorkflowTraceStatus
    stage: str | None = None
    agent_name: str | None = None
    agent_run_id: str | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    input_summary: str | None = None
    output_summary: str | None = None
    duration_ms: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    progress: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_trace_dict(self) -> dict[str, Any]:
        """转换为可写入 NodeResult.trace_events 的 dict。

        Returns:
            不含敏感长正文的 trace dict。
        """
        payload = self.model_dump()
        payload["metadata"] = sanitize_trace_mapping(payload.get("metadata") or {})
        if payload.get("input_summary") is not None:
            payload["input_summary"] = redact_sensitive_text(str(payload["input_summary"]))
        if payload.get("output_summary") is not None:
            payload["output_summary"] = redact_sensitive_text(str(payload["output_summary"]))
        if payload.get("error_message") is not None:
            payload["error_message"] = redact_sensitive_text(str(payload["error_message"]))
        return payload


def sanitize_trace_mapping(value: dict[str, Any]) -> dict[str, Any]:
    """清洗 trace metadata 短字段。

    Args:
        value: 原始 metadata。

    Returns:
        已脱敏和摘要化的 metadata。
    """
    return {str(key): _safe_trace_value(str(key), item) for key, item in value.items()}


def summarize_trace_value(value: Any, max_text_chars: int = 80) -> str:
    """生成不含长正文的 trace 摘要。

    Args:
        value: 任意待摘要值。
        max_text_chars: 字符串摘要最大长度。

    Returns:
        描述类型、数量或短文本的安全摘要。
    """
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            parts.append(f"{key}={_summary_value_for_key(str(key), item, max_text_chars)}")
        return ", ".join(parts)
    return _summary_value_for_key("value", value, max_text_chars)


def _safe_trace_value(key: str, value: Any) -> Any:
    """按字段名清洗单个 trace 值。"""
    if _is_sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, str):
        return summarize_trace_value(value)
    if isinstance(value, dict):
        return sanitize_trace_mapping(value)
    if isinstance(value, list):
        return f"list(len={len(value)})"
    return value


def _summary_value_for_key(key: str, value: Any, max_text_chars: int) -> str:
    """按字段名生成单个值摘要。"""
    if _is_sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, str):
        text = redact_sensitive_text(value, max_length=max_text_chars)
        if len(value) > max_text_chars or "content" in key.lower() or "prompt" in key.lower():
            return f"str(len={len(value)})"
        return f"str({text})"
    if isinstance(value, list):
        return f"list(len={len(value)})"
    if isinstance(value, dict):
        return f"dict(keys={len(value)})"
    return type(value).__name__


def _is_sensitive_key(key: str) -> bool:
    """判断字段名是否疑似敏感。"""
    lowered = key.lower()
    return any(name in lowered for name in _SENSITIVE_FIELD_NAMES)
