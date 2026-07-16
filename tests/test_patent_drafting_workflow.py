import json

from app.core.config import Settings
from app.models.schemas import WorkflowState
from app.nodes.drafting_content import (
    DraftingFinalizeNode,
    DraftingGenerateOutlineNode,
    DraftingGenerateSectionsNode,
    DraftingMergeDocumentNode,
    DraftingReviewDocumentNode,
)
from app.services.agent_dispatch_service import AgentDispatchService
from app.services.case_service import CaseService
from app.tools.draft_workspace import DraftWorkspaceTool


def test_patent_drafting_workflow_generates_markdown_artifacts(tmp_path, monkeypatch) -> None:
    """patent_drafting 应从请求生成完整 Markdown 产物。"""
    from app.core.config import Settings

    settings = Settings(draft_workspace_dir=str(tmp_path), react_max_steps=8, react_token_budget=2000, react_timeout_seconds=5)
    case_id = CaseService(settings=settings).create_case()["case_id"]
    monkeypatch.setattr(
        "app.services.agent_dispatch_service.get_settings",
        lambda: settings,
    )
    service = AgentDispatchService()

    result = service.dispatch("请根据一种夹爪控制方法生成专利文书", case_id=case_id)

    assert result["status"] == "success"
    assert result["intent"] == "patent_drafting"
    assert result["workflow"] == "patent_drafting"
    assert result["abstract_md"].startswith("# 摘要")
    assert result["claims_md"].startswith("# 权利要求")
    assert result["description_md"].startswith("# 说明书")
    assert result["figures_md"].startswith("# 附图说明")
    assert result["complete_patent_md"].startswith("# 完整专利文书")
    assert result["drafting_incomplete"] is False
    events = [event["event"] for event in result["trace"]]
    assert "drafting_outline_generated" in events
    assert "drafting_finalized" in events


def test_patent_drafting_workflow_consumes_uploaded_documents(tmp_path, monkeypatch) -> None:
    """patent_drafting 应复用 R10 附件 documents 作为输入数据。"""
    from app.core.config import Settings
    from app.services.attachment_service import AttachmentService

    settings = Settings(
        attachment_storage_dir=str(tmp_path / "attachments"),
        draft_workspace_dir=str(tmp_path / "drafts"),
        react_max_steps=8,
        react_token_budget=2000,
        react_timeout_seconds=5,
    )
    attachment_id = AttachmentService(settings=settings).save_upload(
        "交底书.txt",
        "text/plain",
        "附件技术交底".encode("utf-8"),
        "invention_disclosure",
    )["attachment_id"]
    case_id = CaseService(settings=settings).create_case()["case_id"]
    monkeypatch.setattr("app.services.agent_dispatch_service.get_settings", lambda: settings)

    result = AgentDispatchService().dispatch("请生成专利文书", case_id=case_id, attachment_ids=[attachment_id])

    assert result["status"] == "success"
    assert "附件技术交底" in result["input_points_md"]
    assert "attachment_injected" in [event["event"] for event in result["trace"]]


def _content_workspace(tmp_path) -> DraftWorkspaceTool:
    """构造内容节点测试 workspace。"""
    workspace = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path)))
    workspace.run({"action": "write", "artifact_key": "01_input/parsed_info.json", "content": json.dumps({"technical_topic": "夹爪控制"}, ensure_ascii=False)})
    workspace.run(
        {
            "action": "write",
            "artifact_key": "02_research/prior_art_analysis.json",
            "content": json.dumps({"distinguishing_features": ["柔顺夹持"], "technical_effects": ["降低损伤"], "confidence": "medium"}, ensure_ascii=False),
        }
    )
    workspace.run(
        {
            "action": "write",
            "artifact_key": "02_research/drawing_analysis.json",
            "content": json.dumps({"figures": [{"figure_no": "图1", "description": "夹爪结构示意图"}], "confidence": "medium"}, ensure_ascii=False),
        }
    )
    workspace.run(
        {
            "action": "write",
            "artifact_key": "02_research/writing_style_guide.json",
            "content": json.dumps({"claim_style": {"focus_features": ["柔顺夹持"]}, "description_style": {"technical_effects": ["降低损伤"]}, "confidence": "medium"}, ensure_ascii=False),
        }
    )
    return workspace


def test_drafting_generate_outline_writes_outline_artifact(tmp_path) -> None:
    """drafting_generate_outline 应读取前置 artifact 并写入大纲 artifact。"""
    workspace = _content_workspace(tmp_path)
    node = DraftingGenerateOutlineNode(workspace=workspace)
    state = WorkflowState(
        raw_input="请生成专利文书",
        drafting_context={
            "parsed_info_key": "01_input/parsed_info.json",
            "prior_art_analysis_key": "02_research/prior_art_analysis.json",
            "drawing_analysis_key": "02_research/drawing_analysis.json",
            "writing_style_guide_key": "02_research/writing_style_guide.json",
        },
    )

    result = node.run(state)
    stored = workspace.run({"action": "read", "artifact_key": "03_outline/patent_outline.md"})

    assert result.status == "success"
    assert stored.evidence[0]["content"].startswith("# 专利大纲")
    assert "夹爪控制" in stored.evidence[0]["content"]
    assert result.output == {"outline_key": "03_outline/patent_outline.md"}
    assert state.drafting_context["outline_key"] == "03_outline/patent_outline.md"


def test_drafting_generate_sections_writes_content_artifacts(tmp_path) -> None:
    """drafting_generate_sections 应写入摘要、权利要求、说明书和附图说明 artifact。"""
    workspace = _content_workspace(tmp_path)
    workspace.run({"action": "write", "artifact_key": "03_outline/patent_outline.md", "content": "# 专利大纲\n\n主题：夹爪控制"})
    node = DraftingGenerateSectionsNode(workspace=workspace)
    state = WorkflowState(raw_input="请生成专利文书", drafting_context={"outline_key": "03_outline/patent_outline.md", "writing_style_guide_key": "02_research/writing_style_guide.json"})

    result = node.run(state)
    abstract = workspace.run({"action": "read", "artifact_key": "04_content/abstract.md"})
    claims = workspace.run({"action": "read", "artifact_key": "04_content/claims.md"})
    description = workspace.run({"action": "read", "artifact_key": "04_content/description.md"})
    figures = workspace.run({"action": "read", "artifact_key": "04_content/figures.md"})

    assert result.status == "success"
    assert abstract.evidence[0]["content"].startswith("# 摘要")
    assert claims.evidence[0]["content"].startswith("# 权利要求书")
    assert description.evidence[0]["content"].startswith("# 说明书")
    assert figures.evidence[0]["content"].startswith("# 附图说明")
    assert "abstract_md" not in result.output
    assert state.drafting_context["section_keys"] == [
        "04_content/abstract.md",
        "04_content/claims.md",
        "04_content/description.md",
        "04_content/figures.md",
    ]


def test_drafting_merge_document_writes_complete_patent(tmp_path) -> None:
    """drafting_merge_document 应按稳定顺序合并正文 artifact。"""
    workspace = _content_workspace(tmp_path)
    workspace.run({"action": "write", "artifact_key": "04_content/abstract.md", "content": "# 摘要\n\n摘要"})
    workspace.run({"action": "write", "artifact_key": "04_content/claims.md", "content": "# 权利要求书\n\n权利要求"})
    workspace.run({"action": "write", "artifact_key": "04_content/description.md", "content": "# 说明书\n\n说明书"})
    workspace.run({"action": "write", "artifact_key": "04_content/figures.md", "content": "# 附图说明\n\n附图"})
    node = DraftingMergeDocumentNode(workspace=workspace)
    state = WorkflowState(raw_input="请生成专利文书", drafting_context={})

    result = node.run(state)
    stored = workspace.run({"action": "read", "artifact_key": "05_final/complete_patent.md"})

    assert result.status == "success"
    assert stored.evidence[0]["content"].startswith("# 完整专利文书")
    assert stored.evidence[0]["content"].index("# 摘要") < stored.evidence[0]["content"].index("# 权利要求书")
    assert result.output == {"complete_patent_key": "05_final/complete_patent.md"}
    assert state.drafting_context["complete_patent_key"] == "05_final/complete_patent.md"


def test_drafting_review_document_writes_review_report(tmp_path) -> None:
    """drafting_review_document 应读取终稿和指南并写入评审报告。"""
    workspace = _content_workspace(tmp_path)
    workspace.run({"action": "write", "artifact_key": "05_final/complete_patent.md", "content": "# 完整专利文书\n\n# 摘要\n\n# 权利要求书\n\n# 说明书"})
    node = DraftingReviewDocumentNode(workspace=workspace)
    state = WorkflowState(raw_input="请生成专利文书", drafting_context={"complete_patent_key": "05_final/complete_patent.md", "writing_style_guide_key": "02_research/writing_style_guide.json"})

    result = node.run(state)
    stored = workspace.run({"action": "read", "artifact_key": "05_final/review_report.json"})
    payload = json.loads(stored.evidence[0]["content"])

    assert result.status == "success"
    assert payload["passed"] is True
    assert payload["checked_artifacts"] == ["05_final/complete_patent.md", "02_research/writing_style_guide.json"]
    assert result.output == {"review_report_key": "05_final/review_report.json"}
    assert state.drafting_context["review_report_key"] == "05_final/review_report.json"


def test_drafting_finalize_backfills_compatible_fields(tmp_path) -> None:
    """drafting_finalize 应读取 artifact 并回填现有 API 兼容字段。"""
    workspace = _content_workspace(tmp_path)
    artifacts = {
        "01_input/parsed_info.json": "# 输入要点\n\n夹爪控制",
        "02_research/prior_art_analysis.json": "# 现有技术\n\n检索分析",
        "03_outline/patent_outline.md": "# 专利大纲\n\n大纲",
        "04_content/abstract.md": "# 摘要\n\n摘要",
        "04_content/claims.md": "# 权利要求书\n\n权利要求",
        "04_content/description.md": "# 说明书\n\n说明书",
        "04_content/figures.md": "# 附图说明\n\n附图",
        "05_final/complete_patent.md": "# 完整专利文书\n\n终稿",
        "05_final/review_report.json": json.dumps({"passed": True}, ensure_ascii=False),
    }
    for artifact_key, content in artifacts.items():
        workspace.run({"action": "write", "artifact_key": artifact_key, "content": content})
    node = DraftingFinalizeNode(workspace=workspace)
    state = WorkflowState(raw_input="请生成专利文书")

    result = node.run(state)

    assert result.status == "success"
    assert result.output["input_points_md"].startswith("# 输入要点")
    assert result.output["prior_art_md"].startswith("# 现有技术")
    assert result.output["outline_md"].startswith("# 专利大纲")
    assert result.output["abstract_md"].startswith("# 摘要")
    assert result.output["claims_md"].startswith("# 权利要求书")
    assert result.output["description_md"].startswith("# 说明书")
    assert result.output["figures_md"].startswith("# 附图说明")
    assert result.output["complete_patent_md"].startswith("# 完整专利文书")
    assert result.output["drafting_incomplete"] is False
    assert state.complete_patent_md.startswith("# 完整专利文书")


def test_drafting_finalize_marks_incomplete_when_artifact_missing(tmp_path) -> None:
    """drafting_finalize 缺少兼容字段 artifact 时应标记 incomplete。"""
    workspace = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path)))
    workspace.run({"action": "write", "artifact_key": "05_final/complete_patent.md", "content": "# 完整专利文书\n\n终稿"})
    node = DraftingFinalizeNode(workspace=workspace)
    state = WorkflowState(raw_input="请生成专利文书")

    result = node.run(state)

    assert result.status == "success"
    assert result.output["complete_patent_md"].startswith("# 完整专利文书")
    assert result.output["drafting_incomplete"] is True
    assert state.drafting_incomplete is True
