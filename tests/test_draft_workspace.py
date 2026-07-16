from app.core.config import Settings
from app.orchestrator.tool_registry import build_default_tool_registry
from app.tools.draft_workspace import DraftWorkspaceTool


def test_draft_workspace_uses_memory_store_by_default(tmp_path) -> None:
    """draft_workspace 默认应使用内存 key-store,不创建磁盘 artifact。"""
    tool = DraftWorkspaceTool(Settings(draft_workspace_dir="", draft_artifact_max_chars=20))

    written = tool.run({"action": "write", "artifact_key": "04_content/abstract.md", "content": "摘要内容"})
    read = tool.run({"action": "read", "artifact_key": "04_content/abstract.md"})

    assert written.error is None
    assert written.evidence[0]["artifact_key"] == "04_content/abstract.md"
    assert read.error is None
    assert read.evidence[0]["content"] == "摘要内容"
    assert list(tmp_path.iterdir()) == []


def test_draft_workspace_supports_disk_project_workspace(tmp_path) -> None:
    """配置目录后 draft_workspace 应将 artifact 落在项目工作区内。"""
    tool = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path), draft_artifact_max_chars=20))

    written = tool.run({"action": "write", "artifact_key": "04_content/claims.md", "content": "权利要求"})
    read = tool.run({"action": "read", "artifact_key": "04_content/claims.md"})

    assert written.error is None
    assert read.evidence[0]["content"] == "权利要求"
    assert (tmp_path / "temp_default" / "04_content" / "claims.md").read_text(encoding="utf-8") == "权利要求"


def test_draft_workspace_supports_case_workspace_name(tmp_path) -> None:
    """传入 workspace_name 时应直接使用指定案件 workspace 目录。"""
    tool = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path)), workspace_name="tmp_case123")

    written = tool.run({"action": "write", "artifact_key": "04_content/claims.md", "content": "权利要求"})

    assert written.error is None
    assert (tmp_path / "tmp_case123" / "04_content" / "claims.md").read_text(encoding="utf-8") == "权利要求"
    assert not (tmp_path / "temp_default").exists()


def test_draft_workspace_lists_artifacts_by_prefix(tmp_path) -> None:
    """list 动作应枚举指定目录下的 artifact。"""
    tool = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path)))
    tool.run({"action": "write", "artifact_key": "04_content/abstract.md", "content": "摘要"})
    tool.run({"action": "write", "artifact_key": "04_content/claims.md", "content": "权利要求"})
    tool.run({"action": "write", "artifact_key": "05_final/summary_report.md", "content": "报告"})

    listed = tool.run({"action": "list", "prefix": "04_content"})

    assert listed.error is None
    assert listed.evidence[0]["artifacts"] == ["04_content/abstract.md", "04_content/claims.md"]
    assert listed.evidence[0]["directories"] == ["01_input", "02_research", "03_outline", "04_content", "05_final"]


def test_draft_workspace_merges_artifacts_in_order(tmp_path) -> None:
    """merge 动作应按 source_artifact_keys 顺序合并并写入 output_artifact_key。"""
    tool = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path)))
    tool.run({"action": "write", "artifact_key": "04_content/abstract.md", "content": "摘要"})
    tool.run({"action": "write", "artifact_key": "04_content/claims.md", "content": "权利要求"})

    merged = tool.run(
        {
            "action": "merge",
            "source_artifact_keys": ["04_content/abstract.md", "04_content/claims.md"],
            "output_artifact_key": "05_final/complete_patent.md",
        }
    )
    read = tool.run({"action": "read", "artifact_key": "05_final/complete_patent.md"})

    assert merged.error is None
    assert read.evidence[0]["content"] == "摘要\n\n权利要求"


def test_draft_workspace_rejects_unsafe_relative_paths(tmp_path) -> None:
    """artifact key 必须是安全的相对路径。"""
    tool = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path)))

    escaped = tool.run({"action": "write", "artifact_key": "../secret.md", "content": "secret"})
    absolute = tool.run({"action": "write", "artifact_key": "/04_content/abstract.md", "content": "secret"})
    invalid = tool.run({"action": "write", "artifact_key": "04_content/abs tract.md", "content": "secret"})

    assert escaped.error == "invalid_artifact_key"
    assert absolute.error == "invalid_artifact_key"
    assert invalid.error == "invalid_artifact_key"


def test_draft_workspace_truncates_content(tmp_path) -> None:
    """draft_workspace 应按配置截断过长 artifact。"""
    tool = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path), draft_artifact_max_chars=5))

    written = tool.run({"action": "write", "artifact_key": "04_content/description.md", "content": "123456789"})
    read = tool.run({"action": "read", "artifact_key": "04_content/description.md"})

    assert written.evidence[0]["truncated"] is True
    assert read.evidence[0]["content"] == "12345"


def test_default_tool_registry_registers_r12_draft_workspace_schema(tmp_path) -> None:
    """默认 ToolRegistry 应注册支持 list 与 merge 的 draft_workspace schema。"""
    registry = build_default_tool_registry(Settings(draft_workspace_dir=str(tmp_path)))
    spec = registry.tool_specs()["draft_workspace"]

    assert spec.input_schema["properties"]["action"]["enum"] == ["write", "read", "list", "merge"]
    assert "source_artifact_keys" in spec.input_schema["properties"]
    assert "output_artifact_key" in spec.input_schema["properties"]
