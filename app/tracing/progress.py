from typing import Any

from app.tracing.workflow_trace import WorkflowTraceEvent


def project_progress_event(event: WorkflowTraceEvent) -> dict[str, Any] | None:
    """将 workflow trace 事件投影为前端进度事件。

    Args:
        event: 标准 workflow trace 事件。

    Returns:
        用户可见进度事件;不可见时返回 None。
    """
    progress = event.progress or {}
    if not progress.get("visible"):
        return None
    return {
        "trace_id": event.trace_id,
        "workflow_id": event.workflow_id,
        "node_name": event.node_name,
        "stage": str(progress.get("stage") or event.stage or ""),
        "status": event.status,
        "label": str(progress.get("label") or ""),
        "message": str(progress.get("message") or ""),
        "visible": True,
        "order": int(progress.get("order") or 0),
        "timestamp": event.timestamp,
    }
