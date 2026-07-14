from app.core.config import Settings
from app.models.schemas import WorkflowState
from app.nodes.drafting_research import DraftingParseInputNode
from app.tools.draft_workspace import DraftWorkspaceTool


class FakeToolRegistry:
    """测试用工具注册表,模拟 input_parser 子代理。"""

    def __init__(self, workspace: DraftWorkspaceTool) -> None:
        """初始化测试 registry。"""
        self.workspace = workspace
        self.calls = []

    def run(self, name: str, tool_input: dict):
        """模拟子代理调用并写入 parsed_info artifact。"""
        self.calls.append({"name": name, "input": dict(tool_input)})
        if name != "input_parser":
            return type("Observation", (), {"error": "tool_unavailable", "evidence": []})()
        key = "01_input/parsed_info.json"
        written = self.workspace.run({"action": "write", "artifact_key": key, "content": '{"technical_topic":"夹爪控制"}'})
        if written.error:
            return type("Observation", (), {"error": written.error, "evidence": []})()
        return type("Observation", (), {"error": None, "evidence": [{"artifact_key": key, "done": True}]})()


def test_drafting_parse_input_writes_source_and_parsed_artifacts(tmp_path) -> None:
    """drafting_parse_input 应写入原始输入和 parsed_info artifact。"""
    workspace = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path)))
    registry = FakeToolRegistry(workspace)
    node = DraftingParseInputNode(workspace=workspace, tool_registry=registry)
    state = WorkflowState(raw_input="原始指令", normalized_input="归一化指令")

    result = node.run(state)
    source = workspace.run({"action": "read", "artifact_key": "01_input/raw_document.md"})
    parsed = workspace.run({"action": "read", "artifact_key": "01_input/parsed_info.json"})

    assert result.status == "success"
    assert source.evidence[0]["content"] == "归一化指令"
    assert parsed.evidence[0]["content"] == '{"technical_topic":"夹爪控制"}'
    assert state.drafting_context["input_key"] == "01_input/raw_document.md"
    assert state.drafting_context["parsed_info_key"] == "01_input/parsed_info.json"
    assert registry.calls == [{"name": "input_parser", "input": {"source_artifact_key": "01_input/raw_document.md"}}]


def test_drafting_parse_input_consumes_documents_and_sanitizes_trace(tmp_path) -> None:
    """drafting_parse_input 应合并附件正文但不在 trace 中泄露正文。"""
    workspace = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path)))
    registry = FakeToolRegistry(workspace)
    node = DraftingParseInputNode(workspace=workspace, tool_registry=registry)
    state = WorkflowState(raw_input="用户原文", documents=[{"text": "附件敏感正文"}])

    result = node.run(state)
    source = workspace.run({"action": "read", "artifact_key": "01_input/raw_document.md"})

    assert result.status == "success"
    assert source.evidence[0]["content"] == "用户原文\n\n附件敏感正文"
    trace_text = str(result.trace_events)
    assert "用户原文" not in trace_text
    assert "附件敏感正文" not in trace_text
    assert "01_input/raw_document.md" in trace_text


def test_drafting_parse_input_fails_when_parser_does_not_write_artifact(tmp_path) -> None:
    """input_parser 未产出 parsed_info 时节点应返回可解释失败。"""
    class MissingParserRegistry(FakeToolRegistry):
        """测试用 registry,模拟 parser 未写文件。"""

        def run(self, name: str, tool_input: dict):
            """返回成功但不写 artifact。"""
            self.calls.append({"name": name, "input": dict(tool_input)})
            return type("Observation", (), {"error": None, "evidence": [{"artifact_key": "01_input/parsed_info.json", "done": True}]})()

    workspace = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path)))
    node = DraftingParseInputNode(workspace=workspace, tool_registry=MissingParserRegistry(workspace))

    result = node.run(WorkflowState(raw_input="交底书正文"))

    assert result.status == "failed"
    assert result.errors == ["parsed_info_missing"]
