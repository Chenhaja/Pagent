import json
from collections.abc import Callable
from typing import Any

from app.orchestrator.react_loop import ReActTool, ToolObservation
from app.tools.draft_workspace import DraftWorkspaceTool
from app.tools.subagents.file_policy import FileToolPolicy


ToolCallable = Callable[..., str]


def build_file_tools(workspace: DraftWorkspaceTool, policy: FileToolPolicy) -> dict[str, ToolCallable]:
    """构造受 file policy 保护的通用文件工具。

    Args:
        workspace: 草稿 artifact 工作区工具。
        policy: 当前 agent/node 的文件访问策略。

    Returns:
        以稳定工具名索引的 LangChain tool callable 字典。
    """
    try:
        from langchain_core.tools import tool
    except ImportError:
        return {}

    @tool
    def read_file(path: str) -> str:
        """读取 policy 允许的 artifact 文件。"""
        artifact_key = policy.check("read", path)
        if artifact_key is None:
            return _json_error("file_access_denied")
        observation = workspace.run({"action": "read", "artifact_key": artifact_key})
        if observation.error or not observation.evidence:
            return _json_error(observation.error or "artifact_not_found")
        content = str(observation.evidence[0].get("content") or "")
        return json.dumps({"artifact_key": artifact_key, "content": content}, ensure_ascii=False)

    @tool
    def write_file(path: str, content: str) -> str:
        """写入 policy 允许的 artifact 文件。"""
        artifact_key = policy.check("write", path)
        if artifact_key is None:
            return _json_error("file_access_denied")
        observation = workspace.run({"action": "write", "artifact_key": artifact_key, "content": content})
        if observation.error:
            return _json_error(observation.error)
        evidence = observation.evidence[0] if observation.evidence else {}
        return json.dumps({"artifact_key": artifact_key, "done": True, "chars": int(evidence.get("chars") or 0)}, ensure_ascii=False)

    @tool
    def mkdir(path: str) -> str:
        """创建 policy 允许写入的 artifact 目录。"""
        directory = policy.check("write", path)
        if directory is None:
            return _json_error("file_access_denied")
        observation = workspace.run({"action": "mkdir", "path": directory})
        if observation.error:
            return _json_error(observation.error)
        return json.dumps({"path": directory, "done": True}, ensure_ascii=False)

    @tool
    def list_directory(path: str = "") -> str:
        """列出 policy 允许读取目录的直接子项。"""
        directory = policy.check("read", path)
        if directory is None:
            return _json_error("file_access_denied")
        observation = workspace.run({"action": "list_directory", "path": directory})
        if observation.error or not observation.evidence:
            return _json_error(observation.error or "directory_not_found")
        evidence = observation.evidence[0]
        return json.dumps(
            {"path": directory, "files": evidence.get("files", []), "directories": evidence.get("directories", [])},
            ensure_ascii=False,
        )

    return {"read_file": read_file, "write_file": write_file, "mkdir": mkdir, "list_directory": list_directory}


def build_react_tool_adapters(tools: dict[str, ReActTool]) -> dict[str, ToolCallable]:
    """将内部 ReAct 工具包装为 LangChain tool callable。

    Args:
        tools: 以稳定工具名索引的内部工具实例。

    Returns:
        可直接传给 create_agent 的 LangChain tool callable 字典。
    """
    try:
        from langchain_core.tools import tool
    except ImportError:
        return {}

    patent_tool = tools.get("patent_search")
    skill_tool = tools.get("skill_loader")
    adapters: dict[str, ToolCallable] = {}

    if patent_tool is not None:

        @tool
        def patent_search(query: str, top_k: int | None = None, country: str = "CN", status: str = "GRANT") -> str:
            """检索专利证据,返回结构化 JSON observation。"""
            observation = patent_tool.run({"query": query, "top_k": top_k, "country": country, "status": status})
            return _observation_to_json(observation)

        adapters["patent_search"] = patent_search

    if skill_tool is not None:

        @tool
        def skill_loader(skill_name: str) -> str:
            """读取白名单 skill 文档,返回结构化 JSON observation。"""
            observation = skill_tool.run({"skill_name": skill_name})
            return _observation_to_json(observation)

        adapters["skill_loader"] = skill_loader

    return adapters


def select_tools(tools: dict[str, ToolCallable], allowed_tools: list[str]) -> list[ToolCallable]:
    """按 allowed_tools 白名单选择可传给 create_agent 的工具。

    Args:
        tools: 全量工具字典。
        allowed_tools: 当前 agent 允许使用的工具名列表。

    Returns:
        按 allowed_tools 顺序排列的工具列表。
    """
    return [tools[name] for name in allowed_tools if name in tools]


def _json_error(error: Any) -> str:
    """生成不泄露路径细节的工具错误 JSON。"""
    return json.dumps({"error": str(error or "tool_error")}, ensure_ascii=False)


def _observation_to_json(observation: ToolObservation) -> str:
    """将内部 observation 转为 LangChain tool 返回 JSON。"""
    if observation.error:
        payload = {"error": observation.error, "tool_name": observation.tool_name, "external": observation.external}
    else:
        payload = {
            "tool_name": observation.tool_name,
            "evidence": observation.evidence,
            "sufficient": observation.sufficient,
            "external": observation.external,
            "top_score": observation.top_score,
        }
    return json.dumps(payload, ensure_ascii=False)
