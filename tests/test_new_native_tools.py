from app.core.config import Settings
from app.orchestrator.tool_registry import build_default_tool_registry
from app.tools.draft_workspace import DraftWorkspaceTool
from app.tools.patent_search import PatentSearchTool
from app.tools.skill_loader import SkillLoaderTool


def test_draft_workspace_writes_and_reads_artifacts(tmp_path) -> None:
    """draft_workspace 应安全写入和读取 artifact。"""
    tool = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path), draft_artifact_max_chars=20))

    written = tool.run({"action": "write", "artifact_key": "input_points", "content": "技术要点"})
    read = tool.run({"action": "read", "artifact_key": "input_points"})

    assert written.error is None
    assert written.evidence[0]["artifact_key"] == "input_points.md"
    assert written.evidence[0]["chars"] == 4
    assert read.error is None
    assert read.evidence[0]["content"] == "技术要点"


def test_draft_workspace_rejects_unsafe_keys_and_truncates(tmp_path) -> None:
    """draft_workspace 应拒绝不安全 key 并按配置截断正文。"""
    tool = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path), draft_artifact_max_chars=5))

    unsafe = tool.run({"action": "write", "artifact_key": "../secret", "content": "内容"})
    written = tool.run({"action": "write", "artifact_key": "claims", "content": "123456789"})
    read = tool.run({"action": "read", "artifact_key": "claims"})

    assert unsafe.error == "invalid_artifact_key"
    assert written.evidence[0]["truncated"] is True
    assert read.evidence[0]["content"] == "12345"


def test_skill_loader_reads_only_known_skills() -> None:
    """skill_loader 只允许读取白名单技能内容。"""
    tool = SkillLoaderTool()

    loaded = tool.run({"skill_name": "patent_qa"})
    rejected = tool.run({"skill_name": "../secret"})

    assert loaded.error is None
    assert loaded.evidence[0]["skill_name"] == "patent_qa"
    assert loaded.evidence[0]["content"]
    assert rejected.error == "skill_unavailable"


def test_patent_search_is_skipped_without_network() -> None:
    """patent_search 默认离线 skipped,不误触网。"""
    tool = PatentSearchTool(Settings(allow_network=False))

    observation = tool.run({"query": "夹爪"})

    assert observation.error == "network_disabled"
    assert observation.external is True
    assert observation.evidence == []


def test_patent_search_returns_fake_evidence_when_network_allowed() -> None:
    """联网打开时 patent_search 返回可核对的占位 evidence。"""
    tool = PatentSearchTool(Settings(allow_network=True))

    observation = tool.run({"query": "夹爪"})

    assert observation.error is None
    assert observation.external is True
    assert observation.evidence[0]["content"] == "patent_search skipped: 夹爪"
    assert observation.evidence[0]["provenance"]["source"] == "patent_search://fake"


def test_default_tool_registry_registers_drafting_native_tools(tmp_path) -> None:
    """默认 ToolRegistry 应注册 R11 drafting native tools。"""
    settings = Settings(draft_workspace_dir=str(tmp_path), allow_network=False)
    registry = build_default_tool_registry(settings)

    assert registry.run("draft_workspace", {"action": "write", "artifact_key": "outline", "content": "提纲"}).error is None
    assert registry.run("skill_loader", {"skill_name": "patent_qa"}).error is None
    assert registry.run("patent_search", {"query": "夹爪"}).error == "network_disabled"
