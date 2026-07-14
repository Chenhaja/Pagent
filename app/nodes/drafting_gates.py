from typing import Any

from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.models.schemas import DraftingGateDecision, NodeResult, WorkflowState
from app.orchestrator.node_base import Node
from app.orchestrator.tool_registry import ToolRegistry, build_default_tool_registry
from app.tools.draft_workspace import DraftWorkspaceTool


class DraftingLeaderGateBase(Node):
    """文书生成 Leader gate 基类。

    Args:
        name: 当前 gate 节点名称。
        allowed_targets: 当前 gate 允许跳转的节点集合。
        settings: 应用配置,未传入时读取全局配置。
        workspace: 可注入的草稿 artifact 工作区工具。
        tool_registry: 可注入工具注册表,用于调用 gate 子代理。

    Returns:
        可校验结构化 gate 决策并转换为 NodeResult 的节点基类。
    """

    def __init__(
        self,
        name: str,
        allowed_targets: set[str],
        settings: Settings | None = None,
        workspace: DraftWorkspaceTool | None = None,
        tool_registry: ToolRegistry | Any | None = None,
    ) -> None:
        """初始化 Leader gate 基类。"""
        super().__init__(name=name)
        self.settings = settings or get_settings()
        self.workspace = workspace or DraftWorkspaceTool(self.settings)
        self.tool_registry = tool_registry or build_default_tool_registry(self.settings)
        self.allowed_targets = allowed_targets

    def _parse_decision(self, observation: Any) -> DraftingGateDecision | NodeResult:
        """从 observation 中解析并校验 gate 决策。"""
        if getattr(observation, "error", None):
            return NodeResult.failed(errors=[str(observation.error)])
        evidence = list(getattr(observation, "evidence", []) or [])
        payload = evidence[0].get("decision") if evidence else None
        if not isinstance(payload, dict):
            return NodeResult.failed(errors=["invalid_gate_decision"])
        try:
            decision = DraftingGateDecision.model_validate(payload)
        except ValidationError:
            return NodeResult.failed(errors=["invalid_gate_decision"])
        if decision.target_node not in self.allowed_targets:
            return NodeResult.failed(errors=[f"illegal_gate_target:{decision.target_node}"])
        return decision

    def _result_from_decision(self, state: WorkflowState, context_key: str, decision: DraftingGateDecision) -> NodeResult:
        """把结构化 gate 决策转换为 NodeResult。"""
        payload = decision.model_dump()
        state.drafting_context[context_key] = payload
        trace_event = {"event": f"{context_key}_decided", "data": payload}
        if decision.decision == "escalate":
            return NodeResult.need_user_input(
                output={"reason": decision.reason, "required_changes": decision.required_changes},
                errors=["drafting_gate_escalated"],
            )
        return NodeResult.success(output={context_key: payload}, next_node=decision.target_node, trace_events=[trace_event])


class DraftingLeaderGatePriorArtNode(DraftingLeaderGateBase):
    """现有技术阶段 Leader gate 节点。

    Args:
        settings: 应用配置,未传入时读取全局配置。
        workspace: 可注入的草稿 artifact 工作区工具。
        tool_registry: 可注入工具注册表,用于调用 prior art gate 子代理。

    Returns:
        根据 prior art analysis 质量决定继续、重试、返修或人工介入的 gate 节点。
    """

    name = "drafting_leader_gate_prior_art"

    def __init__(
        self,
        settings: Settings | None = None,
        workspace: DraftWorkspaceTool | None = None,
        tool_registry: ToolRegistry | Any | None = None,
    ) -> None:
        """初始化现有技术 Leader gate 节点。"""
        super().__init__(
            name=self.name,
            allowed_targets={
                "drafting_patent_search",
                "drafting_prior_art_analysis",
                "drafting_leader_gate_prior_art",
                "drafting_drawing_analysis",
            },
            settings=settings,
            workspace=workspace,
            tool_registry=tool_registry,
        )

    def run(self, state: WorkflowState) -> NodeResult:
        """读取 prior art analysis key 并输出结构化 gate 决策。

        Args:
            state: 当前 workflow 状态,需包含 prior art analysis artifact key。

        Returns:
            成功时返回合法 next_node;人工介入时返回 requires_user_input。
        """
        prior_art_key = str(state.drafting_context.get("prior_art_analysis_key") or "")
        if not prior_art_key or not self._artifact_exists(prior_art_key):
            return NodeResult.failed(errors=["prior_art_analysis_missing"])
        observation = self.tool_registry.run(self.name, {"prior_art_analysis_key": prior_art_key})
        decision = self._parse_decision(observation)
        if isinstance(decision, NodeResult):
            return decision
        return self._result_from_decision(state, "leader_gate_prior_art", decision)

    def _artifact_exists(self, artifact_key: str) -> bool:
        """检查 prior art analysis artifact 是否存在。"""
        observation = self.workspace.run({"action": "read", "artifact_key": artifact_key})
        return not observation.error and bool(getattr(observation, "evidence", None))
