from typing import Any

from app.models.schemas import WorkflowState
from app.nodes.intent_router import IntentRouterNode
from app.nodes.normalize_input import NormalizeInputNode
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

        if state.intent == "claim_generation":
            result = WorkflowService().generate_claims(state.normalized_input or state.raw_input)
            return {"intent": state.intent, "workflow": "claim_generation", **result, "trace": state.trace + result.get("trace", [])}
        if state.intent == "translation":
            result = TranslateService().translate(state.normalized_input or state.raw_input)
            return {"intent": state.intent, "workflow": "translation", **result}
        if state.intent == "claim_revision":
            result = RevisionService().revise_claim(state.claims_draft, state.normalized_input or state.raw_input)
            return {"intent": state.intent, "workflow": "claim_revision", **result}

        return {"status": "requires_user_input", "errors": ["unknown_intent"], "message": "请补充要办理的专利任务类型。"}
