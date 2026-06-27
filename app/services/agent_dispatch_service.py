from typing import Any

from app.models.schemas import WorkflowState
from app.nodes.intent_router import IntentRouterNode
from app.nodes.normalize_input import NormalizeInputNode
from app.nodes.qa import QANode
from app.orchestrator.engine import Orchestrator
from app.orchestrator.workflow_defs import WorkflowDef, WorkflowRegistry
from app.services.revision_service import RevisionService
from app.services.translate_service import TranslateService
from app.services.workflow_service import WorkflowService


class AgentDispatchService:
    """统一 Agent 入口 dispatch 服务。

    Returns:
        先执行 normalize 和 intent_router,再按预定义 workflow 分派到具体业务服务的入口服务。
    """

    def __init__(self) -> None:
        self.normalize_node = NormalizeInputNode()
        self.intent_router_node = IntentRouterNode()
        self.workflow_registry = WorkflowRegistry()

    def dispatch(self, raw_input: str, claims_draft: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """根据用户输入识别意图并分派到预定义 workflow。

        Args:
            raw_input: 用户原始输入。
            claims_draft: 修改权利要求时传入的当前权利要求草稿。

        Returns:
            具体 workflow 的结构化结果,或需要用户补充输入的错误结果。
        """
        state = WorkflowState(raw_input=raw_input, claims_draft=claims_draft or [])
        normalize_result = self.normalize_node.run(state)
        if normalize_result.status != "success":
            return {"status": normalize_result.status, "errors": normalize_result.errors, "message": "请补充要办理的专利任务类型。"}
        for trace_event in normalize_result.trace_events:
            state.add_trace_event(event=str(trace_event.get("event", "node_event")), data=trace_event.get("data", {}))

        route_result = self.intent_router_node.run(state)
        for trace_event in route_result.trace_events:
            state.add_trace_event(event=str(trace_event.get("event", "node_event")), data=trace_event.get("data", {}))
        if route_result.status != "success":
            return {"status": route_result.status, "errors": route_result.errors, "message": "请补充要办理的专利任务类型。"}

        workflow_def = self.workflow_registry.get_workflow_def(state.intent or "")
        remaining_nodes = self._remaining_nodes_after(workflow_def, route_result.next_node)
        if state.intent == "claim_generation":
            result = WorkflowService().generate_claims(
                state.normalized_input or state.raw_input,
                state=state,
                workflow_def=remaining_nodes,
            )
            return {"intent": state.intent, "workflow": "claim_generation", **result}
        if state.intent == "translation":
            result = TranslateService().translate(
                state.normalized_input or state.raw_input,
                state=state,
                workflow_def=remaining_nodes,
            )
            return {"intent": state.intent, "workflow": "translation", **result}
        if state.intent == "claim_revision":
            state.user_feedback = state.normalized_input or state.raw_input
            result = RevisionService().revise_claim(
                state.claims_draft,
                state.user_feedback,
                state=state,
                workflow_def=remaining_nodes,
            )
            return {"intent": state.intent, "workflow": "claim_revision", **result}
        if state.intent == "qa":
            result = self._run_qa(state, remaining_nodes)
            return {"intent": state.intent, "workflow": "qa", **result}

        return {"status": "requires_user_input", "errors": ["unknown_intent"], "message": "请补充要办理的专利任务类型。"}

    def _run_qa(self, state: WorkflowState, workflow_def: list[str]) -> dict[str, Any]:
        """执行 QA workflow 并转换为服务响应。

        Args:
            state: 已完成 normalize 和 intent_router 的 workflow 状态。
            workflow_def: 从 QA 节点开始的节点序列。

        Returns:
            QA 成功输出或结构化失败结果。
        """
        result = Orchestrator(nodes={"qa": QANode()}).run(state, workflow_def)
        if result.status != "success":
            return {"status": result.status, "errors": result.errors, "message": "问答服务暂时不可用,请稍后重试。"}
        return {"status": "success", **result.output, "trace": state.trace}

    def _remaining_nodes_after(self, workflow_def: WorkflowDef, next_node: str | None) -> list[str]:
        """根据 intent_router 的下一节点裁剪待执行节点序列。

        Args:
            workflow_def: 已识别 intent 对应的 workflow 定义。
            next_node: intent_router 返回的业务起始节点。

        Returns:
            从业务起始节点开始的节点序列;未命中时返回完整节点序列。
        """
        if next_node in workflow_def.nodes:
            return workflow_def.nodes[workflow_def.nodes.index(next_node) :]
        return list(workflow_def.nodes)
