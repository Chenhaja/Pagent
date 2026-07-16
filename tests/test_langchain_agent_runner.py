import json

from app.core.config import Settings
from app.orchestrator.react_loop import ToolObservation
from app.tools.draft_workspace import DraftWorkspaceTool
from app.tools.subagents.agent_runner import LangChainAgentRunner
from app.tools.subagents.file_policy import FileToolPolicy
from app.tools.subagents.file_tools import build_file_tools, select_tools
from app.tracing.sinks import MemoryWorkflowTraceEmitter


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


def test_agent_runner_exposes_skill_loader_adapter(monkeypatch, tmp_path) -> None:
    """runner 应能按白名单暴露 skill_loader LangChain tool。"""

    class FakeSkillLoaderTool:
        """测试用 skill_loader。"""

        def __init__(self, settings: Settings) -> None:
            """接收 runner 传入的配置。"""

        def run(self, tool_input: dict) -> ToolObservation:
            """返回固定 skill evidence。"""
            return ToolObservation(tool_name="skill_loader", evidence=[{"skill_name": tool_input["skill_name"], "content": "规则"}], sufficient=True)

    monkeypatch.setattr("app.tools.subagents.agent_runner.SkillLoaderTool", FakeSkillLoaderTool)
    runner = _runner_for_allowed_tools(tmp_path, ["skill_loader"])

    tools = runner._allowed_langchain_tools()
    result = json.loads(tools[0].invoke({"skill_name": "patent_drafting"}))

    assert [tool.name for tool in tools] == ["skill_loader"]
    assert result == {
        "tool_name": "skill_loader",
        "evidence": [{"skill_name": "patent_drafting", "content": "规则"}],
        "sufficient": True,
        "external": False,
        "top_score": 0.0,
    }


def test_agent_runner_exposes_patent_search_adapter(monkeypatch, tmp_path) -> None:
    """runner 应能按白名单暴露 patent_search LangChain tool。"""

    class FakePatentSearchTool:
        """测试用 patent_search。"""

        def __init__(self, settings: Settings) -> None:
            """接收 runner 传入的配置。"""

        def run(self, tool_input: dict) -> ToolObservation:
            """返回固定专利 evidence。"""
            return ToolObservation(
                tool_name="patent_search",
                evidence=[{"title": tool_input["query"], "publication_number": "CN1"}],
                sufficient=True,
                external=True,
                top_score=0.8,
            )

    monkeypatch.setattr("app.tools.subagents.agent_runner.PatentSearchTool", FakePatentSearchTool)
    runner = _runner_for_allowed_tools(tmp_path, ["patent_search"])

    tools = runner._allowed_langchain_tools()
    result = json.loads(tools[0].invoke({"query": "折叠屏", "top_k": 1}))

    assert [tool.name for tool in tools] == ["patent_search"]
    assert result == {
        "tool_name": "patent_search",
        "evidence": [{"title": "折叠屏", "publication_number": "CN1"}],
        "sufficient": True,
        "external": True,
        "top_score": 0.8,
    }


def test_agent_runner_adapter_returns_structured_error(monkeypatch, tmp_path) -> None:
    """内部工具错误应转为结构化 JSON。"""

    class FakePatentSearchTool:
        """测试用失败 patent_search。"""

        def __init__(self, settings: Settings) -> None:
            """接收 runner 传入的配置。"""

        def run(self, tool_input: dict) -> ToolObservation:
            """返回固定错误 observation。"""
            return ToolObservation(tool_name="patent_search", error="network_disabled", external=True)

    monkeypatch.setattr("app.tools.subagents.agent_runner.PatentSearchTool", FakePatentSearchTool)
    runner = _runner_for_allowed_tools(tmp_path, ["patent_search"])

    result = json.loads(runner._allowed_langchain_tools()[0].invoke({"query": "折叠屏"}))

    assert result == {"error": "network_disabled", "tool_name": "patent_search", "external": True}


def _runner_for_allowed_tools(tmp_path, allowed_tools: list[str]) -> LangChainAgentRunner:
    """构造只用于检查工具白名单的 runner。"""
    settings = Settings(draft_workspace_dir=str(tmp_path), allow_network=True, llm_base_url="https://example.test/v1", llm_model="fake", llm_api_key="fake")
    return LangChainAgentRunner(
        node_name="node",
        stage="stage",
        agent_name="agent",
        prompt_name="PROMPT",
        system_prompt="系统 prompt",
        allowed_tools=allowed_tools,
        file_policy=FileToolPolicy(readRoots=["input/"], writeRoots=["output/"]),
        output_artifact_key="output/result.md",
        fallback_builder=_fallback_content,
        settings=settings,
        workspace=DraftWorkspaceTool(settings),
    )


def _fallback_content(reason: str, workspace: DraftWorkspaceTool) -> str:
    """生成测试用 fallback 正文。"""
    return f"fallback:{reason}"


def test_agent_runner_fallback_writes_output_when_llm_unavailable(tmp_path) -> None:
    """LLM 不可用时通用 runner 应写入目标 artifact。"""
    settings = Settings(draft_workspace_dir=str(tmp_path), allow_network=False, llm_base_url=None, llm_model="", llm_api_key=None)
    workspace = DraftWorkspaceTool(settings)
    runner = LangChainAgentRunner(
        node_name="node",
        stage="stage",
        agent_name="agent",
        prompt_name="PROMPT",
        system_prompt="系统 prompt",
        allowed_tools=["read_file", "write_file"],
        file_policy=FileToolPolicy(readRoots=["input/"], writeRoots=["output/"]),
        output_artifact_key="output/result.md",
        fallback_builder=_fallback_content,
        settings=settings,
        workspace=workspace,
    )

    result = runner.run({"task": "测试"})
    stored = workspace.run({"action": "read", "artifact_key": "output/result.md"})

    assert result.error is None
    assert result.evidence == [{"artifact_key": "output/result.md", "done": True}]
    assert stored.evidence[0]["content"] == "fallback:llm_unavailable"


def test_agent_runner_passes_allowed_tools_and_middleware_to_create_agent(monkeypatch, tmp_path) -> None:
    """真实 agent 路径应传入白名单工具和 trace middleware。"""
    settings = Settings(draft_workspace_dir=str(tmp_path), allow_network=True, llm_base_url="https://example.test/v1", llm_model="fake", llm_api_key="fake")
    workspace = DraftWorkspaceTool(settings)
    emitter = MemoryWorkflowTraceEmitter()
    runner = LangChainAgentRunner(
        node_name="node",
        stage="stage",
        agent_name="agent",
        prompt_name="PROMPT",
        system_prompt="系统 prompt",
        allowed_tools=["write_file"],
        file_policy=FileToolPolicy(writeRoots=["output/"]),
        output_artifact_key="output/result.md",
        fallback_builder=_fallback_content,
        settings=settings,
        workspace=workspace,
        workflow_trace_emitter=emitter,
    )
    captured = {}

    class FakeAgent:
        """测试用 LangChain agent。"""

        def invoke(self, payload: dict) -> dict:
            """模拟 agent 通过工具写入目标 artifact。"""
            captured["payload"] = payload
            tool = captured["tools"][0]
            tool.invoke({"path": "output/result.md", "content": "ok"})
            return {}

    def fake_create_agent(**kwargs):
        """捕获 create_agent 参数。"""
        captured.update(kwargs)
        return FakeAgent()

    monkeypatch.setattr(runner, "_import_langchain", lambda: (fake_create_agent, lambda **kwargs: object()))

    result = runner.run({"task": "写入结果"})

    assert result.error is None
    assert [tool.name for tool in captured["tools"]] == ["write_file"]
    assert captured["middleware"][0].node_name == "node"
    assert captured["middleware"][0].stage == "stage"
    assert captured["middleware"][0].agent_name == "agent"
    assert "系统 prompt" == captured["system_prompt"]


def test_agent_runner_policy_blocks_wrapped_tool_before_workspace(monkeypatch, tmp_path) -> None:
    """runner 传入 create_agent 的工具应在 workspace 前执行 policy。"""
    settings = Settings(draft_workspace_dir=str(tmp_path), allow_network=True, llm_base_url="https://example.test/v1", llm_model="fake", llm_api_key="fake")
    workspace = DraftWorkspaceTool(settings)
    runner = LangChainAgentRunner(
        node_name="node",
        stage="stage",
        agent_name="agent",
        prompt_name="PROMPT",
        system_prompt="系统 prompt",
        allowed_tools=["write_file"],
        file_policy=FileToolPolicy(writeRoots=["output/"]),
        output_artifact_key="output/result.md",
        fallback_builder=_fallback_content,
        settings=settings,
        workspace=workspace,
    )

    def fail_run(tool_input: dict):
        """越权工具调用不能触达 workspace。"""
        raise AssertionError("workspace should not be touched")

    monkeypatch.setattr(workspace, "run", fail_run)
    tool = runner._allowed_langchain_tools()[0]

    result = json.loads(tool.invoke({"path": "secrets/result.md", "content": "x"}))

    assert result == {"error": "file_access_denied"}
