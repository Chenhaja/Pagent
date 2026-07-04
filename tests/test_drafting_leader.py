from app.models.schemas import WorkflowState
from app.nodes.drafting_leader import DRAFTING_ALLOWED_TOOLS, DRAFTING_ARTIFACT_FIELDS, DraftingLeaderNode
from app.orchestrator.react_loop import ReActOutcome
from app.tools.draft_workspace import DraftWorkspaceTool


class FakeReactLoop:
    """测试用 drafting ReAct loop,记录调用并返回固定 outcome。"""

    def __init__(self, outcome: ReActOutcome) -> None:
        """初始化测试 loop。

        Args:
            outcome: 每次 run 返回的固定结果。

        Returns:
            无返回值。
        """
        self.outcome = outcome
        self.calls = []

    def run(self, task_input: str, allowed_tools: list[str]) -> ReActOutcome:
        """记录任务输入和工具白名单。"""
        self.calls.append({"task_input": task_input, "allowed_tools": allowed_tools})
        return self.outcome


class RecordingWorkspace:
    """测试用 workspace,记录写入并提供 artifact 内容。"""

    def __init__(self, contents: dict[str, str] | None = None) -> None:
        """初始化内存 workspace。"""
        self.contents = contents or {}
        self.calls = []

    def run(self, tool_input: dict):
        """按 DraftWorkspaceTool 协议读写内存 artifact。"""
        self.calls.append(tool_input)
        action = tool_input["action"]
        key = tool_input["artifact_key"]
        if action == "write":
            self.contents[key] = tool_input.get("content", "")
            return type("Observation", (), {"error": None, "evidence": [{"artifact_key": key, "chars": len(self.contents[key])}]})()
        if key not in self.contents:
            return type("Observation", (), {"error": "artifact_not_found", "evidence": []})()
        return type("Observation", (), {"error": None, "evidence": [{"artifact_key": key, "content": self.contents[key], "chars": len(self.contents[key])}]})()


def make_outcome(reason: str = "sufficient", evidence: list[dict] | None = None) -> ReActOutcome:
    """构造测试用 ReAct outcome。"""
    return ReActOutcome(
        evidence=evidence or [],
        reason=reason,
        steps_used=8,
        tool_calls=8,
        trace_events=[
            {"event": "react_main_step", "data": {"tool_name": "subagent_input_points", "input_len": 20}},
            {"event": "react_main_converged", "data": {"reason": reason, "steps_used": 8, "tool_calls": 8}},
        ],
    )


def test_drafting_leader_uses_drafting_tool_whitelist() -> None:
    """drafting leader 只能向 ReAct loop 暴露 drafting 白名单工具。"""
    loop = FakeReactLoop(make_outcome())
    workspace = RecordingWorkspace({key: f"# {key}" for key in DRAFTING_ARTIFACT_FIELDS})
    node = DraftingLeaderNode(react_loop=loop, workspace=workspace)

    result = node.run(WorkflowState(raw_input="请撰写专利文书", normalized_input="请撰写专利文书"))

    assert result.status == "success"
    assert loop.calls[0]["allowed_tools"] == DRAFTING_ALLOWED_TOOLS
    assert "请撰写专利文书" not in loop.calls[0]["task_input"]
    assert "source_artifact_key=drafting_source" in loop.calls[0]["task_input"]


def test_drafting_leader_writes_source_and_state_fields() -> None:
    """drafting leader 应写入 source artifact 并回填 Markdown 产物字段。"""
    contents = {key: f"# {key}" for key in DRAFTING_ARTIFACT_FIELDS}
    workspace = RecordingWorkspace(contents)
    node = DraftingLeaderNode(react_loop=FakeReactLoop(make_outcome()), workspace=workspace)
    state = WorkflowState(
        raw_input="交底书正文",
        normalized_input="交底书正文",
        documents=[{"filename": "交底书.txt", "text": "附件正文", "truncated": False}],
    )

    result = node.run(state)

    assert workspace.calls[0] == {"action": "write", "artifact_key": "drafting_source", "content": "交底书正文\n\n附件正文"}
    assert result.output["complete_patent_md"] == "# complete_patent"
    assert state.input_points_md == "# input_points"
    assert state.complete_patent_md == "# complete_patent"
    assert state.drafting_incomplete is False


def test_drafting_leader_marks_incomplete_when_budget_exhausted() -> None:
    """预算耗尽时 drafting leader 应标记 incomplete。"""
    workspace = RecordingWorkspace({key: f"# {key}" for key in DRAFTING_ARTIFACT_FIELDS})
    node = DraftingLeaderNode(react_loop=FakeReactLoop(make_outcome(reason="max_steps")), workspace=workspace)
    state = WorkflowState(raw_input="交底书正文")

    result = node.run(state)

    assert result.status == "success"
    assert result.output["drafting_incomplete"] is True
    assert state.drafting_incomplete is True


def test_drafting_leader_trace_is_sanitized() -> None:
    """drafting leader trace 不应包含附件正文或完整文书正文。"""
    sensitive = "敏感完整专利正文"
    workspace = RecordingWorkspace({key: f"# {key} {sensitive}" for key in DRAFTING_ARTIFACT_FIELDS})
    outcome = make_outcome(evidence=[{"artifact_key": "complete_patent", "markdown": sensitive, "done": True}])
    node = DraftingLeaderNode(react_loop=FakeReactLoop(outcome), workspace=workspace)

    result = node.run(WorkflowState(raw_input="用户原文", documents=[{"text": "附件敏感正文"}]))

    trace_text = str(result.trace_events)
    assert "附件敏感正文" not in trace_text
    assert sensitive not in trace_text
    completed = next(event for event in result.trace_events if event["event"] == "drafting_leader_completed")
    assert completed["data"]["artifact_keys"] == list(DRAFTING_ARTIFACT_FIELDS)
    assert completed["data"]["complete_patent_chars"] == len(f"# complete_patent {sensitive}")


def test_drafting_leader_default_loop_runs_subagents_in_sop_order(tmp_path) -> None:
    """默认 bounded ReAct loop 应按 SOP 顺序调用 8 个子代理。"""
    from app.core.config import Settings

    settings = Settings(draft_workspace_dir=str(tmp_path), react_max_steps=8, react_token_budget=2000, react_timeout_seconds=5)
    workspace = DraftWorkspaceTool(settings)
    node = DraftingLeaderNode(settings=settings, workspace=workspace)
    state = WorkflowState(raw_input="技术交底内容")

    result = node.run(state)

    assert result.status == "success"
    assert [event["data"]["tool_name"] for event in result.trace_events if event["event"] == "react_main_step"] == DRAFTING_ALLOWED_TOOLS
    assert state.complete_patent_md.startswith("# 完整专利文书")
