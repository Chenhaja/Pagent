import json

from app.core.config import Settings
from app.models.schemas import WorkflowState
from app.nodes.drafting_research import DraftingParseInputNode, DraftingPatentSearchNode, DraftingPriorArtAnalysisNode
from app.orchestrator.react_loop import ToolObservation
from app.tools.draft_workspace import DraftWorkspaceTool
from app.tracing.sinks import MemoryWorkflowTraceEmitter
from app.tracing.workflow_trace import WorkflowTraceEvent


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


def test_drafting_parse_input_uses_injected_runner(tmp_path) -> None:
    """drafting_parse_input 应优先使用注入 runner。"""
    class FakeRunner:
        """测试用 runner,模拟 LangChain input_parser。"""

        def __init__(self, workspace: DraftWorkspaceTool) -> None:
            """初始化测试 runner。"""
            self.workspace = workspace
            self.calls = []

        def run(self, tool_input: dict):
            """写入测试 parsed_info 并返回短 observation。"""
            self.calls.append(dict(tool_input))
            key = "01_input/parsed_info.json"
            self.workspace.run({"action": "write", "artifact_key": key, "content": '{"technical_topic":"runner"}'})
            return ToolObservation(tool_name="input_parser", evidence=[{"artifact_key": key, "done": True}], sufficient=True)

    workspace = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path)))
    runner = FakeRunner(workspace)
    node = DraftingParseInputNode(workspace=workspace, input_parser_runner=runner)

    result = node.run(WorkflowState(raw_input="交底书正文"))

    assert result.status == "success"
    assert runner.calls == [{"source_artifact_key": "01_input/raw_document.md"}]


def test_drafting_parse_input_default_runner_falls_back_without_llm(tmp_path) -> None:
    """默认 runner 在 LLM 配置不完整时应本地写入合法 parsed_info。"""
    workspace = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path), allow_network=False, llm_base_url=None, llm_model="", llm_api_key=None))
    node = DraftingParseInputNode(settings=workspace.settings, workspace=workspace)

    result = node.run(WorkflowState(raw_input="一种夹爪控制方法"))
    parsed = workspace.run({"action": "read", "artifact_key": "01_input/parsed_info.json"})
    payload = json.loads(parsed.evidence[0]["content"])

    assert result.status == "success"
    assert payload["uncertain"] is True
    assert payload["technical_topic"] == "一种夹爪控制方法"


def test_drafting_parse_input_aggregates_default_runner_trace_events(monkeypatch, tmp_path) -> None:
    """默认 LangChain runner 的 agent/tool trace 应汇总进节点结果。"""
    workspace = DraftWorkspaceTool(
        Settings(draft_workspace_dir=str(tmp_path), allow_network=True, llm_base_url="https://example.test/v1", llm_model="fake", llm_api_key="fake")
    )
    node = DraftingParseInputNode(settings=workspace.settings, workspace=workspace)

    def fake_run(tool_input: dict) -> ToolObservation:
        """模拟 runner 写入 parsed_info 并发送 agent/tool 事件。"""
        workspace.run({"action": "write", "artifact_key": "01_input/parsed_info.json", "content": '{"technical_topic":"夹爪控制"}'})
        node.input_parser_runner.workflow_trace_emitter.emit(
            WorkflowTraceEvent(node_name="drafting_parse_input", node_type="agent", event="agent_started", status="started", stage="drafting.parse_input", agent_name="input_parser_agent")
        )
        node.input_parser_runner.workflow_trace_emitter.emit(
            WorkflowTraceEvent(
                node_name="drafting_parse_input",
                node_type="tool",
                event="tool_call_completed",
                status="completed",
                stage="drafting.parse_input",
                agent_name="input_parser_agent",
                tool_name="write_parsed_info",
                output_summary="artifact_key=str(len=25), done=bool",
            )
        )
        node.input_parser_runner.workflow_trace_emitter.emit(
            WorkflowTraceEvent(node_name="drafting_parse_input", node_type="agent", event="agent_completed", status="completed", stage="drafting.parse_input", agent_name="input_parser_agent")
        )
        return ToolObservation(tool_name="input_parser", evidence=[{"artifact_key": "01_input/parsed_info.json", "done": True}], sufficient=True)

    monkeypatch.setattr(node.input_parser_runner, "run", fake_run)

    result = node.run(WorkflowState(raw_input="交底书正文"))
    events = [item["event"] for item in result.trace_events]

    assert result.status == "success"
    assert events == ["drafting_source_written", "agent_started", "tool_call_completed", "agent_completed", "drafting_input_parsed"]
    assert result.output == {"input_key": "01_input/raw_document.md", "parsed_info_key": "01_input/parsed_info.json"}
    assert result.trace_events[1]["schema_version"] == "1"
    assert result.trace_events[2]["tool_name"] == "write_parsed_info"
    assert "交底书正文" not in str(result.output)
    assert "交底书正文" not in str(result.trace_events)


def test_drafting_parse_input_uses_injected_workflow_trace_emitter(tmp_path) -> None:
    """显式注入 emitter 时节点与默认 runner 应共用同一 trace 出口。"""
    workspace = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path), allow_network=False, llm_base_url=None, llm_model="", llm_api_key=None))
    emitter = MemoryWorkflowTraceEmitter()
    node = DraftingParseInputNode(settings=workspace.settings, workspace=workspace, workflow_trace_emitter=emitter)

    result = node.run(WorkflowState(raw_input="交底书正文"))

    assert result.status == "success"
    assert node.input_parser_runner.workflow_trace_emitter is emitter
    assert result.trace_events == [
        {"event": "drafting_source_written", "data": {"artifact_key": "01_input/raw_document.md", "chars": 5}},
        {"event": "drafting_input_parsed", "data": {"artifact_key": "01_input/parsed_info.json"}},
    ]


def test_drafting_parse_input_fails_when_parser_writes_invalid_json(tmp_path) -> None:
    """parser 写入非法 JSON 时节点应返回 parsed_info_missing。"""
    class InvalidJsonRunner:
        """测试用 runner,模拟写入非法 JSON。"""

        def __init__(self, workspace: DraftWorkspaceTool) -> None:
            """初始化测试 runner。"""
            self.workspace = workspace

        def run(self, tool_input: dict):
            """写入非法 JSON 并声称成功。"""
            key = "01_input/parsed_info.json"
            self.workspace.run({"action": "write", "artifact_key": key, "content": "not-json"})
            return ToolObservation(tool_name="input_parser", evidence=[{"artifact_key": key, "done": True}], sufficient=True)

    workspace = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path)))
    node = DraftingParseInputNode(workspace=workspace, input_parser_runner=InvalidJsonRunner(workspace))

    result = node.run(WorkflowState(raw_input="交底书正文"))

    assert result.status == "failed"
    assert result.errors == ["parsed_info_missing"]


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


class FakePatentSearchRegistry:
    """测试用专利检索 registry。"""

    def __init__(self, evidence=None, error: str | None = None) -> None:
        """初始化检索结果。"""
        self.evidence = evidence or []
        self.error = error
        self.calls = []

    def run(self, name: str, tool_input: dict):
        """模拟 patent_search 工具调用。"""
        self.calls.append({"name": name, "input": dict(tool_input)})
        return type(
            "Observation",
            (),
            {"error": self.error, "evidence": self.evidence, "sufficient": bool(self.evidence), "external": True},
        )()


def test_drafting_patent_search_writes_results_artifact(tmp_path) -> None:
    """drafting_patent_search 应调用 patent_search 并写入检索结果 artifact。"""
    workspace = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path)))
    workspace.run({"action": "write", "artifact_key": "01_input/parsed_info.json", "content": '{"technical_topic":"夹爪控制"}'})
    evidence = [
        {
            "title": "夹爪控制方法",
            "publication_number": "CN123456B",
            "abstract": "一种夹爪控制方法。",
            "url": "https://example.test/patent/CN123456B",
            "country": "CN",
            "status": "GRANT",
            "provenance": {"source": "serpapi://google_patents"},
        }
    ]
    registry = FakePatentSearchRegistry(evidence=evidence)
    node = DraftingPatentSearchNode(workspace=workspace, tool_registry=registry)
    state = WorkflowState(raw_input="请生成专利文书", drafting_context={"parsed_info_key": "01_input/parsed_info.json"})

    result = node.run(state)
    stored = workspace.run({"action": "read", "artifact_key": "02_research/patent_search_results.json"})
    payload = json.loads(stored.evidence[0]["content"])

    assert result.status == "success"
    assert registry.calls[0]["name"] == "patent_search"
    assert registry.calls[0]["input"]["query"] == "夹爪控制"
    assert payload["results"] == evidence
    assert payload["sufficient"] is True
    assert payload["skipped"] is False
    assert state.drafting_context["patent_search_key"] == "02_research/patent_search_results.json"


def test_drafting_patent_search_degrades_without_fabricating_results(tmp_path) -> None:
    """检索不可用时 drafting_patent_search 应写入 skipped 结果且不编造 evidence。"""
    workspace = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path)))
    workspace.run({"action": "write", "artifact_key": "01_input/parsed_info.json", "content": '{"technical_topic":"夹爪控制"}'})
    node = DraftingPatentSearchNode(workspace=workspace, tool_registry=FakePatentSearchRegistry(error="network_disabled"))
    state = WorkflowState(raw_input="请生成专利文书", drafting_context={"parsed_info_key": "01_input/parsed_info.json"})

    result = node.run(state)
    stored = workspace.run({"action": "read", "artifact_key": "02_research/patent_search_results.json"})
    payload = json.loads(stored.evidence[0]["content"])

    assert result.status == "success"
    assert payload["results"] == []
    assert payload["sufficient"] is False
    assert payload["skipped"] is True
    assert payload["reason"] == "network_disabled"


def test_drafting_prior_art_analysis_writes_structured_analysis(tmp_path) -> None:
    """drafting_prior_art_analysis 应把检索结果转为现有技术分析 artifact。"""
    workspace = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path)))
    workspace.run({"action": "write", "artifact_key": "01_input/parsed_info.json", "content": '{"technical_topic":"夹爪控制"}'})
    workspace.run(
        {
            "action": "write",
            "artifact_key": "02_research/patent_search_results.json",
            "content": json.dumps(
                {
                    "queries": ["夹爪控制"],
                    "results": [{"title": "夹爪控制方法", "publication_number": "CN123456B", "abstract": "一种夹爪控制方法。"}],
                    "sufficient": True,
                    "skipped": False,
                    "reason": "",
                },
                ensure_ascii=False,
            ),
        }
    )
    node = DraftingPriorArtAnalysisNode(workspace=workspace)
    state = WorkflowState(
        raw_input="请生成专利文书",
        drafting_context={
            "parsed_info_key": "01_input/parsed_info.json",
            "patent_search_key": "02_research/patent_search_results.json",
        },
    )

    result = node.run(state)
    stored = workspace.run({"action": "read", "artifact_key": "02_research/prior_art_analysis.json"})
    payload = json.loads(stored.evidence[0]["content"])

    assert result.status == "success"
    assert payload["closest_prior_art"][0]["publication_number"] == "CN123456B"
    assert "distinguishing_features" in payload
    assert "technical_effects" in payload
    assert payload["confidence"] == "medium"
    assert state.drafting_context["prior_art_analysis_key"] == "02_research/prior_art_analysis.json"


def test_drafting_prior_art_analysis_marks_uncertain_when_search_insufficient(tmp_path) -> None:
    """检索不足时 prior_art_analysis 应显式标注不确定且不编造专利号。"""
    workspace = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path)))
    workspace.run({"action": "write", "artifact_key": "01_input/parsed_info.json", "content": '{"technical_topic":"夹爪控制"}'})
    workspace.run(
        {
            "action": "write",
            "artifact_key": "02_research/patent_search_results.json",
            "content": json.dumps({"queries": ["夹爪控制"], "results": [], "sufficient": False, "skipped": True, "reason": "network_disabled"}, ensure_ascii=False),
        }
    )
    node = DraftingPriorArtAnalysisNode(workspace=workspace)
    state = WorkflowState(
        raw_input="请生成专利文书",
        drafting_context={
            "parsed_info_key": "01_input/parsed_info.json",
            "patent_search_key": "02_research/patent_search_results.json",
        },
    )

    result = node.run(state)
    stored = workspace.run({"action": "read", "artifact_key": "02_research/prior_art_analysis.json"})
    payload = json.loads(stored.evidence[0]["content"])

    assert result.status == "success"
    assert payload["closest_prior_art"] == []
    assert payload["uncertain_points"] == ["专利检索未获得足够结果: network_disabled"]
    assert payload["confidence"] == "low"
    assert "CN" not in json.dumps(payload, ensure_ascii=False)
