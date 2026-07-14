import pytest
from pydantic import ValidationError

from app.models.schemas import DraftingGateDecision, WorkflowState
from app.orchestrator.workflow_defs import WorkflowRegistry


EXPECTED_DRAFTING_NODES = [
    "normalize_input",
    "drafting_parse_input",
    "drafting_patent_search",
    "drafting_prior_art_analysis",
    "drafting_leader_gate_prior_art",
    "drafting_drawing_analysis",
    "drafting_writing_style_guide",
    "drafting_leader_gate_guidance",
    "drafting_generate_outline",
    "drafting_generate_sections",
    "drafting_merge_document",
    "drafting_review_document",
    "drafting_leader_gate_review",
    "drafting_finalize",
]


def test_patent_drafting_workflow_expands_to_top_level_nodes() -> None:
    """patent_drafting 应在顶层 workflow 中展开完整文书生成节点。"""
    workflow_def = WorkflowRegistry().get_workflow_def("patent_drafting")

    assert workflow_def.intent == "patent_drafting"
    assert workflow_def.start_node == "normalize_input"
    assert workflow_def.max_loop_count == 3
    assert workflow_def.nodes == EXPECTED_DRAFTING_NODES
    assert workflow_def.nodes.count("drafting_leader") == 0


@pytest.mark.parametrize(
    "gate_node",
    [
        "drafting_leader_gate_prior_art",
        "drafting_leader_gate_guidance",
        "drafting_leader_gate_review",
    ],
)
def test_patent_drafting_workflow_contains_limited_leader_gates(gate_node: str) -> None:
    """Leader 应只作为少量 gate 节点出现在顶层 workflow 中。"""
    workflow_def = WorkflowRegistry().get_workflow_def("patent_drafting")

    assert gate_node in workflow_def.nodes


def test_drafting_gate_decision_accepts_structured_decision() -> None:
    """gate decision 应表达结构化路由决策。"""
    decision = DraftingGateDecision(
        decision="retry",
        target_node="drafting_patent_search",
        reason="现有检索结果不足以判断最接近现有技术。",
        required_changes=["扩大关键词", "补充 IPC 检索"],
        confidence="low",
    )

    assert decision.decision == "retry"
    assert decision.target_node == "drafting_patent_search"
    assert decision.required_changes == ["扩大关键词", "补充 IPC 检索"]
    assert decision.confidence == "low"


def test_drafting_gate_decision_rejects_invalid_enum() -> None:
    """gate decision 应拒绝非法 decision 与 confidence 枚举值。"""
    with pytest.raises(ValidationError):
        DraftingGateDecision(
            decision="jump",
            target_node="drafting_patent_search",
            reason="非法决策。",
            confidence="medium",
        )

    with pytest.raises(ValidationError):
        DraftingGateDecision(
            decision="continue",
            target_node="drafting_generate_outline",
            reason="非法置信度。",
            confidence="certain",
        )


def test_workflow_state_keeps_drafting_context_short() -> None:
    """WorkflowState 应提供短字段 drafting_context 保存 artifact key 和 gate 决策。"""
    state = WorkflowState(raw_input="用户长输入正文")
    state.drafting_context["parsed_info_key"] = "01_input/parsed_info.json"
    state.drafting_context["last_gate_decision"] = DraftingGateDecision(
        decision="continue",
        target_node="drafting_generate_outline",
        reason="前置产物足够进入大纲生成。",
        confidence="high",
    ).model_dump()

    assert state.drafting_context["parsed_info_key"] == "01_input/parsed_info.json"
    assert "用户长输入正文" not in str(state.drafting_context)
