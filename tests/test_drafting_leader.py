from app.models.schemas import WorkflowState
from app.nodes.drafting_leader import DraftingLeaderNode


def test_drafting_leader_no_longer_runs_hidden_fixed_flow() -> None:
    """旧 drafting_leader 不应再隐藏执行完整文书生成固定流程。"""
    node = DraftingLeaderNode()

    result = node.run(WorkflowState(raw_input="请撰写专利文书"))

    assert result.status == "failed"
    assert result.errors == ["drafting_leader_deprecated"]
    assert result.output["next_node"] == "drafting_parse_input"
    assert result.trace_events == [
        {
            "event": "drafting_leader_deprecated",
            "data": {"next_node": "drafting_parse_input"},
        }
    ]
