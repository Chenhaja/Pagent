import logging
from typing import Protocol

from app.core.logging import log_event
from app.tracing.workflow_trace import WorkflowTraceEvent

logger = logging.getLogger(__name__)


class WorkflowTraceEmitter(Protocol):
    """Workflow trace 事件发送协议。

    Returns:
        可接收 WorkflowTraceEvent 的发送端协议。
    """

    def emit(self, event: WorkflowTraceEvent) -> None:
        """发送单个 workflow trace 事件。

        Args:
            event: 标准 workflow trace 事件。

        Returns:
            无返回值。
        """


class NoopWorkflowTraceEmitter:
    """忽略所有 workflow trace 事件的安全 emitter。"""

    @property
    def trace_events(self) -> list[dict]:
        """返回空 trace 事件列表。"""
        return []

    def emit(self, event: WorkflowTraceEvent) -> None:
        """忽略单个 workflow trace 事件。

        Args:
            event: 标准 workflow trace 事件。

        Returns:
            无返回值。
        """
        return None


class MemoryWorkflowTraceEmitter:
    """收集 workflow trace 事件的内存 emitter。"""

    def __init__(self) -> None:
        """初始化空事件列表。"""
        self.events: list[WorkflowTraceEvent] = []

    @property
    def trace_events(self) -> list[dict]:
        """返回可进入 NodeResult.trace_events 的事件列表。"""
        return [event.to_trace_dict() for event in self.events]

    def emit(self, event: WorkflowTraceEvent) -> None:
        """收集单个 workflow trace 事件。

        Args:
            event: 标准 workflow trace 事件。

        Returns:
            无返回值。
        """
        self.events.append(event)


class LoggerWorkflowTraceSink:
    """将 workflow trace 事件写入结构化日志。"""

    def __init__(self, logger: logging.Logger | None = None, level: int = logging.INFO) -> None:
        """初始化 logger sink。

        Args:
            logger: 目标 logger,未传时使用当前模块 logger。
            level: 日志级别。

        Returns:
            无返回值。
        """
        self.logger = logger or logging.getLogger(__name__)
        self.level = level

    def emit(self, event: WorkflowTraceEvent) -> None:
        """输出单个 workflow trace 结构化日志。

        Args:
            event: 标准 workflow trace 事件。

        Returns:
            无返回值。
        """
        payload = event.to_trace_dict()
        log_event(
            self.logger,
            self.level,
            str(payload["event"]),
            "workflow trace 事件",
            **{key: value for key, value in payload.items() if key not in {"event", "timestamp"}},
        )


def safe_emit_workflow_trace(emitter: WorkflowTraceEmitter | None, event: WorkflowTraceEvent) -> None:
    """安全发送 workflow trace 事件。

    Args:
        emitter: 可选事件发送端。
        event: 标准 workflow trace 事件。

    Returns:
        无返回值;发送失败时只记录 warning。
    """
    if emitter is None:
        return
    try:
        emitter.emit(event)
    except Exception as exc:
        log_event(logger, logging.WARNING, "workflow_trace_emit_failed", "workflow trace 写入失败", reason=exc.__class__.__name__)
