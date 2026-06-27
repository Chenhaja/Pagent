from app.services.agent_dispatch_service import AgentDispatchService


def test_agent_dispatch_routes_claim_generation_workflow() -> None:
    """统一 Agent 入口应路由到权利要求生成 workflow。"""
    service = AgentDispatchService()

    result = service.dispatch("请根据技术方案生成权利要求")

    assert result["status"] == "success"
    assert result["intent"] == "claim_generation"
    assert result["workflow"] == "claim_generation"
    assert result["claims_draft"][0]["text"] == "一种控制方法。"
    assert [event["event"] for event in result["trace"]] == [
        "normalize_input_completed",
        "intent_router_completed",
        "completeness_gate_completed",
        "feature_extract_completed",
        "claim_plan_completed",
        "claim_generate_completed",
        "claim_check_completed",
    ]
    assert [event["event"] for event in result["trace"]].count("normalize_input_completed") == 1


def test_agent_dispatch_routes_translation_workflow() -> None:
    """统一 Agent 入口应路由到翻译 workflow。"""
    service = AgentDispatchService()

    result = service.dispatch("请翻译一种控制方法")

    assert result["status"] == "success"
    assert result["intent"] == "translation"
    assert result["workflow"] == "translation"
    assert result["translated_text"] == "A control method."


def test_agent_dispatch_routes_claim_revision_workflow() -> None:
    """统一 Agent 入口应路由到权利要求修改 workflow。"""
    service = AgentDispatchService()

    result = service.dispatch(
        "修改权利要求1",
        claims_draft=[{"number": 1, "claim_type": "independent", "text": "一种控制方法。"}],
    )

    assert result["status"] == "success"
    assert result["intent"] == "claim_revision"
    assert result["workflow"] == "claim_revision"
    assert result["claim"]["text"] == "一种改进的控制方法。"


def test_agent_dispatch_routes_qa_workflow() -> None:
    """统一 Agent 入口应路由到 QA workflow。"""
    service = AgentDispatchService()

    result = service.dispatch("这个权利要求有什么风险？")

    assert result["status"] == "success"
    assert result["intent"] == "qa"
    assert result["workflow"] == "qa"
    assert result["qa_result"]["answer"] == "该问题需要结合权利要求文本和技术方案初步判断。"



def test_agent_dispatch_returns_user_input_request_for_unknown_intent() -> None:
    """统一 Agent 入口遇到未知意图时应返回补充输入提示。"""
    service = AgentDispatchService()

    result = service.dispatch("你好")

    assert result == {
        "status": "requires_user_input",
        "errors": ["unknown_intent"],
        "message": "请补充要办理的专利任务类型。",
    }
