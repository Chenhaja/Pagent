import json

from app.core.config import Settings
from app.models.schemas import WorkflowState
from app.nodes.drafting_gates import DraftingLeaderGateGuidanceNode, DraftingLeaderGatePriorArtNode, DraftingLeaderGateReviewNode
from app.orchestrator.engine import Orchestrator
from app.orchestrator.node_base import Node
from app.models.schemas import NodeResult
from app.tools.draft_workspace import DraftWorkspaceTool


class FakeDecisionRegistry:
    """测试用 Leader gate 决策 registry。"""

    def __init__(self, payload: dict | None = None, error: str | None = None) -> None:
        """初始化 fake 决策结果。"""
        self.payload = payload or {}
        self.error = error
        self.calls = []

    def run(self, name: str, tool_input: dict):
        """模拟 prior_art_gate 子代理调用。"""
        self.calls.append({"name": name, "input": dict(tool_input)})
        return type("Observation", (), {"error": self.error, "evidence": [{"decision": self.payload}]})()


class CountingNode(Node):
    """记录节点执行次数的 fake node。"""

    def run(self, state: WorkflowState) -> NodeResult:
        """累计当前节点执行次数并返回成功。"""
        state.drafting_context[self.name] = int(state.drafting_context.get(self.name, 0)) + 1
        return NodeResult.success()


class AlwaysRetryGate(Node):
    """固定回跳到检索节点的 fake gate。"""

    def run(self, state: WorkflowState) -> NodeResult:
        """返回回跳专利检索节点的结果。"""
        return NodeResult.success(next_node="drafting_patent_search")


def _workspace_with_prior_art(tmp_path) -> DraftWorkspaceTool:
    """构造包含 prior art artifact 的测试 workspace。"""
    workspace = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path)))
    workspace.run(
        {
            "action": "write",
            "artifact_key": "02_research/prior_art_analysis.json",
            "content": json.dumps({"confidence": "medium", "uncertain_points": []}, ensure_ascii=False),
        }
    )
    return workspace


def _workspace_with_guidance(tmp_path, include_drawing: bool = True, include_guide: bool = True) -> DraftWorkspaceTool:
    """构造包含 guidance gate 前置 artifact 的测试 workspace。"""
    workspace = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path)))
    if include_drawing:
        workspace.run(
            {
                "action": "write",
                "artifact_key": "02_research/drawing_analysis.json",
                "content": json.dumps({"confidence": "medium", "uncertain_points": []}, ensure_ascii=False),
            }
        )
    if include_guide:
        workspace.run(
            {
                "action": "write",
                "artifact_key": "02_research/writing_style_guide.json",
                "content": json.dumps({"confidence": "medium", "uncertain_points": []}, ensure_ascii=False),
            }
        )
    return workspace


def _workspace_with_review(tmp_path) -> DraftWorkspaceTool:
    """构造包含 review gate 前置 artifact 的测试 workspace。"""
    workspace = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path)))
    workspace.run({"action": "write", "artifact_key": "05_final/complete_patent.md", "content": "# 完整专利文书"})
    workspace.run(
        {
            "action": "write",
            "artifact_key": "05_final/review_report.md",
            "content": "# 终稿评审报告\n\n- 是否通过：是\n- 置信度：medium",
        }
    )
    return workspace


def _decision(decision: str, target_node: str) -> dict:
    """构造 gate 决策 payload。"""
    return {
        "decision": decision,
        "target_node": target_node,
        "reason": "测试决策",
        "required_changes": ["补充检索"],
        "confidence": "medium",
    }


def test_prior_art_gate_continue_goes_to_drawing_analysis(tmp_path) -> None:
    """prior art gate continue 时应进入附图分析节点。"""
    workspace = _workspace_with_prior_art(tmp_path)
    registry = FakeDecisionRegistry(_decision("continue", "drafting_drawing_analysis"))
    node = DraftingLeaderGatePriorArtNode(workspace=workspace, tool_registry=registry)
    state = WorkflowState(raw_input="请生成专利文书", drafting_context={"prior_art_analysis_key": "02_research/prior_art_analysis.json"})

    result = node.run(state)

    assert result.status == "success"
    assert result.next_node == "drafting_drawing_analysis"
    assert state.drafting_context["leader_gate_prior_art"]["decision"] == "continue"
    assert registry.calls[0]["name"] == "drafting_leader_gate_prior_art"
    assert registry.calls[0]["input"] == {"prior_art_analysis_key": "02_research/prior_art_analysis.json"}


def test_prior_art_gate_retry_goes_to_patent_search(tmp_path) -> None:
    """prior art gate retry 时应回到专利检索节点。"""
    node = DraftingLeaderGatePriorArtNode(
        workspace=_workspace_with_prior_art(tmp_path),
        tool_registry=FakeDecisionRegistry(_decision("retry", "drafting_patent_search")),
    )

    result = node.run(WorkflowState(raw_input="请生成专利文书", drafting_context={"prior_art_analysis_key": "02_research/prior_art_analysis.json"}))

    assert result.status == "success"
    assert result.next_node == "drafting_patent_search"


def test_prior_art_gate_revise_goes_to_prior_art_analysis(tmp_path) -> None:
    """prior art gate revise 时应回到现有技术分析节点。"""
    node = DraftingLeaderGatePriorArtNode(
        workspace=_workspace_with_prior_art(tmp_path),
        tool_registry=FakeDecisionRegistry(_decision("revise", "drafting_prior_art_analysis")),
    )

    result = node.run(WorkflowState(raw_input="请生成专利文书", drafting_context={"prior_art_analysis_key": "02_research/prior_art_analysis.json"}))

    assert result.status == "success"
    assert result.next_node == "drafting_prior_art_analysis"


def test_prior_art_gate_escalate_requires_user_input(tmp_path) -> None:
    """prior art gate escalate 时应要求人工介入。"""
    node = DraftingLeaderGatePriorArtNode(
        workspace=_workspace_with_prior_art(tmp_path),
        tool_registry=FakeDecisionRegistry(_decision("escalate", "drafting_leader_gate_prior_art")),
    )

    result = node.run(WorkflowState(raw_input="请生成专利文书", drafting_context={"prior_art_analysis_key": "02_research/prior_art_analysis.json"}))

    assert result.status == "requires_user_input"
    assert result.errors == ["drafting_gate_escalated"]
    assert result.output["required_changes"] == ["补充检索"]


def test_prior_art_gate_rejects_invalid_decision(tmp_path) -> None:
    """prior art gate 应拒绝非法 decision。"""
    node = DraftingLeaderGatePriorArtNode(
        workspace=_workspace_with_prior_art(tmp_path),
        tool_registry=FakeDecisionRegistry(_decision("skip", "drafting_drawing_analysis")),
    )

    result = node.run(WorkflowState(raw_input="请生成专利文书", drafting_context={"prior_art_analysis_key": "02_research/prior_art_analysis.json"}))

    assert result.status == "failed"
    assert result.errors == ["invalid_gate_decision"]


def test_prior_art_gate_rejects_invalid_target_node(tmp_path) -> None:
    """prior art gate 应拒绝非法 target_node。"""
    node = DraftingLeaderGatePriorArtNode(
        workspace=_workspace_with_prior_art(tmp_path),
        tool_registry=FakeDecisionRegistry(_decision("retry", "drafting_merge_document")),
    )

    result = node.run(WorkflowState(raw_input="请生成专利文书", drafting_context={"prior_art_analysis_key": "02_research/prior_art_analysis.json"}))

    assert result.status == "failed"
    assert result.errors == ["illegal_gate_target:drafting_merge_document"]


def test_prior_art_gate_retry_route_obeys_loop_limit() -> None:
    """prior art gate 回跳路由超过 workflow loop limit 时应安全失败。"""
    state = WorkflowState(raw_input="请生成专利文书")
    orchestrator = Orchestrator(
        nodes={
            "drafting_patent_search": CountingNode("drafting_patent_search"),
            "drafting_prior_art_analysis": CountingNode("drafting_prior_art_analysis"),
            "drafting_leader_gate_prior_art": AlwaysRetryGate("drafting_leader_gate_prior_art"),
        }
    )

    result = orchestrator.run(
        state,
        ["drafting_patent_search", "drafting_prior_art_analysis", "drafting_leader_gate_prior_art"],
        max_loop_count=1,
    )

    assert result.status == "failed"
    assert result.errors == ["loop_limit_exceeded:drafting_patent_search"]
    assert state.drafting_context["drafting_patent_search"] == 2


def test_guidance_gate_continue_goes_to_outline(tmp_path) -> None:
    """guidance gate continue 时应进入大纲生成节点。"""
    registry = FakeDecisionRegistry(_decision("continue", "drafting_generate_outline"))
    node = DraftingLeaderGateGuidanceNode(workspace=_workspace_with_guidance(tmp_path), tool_registry=registry)
    state = WorkflowState(
        raw_input="请生成专利文书",
        drafting_context={
            "drawing_analysis_key": "02_research/drawing_analysis.json",
            "writing_style_guide_key": "02_research/writing_style_guide.json",
        },
    )

    result = node.run(state)

    assert result.status == "success"
    assert result.next_node == "drafting_generate_outline"
    assert state.drafting_context["leader_gate_guidance"]["decision"] == "continue"
    assert registry.calls[0]["name"] == "drafting_leader_gate_guidance"
    assert registry.calls[0]["input"] == {
        "drawing_analysis_key": "02_research/drawing_analysis.json",
        "writing_style_guide_key": "02_research/writing_style_guide.json",
    }


def test_guidance_gate_fails_when_drawing_missing(tmp_path) -> None:
    """guidance gate 应在附图分析缺失时失败。"""
    node = DraftingLeaderGateGuidanceNode(
        workspace=_workspace_with_guidance(tmp_path, include_drawing=False),
        tool_registry=FakeDecisionRegistry(_decision("continue", "drafting_generate_outline")),
    )
    state = WorkflowState(
        raw_input="请生成专利文书",
        drafting_context={
            "drawing_analysis_key": "02_research/drawing_analysis.json",
            "writing_style_guide_key": "02_research/writing_style_guide.json",
        },
    )

    result = node.run(state)

    assert result.status == "failed"
    assert result.errors == ["drawing_analysis_missing"]


def test_guidance_gate_fails_when_style_guide_missing(tmp_path) -> None:
    """guidance gate 应在写作指南缺失时失败。"""
    node = DraftingLeaderGateGuidanceNode(
        workspace=_workspace_with_guidance(tmp_path, include_guide=False),
        tool_registry=FakeDecisionRegistry(_decision("continue", "drafting_generate_outline")),
    )
    state = WorkflowState(
        raw_input="请生成专利文书",
        drafting_context={
            "drawing_analysis_key": "02_research/drawing_analysis.json",
            "writing_style_guide_key": "02_research/writing_style_guide.json",
        },
    )

    result = node.run(state)

    assert result.status == "failed"
    assert result.errors == ["writing_style_guide_missing"]


def test_guidance_gate_retry_goes_to_drawing_analysis(tmp_path) -> None:
    """guidance gate retry 时可回到附图分析节点。"""
    node = DraftingLeaderGateGuidanceNode(
        workspace=_workspace_with_guidance(tmp_path),
        tool_registry=FakeDecisionRegistry(_decision("retry", "drafting_drawing_analysis")),
    )

    result = node.run(
        WorkflowState(
            raw_input="请生成专利文书",
            drafting_context={
                "drawing_analysis_key": "02_research/drawing_analysis.json",
                "writing_style_guide_key": "02_research/writing_style_guide.json",
            },
        )
    )

    assert result.status == "success"
    assert result.next_node == "drafting_drawing_analysis"


def test_guidance_gate_revise_goes_to_style_guide(tmp_path) -> None:
    """guidance gate revise 时可回到写作指南节点。"""
    node = DraftingLeaderGateGuidanceNode(
        workspace=_workspace_with_guidance(tmp_path),
        tool_registry=FakeDecisionRegistry(_decision("revise", "drafting_writing_style_guide")),
    )

    result = node.run(
        WorkflowState(
            raw_input="请生成专利文书",
            drafting_context={
                "drawing_analysis_key": "02_research/drawing_analysis.json",
                "writing_style_guide_key": "02_research/writing_style_guide.json",
            },
        )
    )

    assert result.status == "success"
    assert result.next_node == "drafting_writing_style_guide"


def test_guidance_gate_escalate_requires_user_input(tmp_path) -> None:
    """guidance gate escalate 时应要求人工介入。"""
    node = DraftingLeaderGateGuidanceNode(
        workspace=_workspace_with_guidance(tmp_path),
        tool_registry=FakeDecisionRegistry(_decision("escalate", "drafting_leader_gate_guidance")),
    )

    result = node.run(
        WorkflowState(
            raw_input="请生成专利文书",
            drafting_context={
                "drawing_analysis_key": "02_research/drawing_analysis.json",
                "writing_style_guide_key": "02_research/writing_style_guide.json",
            },
        )
    )

    assert result.status == "requires_user_input"
    assert result.errors == ["drafting_gate_escalated"]


def test_guidance_gate_rejects_illegal_target(tmp_path) -> None:
    """guidance gate 应拒绝非法目标节点。"""
    node = DraftingLeaderGateGuidanceNode(
        workspace=_workspace_with_guidance(tmp_path),
        tool_registry=FakeDecisionRegistry(_decision("retry", "drafting_patent_search")),
    )

    result = node.run(
        WorkflowState(
            raw_input="请生成专利文书",
            drafting_context={
                "drawing_analysis_key": "02_research/drawing_analysis.json",
                "writing_style_guide_key": "02_research/writing_style_guide.json",
            },
        )
    )

    assert result.status == "failed"
    assert result.errors == ["illegal_gate_target:drafting_patent_search"]


def test_review_gate_continue_goes_to_finalize(tmp_path) -> None:
    """review gate continue 时应进入 finalize 节点。"""
    registry = FakeDecisionRegistry(_decision("continue", "drafting_finalize"))
    node = DraftingLeaderGateReviewNode(workspace=_workspace_with_review(tmp_path), tool_registry=registry)
    state = WorkflowState(
        raw_input="请生成专利文书",
        drafting_context={"complete_patent_key": "05_final/complete_patent.md", "review_report_key": "05_final/review_report.md"},
    )

    result = node.run(state)

    assert result.status == "success"
    assert result.next_node == "drafting_finalize"
    assert state.drafting_context["leader_gate_review"]["decision"] == "continue"
    assert registry.calls[0]["name"] == "drafting_leader_gate_review"


def test_review_gate_revise_goes_to_generate_sections(tmp_path) -> None:
    """review gate revise 时应回到正文生成节点。"""
    node = DraftingLeaderGateReviewNode(
        workspace=_workspace_with_review(tmp_path),
        tool_registry=FakeDecisionRegistry(_decision("revise", "drafting_generate_sections")),
    )

    result = node.run(WorkflowState(raw_input="请生成专利文书", drafting_context={"complete_patent_key": "05_final/complete_patent.md", "review_report_key": "05_final/review_report.md"}))

    assert result.status == "success"
    assert result.next_node == "drafting_generate_sections"


def test_review_gate_retry_goes_to_review_document(tmp_path) -> None:
    """review gate retry 时应回到评审节点。"""
    node = DraftingLeaderGateReviewNode(
        workspace=_workspace_with_review(tmp_path),
        tool_registry=FakeDecisionRegistry(_decision("retry", "drafting_review_document")),
    )

    result = node.run(WorkflowState(raw_input="请生成专利文书", drafting_context={"complete_patent_key": "05_final/complete_patent.md", "review_report_key": "05_final/review_report.md"}))

    assert result.status == "success"
    assert result.next_node == "drafting_review_document"


def test_review_gate_escalate_requires_user_input(tmp_path) -> None:
    """review gate escalate 时应要求人工介入。"""
    node = DraftingLeaderGateReviewNode(
        workspace=_workspace_with_review(tmp_path),
        tool_registry=FakeDecisionRegistry(_decision("escalate", "drafting_leader_gate_review")),
    )

    result = node.run(WorkflowState(raw_input="请生成专利文书", drafting_context={"complete_patent_key": "05_final/complete_patent.md", "review_report_key": "05_final/review_report.md"}))

    assert result.status == "requires_user_input"
    assert result.errors == ["drafting_gate_escalated"]


def test_review_gate_fails_when_review_report_missing(tmp_path) -> None:
    """review gate 应在评审报告缺失时安全失败。"""
    workspace = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path)))
    workspace.run({"action": "write", "artifact_key": "05_final/complete_patent.md", "content": "# 完整专利文书"})
    node = DraftingLeaderGateReviewNode(workspace=workspace, tool_registry=FakeDecisionRegistry(_decision("continue", "drafting_finalize")))

    result = node.run(WorkflowState(raw_input="请生成专利文书", drafting_context={"complete_patent_key": "05_final/complete_patent.md", "review_report_key": "05_final/review_report.md"}))

    assert result.status == "failed"
    assert result.errors == ["review_report_missing"]


def test_review_gate_rejects_illegal_target(tmp_path) -> None:
    """review gate 应拒绝非法目标节点。"""
    node = DraftingLeaderGateReviewNode(
        workspace=_workspace_with_review(tmp_path),
        tool_registry=FakeDecisionRegistry(_decision("retry", "drafting_patent_search")),
    )

    result = node.run(WorkflowState(raw_input="请生成专利文书", drafting_context={"complete_patent_key": "05_final/complete_patent.md", "review_report_key": "05_final/review_report.md"}))

    assert result.status == "failed"
    assert result.errors == ["illegal_gate_target:drafting_patent_search"]
