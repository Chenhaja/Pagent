from typing import Any

from app.orchestrator.react_loop import ToolObservation


_ALLOWED_STATUSES = {"pending", "in_progress", "done"}
_DEFAULT_OWNER = "leader"


def render_todo_context(owner: str, todos: list[dict[str, str]]) -> str:
    """将指定 owner 的 todo 列表渲染为可注入上下文的 Markdown。

    Args:
        owner: todo 所属角色。
        todos: 当前完整 todo 列表。

    Returns:
        Markdown 格式的 todo 上下文。
    """
    lines = [f"# 当前 Todo（{owner}）"]
    if not todos:
        lines.append("- 无")
        return "\n".join(lines)
    for item in todos:
        lines.append(f"- [{item['status']}] {item['content']}")
    return "\n".join(lines)


class TodoTool:
    """维护 Leader 或子代理私有 todo 列表的工具。"""

    def __init__(self) -> None:
        """初始化内存 todo 存储。

        Returns:
            无返回值。
        """
        self._todos_by_owner: dict[str, list[dict[str, str]]] = {}

    def run(self, tool_input: dict[str, Any]) -> ToolObservation:
        """执行 todo 列表覆盖或上下文渲染。

        Args:
            tool_input: 包含 owner、todos 和可选 action 的输入。

        Returns:
            todo 更新结果或渲染后的上下文。
        """
        owner = str(tool_input.get("owner") or _DEFAULT_OWNER).strip() or _DEFAULT_OWNER
        action = str(tool_input.get("action") or "replace").strip()
        if action == "render":
            todos = self._todos_by_owner.get(owner, [])
            return ToolObservation(
                tool_name="todo",
                evidence=[{"owner": owner, "context": render_todo_context(owner, todos), "todos": list(todos)}],
                sufficient=True,
            )
        if action != "replace":
            return ToolObservation(tool_name="todo", error="invalid_action")
        todos_input = tool_input.get("todos")
        if not isinstance(todos_input, list):
            return ToolObservation(tool_name="todo", error="invalid_input")
        normalized = []
        for item in todos_input:
            if not isinstance(item, dict):
                return ToolObservation(tool_name="todo", error="invalid_input")
            content = str(item.get("content") or "").strip()
            status = str(item.get("status") or "").strip()
            if not content:
                return ToolObservation(tool_name="todo", error="invalid_input")
            if status not in _ALLOWED_STATUSES:
                return ToolObservation(tool_name="todo", error="invalid_todo_status")
            normalized.append({"content": content, "status": status})
        self._todos_by_owner[owner] = normalized
        return ToolObservation(
            tool_name="todo",
            evidence=[{"owner": owner, "todos": list(normalized), "context": render_todo_context(owner, normalized)}],
            sufficient=True,
        )
