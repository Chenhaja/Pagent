import json

from app.core.config import Settings
from app.models.schemas import WorkflowState
from app.nodes.drafting_content import (
    DraftingAbstractWriterNode,
    DraftingClaimsWriterNode,
    DraftingDescriptionWriterNode,
    DraftingDiagramGeneratorNode,
    DraftingGenerateOutlineNode,
    DraftingMergeDocumentNode,
)
from app.orchestrator.react_loop import ToolObservation
from app.tools.draft_workspace import DraftWorkspaceTool
from app.tracing.langchain_trace import WorkflowTraceAgentMiddleware
from app.tracing.sinks import MemoryWorkflowTraceEmitter


def _workspace_with_research(tmp_path) -> DraftWorkspaceTool:
    """构造包含 parsed/search/prior_art 的测试工作区。"""
    workspace = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path), allow_network=False, llm_base_url=None, llm_model="", llm_api_key=None))
    workspace.run({"action": "write", "artifact_key": "01_input/parsed_info.json", "content": '{"technical_topic":"夹爪控制"}'})
    workspace.run({"action": "write", "artifact_key": "02_research/patent_search_results.json", "content": json.dumps({"results": [], "sufficient": False}, ensure_ascii=False)})
    workspace.run({"action": "write", "artifact_key": "02_research/prior_art_analysis.json", "content": json.dumps({"distinguishing_features": ["柔性夹持"], "confidence": "low"}, ensure_ascii=False)})
    return workspace


def test_content_default_runners_allow_list_skills(monkeypatch, tmp_path) -> None:
    """内容节点默认 runner 应允许 list/load skill 工具。"""
    captured_allowed_tools = []

    class FakeLangChainAgentRunner:
        """捕获内容节点默认 runner 构造参数。"""

        def __init__(self, *args, **kwargs) -> None:
            """保存 allowed_tools 便于断言。"""
            allowed_tools = kwargs.get("allowed_tools") if "allowed_tools" in kwargs else args[5]
            captured_allowed_tools.append(allowed_tools)

    monkeypatch.setattr("app.nodes.drafting_content.LangChainAgentRunner", FakeLangChainAgentRunner)
    settings = Settings(draft_workspace_dir=str(tmp_path))
    workspace = DraftWorkspaceTool(settings)

    DraftingGenerateOutlineNode(settings=settings, workspace=workspace)
    DraftingClaimsWriterNode(settings=settings, workspace=workspace)
    DraftingDescriptionWriterNode(settings=settings, workspace=workspace)
    DraftingMergeDocumentNode(settings=settings, workspace=workspace)

    assert captured_allowed_tools == [
        ["read_file", "write_file", "mkdir", "list_directory", "list_skills", "load_skill"],
        ["read_file", "write_file", "mkdir", "list_directory", "list_skills", "load_skill"],
        ["read_file", "write_file", "mkdir", "list_directory", "list_skills", "load_skill"],
        ["read_file", "write_file", "mkdir", "list_directory", "list_skills", "load_skill"],
        ["read_file", "write_file", "mkdir", "list_directory", "list_skills", "load_skill"],
    ]


def test_outline_node_no_longer_requires_legacy_drawing_or_style(tmp_path) -> None:
    """outline 节点不应依赖旧 drawing/style guide artifact。"""
    workspace = _workspace_with_research(tmp_path)
    node = DraftingGenerateOutlineNode(settings=workspace.settings, workspace=workspace)
    state = WorkflowState(raw_input="", drafting_context={"parsed_info_key": "01_input/parsed_info.json"})

    result = node.run(state)
    stored = workspace.run({"action": "read", "artifact_key": "03_outline/patent_outline.md"})

    assert result.status == "success"
    assert result.output == {"outline_key": "03_outline/patent_outline.md"}
    assert "夹爪控制" in stored.evidence[0]["content"]


def test_explicit_content_nodes_write_expected_artifacts(tmp_path) -> None:
    """显式内容节点应离线写入 claims/description/figures/abstract artifacts。"""
    workspace = _workspace_with_research(tmp_path)
    state = WorkflowState(raw_input="", drafting_context={"parsed_info_key": "01_input/parsed_info.json"})
    outline = DraftingGenerateOutlineNode(settings=workspace.settings, workspace=workspace).run(state)
    claims = DraftingClaimsWriterNode(settings=workspace.settings, workspace=workspace).run(state)
    description = DraftingDescriptionWriterNode(settings=workspace.settings, workspace=workspace).run(state)
    figures = DraftingDiagramGeneratorNode(settings=workspace.settings, workspace=workspace).run(state)
    abstract = DraftingAbstractWriterNode(settings=workspace.settings, workspace=workspace).run(state)

    assert outline.status == "success"
    assert claims.output == {"claims_key": "04_content/claims.md"}
    assert description.output == {"description_key": "04_content/description.md"}
    assert figures.output == {"figures_key": "04_content/figures.md"}
    assert abstract.output == {"abstract_key": "04_content/abstract.md"}
    assert workspace.run({"action": "read", "artifact_key": "04_content/description_part1.md"}).error is None
    assert workspace.run({"action": "read", "artifact_key": "04_content/description_part2.md"}).error is None
    assert "# 权利要求书" in workspace.run({"action": "read", "artifact_key": "04_content/claims.md"}).evidence[0]["content"]
    assert "# 说明书" in workspace.run({"action": "read", "artifact_key": "04_content/description.md"}).evidence[0]["content"]
    assert "# 附图说明" in workspace.run({"action": "read", "artifact_key": "04_content/figures.md"}).evidence[0]["content"]
    assert "# 摘要" in workspace.run({"action": "read", "artifact_key": "04_content/abstract.md"}).evidence[0]["content"]


def test_content_node_aggregates_agent_trace_without_long_text(tmp_path) -> None:
    """新增内容节点应汇总 agent trace 且不泄露长正文。"""
    class FakeRunner:
        """测试用 runner,模拟 middleware trace。"""

        def __init__(self, workspace: DraftWorkspaceTool, emitter: MemoryWorkflowTraceEmitter) -> None:
            """初始化测试 runner。"""
            self.workspace = workspace
            self.emitter = emitter

        def run(self, tool_input: dict) -> ToolObservation:
            """发送 trace 并写入 claims artifact。"""
            middleware = WorkflowTraceAgentMiddleware(self.emitter, "drafting_claims_writer", "drafting.claims", "claims_writer_agent")
            middleware.before_agent({"messages": [{"content": "超长敏感交底正文" * 50}]}, object())
            self.workspace.run({"action": "write", "artifact_key": "04_content/claims.md", "content": "# 权利要求书\n\n1. 一种夹爪控制方法。"})
            middleware.after_agent({"messages": []}, object())
            return ToolObservation(tool_name="claims_writer_agent", evidence=[{"artifact_key": "04_content/claims.md", "done": True}], sufficient=True)

    workspace = _workspace_with_research(tmp_path)
    DraftingGenerateOutlineNode(settings=workspace.settings, workspace=workspace).run(WorkflowState(raw_input=""))
    emitter = MemoryWorkflowTraceEmitter()
    runner = FakeRunner(workspace, emitter)
    node = DraftingClaimsWriterNode(settings=workspace.settings, workspace=workspace, claims_runner=runner, workflow_trace_emitter=emitter)

    result = node.run(WorkflowState(raw_input=""))
    trace_text = str(result.trace_events)

    assert result.status == "success"
    assert "agent_started" in [item["event"] for item in result.trace_events]
    assert "超长敏感交底正文" not in trace_text
    assert "04_content/claims.md" in str(result.output)


def test_merge_document_node_requires_runner_review_report(tmp_path) -> None:
    """merge 节点应校验 runner 写入完整文书和评审报告。"""
    class FakeMergeRunner:
        """测试用 merge runner,模拟 LLM 写入终稿和评审报告。"""

        def __init__(self, workspace: DraftWorkspaceTool) -> None:
            """初始化测试 runner。"""
            self.workspace = workspace
            self.calls = []

        def run(self, tool_input: dict) -> ToolObservation:
            """写入终稿和 LLM 评审报告。"""
            self.calls.append(dict(tool_input))
            self.workspace.run({"action": "write", "artifact_key": "05_final/complete_patent.md", "content": "# 完整专利文书\n\n# 摘要\n\n# 权利要求书\n\n# 说明书\n\n# 附图说明"})
            self.workspace.run({"action": "write", "artifact_key": "05_final/review_report.md", "content": "# 终稿评审报告\n\nLLM 评审结论"})
            return ToolObservation(tool_name="markdown_merger_agent", evidence=[{"artifact_key": "05_final/complete_patent.md", "done": True}], sufficient=True)

    workspace = _workspace_with_research(tmp_path)
    state = WorkflowState(raw_input="", drafting_context={"parsed_info_key": "01_input/parsed_info.json"})
    DraftingGenerateOutlineNode(settings=workspace.settings, workspace=workspace).run(state)
    DraftingClaimsWriterNode(settings=workspace.settings, workspace=workspace).run(state)
    DraftingDescriptionWriterNode(settings=workspace.settings, workspace=workspace).run(state)
    DraftingDiagramGeneratorNode(settings=workspace.settings, workspace=workspace).run(state)
    DraftingAbstractWriterNode(settings=workspace.settings, workspace=workspace).run(state)

    runner = FakeMergeRunner(workspace)
    result = DraftingMergeDocumentNode(settings=workspace.settings, workspace=workspace, merge_runner=runner).run(state)
    complete = workspace.run({"action": "read", "artifact_key": "05_final/complete_patent.md"})
    report = workspace.run({"action": "read", "artifact_key": "05_final/review_report.md"})

    assert result.status == "success"
    assert result.output == {"complete_patent_key": "05_final/complete_patent.md"}
    assert "# 摘要" in complete.evidence[0]["content"]
    assert "# 权利要求书" in complete.evidence[0]["content"]
    assert "# 说明书" in complete.evidence[0]["content"]
    assert "# 附图说明" in complete.evidence[0]["content"]
    assert "# 终稿评审报告" in report.evidence[0]["content"]
    assert "LLM 评审结论" in report.evidence[0]["content"]
    assert runner.calls and "05_final/review_report.md" in runner.calls[0]["task"]
