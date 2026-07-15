import time
from typing import Any, Callable

from app.tracing.sinks import WorkflowTraceEmitter, safe_emit_workflow_trace
from app.tracing.workflow_trace import WorkflowTraceEvent, summarize_trace_value

try:
    from langchain.agents.middleware import AgentMiddleware
except ImportError:  # pragma: no cover - 仅用于缺少 LangChain 时保持模块可导入
    AgentMiddleware = object  # type: ignore[misc,assignment]


class WorkflowTraceAgentMiddleware(AgentMiddleware):  # type: ignore[misc,valid-type]
    """将 LangChain create_agent middleware 事件转换为 workflow trace。

    Args:
        emitter: workflow trace 事件发送端。
        node_name: 所属 workflow 节点名称。
        stage: 业务阶段命名空间。
        agent_name: agent 名称。

    Returns:
        可传给 create_agent(middleware=...) 的 middleware 实例。
    """

    def __init__(self, emitter: WorkflowTraceEmitter | None, node_name: str, stage: str, agent_name: str) -> None:
        """初始化 trace middleware 上下文。"""
        self.emitter = emitter
        self.node_name = node_name
        self.stage = stage
        self.agent_name = agent_name
        self._agent_started_at: float | None = None

    def before_agent(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        """agent 执行前发送 started 事件。"""
        self._agent_started_at = time.perf_counter()
        self._emit(event="agent_started", status="started", node_type="agent", input_summary=summarize_trace_value(_safe_state_summary(state)))
        return None

    def after_agent(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        """agent 正常结束后发送 completed 事件。"""
        self._emit(
            event="agent_completed",
            status="completed",
            node_type="agent",
            duration_ms=_duration_ms(self._agent_started_at),
            output_summary=summarize_trace_value(_safe_state_summary(state)),
        )
        return None

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        """包裹模型调用并发送 model started/completed/failed 事件。"""
        started_at = time.perf_counter()
        self._emit(event="model_call_started", status="started", node_type="agent", input_summary=_model_request_summary(request))
        try:
            response = handler(request)
        except Exception as exc:
            self._emit(
                event="model_call_failed",
                status="failed",
                node_type="agent",
                duration_ms=_duration_ms(started_at),
                error_type=exc.__class__.__name__,
                error_message=str(exc) or exc.__class__.__name__,
            )
            raise
        self._emit(event="model_call_completed", status="completed", node_type="agent", duration_ms=_duration_ms(started_at), output_summary=_model_response_summary(response))
        return response

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        """包裹工具调用并发送 tool started/completed/failed 事件。"""
        started_at = time.perf_counter()
        tool_name = _tool_name(request)
        tool_call_id = _tool_call_id(request)
        self._emit(
            event="tool_call_started",
            status="started",
            node_type="tool",
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            input_summary=_tool_input_summary(request),
        )
        try:
            response = handler(request)
        except Exception as exc:
            self._emit(
                event="tool_call_failed",
                status="failed",
                node_type="tool",
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                duration_ms=_duration_ms(started_at),
                error_type=exc.__class__.__name__,
                error_message=str(exc) or exc.__class__.__name__,
            )
            raise
        self._emit(
            event="tool_call_completed",
            status="completed",
            node_type="tool",
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            duration_ms=_duration_ms(started_at),
            output_summary=summarize_trace_value(_safe_public_attrs(response)),
        )
        return response

    def _emit(self, event: str, status: str, node_type: str, **kwargs: Any) -> None:
        """发送单个标准 workflow trace 事件。"""
        safe_emit_workflow_trace(
            self.emitter,
            WorkflowTraceEvent(
                node_name=self.node_name,
                node_type=node_type,  # type: ignore[arg-type]
                event=event,  # type: ignore[arg-type]
                status=status,  # type: ignore[arg-type]
                stage=self.stage,
                agent_name=self.agent_name,
                **kwargs,
            ),
        )


def emit_langchain_step_event(emitter: WorkflowTraceEmitter | None, event_payload: dict[str, Any], node_name: str, stage: str, agent_name: str) -> None:
    """将 LangChain stream event 转换为 agent step trace 事件。

    Args:
        emitter: workflow trace 事件发送端。
        event_payload: LangChain stream_events/astream_events 产出的单个事件。
        node_name: 所属 workflow 节点名称。
        stage: 业务阶段命名空间。
        agent_name: agent 名称。

    Returns:
        无返回值;不识别的事件会被忽略。
    """
    event_name = _step_event_name(event_payload)
    if event_name is None:
        return
    safe_emit_workflow_trace(
        emitter,
        WorkflowTraceEvent(
            node_name=node_name,
            node_type="agent",
            event=event_name,
            status=_status_for_step_event(event_name),
            stage=stage,
            agent_name=agent_name,
            input_summary=summarize_trace_value(event_payload.get("data") or {}),
            metadata={
                "langchain_event": event_payload.get("event"),
                "name": event_payload.get("name"),
                "run_id": event_payload.get("run_id"),
                "parent_ids": event_payload.get("parent_ids") or [],
            },
        ),
    )


def _step_event_name(event_payload: dict[str, Any]) -> str | None:
    """从 LangChain stream event 名称判断 step 事件名。"""
    raw_event = str(event_payload.get("event") or "")
    if raw_event in {"on_chain_start", "on_graph_start"}:
        return "agent_step_started"
    if raw_event in {"on_chain_end", "on_graph_end"}:
        return "agent_step_completed"
    if raw_event in {"on_chain_error", "on_graph_error"}:
        return "agent_step_failed"
    return None


def _status_for_step_event(event_name: str) -> str:
    """按 step 事件名返回标准状态。"""
    if event_name.endswith("started"):
        return "started"
    if event_name.endswith("failed"):
        return "failed"
    return "completed"


def _duration_ms(started_at: float | None) -> int | None:
    """计算耗时毫秒,缺少起点时返回 None。"""
    if started_at is None:
        return None
    return int((time.perf_counter() - started_at) * 1000)


def _model_request_summary(request: Any) -> str:
    """生成模型请求的安全摘要。"""
    return summarize_trace_value(
        {
            "messages": getattr(request, "messages", []),
            "tools": getattr(request, "tools", []),
            "tool_choice": getattr(request, "tool_choice", None),
            "model_settings": getattr(request, "model_settings", {}),
        }
    )


def _model_response_summary(response: Any) -> str:
    """生成模型响应的安全摘要。"""
    return summarize_trace_value(_safe_public_attrs(response))


def _tool_name(request: Any) -> str | None:
    """提取工具名称。"""
    tool = getattr(request, "tool", None)
    tool_call = getattr(request, "tool_call", {}) or {}
    return str(getattr(tool, "name", None) or tool_call.get("name") or "") or None


def _tool_call_id(request: Any) -> str | None:
    """提取工具调用 ID。"""
    tool_call = getattr(request, "tool_call", {}) or {}
    value = tool_call.get("id") or tool_call.get("tool_call_id")
    return str(value) if value else None


def _tool_input_summary(request: Any) -> str:
    """生成工具输入安全摘要。"""
    tool_call = getattr(request, "tool_call", {}) or {}
    return summarize_trace_value({"args": tool_call.get("args", {}), "name": tool_call.get("name")})


def _safe_state_summary(state: Any) -> dict[str, Any]:
    """提取 agent state 的非原文摘要。"""
    if isinstance(state, dict):
        return {"keys": sorted(str(key) for key in state.keys()), "messages": state.get("messages", [])}
    return _safe_public_attrs(state)


def _safe_public_attrs(value: Any) -> dict[str, Any]:
    """提取对象公开字段的短摘要输入。"""
    if isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for name in ("result", "structured_response", "content", "status", "name"):
        if hasattr(value, name):
            result[name] = getattr(value, name)
    return result or {"type": value.__class__.__name__}
