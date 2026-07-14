from typing import Any

from app.core.config import Settings, get_settings
from app.models.schemas import NodeResult, WorkflowState
from app.orchestrator.node_base import Node
from app.orchestrator.tool_registry import ToolRegistry
from app.tools.draft_workspace import DraftWorkspaceTool


class DraftingLeaderNode(Node):
    """旧专利文书 Leader 节点兼容壳。

    Args:
        settings: 应用配置,未传入时读取全局配置。
        workspace: 保留的兼容参数,旧调用方可继续构造但不会执行隐藏流程。
        tool_registry: 保留的兼容参数,旧调用方可继续构造但不会委托子代理。

    Returns:
        提示调用方改用显式 `patent_drafting` workflow 的兼容节点。
    """

    name = "drafting_leader"

    def __init__(
        self,
        settings: Settings | None = None,
        workspace: DraftWorkspaceTool | None = None,
        tool_registry: ToolRegistry | Any | None = None,
        **_: Any,
    ) -> None:
        """初始化旧 Leader 兼容壳。"""
        super().__init__(name=self.name)
        self.settings = settings or get_settings()
        self.workspace = workspace
        self.tool_registry = tool_registry

    def run(self, state: WorkflowState) -> NodeResult:
        """拒绝执行旧固定流程,要求进入顶层显式 workflow。"""
        return NodeResult(
            status="failed",
            output={"next_node": "drafting_parse_input"},
            errors=["drafting_leader_deprecated"],
            trace_events=[{"event": "drafting_leader_deprecated", "data": {"next_node": "drafting_parse_input"}}],
        )
