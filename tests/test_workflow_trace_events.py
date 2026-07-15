from app.tracing.progress import project_progress_event
from app.tracing.workflow_trace import WorkflowTraceEvent, summarize_trace_value


def test_workflow_trace_event_outputs_schema_dict() -> None:
    """WorkflowTraceEvent 应输出可进入 NodeResult.trace_events 的 schema dict。"""
    event = WorkflowTraceEvent(
        node_name="drafting_parse_input",
        node_type="agent",
        event="agent_started",
        status="started",
        stage="drafting.parse_input",
        agent_name="input_parser_agent",
    )

    payload = event.to_trace_dict()

    assert payload["schema_version"] == "1"
    assert payload["node_name"] == "drafting_parse_input"
    assert payload["node_type"] == "agent"
    assert payload["event"] == "agent_started"
    assert payload["status"] == "started"
    assert payload["stage"] == "drafting.parse_input"
    assert payload["agent_name"] == "input_parser_agent"
    assert "timestamp" in payload


def test_workflow_trace_summary_redacts_sensitive_and_long_values() -> None:
    """摘要 helper 不应泄露长正文或敏感字段。"""
    value = {
        "api_key": "sk-secret-value",
        "token": "Bearer very-secret",
        "content": "夹爪控制交底书" * 80,
        "items": [1, 2, 3],
    }

    summary = summarize_trace_value(value, max_text_chars=24)

    assert "sk-secret-value" not in summary
    assert "very-secret" not in summary
    assert "夹爪控制交底书" not in summary
    assert "api_key=[REDACTED]" in summary
    assert "token=[REDACTED]" in summary
    assert "content=str" in summary
    assert "items=list(len=3)" in summary


def test_progress_projection_uses_visible_progress_fields() -> None:
    """ProgressEvent projection 应只输出前端需要的受控字段。"""
    event = WorkflowTraceEvent(
        trace_id="trace-1",
        workflow_id="workflow-1",
        node_name="drafting_parse_input",
        node_type="agent",
        event="agent_started",
        status="running",
        stage="drafting.parse_input",
        progress={
            "visible": True,
            "stage": "drafting.parse_input",
            "label": "解析输入",
            "message": "正在解析交底材料和用户要求",
            "order": 10,
        },
        tool_call_id="internal-tool-call",
        metadata={"artifact_key": "01_input/raw_document.md"},
    )

    progress = project_progress_event(event)

    assert progress == {
        "trace_id": "trace-1",
        "workflow_id": "workflow-1",
        "node_name": "drafting_parse_input",
        "stage": "drafting.parse_input",
        "status": "running",
        "label": "解析输入",
        "message": "正在解析交底材料和用户要求",
        "visible": True,
        "order": 10,
        "timestamp": event.timestamp,
    }


def test_progress_projection_skips_hidden_events() -> None:
    """不可见 progress 不应投影给前端。"""
    event = WorkflowTraceEvent(
        node_name="qa",
        node_type="normal",
        event="node_completed",
        status="completed",
        stage="qa.answer_generation",
        progress={"visible": False, "label": "问答完成"},
    )

    assert project_progress_event(event) is None


def test_workflow_trace_schema_supports_non_drafting_stage() -> None:
    """schema 应支持 QA 等非文书生成节点。"""
    event = WorkflowTraceEvent(
        node_name="qa",
        node_type="normal",
        event="node_started",
        status="started",
        stage="qa.retrieval",
        progress={
            "visible": True,
            "stage": "qa.retrieval",
            "label": "检索资料",
            "message": "正在检索相关资料",
            "order": 20,
        },
    )

    payload = event.to_trace_dict()
    progress = project_progress_event(event)

    assert payload["stage"] == "qa.retrieval"
    assert payload["node_name"] == "qa"
    assert progress["label"] == "检索资料"
