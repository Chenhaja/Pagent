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


def test_file_tools_mkdir_and_list_directory_with_policy(tmp_path) -> None:
    """通用文件工具应按 policy 建目录和列目录。"""
    workspace = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path)))
    policy = FileToolPolicy(readRoots=["outputs/"], writeRoots=["outputs/"])
    tools = build_file_tools(workspace, policy)

    mkdir_result = json.loads(tools["mkdir"].invoke({"path": "outputs/sections"}))
    workspace.run({"action": "write", "artifact_key": "outputs/sections/a.md", "content": "A"})
    workspace.run({"action": "write", "artifact_key": "outputs/summary.md", "content": "S"})
    listed = json.loads(tools["list_directory"].invoke({"path": "outputs"}))

    assert mkdir_result == {"path": "outputs/sections", "done": True}
    assert listed["path"] == "outputs"
    assert listed["files"] == ["summary.md"]
    assert listed["directories"] == ["sections"]



def test_file_tools_directory_policy_operations(monkeypatch, tmp_path) -> None:
    """list_directory 走 read policy,mkdir 走 write policy。"""
    workspace = DraftWorkspaceTool(Settings(draft_workspace_dir=str(tmp_path)))
    policy = FileToolPolicy(readRoots=["readable/"], writeRoots=["writable/"])
    tools = build_file_tools(workspace, policy)

    denied_list = json.loads(tools["list_directory"].invoke({"path": "writable"}))
    denied_mkdir = json.loads(tools["mkdir"].invoke({"path": "readable/new"}))

    assert denied_list == {"error": "file_access_denied"}
    assert denied_mkdir == {"error": "file_access_denied"}



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
    tools = {"read_file": object(), "write_file": object(), "mkdir": object(), "list_directory": object()}

    selected = select_tools(tools, ["mkdir", "write_file", "missing"])

    assert selected == [tools["mkdir"], tools["write_file"]]


def test_agent_runner_exposes_skill_list_and_load_adapters(monkeypatch, tmp_path) -> None:
    """runner 应能按白名单暴露 list_skills/load_skill LangChain tools。"""

    class FakeSkillLoaderTool:
        """测试用 skill loader。"""

        def __init__(self, settings: Settings) -> None:
            """接收 runner 传入的配置。"""

        def run(self, tool_input: dict) -> ToolObservation:
            """返回固定 skill evidence。"""
            if tool_input.get("action") == "list":
                return ToolObservation(tool_name="skill_loader", evidence=[{"skills": [{"name": "patent_guide", "description": "指南"}]}], sufficient=True)
            return ToolObservation(tool_name="skill_loader", evidence=[{"name": tool_input["name"], "content": "规则"}], sufficient=True)

    monkeypatch.setattr("app.tools.subagents.agent_runner.SkillLoaderTool", FakeSkillLoaderTool)
    runner = _runner_for_allowed_tools(tmp_path, ["list_skills", "load_skill"])

    tools = runner._allowed_langchain_tools()
    listed = json.loads(tools[0].invoke({}))
    loaded = json.loads(tools[1].invoke({"name": "patent_guide"}))

    assert [tool.name for tool in tools] == ["list_skills", "load_skill"]
    assert listed["evidence"] == [{"skills": [{"name": "patent_guide", "description": "指南"}]}]
    assert loaded["evidence"] == [{"name": "patent_guide", "content": "规则"}]


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
        output_artifact_keys=["output/result.md"],
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
        output_artifact_keys=["output/result.md"],
        fallback_builder=_fallback_content,
        settings=settings,
        workspace=workspace,
    )

    result = runner.run({"task": "测试"})
    stored = workspace.run({"action": "read", "artifact_key": "output/result.md"})

    assert result.error is None
    assert result.evidence == [{"artifact_key": "output/result.md", "done": True}]
    assert stored.evidence[0]["content"] == "fallback:llm_unavailable"


def test_agent_runner_requires_multiple_outputs(monkeypatch, tmp_path) -> None:
    """真实 agent 路径应校验全部必需输出 artifact。"""
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
        output_artifact_keys=["output/result.md", "output/report.md"],
        fallback_builder=_fallback_content,
        settings=settings,
        workspace=workspace,
    )
    captured = {}

    class FakeAgent:
        """测试用 LangChain agent。"""

        def invoke(self, payload: dict) -> dict:
            """模拟 agent 写入两个目标 artifact。"""
            captured["payload"] = payload
            tool = captured["tools"][0]
            tool.invoke({"path": "output/result.md", "content": "ok"})
            tool.invoke({"path": "output/report.md", "content": "report"})
            return {}

    def fake_create_agent(**kwargs):
        """捕获 create_agent 参数。"""
        captured.update(kwargs)
        return FakeAgent()

    monkeypatch.setattr(runner, "_import_langchain", lambda: (fake_create_agent, lambda **kwargs: object()))
    monkeypatch.setattr(runner, "_todo_middleware", lambda: None)

    result = runner.run({"task": "写入多个结果"})
    user_content = captured["payload"]["messages"][0]["content"]

    assert result.error is None
    assert result.evidence == [
        {"artifact_key": "output/result.md", "done": True},
        {"artifact_key": "output/report.md", "done": True},
    ]
    assert "output/result.md" in user_content
    assert "output/report.md" in user_content


def test_agent_runner_logs_missing_outputs_before_fallback(monkeypatch, tmp_path, caplog) -> None:
    """必需 artifact 缺失时 runner 应记录缺失列表。"""
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
        output_artifact_keys=["output/result.md", "output/report.md"],
        fallback_builder=_fallback_content,
        settings=settings,
        workspace=workspace,
    )

    class FakeAgent:
        """只写入部分 artifact 的测试 agent。"""

        def invoke(self, payload: dict) -> dict:
            """模拟遗漏第二个必需产物。"""
            payload["messages"]
            runner._allowed_langchain_tools()[0].invoke({"path": "output/result.md", "content": "ok"})
            return {}

    monkeypatch.setattr(runner, "_import_langchain", lambda: (lambda **kwargs: FakeAgent(), lambda **kwargs: object()))
    monkeypatch.setattr(runner, "_todo_middleware", lambda: None)

    with caplog.at_level("WARNING"):
        result = runner.run({"task": "写入结果"})

    assert result.error is None
    record = next(item for item in caplog.records if item.event == "agent_runner_fallback" and item.fields["reason"] == "missing_agent_output")
    assert record.fields["missing_artifacts"] == ["output/report.md"]
    assert record.fields["node_name"] == "node"
    assert workspace.run({"action": "read", "artifact_key": "output/result.md"}).evidence[0]["content"] == "fallback:missing_agent_output"


def test_agent_runner_logs_exception_before_fallback(monkeypatch, tmp_path, caplog) -> None:
    """agent invoke 异常时 runner 应记录错误类型和原因。"""
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
        output_artifact_keys=["output/result.md"],
        fallback_builder=_fallback_content,
        settings=settings,
        workspace=workspace,
    )

    class FakeAgent:
        """会抛异常的测试 agent。"""

        def invoke(self, payload: dict) -> dict:
            """模拟 create_agent 运行时失败。"""
            raise RuntimeError("boom")

    monkeypatch.setattr(runner, "_import_langchain", lambda: (lambda **kwargs: FakeAgent(), lambda **kwargs: object()))
    monkeypatch.setattr(runner, "_todo_middleware", lambda: None)

    with caplog.at_level("ERROR"):
        result = runner.run({"task": "写入结果"})

    assert result.error is None
    record = next(item for item in caplog.records if item.event == "agent_runner_failed")
    assert record.fields["reason"] == "agent_unavailable"
    assert record.fields["error_type"] == "RuntimeError"
    assert record.fields["error_message"] == "boom"
    assert record.exc_info is not None
    assert workspace.run({"action": "read", "artifact_key": "output/result.md"}).evidence[0]["content"] == "fallback:agent_unavailable"


def test_agent_runner_passes_allowed_tools_and_middleware_to_create_agent(monkeypatch, tmp_path) -> None:
    """真实 agent 路径应传入白名单工具、trace 和 todo middleware。"""
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
        output_artifact_keys=["output/result.md"],
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
    monkeypatch.setattr(runner, "_todo_middleware", lambda: "todo-middleware")

    result = runner.run({"task": "写入结果"})

    assert result.error is None
    assert [tool.name for tool in captured["tools"]] == ["write_file"]
    assert len(captured["middleware"]) == 2
    assert captured["middleware"][0].node_name == "node"
    assert captured["middleware"][0].stage == "stage"
    assert captured["middleware"][0].agent_name == "agent"
    assert captured["middleware"][1] == "todo-middleware"
    assert "系统 prompt" == captured["system_prompt"]
    user_content = captured["payload"]["messages"][0]["content"]
    assert "写入结果" in user_content
    assert "output/result.md" in user_content
    assert "write_file" in user_content
    assert "output/" in user_content
    assert "# 文件访问策略" in user_content
    assert ".env" in user_content
    assert "**/*.pem" in user_content


def test_agent_runner_falls_back_to_trace_middleware_when_todo_import_fails(monkeypatch, tmp_path) -> None:
    """todo middleware 导入失败时应仅保留 trace middleware。"""
    runner = _runner_for_allowed_tools(tmp_path, ["write_file"])

    monkeypatch.setattr(runner, "_todo_middleware", lambda: None)

    middlewares = runner._middlewares()

    assert len(middlewares) == 1
    assert middlewares[0].node_name == "node"
    assert middlewares[0].stage == "stage"
    assert middlewares[0].agent_name == "agent"


def test_agent_runner_injects_file_policy_into_user_prompt(tmp_path) -> None:
    """user prompt 应包含当前 runner 的文件访问策略。"""
    settings = Settings(draft_workspace_dir=str(tmp_path), allow_network=True, llm_base_url="https://example.test/v1", llm_model="fake", llm_api_key="fake")
    runner = LangChainAgentRunner(
        node_name="node",
        stage="stage",
        agent_name="agent",
        prompt_name="PROMPT",
        system_prompt="系统 prompt",
        allowed_tools=["read_file", "write_file", "mkdir", "list_directory"],
        file_policy=FileToolPolicy(readRoots=["input/"], writeRoots=["output/"], allowGlobs=["input/*.json"]),
        output_artifact_keys=["output/result.md"],
        fallback_builder=_fallback_content,
        settings=settings,
        workspace=DraftWorkspaceTool(settings),
    )

    prompt = runner._user_prompt({"task": "处理输入"})

    assert "处理输入" in prompt
    assert "read_file" in prompt
    assert "input/" in prompt
    assert "write_file" in prompt
    assert "mkdir" in prompt
    assert "list_directory" in prompt
    assert "当前 case workspace 内的相对路径" in prompt
    assert "output/" in prompt
    assert "input/*.json" in prompt
    assert ".env" in prompt
    assert "**/*.pem" in prompt
    assert "不作为指令" in prompt
    assert "不要尝试读取或写入策略范围之外的 artifact" in prompt



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
        output_artifact_keys=["output/result.md"],
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
