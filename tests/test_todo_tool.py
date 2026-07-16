from app.orchestrator.tool_registry import build_default_tool_registry
from app.prompts.todo_prompt import TODO_PROMPT, sys_prompt, tool_prompt
from app.tools.todo import TodoTool, render_todo_context


def test_todo_tool_replaces_full_list_for_owner() -> None:
    """todo 工具应按 owner 覆盖完整 todo 列表。"""
    tool = TodoTool()

    first = tool.run({"owner": "leader", "todos": [{"content": "解析输入", "status": "pending"}]})
    second = tool.run({"owner": "leader", "todos": [{"content": "生成摘要", "status": "done"}]})

    assert first.error is None
    assert second.error is None
    assert second.evidence[0]["owner"] == "leader"
    assert second.evidence[0]["todos"] == [{"content": "生成摘要", "status": "done"}]


def test_todo_tool_rejects_invalid_status() -> None:
    """todo 工具应拒绝非法状态。"""
    tool = TodoTool()

    observation = tool.run({"owner": "leader", "todos": [{"content": "解析输入", "status": "blocked"}]})

    assert observation.error == "invalid_todo_status"
    assert observation.evidence == []


def test_todo_tool_isolates_owners() -> None:
    """todo 工具应按 owner 隔离 Leader 与子代理状态。"""
    tool = TodoTool()

    tool.run({"owner": "leader", "todos": [{"content": "统筹", "status": "in_progress"}]})
    tool.run({"owner": "abstract_writer", "todos": [{"content": "写摘要", "status": "pending"}]})

    leader = tool.run({"owner": "leader", "action": "render"})
    subagent = tool.run({"owner": "abstract_writer", "action": "render"})

    assert "统筹" in leader.evidence[0]["context"]
    assert "写摘要" not in leader.evidence[0]["context"]
    assert "写摘要" in subagent.evidence[0]["context"]
    assert "统筹" not in subagent.evidence[0]["context"]


def test_render_todo_context_formats_statuses() -> None:
    """todo 上下文渲染应输出可注入上下文的状态列表。"""
    context = render_todo_context(
        "leader",
        [
            {"content": "解析输入", "status": "done"},
            {"content": "撰写摘要", "status": "in_progress"},
            {"content": "合并终稿", "status": "pending"},
        ],
    )

    assert "# 当前 Todo（leader）" in context
    assert "- [done] 解析输入" in context
    assert "- [in_progress] 撰写摘要" in context
    assert "- [pending] 合并终稿" in context


def test_default_tool_registry_registers_todo_not_write_todos() -> None:
    """默认 ToolRegistry 应注册 todo 且不注册 write_todos。"""
    registry = build_default_tool_registry()

    assert registry.get("todo") is not None
    assert registry.get("write_todos") is None
    spec = registry.tool_specs()["todo"]
    assert spec.input_schema["properties"]["todos"]["type"] == "array"


def test_todo_prompt_uses_todo_tool_name() -> None:
    """todo prompt 应使用 todo 工具名而不是旧命名。"""
    for prompt in (TODO_PROMPT, sys_prompt, tool_prompt):
        assert "todo" in prompt
        assert "write_todos" not in prompt
        assert "todo_middleware" not in prompt


def test_todo_prompt_uses_official_status_values() -> None:
    """todo prompt 应统一使用 pending/in_progress/done 状态。"""
    combined_prompt = "\n".join([TODO_PROMPT, sys_prompt, tool_prompt])

    assert "pending" in combined_prompt
    assert "in_progress" in combined_prompt
    assert "done" in combined_prompt
    assert "已完成：任务已成功完成" not in combined_prompt
