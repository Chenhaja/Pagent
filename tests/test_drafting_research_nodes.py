import json

from app.core.config import Settings
from app.models.schemas import WorkflowState
from app.nodes.drafting_research import DraftingParseInputNode, DraftingPatentSearchNode
from app.orchestrator.react_loop import ToolObservation
from app.tools.draft_workspace import DraftWorkspaceTool
from app.tracing.langchain_trace import WorkflowTraceAgentMiddleware
from app.tracing.sinks import MemoryWorkflowTraceEmitter


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


def test_drafting_parse_input_aggregates_adapter_trace_events(monkeypatch, tmp_path) -> None:
    """默认 LangChain runner 的 adapter trace 应汇总进节点结果。"""
    workspace = DraftWorkspaceTool(
        Settings(draft_workspace_dir=str(tmp_path), allow_network=True, llm_base_url="https://example.test/v1", llm_model="fake", llm_api_key="fake")
    )
    node = DraftingParseInputNode(settings=workspace.settings, workspace=workspace)

    def fake_run(tool_input: dict) -> ToolObservation:
        """模拟 runner 写入 parsed_info 并通过 adapter 发送事件。"""
        middleware = WorkflowTraceAgentMiddleware(
            node.input_parser_runner.workflow_trace_emitter,
            node_name="drafting_parse_input",
            stage="drafting.parse_input",
            agent_name="input_parser_agent",
        )
        middleware.before_agent({"messages": [{"content": "交底书正文"}]}, object())
        middleware.wrap_tool_call(
            type("Request", (), {"tool_call": {"id": "call-1", "name": "write_parsed_info", "args": {"content": "交底书正文"}}, "tool": None})(),
            lambda request: {"artifact_key": "01_input/parsed_info.json", "done": True},
        )
        workspace.run({"action": "write", "artifact_key": "01_input/parsed_info.json", "content": '{"technical_topic":"夹爪控制"}'})
        middleware.after_agent({"messages": []}, object())
        return ToolObservation(tool_name="input_parser", evidence=[{"artifact_key": "01_input/parsed_info.json", "done": True}], sufficient=True)

    monkeypatch.setattr(node.input_parser_runner, "run", fake_run)

    result = node.run(WorkflowState(raw_input="交底书正文"))
    events = [item["event"] for item in result.trace_events]

    assert result.status == "success"
    assert events == ["drafting_source_written", "agent_started", "tool_call_started", "tool_call_completed", "agent_completed", "drafting_input_parsed"]
    assert result.output == {"input_key": "01_input/raw_document.md", "parsed_info_key": "01_input/parsed_info.json"}
    assert result.trace_events[1]["schema_version"] == "1"
    assert result.trace_events[2]["tool_name"] == "write_parsed_info"
    assert result.trace_events[2]["tool_call_id"] == "call-1"
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


def test_drafting_patent_search_default_runner_allows_patent_search(monkeypatch, tmp_path) -> None:
    """drafting_patent_search 默认 runner 应允许 patent_search。"""
    captured = {}

    class FakeLangChainAgentRunner:
        """捕获默认 runner 构造参数。"""

        def __init__(self, **kwargs) -> None:
            """保存 allowed_tools 便于断言。"""
            captured.update(kwargs)

    monkeypatch.setattr("app.nodes.drafting_research.LangChainAgentRunner", FakeLangChainAgentRunner)

    DraftingPatentSearchNode(settings=Settings(draft_workspace_dir=str(tmp_path)))

    assert captured["allowed_tools"] == ["read_file", "write_file", "mkdir", "list_directory", "patent_search"]
    assert captured["file_policy"].writeRoots == [
        "02_research",
        "02_research/patent_search_results.json",
        "02_research/prior_art_analysis.md",
        "02_research/abstract_writing_style.md",
        "02_research/claims_writing_style.md",
        "02_research/description_writing_style.md",
    ]


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


def test_drafting_patent_search_uses_injected_runner_and_requires_prior_art_md(tmp_path) -> None:
    """drafting_patent_search 应支持注入 runner 并校验 prior_art markdown。"""
    class FakeRunner:
        """测试用 patent search runner。"""

        def __init__(self, workspace: DraftWorkspaceTool) -> None:
            """初始化测试 runner。"""
            self.workspace = workspace
            self.calls = []

        def run(self, tool_input: dict) -> ToolObservation:
            """写入检索和现有技术分析 artifact。"""
            self.calls.append(dict(tool_input))
            self.workspace.run(
                {
                    "action": "write",
                    "artifact_key": "02_research/patent_search_results.json",
                    "content": json.dumps({"queries": ["夹爪控制"], "results": [], "sufficient": False, "skipped": True, "reason": "fake"}, ensure_ascii=False),
                }
            )
            self.workspace.run(
                {
                    "action": "write",
                    "artifact_key": "02_research/prior_art_analysis.md",
                    "content": "# 现有技术分析\n\n检索结果不足。",
                }
            )
            return ToolObservation(
                tool_name="patent_searcher_agent",
                evidence=[{"artifact_key": "02_research/patent_search_results.json", "done": True}],
                sufficient=True,
            )

    workspace = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path)))
    workspace.run({"action": "write", "artifact_key": "01_input/parsed_info.json", "content": '{"technical_topic":"夹爪控制"}'})
    runner = FakeRunner(workspace)
    node = DraftingPatentSearchNode(workspace=workspace, patent_search_runner=runner)
    state = WorkflowState(raw_input="请生成专利文书", drafting_context={"parsed_info_key": "01_input/parsed_info.json"})

    result = node.run(state)
    prior_md = workspace.run({"action": "read", "artifact_key": "02_research/prior_art_analysis.md"})

    assert result.status == "success"
    assert runner.calls == [{"parsed_info_key": "01_input/parsed_info.json", "query": "夹爪控制"}]
    assert "# 现有技术分析" in prior_md.evidence[0]["content"]
    assert state.drafting_context["patent_search_key"] == "02_research/patent_search_results.json"
    assert state.drafting_context["prior_art_analysis_key"] == "02_research/prior_art_analysis.md"


def test_drafting_patent_search_fails_without_prior_art_md(tmp_path) -> None:
    """旧 registry 路径未产出 prior_art markdown 时应 fail-fast。"""
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

    assert result.status == "failed"
    assert result.errors == ["prior_art_analysis_missing"]
    assert registry.calls[0]["name"] == "patent_search"
    assert registry.calls[0]["input"]["query"] == "夹爪控制"
    assert payload["results"] == evidence
    assert payload["sufficient"] is True
    assert payload["skipped"] is False


def test_drafting_patent_search_degrades_without_fabricating_results(tmp_path) -> None:
    """检索不可用且未产出 prior_art markdown 时应失败且不编造 evidence。"""
    workspace = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path)))
    workspace.run({"action": "write", "artifact_key": "01_input/parsed_info.json", "content": '{"technical_topic":"夹爪控制"}'})
    node = DraftingPatentSearchNode(workspace=workspace, tool_registry=FakePatentSearchRegistry(error="network_disabled"))
    state = WorkflowState(raw_input="请生成专利文书", drafting_context={"parsed_info_key": "01_input/parsed_info.json"})

    result = node.run(state)
    stored = workspace.run({"action": "read", "artifact_key": "02_research/patent_search_results.json"})
    payload = json.loads(stored.evidence[0]["content"])

    assert result.status == "failed"
    assert result.errors == ["prior_art_analysis_missing"]
    assert payload["results"] == []
    assert payload["sufficient"] is False
    assert payload["skipped"] is True
    assert payload["reason"] == "network_disabled"
    assert "CN" not in json.dumps(payload, ensure_ascii=False)
