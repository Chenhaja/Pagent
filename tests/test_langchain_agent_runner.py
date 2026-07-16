import json

from app.core.config import Settings
from app.tools.draft_workspace import DraftWorkspaceTool
from app.tools.subagents.file_policy import FileToolPolicy
from app.tools.subagents.file_tools import build_file_tools, select_tools


def test_file_tools_read_and_write_with_policy(tmp_path) -> None:
    """通用文件工具应按 policy 读写 workspace。"""
    workspace = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path)))
    workspace.run({"action": "write", "artifact_key": "docs/source.md", "content": "正文"})
    policy = FileToolPolicy(readRoots=["docs/"], writeRoots=["outputs/"])
    tools = build_file_tools(workspace, policy)

    read_result = json.loads(tools["read_file"].invoke({"path": "docs/source.md"}))
    write_result = json.loads(tools["write_file"].invoke({"path": "outputs/result.md", "content": "结果"}))
    stored = workspace.run({"action": "read", "artifact_key": "outputs/result.md"})

    assert read_result == {"artifact_key": "docs/source.md", "content": "正文"}
    assert write_result["artifact_key"] == "outputs/result.md"
    assert write_result["done"] is True
    assert stored.evidence[0]["content"] == "结果"


def test_file_tools_denied_access_does_not_touch_workspace(monkeypatch, tmp_path) -> None:
    """policy 拒绝时工具不应访问 workspace。"""
    workspace = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path)))
    policy = FileToolPolicy(readRoots=["docs/"], writeRoots=[])
    tools = build_file_tools(workspace, policy)

    def fail_run(tool_input: dict):
        """确保拒绝路径不会触达 workspace。"""
        raise AssertionError("workspace should not be touched")

    monkeypatch.setattr(workspace, "run", fail_run)

    read_result = json.loads(tools["read_file"].invoke({"path": "secrets/token.txt"}))
    write_result = json.loads(tools["write_file"].invoke({"path": "docs/result.md", "content": "x"}))

    assert read_result == {"error": "file_access_denied"}
    assert write_result == {"error": "file_access_denied"}


def test_select_tools_uses_allowed_tools_order() -> None:
    """allowed_tools 应控制传入 create_agent 的工具集合和顺序。"""
    tools = {"read_file": object(), "write_file": object()}

    selected = select_tools(tools, ["write_file", "missing"])

    assert selected == [tools["write_file"]]
