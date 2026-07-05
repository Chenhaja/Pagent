from app.models.schemas import WorkflowState
from app.nodes.drafting_leader import DRAFTING_ALLOWED_TOOLS, DRAFTING_ARTIFACT_FIELDS, DRAFTING_SOURCE_ARTIFACT_KEY, DraftingLeaderNode


class RecordingWorkspace:
    """测试用 workspace,记录读写和 list 操作。"""

    def __init__(self, contents: dict[str, str] | None = None) -> None:
        """初始化内存 workspace。"""
        self.contents = contents or {}
        self.calls = []

    def run(self, tool_input: dict):
        """按 DraftWorkspaceTool 协议处理内存 artifact。"""
        self.calls.append(dict(tool_input))
        action = tool_input["action"]
        if action == "write":
            key = tool_input["artifact_key"]
            self.contents[key] = tool_input.get("content", "")
            return type("Observation", (), {"error": None, "evidence": [{"artifact_key": key, "chars": len(self.contents[key])}]})()
        if action == "read":
            key = tool_input["artifact_key"]
            if key not in self.contents:
                return type("Observation", (), {"error": "artifact_not_found", "evidence": []})()
            return type("Observation", (), {"error": None, "evidence": [{"artifact_key": key, "content": self.contents[key], "chars": len(self.contents[key])}]})()
        if action == "list":
            prefix = tool_input.get("prefix", "")
            artifacts = sorted(key for key in self.contents if key.startswith(prefix))
            return type("Observation", (), {"error": None, "evidence": [{"prefix": prefix, "artifacts": artifacts, "count": len(artifacts)}]})()
        return type("Observation", (), {"error": "invalid_action", "evidence": []})()


class RecordingRegistry:
    """测试用工具注册表,记录子代理和 todo 调用。"""

    def __init__(self, workspace: RecordingWorkspace, missing_once: str | None = None) -> None:
        """初始化记录型 registry。"""
        self.workspace = workspace
        self.missing_once = missing_once
        self.calls = []
        self.output_by_tool = {
            "input_parser": "01_input/parsed_info.json",
            "patent_searcher": "02_research/prior_art_analysis.md",
            "outline_generator": "03_outline/patent_outline.md",
            "abstract_writer": "04_content/abstract.md",
            "claims_writer": "04_content/claims.md",
            "description_writer_part1": "04_content/description.md",
            "description_writer_part2": "04_content/description.md",
            "diagram_generator": "04_content/figures.md",
            "markdown_merger": "05_final/complete_patent.md",
        }

    def run(self, name: str, tool_input: dict):
        """模拟 todo 与子代理工具调用。"""
        self.calls.append({"name": name, "input": dict(tool_input)})
        if name == "todo":
            return type("Observation", (), {"error": None, "evidence": [{"owner": tool_input.get("owner"), "todos": tool_input.get("todos", [])}]})()
        output_key = self.output_by_tool[name]
        if self.missing_once == name:
            self.missing_once = None
            return type("Observation", (), {"error": None, "evidence": [{"artifact_key": output_key, "done": True}]})()
        self.workspace.contents[output_key] = f"# {output_key}"
        return type("Observation", (), {"error": None, "evidence": [{"artifact_key": output_key, "done": True}]})()

    def get(self, name: str):
        """返回工具存在性。"""
        return object() if name in ["todo", *DRAFTING_ALLOWED_TOOLS] else None


def test_drafting_leader_runs_r12_subagents_in_order() -> None:
    """drafting leader 应按 R12 9 环节顺序调用子代理。"""
    workspace = RecordingWorkspace()
    registry = RecordingRegistry(workspace)
    node = DraftingLeaderNode(workspace=workspace, tool_registry=registry)

    result = node.run(WorkflowState(raw_input="请撰写专利文书", normalized_input="请撰写专利文书"))

    assert result.status == "success"
    assert [call["name"] for call in registry.calls if call["name"] in DRAFTING_ALLOWED_TOOLS] == DRAFTING_ALLOWED_TOOLS
    assert workspace.calls[0] == {"action": "write", "artifact_key": DRAFTING_SOURCE_ARTIFACT_KEY, "content": "请撰写专利文书"}


def test_drafting_leader_writes_r12_source_and_state_fields() -> None:
    """drafting leader 应初始化 01_input 并回填 R12 产物字段。"""
    workspace = RecordingWorkspace()
    registry = RecordingRegistry(workspace)
    node = DraftingLeaderNode(workspace=workspace, tool_registry=registry)
    state = WorkflowState(raw_input="交底书正文", documents=[{"text": "附件正文"}])

    result = node.run(state)

    assert workspace.contents[DRAFTING_SOURCE_ARTIFACT_KEY] == "交底书正文\n\n附件正文"
    assert result.output["complete_patent_md"] == "# 05_final/complete_patent.md"
    assert state.input_points_md == "# 01_input/parsed_info.json"
    assert state.complete_patent_md == "# 05_final/complete_patent.md"
    assert state.drafting_incomplete is False


def test_drafting_leader_reviews_with_list_and_retries_missing_file() -> None:
    """drafting leader 应用 list 审查产物,缺失时最多重委托。"""
    workspace = RecordingWorkspace()
    registry = RecordingRegistry(workspace, missing_once="abstract_writer")
    node = DraftingLeaderNode(workspace=workspace, tool_registry=registry)

    result = node.run(WorkflowState(raw_input="交底书正文"))

    assert result.status == "success"
    assert [call["name"] for call in registry.calls].count("abstract_writer") == 2
    list_calls = [call for call in workspace.calls if call["action"] == "list"]
    assert any(call["prefix"] == "04_content" for call in list_calls)


def test_drafting_leader_uses_todo_tool_not_write_todos() -> None:
    """drafting leader 应接入 todo 工具且不调用 write_todos。"""
    workspace = RecordingWorkspace()
    registry = RecordingRegistry(workspace)
    node = DraftingLeaderNode(workspace=workspace, tool_registry=registry)

    node.run(WorkflowState(raw_input="交底书正文"))

    called_names = [call["name"] for call in registry.calls]
    assert "todo" in called_names
    assert "write_todos" not in called_names


def test_drafting_leader_trace_is_sanitized() -> None:
    """drafting leader trace 仅包含工具名、artifact key、长度、状态和错误摘要。"""
    workspace = RecordingWorkspace()
    registry = RecordingRegistry(workspace)
    node = DraftingLeaderNode(workspace=workspace, tool_registry=registry)

    result = node.run(WorkflowState(raw_input="用户原文", documents=[{"text": "附件敏感正文"}]))

    trace_text = str(result.trace_events)
    assert "附件敏感正文" not in trace_text
    assert "用户原文" not in trace_text
    completed = next(event for event in result.trace_events if event["event"] == "drafting_leader_completed")
    assert completed["data"]["artifact_keys"] == list(DRAFTING_ARTIFACT_FIELDS)
    assert completed["data"]["complete_patent_chars"] == len("# 05_final/complete_patent.md")
