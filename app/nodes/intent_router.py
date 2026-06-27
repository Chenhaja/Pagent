from app.models.schemas import NodeResult, WorkflowState
from app.orchestrator.node_base import Node


class IntentRouterNode(Node):
    """用户意图路由节点。

    Returns:
        将输入路由到预定义 workflow 的节点。
    """

    name = "intent_router"

    def run(self, state: WorkflowState) -> NodeResult:
        """识别用户意图并选择下一节点。

        Args:
            state: 当前工作流状态。

        Returns:
            成功路由结果或需要用户补充输入的结果。
        """
        text = state.normalized_input or state.raw_input
        routes = [
            ("translation", "translate", ["翻译", "译文"]),
            ("claim_revision", "claim_revise", ["修改", "修订"]),
            ("qa", "report_write", ["风险", "问题", "说明", "？", "?"]),
            ("claim_generation", "feature_extract", ["权利要求", "撰写", "生成"]),
        ]
        for intent, next_node, keywords in routes:
            if any(keyword in text for keyword in keywords):
                state.intent = intent
                return NodeResult.success(
                    output={"intent": intent},
                    next_node=next_node,
                    trace_events=[{"event": "intent_router_completed", "data": {"intent": intent}}],
                )
        return NodeResult.need_user_input(errors=["unknown_intent"])
