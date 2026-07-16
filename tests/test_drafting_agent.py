import json

from app.core.config import Settings
from app.tools.draft_workspace import DraftWorkspaceTool
from app.tools.subagents.drafting_agent import LangChainDraftingAgent
from app.tracing.sinks import MemoryWorkflowTraceEmitter


OUTPUT_KEY = "04_content/claims.md"


def _fallback_content(reason: str, workspace: DraftWorkspaceTool) -> str:
    """生成测试用 fallback 正文。"""
    return f"# 权利要求书\n\n安全降级: {reason}"


def test_drafting_agent_fallback_writes_output_when_llm_unavailable(tmp_path) -> None:
    """LLM 不可用时通用 runner 应写入目标 artifact。"""
    settings = Settings(draft_workspace_dir=str(tmp_path), allow_network=False, llm_base_url=None, llm_model="", llm_api_key=None)
    workspace = DraftWorkspaceTool(settings)
    agent = LangChainDraftingAgent(
        node_name="drafting_claims_writer",
        stage="drafting.claims",
        agent_name="claims_writer_agent",
        prompt_name="CLAIMS_WRITER_PROMPT",
        system_prompt="系统 prompt",
        allowed_read_artifact_keys=["03_outline/patent_outline.md"],
        output_artifact_key=OUTPUT_KEY,
        fallback_builder=_fallback_content,
        settings=settings,
        workspace=workspace,
    )

    result = agent.run({"task": "生成权利要求"})
    stored = workspace.run({"action": "read", "artifact_key": OUTPUT_KEY})

    assert result.error is None
    assert result.evidence == [{"artifact_key": OUTPUT_KEY, "done": True}]
    assert "安全降级: llm_unavailable" in stored.evidence[0]["content"]
    assert "content" not in result.evidence[0]


def test_drafting_agent_tools_only_access_allowed_artifacts(tmp_path) -> None:
    """通用 runner 的受控工具只能读取 allowlist 并写固定输出。"""
    settings = Settings(draft_workspace_dir=str(tmp_path), allow_network=True, llm_base_url="https://example.test/v1", llm_model="fake", llm_api_key="fake")
    workspace = DraftWorkspaceTool(settings)
    workspace.run({"action": "write", "artifact_key": "03_outline/patent_outline.md", "content": "# 大纲"})
    agent = LangChainDraftingAgent(
        node_name="drafting_claims_writer",
        stage="drafting.claims",
        agent_name="claims_writer_agent",
        prompt_name="CLAIMS_WRITER_PROMPT",
        system_prompt="系统 prompt",
        allowed_read_artifact_keys=["03_outline/patent_outline.md"],
        output_artifact_key=OUTPUT_KEY,
        fallback_builder=_fallback_content,
        settings=settings,
        workspace=workspace,
    )
    tools = agent._build_tools()
    read_tool = next(item for item in tools if item.name == "read_artifact")
    write_tool = next(item for item in tools if item.name == "write_output_artifact")

    allowed = json.loads(read_tool.invoke({"artifact_key": "03_outline/patent_outline.md"}))
    blocked = json.loads(read_tool.invoke({"artifact_key": "01_input/raw_document.md"}))
    written = json.loads(write_tool.invoke({"content": "# 权利要求书"}))
    other = workspace.run({"action": "read", "artifact_key": "05_final/complete_patent.md"})

    assert allowed["artifact_key"] == "03_outline/patent_outline.md"
    assert blocked["error"] == "artifact_not_allowed"
    assert written == {"artifact_key": OUTPUT_KEY, "done": True}
    assert other.error == "artifact_not_found"


def test_drafting_agent_passes_trace_middleware_to_create_agent(monkeypatch, tmp_path) -> None:
    """真实 agent 路径应把节点上下文注入 trace middleware。"""
    settings = Settings(draft_workspace_dir=str(tmp_path), allow_network=True, llm_base_url="https://example.test/v1", llm_model="fake", llm_api_key="fake")
    workspace = DraftWorkspaceTool(settings)
    emitter = MemoryWorkflowTraceEmitter()
    agent = LangChainDraftingAgent(
        node_name="drafting_claims_writer",
        stage="drafting.claims",
        agent_name="claims_writer_agent",
        prompt_name="CLAIMS_WRITER_PROMPT",
        system_prompt="系统 prompt",
        allowed_read_artifact_keys=["03_outline/patent_outline.md"],
        output_artifact_key=OUTPUT_KEY,
        fallback_builder=_fallback_content,
        settings=settings,
        workspace=workspace,
        workflow_trace_emitter=emitter,
    )
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

    monkeypatch.setattr(agent, "_import_langchain", lambda: (fake_create_agent, lambda **kwargs: object()))

    result = agent.run({"task": "生成权利要求"})
    events = [item.event for item in emitter.events]

    assert result.error is None
    assert events == ["agent_started", "agent_completed"]
    assert captured["middleware"][0].node_name == "drafting_claims_writer"
    assert captured["middleware"][0].stage == "drafting.claims"
    assert captured["middleware"][0].agent_name == "claims_writer_agent"
