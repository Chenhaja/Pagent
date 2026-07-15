import json

from app.core.config import Settings
from app.tools.draft_workspace import DraftWorkspaceTool
from app.tools.subagents.input_parser_agent import LangChainInputParserAgent
from app.tracing.sinks import MemoryWorkflowTraceEmitter


def test_input_parser_agent_fallback_when_llm_config_incomplete(tmp_path) -> None:
    """LLM 配置不完整时 runner 应写入合法 fallback JSON。"""
    settings = Settings(draft_workspace_dir=str(tmp_path), allow_network=False, llm_base_url=None, llm_model="", llm_api_key=None)
    workspace = DraftWorkspaceTool(settings)
    workspace.run({"action": "write", "artifact_key": "01_input/raw_document.md", "content": "夹爪控制交底书"})
    agent = LangChainInputParserAgent(settings=settings, workspace=workspace)

    result = agent.run({"source_artifact_key": "01_input/raw_document.md"})
    stored = workspace.run({"action": "read", "artifact_key": "01_input/parsed_info.json"})
    payload = json.loads(stored.evidence[0]["content"])

    assert result.error is None
    assert result.evidence == [{"artifact_key": "01_input/parsed_info.json", "done": True}]
    assert payload["uncertain"] is True
    assert payload["source"] == "夹爪控制交底书"


def test_input_parser_agent_rejects_unexpected_source_artifact(tmp_path) -> None:
    """runner 只接受固定 source artifact key。"""
    settings = Settings(draft_workspace_dir=str(tmp_path), allow_network=False)
    workspace = DraftWorkspaceTool(settings)
    agent = LangChainInputParserAgent(settings=settings, workspace=workspace)

    result = agent.run({"source_artifact_key": "../raw_document.md"})

    assert result.error == "invalid_source_artifact_key"


def test_input_parser_agent_restricted_write_only_targets_parsed_info(tmp_path) -> None:
    """受限写入工具只能写 parsed_info artifact。"""
    settings = Settings(draft_workspace_dir=str(tmp_path), allow_network=True, llm_base_url="https://example.test/v1", llm_model="fake", llm_api_key="fake")
    workspace = DraftWorkspaceTool(settings)
    agent = LangChainInputParserAgent(settings=settings, workspace=workspace)
    tools = agent._build_tools("01_input/raw_document.md", [])
    write_tool = next(item for item in tools if item.name == "write_parsed_info")

    result = write_tool.invoke({"content": '{"technical_topic":"夹爪控制"}'})
    parsed = workspace.run({"action": "read", "artifact_key": "01_input/parsed_info.json"})
    other = workspace.run({"action": "read", "artifact_key": "05_final/complete_patent.md"})

    assert json.loads(result)["artifact_key"] == "01_input/parsed_info.json"
    assert json.loads(parsed.evidence[0]["content"])["technical_topic"] == "夹爪控制"
    assert other.error == "artifact_not_found"


def test_input_parser_agent_invalid_json_write_is_rejected(tmp_path) -> None:
    """受限写入工具拒绝非法 JSON。"""
    settings = Settings(draft_workspace_dir=str(tmp_path), allow_network=True, llm_base_url="https://example.test/v1", llm_model="fake", llm_api_key="fake")
    workspace = DraftWorkspaceTool(settings)
    agent = LangChainInputParserAgent(settings=settings, workspace=workspace)
    tools = agent._build_tools("01_input/raw_document.md", [])
    write_tool = next(item for item in tools if item.name == "write_parsed_info")

    result = write_tool.invoke({"content": "not-json"})
    parsed = workspace.run({"action": "read", "artifact_key": "01_input/parsed_info.json"})

    assert json.loads(result)["error"] == "invalid_json_object"
    assert parsed.error == "artifact_not_found"


def test_input_parser_agent_falls_back_after_agent_writes_invalid_json(monkeypatch, tmp_path) -> None:
    """真实 agent 产出非法 JSON 时 runner 应覆盖为合法 fallback JSON。"""
    settings = Settings(draft_workspace_dir=str(tmp_path), allow_network=True, llm_base_url="https://example.test/v1", llm_model="fake", llm_api_key="fake")
    workspace = DraftWorkspaceTool(settings)
    workspace.run({"action": "write", "artifact_key": "01_input/raw_document.md", "content": "交底书正文"})
    agent = LangChainInputParserAgent(settings=settings, workspace=workspace)

    class FakeAgent:
        """测试用 LangChain agent。"""

        def invoke(self, payload: dict) -> dict:
            """写入非法 JSON 后返回。"""
            workspace.run({"action": "write", "artifact_key": "01_input/parsed_info.json", "content": "not-json"})
            return {}

    def fake_import_langchain():
        """返回测试用 create_agent 和 ChatOpenAI。"""
        return (lambda **kwargs: FakeAgent()), lambda **kwargs: object()

    monkeypatch.setattr(agent, "_import_langchain", fake_import_langchain)

    result = agent.run({"source_artifact_key": "01_input/raw_document.md"})
    stored = workspace.run({"action": "read", "artifact_key": "01_input/parsed_info.json"})
    payload = json.loads(stored.evidence[0]["content"])

    assert result.error is None
    assert payload["uncertain"] is True
    assert payload["uncertain_points"] == ["input_parser 使用安全降级结果: invalid_agent_json"]


def test_input_parser_agent_emits_agent_lifecycle_events(monkeypatch, tmp_path) -> None:
    """真实 agent 路径应发送 agent 生命周期事件。"""
    settings = Settings(draft_workspace_dir=str(tmp_path), allow_network=True, llm_base_url="https://example.test/v1", llm_model="fake", llm_api_key="fake")
    workspace = DraftWorkspaceTool(settings)
    emitter = MemoryWorkflowTraceEmitter()
    workspace.run({"action": "write", "artifact_key": "01_input/raw_document.md", "content": "交底书正文"})
    agent = LangChainInputParserAgent(settings=settings, workspace=workspace, workflow_trace_emitter=emitter)

    class FakeAgent:
        """测试用成功 LangChain agent。"""

        def invoke(self, payload: dict) -> dict:
            """写入合法 JSON 后返回。"""
            workspace.run({"action": "write", "artifact_key": "01_input/parsed_info.json", "content": '{"technical_topic":"夹爪控制"}'})
            return {}

    monkeypatch.setattr(agent, "_import_langchain", lambda: ((lambda **kwargs: FakeAgent()), lambda **kwargs: object()))

    result = agent.run({"source_artifact_key": "01_input/raw_document.md"})
    events = [item.event for item in emitter.events]

    assert result.error is None
    assert events == ["agent_started", "agent_completed"]
    assert emitter.events[0].node_name == "drafting_parse_input"
    assert emitter.events[0].agent_name == "input_parser_agent"


def test_input_parser_agent_emits_agent_failed_event(monkeypatch, tmp_path) -> None:
    """agent 异常时应发送失败事件并保持 fallback。"""
    settings = Settings(draft_workspace_dir=str(tmp_path), allow_network=True, llm_base_url="https://example.test/v1", llm_model="fake", llm_api_key="fake")
    workspace = DraftWorkspaceTool(settings)
    emitter = MemoryWorkflowTraceEmitter()
    workspace.run({"action": "write", "artifact_key": "01_input/raw_document.md", "content": "交底书正文"})
    agent = LangChainInputParserAgent(settings=settings, workspace=workspace, workflow_trace_emitter=emitter)

    class FakeAgent:
        """测试用失败 LangChain agent。"""

        def invoke(self, payload: dict) -> dict:
            """模拟 agent 调用失败。"""
            raise RuntimeError("agent down")

    monkeypatch.setattr(agent, "_import_langchain", lambda: ((lambda **kwargs: FakeAgent()), lambda **kwargs: object()))

    result = agent.run({"source_artifact_key": "01_input/raw_document.md"})
    events = [item.event for item in emitter.events]

    assert result.error is None
    assert events == ["agent_started", "agent_failed"]
    assert emitter.events[-1].error_type == "RuntimeError"


def test_input_parser_agent_emits_tool_success_and_failed_events(tmp_path) -> None:
    """受控工具调用应发送 tool 成功和失败事件。"""
    settings = Settings(draft_workspace_dir=str(tmp_path), allow_network=True, llm_base_url="https://example.test/v1", llm_model="fake", llm_api_key="fake")
    workspace = DraftWorkspaceTool(settings)
    emitter = MemoryWorkflowTraceEmitter()
    workspace.run({"action": "write", "artifact_key": "01_input/raw_document.md", "content": "交底书正文"})
    agent = LangChainInputParserAgent(settings=settings, workspace=workspace, workflow_trace_emitter=emitter)
    tools = agent._build_tools("01_input/raw_document.md", [])
    read_tool = next(item for item in tools if item.name == "read_source_artifact")
    write_tool = next(item for item in tools if item.name == "write_parsed_info")

    read_tool.invoke({"artifact_key": "01_input/raw_document.md"})
    write_tool.invoke({"content": "not-json"})
    trace_events = emitter.trace_events
    event_names = [item["event"] for item in trace_events]

    assert event_names == [
        "tool_call_started",
        "tool_call_completed",
        "tool_call_started",
        "tool_call_failed",
    ]
    assert trace_events[0]["tool_name"] == "read_source_artifact"
    assert trace_events[1]["output_summary"]
    assert "交底书正文" not in trace_events[1]["output_summary"]
    assert trace_events[-1]["tool_name"] == "write_parsed_info"
    assert trace_events[-1]["error_message"] == "invalid_json_object"
