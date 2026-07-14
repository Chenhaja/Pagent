from typing import Any

from app.core.config import Settings, get_settings
from app.models.schemas import NodeResult, WorkflowState
from app.orchestrator.node_base import Node
from app.orchestrator.tool_registry import ToolRegistry, build_default_tool_registry
from app.tools.draft_workspace import DraftWorkspaceTool


DRAFTING_SOURCE_ARTIFACT_KEY = "01_input/raw_document.md"
DRAFTING_PARSED_INFO_ARTIFACT_KEY = "01_input/parsed_info.json"


class DraftingParseInputNode(Node):
    """文书生成输入解析节点。

    Args:
        settings: 应用配置,未传入时读取全局配置。
        workspace: 可注入的草稿 artifact 工作区工具。
        tool_registry: 可注入工具注册表,用于调用 input_parser 子代理。

    Returns:
        写入 source 与 parsed_info artifact 的顶层 workflow 节点。
    """

    name = "drafting_parse_input"

    def __init__(
        self,
        settings: Settings | None = None,
        workspace: DraftWorkspaceTool | None = None,
        tool_registry: ToolRegistry | Any | None = None,
    ) -> None:
        """初始化输入解析节点。"""
        super().__init__(name=self.name)
        self.settings = settings or get_settings()
        self.workspace = workspace or DraftWorkspaceTool(self.settings)
        self.tool_registry = tool_registry or build_default_tool_registry(self.settings)

    def run(self, state: WorkflowState) -> NodeResult:
        """写入原始输入 artifact 并委托 input_parser 生成 parsed_info。

        Args:
            state: 当前 workflow 状态,包含用户输入和附件解析文本。

        Returns:
            成功时返回 artifact key 短结果;失败时返回可解释错误。
        """
        trace_events: list[dict[str, Any]] = []
        source_content = self._build_source_content(state)
        written = self.workspace.run(
            {"action": "write", "artifact_key": DRAFTING_SOURCE_ARTIFACT_KEY, "content": source_content}
        )
        if written.error:
            return NodeResult.failed(errors=[written.error])
        source_chars = self._chars(written)
        state.drafting_context["input_key"] = DRAFTING_SOURCE_ARTIFACT_KEY
        trace_events.append(
            self._trace_event("drafting_source_written", artifact_key=DRAFTING_SOURCE_ARTIFACT_KEY, chars=source_chars)
        )

        parsed = self.tool_registry.run("input_parser", {"source_artifact_key": DRAFTING_SOURCE_ARTIFACT_KEY})
        if parsed.error:
            return NodeResult.failed(errors=[parsed.error])
        parsed_key = self._artifact_key_from_observation(parsed) or DRAFTING_PARSED_INFO_ARTIFACT_KEY
        if not self._artifact_exists(parsed_key):
            return NodeResult.failed(errors=["parsed_info_missing"])
        state.drafting_context["parsed_info_key"] = parsed_key
        trace_events.append(self._trace_event("drafting_input_parsed", artifact_key=parsed_key))
        return NodeResult.success(
            output={"input_key": DRAFTING_SOURCE_ARTIFACT_KEY, "parsed_info_key": parsed_key},
            trace_events=trace_events,
        )

    def _build_source_content(self, state: WorkflowState) -> str:
        """拼接用户输入和附件正文作为 source artifact 数据。"""
        parts = [state.normalized_input or state.raw_input]
        for document in state.documents:
            text = str(document.get("text") or "").strip()
            if text:
                parts.append(text)
        return "\n\n".join(part for part in parts if part.strip())

    def _artifact_exists(self, artifact_key: str) -> bool:
        """检查 artifact 是否已写入 workspace。"""
        observation = self.workspace.run({"action": "read", "artifact_key": artifact_key})
        return not observation.error and bool(observation.evidence)

    def _artifact_key_from_observation(self, observation: Any) -> str | None:
        """从工具 observation 中提取 artifact key。"""
        if not getattr(observation, "evidence", None):
            return None
        return str(observation.evidence[0].get("artifact_key") or "") or None

    def _chars(self, observation: Any) -> int:
        """从工具 observation 中提取字符数。"""
        if not getattr(observation, "evidence", None):
            return 0
        return int(observation.evidence[0].get("chars") or 0)

    def _trace_event(self, event: str, **data: Any) -> dict[str, Any]:
        """构造不包含正文内容的 trace 事件。"""
        safe = {key: value for key, value in data.items() if value is not None}
        return {"event": event, "data": safe}
