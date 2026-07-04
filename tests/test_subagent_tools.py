from app.core.config import Settings
from app.orchestrator.tool_registry import build_default_tool_registry
from app.tools.draft_workspace import DraftWorkspaceTool
from app.tools.subagents import build_patent_drafting_subagent_specs


SUBAGENT_NAMES = [
    "subagent_input_points",
    "subagent_prior_art",
    "subagent_outline",
    "subagent_abstract",
    "subagent_claims",
    "subagent_description",
    "subagent_figures",
    "subagent_complete_patent",
]


def test_builds_eight_patent_drafting_subagent_specs(tmp_path) -> None:
    """subagent-as-tool 应提供 8 个专利文书子代理。"""
    settings = Settings(draft_workspace_dir=str(tmp_path))

    specs = build_patent_drafting_subagent_specs(settings)

    assert [spec.name for spec in specs] == SUBAGENT_NAMES
    assert all(spec.enabled for spec in specs)
    assert all(spec.external is False for spec in specs)


def test_subagent_reads_workspace_key_and_writes_markdown_artifact(tmp_path) -> None:
    """子代理应按 workspace key 读取正文并写入 Markdown artifact。"""
    settings = Settings(draft_workspace_dir=str(tmp_path))
    workspace = DraftWorkspaceTool(settings)
    workspace.run({"action": "write", "artifact_key": "source", "content": "技术交底内容"})
    specs = build_patent_drafting_subagent_specs(settings)
    tool = next(spec.runner for spec in specs if spec.name == "subagent_input_points")

    observation = tool.run({"source_artifact_key": "source"})
    read = workspace.run({"action": "read", "artifact_key": "input_points"})

    assert observation.error is None
    assert observation.sufficient is True
    assert observation.evidence == [
        {"artifact_key": "input_points", "markdown": "# 输入要点\n\n技术交底内容", "done": True}
    ]
    assert read.evidence[0]["content"] == "# 输入要点\n\n技术交底内容"


def test_subagent_rejects_long_inline_content(tmp_path) -> None:
    """子代理不接收长正文参数,只能通过 workspace key 读取。"""
    settings = Settings(draft_workspace_dir=str(tmp_path))
    tool = build_patent_drafting_subagent_specs(settings)[0].runner

    observation = tool.run({"content": "技术交底内容"})

    assert observation.error == "inline_content_not_allowed"


def test_subagent_handles_missing_source_artifact(tmp_path) -> None:
    """源 artifact 缺失时子代理应安全失败。"""
    settings = Settings(draft_workspace_dir=str(tmp_path))
    tool = build_patent_drafting_subagent_specs(settings)[0].runner

    observation = tool.run({"source_artifact_key": "missing"})

    assert observation.error == "artifact_not_found"


def test_default_registry_registers_subagent_tools(tmp_path) -> None:
    """默认 ToolRegistry 应注册 8 个 subagent-as-tool。"""
    registry = build_default_tool_registry(Settings(draft_workspace_dir=str(tmp_path)))

    assert [name for name in SUBAGENT_NAMES if registry.get(name) is not None] == SUBAGENT_NAMES
