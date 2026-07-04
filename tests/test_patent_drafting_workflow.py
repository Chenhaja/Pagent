from app.services.agent_dispatch_service import AgentDispatchService


def test_patent_drafting_workflow_generates_markdown_artifacts(tmp_path, monkeypatch) -> None:
    """patent_drafting 应从请求生成完整 Markdown 产物。"""
    from app.core.config import Settings

    monkeypatch.setattr(
        "app.services.agent_dispatch_service.get_settings",
        lambda: Settings(draft_workspace_dir=str(tmp_path), react_max_steps=8, react_token_budget=2000, react_timeout_seconds=5),
    )
    service = AgentDispatchService()

    result = service.dispatch("请根据一种夹爪控制方法生成专利文书")

    assert result["status"] == "success"
    assert result["intent"] == "patent_drafting"
    assert result["workflow"] == "patent_drafting"
    assert result["abstract_md"].startswith("# 摘要")
    assert result["claims_md"].startswith("# 权利要求")
    assert result["description_md"].startswith("# 说明书")
    assert result["figures_md"].startswith("# 附图说明")
    assert result["complete_patent_md"].startswith("# 完整专利文书")
    assert result["drafting_incomplete"] is False


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
    monkeypatch.setattr("app.services.agent_dispatch_service.get_settings", lambda: settings)

    result = AgentDispatchService().dispatch("请生成专利文书", attachment_ids=[attachment_id])

    assert result["status"] == "success"
    assert "附件技术交底" in result["input_points_md"]
    assert "attachment_injected" in [event["event"] for event in result["trace"]]
