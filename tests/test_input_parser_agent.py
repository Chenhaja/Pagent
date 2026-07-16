import json

from app.core.config import Settings
from app.models.schemas import WorkflowState
from app.nodes.drafting_research import DRAFTING_PARSED_INFO_ARTIFACT_KEY, DRAFTING_SOURCE_ARTIFACT_KEY, DraftingParseInputNode
from app.tools.draft_workspace import DraftWorkspaceTool
from app.tools.subagents.agent_runner import LangChainAgentRunner
from app.tools.subagents.file_policy import FileToolPolicy
from app.tracing.sinks import MemoryWorkflowTraceEmitter


def _fallback_content(reason: str, workspace: DraftWorkspaceTool) -> str:
    """生成测试用 input parser fallback JSON。"""
    source = workspace.run({"action": "read", "artifact_key": DRAFTING_SOURCE_ARTIFACT_KEY})
    source_content = "" if source.error or not source.evidence else str(source.evidence[0].get("content") or "")
    return json.dumps({"technical_topic": source_content[:30] or "技术方案", "source": source_content[:80], "uncertain": True}, ensure_ascii=False)


def _runner(settings: Settings, workspace: DraftWorkspaceTool, emitter: MemoryWorkflowTraceEmitter | None = None) -> LangChainAgentRunner:
    """构造测试用通用 input parser runner。"""
    return LangChainAgentRunner(
        node_name="drafting_parse_input",
        stage="drafting.parse_input",
        agent_name="input_parser_agent",
        prompt_name="INPUT_PARSER_PROMPT",
        system_prompt="系统 prompt",
        allowed_tools=["read_file", "write_file"],
        file_policy=FileToolPolicy(readRoots=[DRAFTING_SOURCE_ARTIFACT_KEY], writeRoots=[DRAFTING_PARSED_INFO_ARTIFACT_KEY]),
        output_artifact_key=DRAFTING_PARSED_INFO_ARTIFACT_KEY,
        fallback_builder=_fallback_content,
        settings=settings,
        workspace=workspace,
        workflow_trace_emitter=emitter,
    )


def test_input_parser_runner_fallback_when_llm_config_incomplete(tmp_path) -> None:
    """LLM 配置不完整时通用 runner 应写入合法 fallback JSON。"""
    settings = Settings(draft_workspace_dir=str(tmp_path), allow_network=False, llm_base_url=None, llm_model="", llm_api_key=None)
    workspace = DraftWorkspaceTool(settings)
    workspace.run({"action": "write", "artifact_key": DRAFTING_SOURCE_ARTIFACT_KEY, "content": "夹爪控制交底书"})
    runner = _runner(settings, workspace)

    result = runner.run({"source_artifact_key": DRAFTING_SOURCE_ARTIFACT_KEY})
    stored = workspace.run({"action": "read", "artifact_key": DRAFTING_PARSED_INFO_ARTIFACT_KEY})
    payload = json.loads(stored.evidence[0]["content"])

    assert result.error is None
    assert result.evidence == [{"artifact_key": DRAFTING_PARSED_INFO_ARTIFACT_KEY, "done": True}]
    assert payload["uncertain"] is True
    assert payload["source"] == "夹爪控制交底书"


def test_drafting_parse_input_rejects_unexpected_source_artifact(tmp_path) -> None:
    """parse node 只接受固定 source artifact key。"""
    settings = Settings(draft_workspace_dir=str(tmp_path), allow_network=False)
    workspace = DraftWorkspaceTool(settings)
    node = DraftingParseInputNode(settings=settings, workspace=workspace)

    result = node.input_parser_runner.run({"source_artifact_key": "../raw_document.md"})

    assert result.error is None
    stored = workspace.run({"action": "read", "artifact_key": DRAFTING_PARSED_INFO_ARTIFACT_KEY})
    assert json.loads(stored.evidence[0]["content"])["uncertain"] is True


def test_input_parser_policy_write_only_targets_parsed_info(tmp_path) -> None:
    """通用 file policy 只允许写 parsed_info artifact。"""
    settings = Settings(draft_workspace_dir=str(tmp_path), allow_network=True, llm_base_url="https://example.test/v1", llm_model="fake", llm_api_key="fake")
    workspace = DraftWorkspaceTool(settings)
    runner = _runner(settings, workspace)
    write_tool = next(item for item in runner._allowed_langchain_tools() if item.name == "write_file")

    allowed = json.loads(write_tool.invoke({"path": DRAFTING_PARSED_INFO_ARTIFACT_KEY, "content": '{"technical_topic":"夹爪控制"}'}))
    blocked = json.loads(write_tool.invoke({"path": "05_final/complete_patent.md", "content": "x"}))
    other = workspace.run({"action": "read", "artifact_key": "05_final/complete_patent.md"})

    assert allowed["artifact_key"] == DRAFTING_PARSED_INFO_ARTIFACT_KEY
    assert blocked == {"error": "file_access_denied"}
    assert other.error == "artifact_not_found"


def test_parse_node_falls_back_after_agent_writes_invalid_json(monkeypatch, tmp_path) -> None:
    """真实 agent 产出非法 JSON 时 parse node 应返回 parsed_info_missing。"""
    settings = Settings(draft_workspace_dir=str(tmp_path), allow_network=True, llm_base_url="https://example.test/v1", llm_model="fake", llm_api_key="fake")
    workspace = DraftWorkspaceTool(settings)
    node = DraftingParseInputNode(settings=settings, workspace=workspace)

    class FakeAgent:
        """测试用 LangChain agent。"""

        def invoke(self, payload: dict) -> dict:
            """写入非法 JSON 后返回。"""
            workspace.run({"action": "write", "artifact_key": DRAFTING_PARSED_INFO_ARTIFACT_KEY, "content": "not-json"})
            return {}

    monkeypatch.setattr(node.input_parser_runner, "_import_langchain", lambda: ((lambda **kwargs: FakeAgent()), lambda **kwargs: object()))

    result = node.run(WorkflowState(raw_input="交底书正文"))

    assert result.status == "failed"
    assert result.errors == ["parsed_info_missing"]


def test_input_parser_runner_passes_trace_middleware_to_create_agent(monkeypatch, tmp_path) -> None:
    """真实 agent 路径应将 trace middleware 交给 create_agent。"""
    settings = Settings(draft_workspace_dir=str(tmp_path), allow_network=True, llm_base_url="https://example.test/v1", llm_model="fake", llm_api_key="fake")
    workspace = DraftWorkspaceTool(settings)
    emitter = MemoryWorkflowTraceEmitter()
    workspace.run({"action": "write", "artifact_key": DRAFTING_SOURCE_ARTIFACT_KEY, "content": "交底书正文"})
    runner = _runner(settings, workspace, emitter)
    captured = {}

    class FakeAgent:
        """测试用成功 LangChain agent。"""

        def invoke(self, payload: dict) -> dict:
            """模拟官方 middleware 发送事件后写入合法 JSON。"""
            middleware = captured["middleware"][0]
            middleware.before_agent(payload, object())
            workspace.run({"action": "write", "artifact_key": DRAFTING_PARSED_INFO_ARTIFACT_KEY, "content": '{"technical_topic":"夹爪控制"}'})
            middleware.after_agent({"messages": []}, object())
            return {}

    def fake_create_agent(**kwargs):
        """捕获 create_agent 参数。"""
        captured.update(kwargs)
        return FakeAgent()

    monkeypatch.setattr(runner, "_import_langchain", lambda: (fake_create_agent, lambda **kwargs: object()))

    result = runner.run({"source_artifact_key": DRAFTING_SOURCE_ARTIFACT_KEY})
    events = [item.event for item in emitter.events]

    assert result.error is None
    assert events == ["agent_started", "agent_completed"]
    assert captured["middleware"][0].emitter is emitter
    assert captured["middleware"][0].node_name == "drafting_parse_input"
    assert captured["middleware"][0].agent_name == "input_parser_agent"


def test_input_parser_tools_do_not_emit_wrapper_trace(tmp_path) -> None:
    """受控工具函数不应手写 trace 事件。"""
    settings = Settings(draft_workspace_dir=str(tmp_path), allow_network=True, llm_base_url="https://example.test/v1", llm_model="fake", llm_api_key="fake")
    workspace = DraftWorkspaceTool(settings)
    emitter = MemoryWorkflowTraceEmitter()
    workspace.run({"action": "write", "artifact_key": DRAFTING_SOURCE_ARTIFACT_KEY, "content": "交底书正文"})
    runner = _runner(settings, workspace, emitter)
    tools = runner._allowed_langchain_tools()
    read_tool = next(item for item in tools if item.name == "read_file")
    write_tool = next(item for item in tools if item.name == "write_file")

    read_tool.invoke({"path": DRAFTING_SOURCE_ARTIFACT_KEY})
    write_tool.invoke({"path": DRAFTING_PARSED_INFO_ARTIFACT_KEY, "content": "not-json"})

    assert emitter.trace_events == []
