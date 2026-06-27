from app.models.schemas import WorkflowState
from app.nodes.intent_router import IntentRouterNode


def test_intent_router_routes_claim_generation() -> None:
    """意图路由 node 应识别权利要求生成 workflow。"""
    state = WorkflowState(raw_input="", normalized_input="请根据技术方案生成权利要求")
    node = IntentRouterNode()

    result = node.run(state)

    assert result.status == "success"
    assert state.intent == "claim_generation"
    assert result.next_node == "completeness_gate"


def test_intent_router_routes_translation() -> None:
    """意图路由 node 应识别翻译 workflow。"""
    state = WorkflowState(raw_input="", normalized_input="请翻译这段专利文本")
    node = IntentRouterNode()

    result = node.run(state)

    assert result.status == "success"
    assert state.intent == "translation"
    assert result.next_node == "translate"


def test_intent_router_routes_question_answering() -> None:
    """意图路由 node 应识别问答 workflow。"""
    state = WorkflowState(raw_input="", normalized_input="这个权利要求有什么风险？")
    node = IntentRouterNode()

    result = node.run(state)

    assert result.status == "success"
    assert state.intent == "qa"
    assert result.next_node == "qa"


def test_intent_router_requires_user_input_for_unknown_intent() -> None:
    """意图路由 node 遇到未知意图时应请求用户补充。"""
    state = WorkflowState(raw_input="", normalized_input="你好")
    node = IntentRouterNode()

    result = node.run(state)

    assert result.status == "requires_user_input"
    assert result.errors == ["unknown_intent"]
