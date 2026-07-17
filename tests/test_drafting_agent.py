import json

from app.core.config import Settings
from app.tools.draft_workspace import DraftWorkspaceTool
from app.tools.subagents.agent_runner import LangChainAgentRunner
from app.tools.subagents.file_policy import FileToolPolicy
from app.tracing.sinks import MemoryWorkflowTraceEmitter


OUTPUT_KEY = "04_content/claims.md"


def _fallback_content(reason: str, workspace: DraftWorkspaceTool) -> str:
    """生成测试用 fallback 正文。"""
    return f"# 权利要求书\n\n安全降级: {reason}"


def _runner(settings: Settings, workspace: DraftWorkspaceTool, emitter: MemoryWorkflowTraceEmitter | None = None) -> LangChainAgentRunner:
    """构造测试用 drafting 通用 runner。"""
    return LangChainAgentRunner(
        node_name="drafting_claims_writer",
        stage="drafting.claims",
        agent_name="claims_writer_agent",
        prompt_name="CLAIMS_WRITER_PROMPT",
        system_prompt="系统 prompt",
        allowed_tools=["read_file", "write_file"],
        file_policy=FileToolPolicy(readRoots=["03_outline/patent_outline.md"], writeRoots=[OUTPUT_KEY]),
        output_artifact_keys=[OUTPUT_KEY],
        fallback_builder=_fallback_content,
        settings=settings,
        workspace=workspace,
        workflow_trace_emitter=emitter,
    )


def test_drafting_agent_fallback_writes_output_when_llm_unavailable(tmp_path) -> None:
    """LLM 不可用时通用 runner 应写入目标 artifact。"""
    settings = Settings(draft_workspace_dir=str(tmp_path), allow_network=False, llm_base_url=None, llm_model="", llm_api_key=None)
    workspace = DraftWorkspaceTool(settings)
    runner = _runner(settings, workspace)

    result = runner.run({"task": "生成权利要求"})
    stored = workspace.run({"action": "read", "artifact_key": OUTPUT_KEY})

    assert result.error is None
    assert result.evidence == [{"artifact_key": OUTPUT_KEY, "done": True}]
    assert "安全降级: llm_unavailable" in stored.evidence[0]["content"]
    assert "content" not in result.evidence[0]


def test_drafting_agent_tools_only_access_allowed_artifacts(tmp_path) -> None:
    """通用 runner 的受控工具只能读取和写入 policy 允许的 artifact。"""
    settings = Settings(draft_workspace_dir=str(tmp_path), allow_network=True, llm_base_url="https://example.test/v1", llm_model="fake", llm_api_key="fake")
    workspace = DraftWorkspaceTool(settings)
    workspace.run({"action": "write", "artifact_key": "03_outline/patent_outline.md", "content": "# 大纲"})
    runner = _runner(settings, workspace)
    tools = runner._allowed_langchain_tools()
    read_tool = next(item for item in tools if item.name == "read_file")
    write_tool = next(item for item in tools if item.name == "write_file")

    allowed = json.loads(read_tool.invoke({"path": "03_outline/patent_outline.md"}))
    blocked = json.loads(read_tool.invoke({"path": "01_input/raw_document.md"}))
    written = json.loads(write_tool.invoke({"path": OUTPUT_KEY, "content": "# 权利要求书"}))
    other = workspace.run({"action": "read", "artifact_key": "05_final/complete_patent.md"})

    assert allowed["artifact_key"] == "03_outline/patent_outline.md"
    assert blocked["error"] == "file_access_denied"
    assert written["artifact_key"] == OUTPUT_KEY
    assert written["done"] is True
    assert other.error == "artifact_not_found"


def test_drafting_agent_passes_trace_middleware_to_create_agent(monkeypatch, tmp_path) -> None:
    """真实 agent 路径应把节点上下文注入 trace middleware。"""
    settings = Settings(draft_workspace_dir=str(tmp_path), allow_network=True, llm_base_url="https://example.test/v1", llm_model="fake", llm_api_key="fake")
    workspace = DraftWorkspaceTool(settings)
    emitter = MemoryWorkflowTraceEmitter()
    runner = _runner(settings, workspace, emitter)
    captured = {}

    class FakeAgent:
        """测试用 LangChain agent。"""

        def invoke(self, payload: dict) -> dict:
            """模拟 middleware 生命周期并写入目标 artifact。"""
            middleware = captured["middleware"][0]
            middleware.before_agent(payload, object())
            workspace.run({"action": "write", "artifact_key": OUTPUT_KEY, "content": "# 权利要求书"})
            middleware.after_agent({"messages": []}, object())
            return {}

    def fake_create_agent(**kwargs):
        """捕获 create_agent 参数。"""
        captured.update(kwargs)
        return FakeAgent()

    monkeypatch.setattr(runner, "_import_langchain", lambda: (fake_create_agent, lambda **kwargs: object()))

    result = runner.run({"task": "生成权利要求"})
    events = [item.event for item in emitter.events]

    assert result.error is None
    assert events == ["agent_started", "agent_completed"]
    assert captured["middleware"][0].node_name == "drafting_claims_writer"
    assert captured["middleware"][0].stage == "drafting.claims"
    assert captured["middleware"][0].agent_name == "claims_writer_agent"
    assert [tool.name for tool in captured["tools"]] == ["read_file", "write_file"]
