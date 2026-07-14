from app.models.schemas import IntentClassification, NodeResult, WorkflowState
from app.orchestrator.node_base import Node
from app.prompts.intent_router import INTENT_ROUTER_OUTPUT_SCHEMA, INTENT_ROUTER_SYSTEM_PROMPT, build_intent_router_user_prompt
from app.tools.llm import LLMClient, LLMMessage, build_llm_client


class IntentRouterNode(Node):
    """用户意图路由节点。

    Returns:
        将输入路由到预定义 workflow 的节点。
    """

    name = "intent_router"

    def __init__(self, llm_client: LLMClient | None = None, confidence_threshold: float = 0.6) -> None:
        """初始化意图路由节点。

        Args:
            llm_client: 可选 LLM client,未传入时使用安全默认构造。
            confidence_threshold: LLM 分类可直接路由的最低置信度。

        Returns:
            无返回值。
        """
        self.llm_client = llm_client or build_llm_client()
        self.confidence_threshold = confidence_threshold

    def run(self, state: WorkflowState) -> NodeResult:
        """识别用户意图并选择下一节点。

        Args:
            state: 当前工作流状态。

        Returns:
            成功路由结果或需要用户补充输入的结果。
        """
        text = state.normalized_input or state.raw_input
        keyword_classification = self._classify_by_keyword(text)
        if keyword_classification is not None:
            return self._route_success(state, keyword_classification, source="keyword")
        return self._classify_by_llm(state, text)

    def _classify_by_keyword(self, text: str) -> IntentClassification | None:
        """用关键词快路识别高置信意图。"""
        routes = [
            ("translation", ["翻译", "译文"]),
            ("patent_drafting", ["权利要求", "撰写", "生成", "专利文书", "说明书"]),
            ("qa", ["创造性", "新颖性", "IPC", "说明", "？", "?"]),
        ]
        for intent, keywords in routes:
            if any(keyword in text for keyword in keywords):
                return IntentClassification(intent=intent, confidence=0.95)
        return None

    def _classify_by_llm(self, state: WorkflowState, text: str) -> NodeResult:
        """用 LLM fallback 识别非关键词意图。"""
        messages = [
            LLMMessage(role="system", content=INTENT_ROUTER_SYSTEM_PROMPT),
            LLMMessage(role="user", content=build_intent_router_user_prompt(text)),
        ]
        try:
            response = self.llm_client.generate(
                messages=messages,
                output_schema=INTENT_ROUTER_OUTPUT_SCHEMA,
                trace_context={"node_name": "intent_router", "task_type": "intent_classification"},
            )
        except Exception:
            return self._clarify("exception")
        if response.errors:
            return self._clarify("llm_error")
        try:
            classification = IntentClassification.model_validate(response.content)
        except Exception:
            return self._clarify("invalid_response")
        if classification.intent == "unknown" or classification.confidence < self.confidence_threshold:
            return self._clarify("low_confidence", classification)
        return self._route_success(state, classification, source="llm")

    def _route_success(self, state: WorkflowState, classification: IntentClassification, source: str) -> NodeResult:
        """写入分类结果并返回固定路由。"""
        next_nodes = {
            "patent_drafting": "drafting_parse_input",
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

    def _clarify(self, reason: str, classification: IntentClassification | None = None) -> NodeResult:
        """生成意图不明确时的澄清结果。"""
        output = {
            "message": "您希望我处理哪类专利任务？可以选择撰写专利文书、翻译专利文本，或咨询专利问答。",
            "supported_intents": ["patent_drafting", "translation", "qa"],
        }
        data = {"reason": reason}
        if classification is not None:
            data.update({"intent": classification.intent, "confidence": classification.confidence})
        return NodeResult(
            status="requires_user_input",
            output=output,
            errors=["unknown_intent"],
            requires_user_input=True,
            trace_events=[{"event": "intent_router_failed_fallback", "data": data}],
        )
