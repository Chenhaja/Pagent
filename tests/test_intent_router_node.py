from app.models.schemas import IntentClassification, WorkflowState
from app.nodes.intent_router import IntentRouterNode


class RaisingLLMClient:
    """测试用 LLM,被调用即失败。"""

    def generate(self, **kwargs):
        """阻止关键词快路误调用 LLM。"""
        raise AssertionError("keyword fast path should not call llm")


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


def test_intent_router_requires_user_input_for_unknown_intent() -> None:
    """意图路由 node 遇到未知意图时应请求用户补充。"""
    state = WorkflowState(raw_input="", normalized_input="你好")
    node = IntentRouterNode()

    result = node.run(state)

    assert result.status == "requires_user_input"
    assert result.errors == ["unknown_intent"]
