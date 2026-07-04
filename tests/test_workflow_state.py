from app.models.schemas import WorkflowState


def test_workflow_state_contains_core_fields() -> None:
    """WorkflowState 应包含规格要求的核心字段。"""
    state = WorkflowState(raw_input="一种节能控制方法")

    assert state.raw_input == "一种节能控制方法"
    assert state.normalized_input is None
    assert state.intent is None
    assert state.dialog_context == {}
    assert state.invention_disclosure == {}
    assert state.documents == []
    assert state.input_points_md == ""
    assert state.prior_art_md == ""
    assert state.outline_md == ""
    assert state.abstract_md == ""
    assert state.claims_md == ""
    assert state.description_md == ""
    assert state.figures_md == ""
    assert state.complete_patent_md == ""
    assert state.drafting_incomplete is False
    assert state.technical_features == []
    assert state.claim_plan == {}
    assert state.claims_draft == []
    assert state.claim_versions == []
    assert state.claim_patches == []
    assert state.validation_report is None
    assert state.user_feedback is None
    assert state.trace == []


def test_workflow_state_uses_independent_default_collections() -> None:
    """默认集合字段不应在不同 state 实例之间共享。"""
    first_state = WorkflowState(raw_input="第一案")
    second_state = WorkflowState(raw_input="第二案")

    first_state.technical_features.append({"name": "节能控制"})
    first_state.trace.append({"event": "feature_extracted"})

    assert second_state.technical_features == []
    assert second_state.trace == []


def test_workflow_state_can_record_trace_event() -> None:
    """WorkflowState 应能记录可审计 trace 事件。"""
    state = WorkflowState(raw_input="一种传感器结构")

    state.add_trace_event("normalize_input_completed", {"node": "normalize_input"})

    assert state.trace == [
        {
            "event": "normalize_input_completed",
            "data": {"node": "normalize_input"},
        }
    ]
