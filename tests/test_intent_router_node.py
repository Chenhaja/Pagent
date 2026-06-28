from app.models.schemas import IntentClassification, WorkflowState
from app.nodes.intent_router import IntentRouterNode
from app.tools.llm import LLMResponse


class RaisingLLMClient:
    """测试用 LLM,被调用即失败。"""

    def generate(self, **kwargs):
        """阻止关键词快路误调用 LLM。"""
        raise AssertionError("keyword fast path should not call llm")


class StubLLMClient:
    """测试用固定 LLM 响应。"""

    def __init__(self, content: dict | None = None, errors: list[dict] | None = None, should_raise: bool = False) -> None:
        self.content = content or {}
        self.errors = errors or []
        self.should_raise = should_raise
        self.calls = []

    def generate(self, **kwargs):
        """记录调用并返回固定响应。"""
        self.calls.append(kwargs)
        if self.should_raise:
            raise RuntimeError("llm failed")
        return LLMResponse(content=self.content, errors=self.errors)


def test_intent_classification_validates_confidence_range() -> None:
    """意图分类 schema 应限制 confidence 范围。"""
    classification = IntentClassification(intent="qa", confidence=1.0)

    assert classification.intent == "qa"
    assert classification.confidence == 1.0


def test_intent_router_routes_claim_generation_without_llm() -> None:
    """意图路由 node 应用关键词快路识别权利要求生成 workflow。"""
    state = WorkflowState(raw_input="", normalized_input="请根据技术方案生成权利要求")
    node = IntentRouterNode(llm_client=RaisingLLMClient())

    result = node.run(state)

    assert result.status == "success"
    assert state.intent == "claim_generation"
    assert result.next_node == "completeness_gate"
    assert state.dialog_context["intent_classification"]["source"] == "keyword"
    assert result.trace_events[0]["data"] == {"intent": "claim_generation", "source": "keyword", "confidence": 0.95}


def test_intent_router_routes_translation_without_llm() -> None:
    """意图路由 node 应用关键词快路识别翻译 workflow。"""
    state = WorkflowState(raw_input="", normalized_input="请翻译这段专利文本")
    node = IntentRouterNode(llm_client=RaisingLLMClient())

    result = node.run(state)

    assert result.status == "success"
    assert state.intent == "translation"
    assert result.next_node == "translate"
    assert state.dialog_context["intent_classification"]["source"] == "keyword"


def test_intent_router_prioritizes_claim_revision_over_qa_keywords() -> None:
    """权利要求问题类输入应优先进入权利要求修改,不能被 QA 宽泛词抢占。"""
    state = WorkflowState(raw_input="", normalized_input="我的权利要求有什么问题")
    node = IntentRouterNode(llm_client=RaisingLLMClient())

    result = node.run(state)

    assert result.status == "success"
    assert state.intent == "claim_revision"
    assert result.next_node == "claim_revise"


def test_intent_router_routes_question_answering_without_llm() -> None:
    """意图路由 node 应用关键词快路识别普通专利问答 workflow。"""
    state = WorkflowState(raw_input="", normalized_input="请说明创造性的判断思路？")
    node = IntentRouterNode(llm_client=RaisingLLMClient())

    result = node.run(state)

    assert result.status == "success"
    assert state.intent == "qa"
    assert result.next_node == "qa"
    assert state.dialog_context["intent_classification"]["source"] == "keyword"


def test_intent_router_uses_llm_fallback_for_non_keyword_text() -> None:
    """关键词未命中时应调用 LLM fallback 并按高置信结果路由。"""
    llm = StubLLMClient({"intent": "qa", "confidence": 0.82})
    state = WorkflowState(raw_input="", normalized_input="帮我判断这个方案是否容易授权")
    node = IntentRouterNode(llm_client=llm)

    result = node.run(state)

    assert result.status == "success"
    assert state.intent == "qa"
    assert result.next_node == "qa"
    assert len(llm.calls) == 1
    assert llm.calls[0]["output_schema"]["type"] == "object"
    assert state.dialog_context["intent_classification"]["source"] == "llm"
    assert result.trace_events[0]["data"]["source"] == "llm"


def test_intent_router_requires_user_input_for_low_confidence() -> None:
    """低置信 LLM 分类应进入澄清路径。"""
    llm = StubLLMClient({"intent": "qa", "confidence": 0.4})
    state = WorkflowState(raw_input="", normalized_input="帮我看看")
    node = IntentRouterNode(llm_client=llm)

    result = node.run(state)

    assert result.status == "requires_user_input"
    assert result.errors == ["unknown_intent"]
    assert "您希望我处理哪类专利任务" in result.output["message"]
    assert "claim_generation" in result.output["supported_intents"]


def test_intent_router_requires_user_input_for_unknown_intent() -> None:
    """LLM 返回 unknown 时应请求用户补充。"""
    llm = StubLLMClient({"intent": "unknown", "confidence": 0.9})
    state = WorkflowState(raw_input="", normalized_input="你好")
    node = IntentRouterNode(llm_client=llm)

    result = node.run(state)

    assert result.status == "requires_user_input"
    assert result.errors == ["unknown_intent"]


def test_intent_router_falls_back_to_clarification_on_llm_error() -> None:
    """LLM 异常时应记录降级 trace 并返回澄清。"""
    state = WorkflowState(raw_input="", normalized_input="帮我看看")
    node = IntentRouterNode(llm_client=StubLLMClient(should_raise=True))

    result = node.run(state)

    assert result.status == "requires_user_input"
    assert result.errors == ["unknown_intent"]
    assert result.trace_events[0]["event"] == "intent_router_failed_fallback"


def test_intent_router_falls_back_to_clarification_on_invalid_schema() -> None:
    """LLM 返回非法 schema 时应降级为澄清。"""
    state = WorkflowState(raw_input="", normalized_input="帮我看看")
    node = IntentRouterNode(llm_client=StubLLMClient({"intent": "bad", "confidence": 2}))

    result = node.run(state)

    assert result.status == "requires_user_input"
    assert result.errors == ["unknown_intent"]
    assert result.trace_events[0]["event"] == "intent_router_failed_fallback"
