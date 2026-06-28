from app.models.schemas import IntentClassification, NodeResult, WorkflowState
from app.orchestrator.node_base import Node


class IntentRouterNode(Node):
    """用户意图路由节点。

    Returns:
        将输入路由到预定义 workflow 的节点。
    """

    name = "intent_router"

    def __init__(self, llm_client=None) -> None:
        """初始化意图路由节点。

        Args:
            llm_client: 可选 LLM client,当前关键词快路优先使用。

        Returns:
            无返回值。
        """
        self.llm_client = llm_client

    def run(self, state: WorkflowState) -> NodeResult:
        """识别用户意图并选择下一节点。

        Args:
            state: 当前工作流状态。

        Returns:
            成功路由结果或需要用户补充输入的结果。
        """
        text = state.normalized_input or state.raw_input
        classification = self._classify_by_keyword(text)
        if classification is None:
            return NodeResult.need_user_input(errors=["unknown_intent"])
        return self._route_success(state, classification, source="keyword")

    def _classify_by_keyword(self, text: str) -> IntentClassification | None:
        """用关键词快路识别高置信意图。"""
        routes = [
            ("translation", ["翻译", "译文"]),
            ("claim_revision", ["修改", "修订", "权利要求有什么问题", "权利要求有啥问题", "权利要求问题"]),
            ("claim_generation", ["权利要求", "撰写", "生成"]),
            ("qa", ["创造性", "新颖性", "IPC", "说明", "？", "?"]),
        ]
        for intent, keywords in routes:
            if any(keyword in text for keyword in keywords):
                return IntentClassification(intent=intent, confidence=0.95)
        return None

    def _route_success(self, state: WorkflowState, classification: IntentClassification, source: str) -> NodeResult:
        """写入分类结果并返回固定路由。"""
        next_nodes = {
            "claim_generation": "completeness_gate",
            "claim_revision": "claim_revise",
            "translation": "translate",
            "qa": "qa",
        }
        state.intent = classification.intent
        classification_data = classification.model_dump()
        classification_data["source"] = source
        state.dialog_context["intent_classification"] = classification_data
        trace_data = {
            "intent": classification.intent,
            "source": source,
            "confidence": classification.confidence,
        }
        return NodeResult.success(
            output={"intent": classification.intent, "confidence": classification.confidence},
            next_node=next_nodes.get(classification.intent),
            trace_events=[{"event": "intent_router_completed", "data": trace_data}],
        )
