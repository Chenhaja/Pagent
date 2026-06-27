from fastapi.testclient import TestClient

from app.main import app

DISCLAIMER = "辅助初稿，不等同于专利代理师法律意见。"


def test_agent_api_routes_claim_generation() -> None:
    """统一 Agent API 应支持权利要求生成。"""
    client = TestClient(app)

    response = client.post("/agent", json={"raw_input": "请根据技术方案生成权利要求"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "claim_generation"
    assert payload["workflow"] == "claim_generation"
    assert payload["claims_draft"][0]["text"] == "一种控制方法。"
    assert payload["disclaimer"] == DISCLAIMER


def test_agent_api_routes_translation() -> None:
    """统一 Agent API 应支持翻译。"""
    client = TestClient(app)

    response = client.post("/agent", json={"raw_input": "请翻译一种控制方法"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "translation"
    assert payload["workflow"] == "translation"
    assert payload["translated_text"] == "A control method."
    assert payload["disclaimer"] == DISCLAIMER


def test_agent_api_routes_claim_revision() -> None:
    """统一 Agent API 应支持权利要求修改。"""
    client = TestClient(app)

    response = client.post(
        "/agent",
        json={
            "raw_input": "修改权利要求1",
            "claims_draft": [{"number": 1, "claim_type": "independent", "text": "一种控制方法。"}],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "claim_revision"
    assert payload["workflow"] == "claim_revision"
    assert payload["claim"]["text"] == "一种改进的控制方法。"
    assert payload["diff"]["target_claim_number"] == 1
    assert payload["disclaimer"] == DISCLAIMER


def test_agent_api_routes_qa() -> None:
    """统一 Agent API 应支持 QA。"""
    client = TestClient(app)

    response = client.post("/agent", json={"raw_input": "这个权利要求有什么风险？"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "qa"
    assert payload["workflow"] == "qa"
    assert payload["qa_result"]["answer"] == "该问题需要结合权利要求文本和技术方案初步判断。"
    assert payload["disclaimer"] == DISCLAIMER


def test_agent_api_returns_common_error_for_unknown_intent() -> None:
    """统一 Agent API 遇到未知意图时应返回统一错误结构。"""
    client = TestClient(app)

    response = client.post("/agent", json={"raw_input": "你好"})

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "status": "requires_user_input",
        "errors": ["unknown_intent"],
        "message": "请补充要办理的专利任务类型。",
        "disclaimer": DISCLAIMER,
    }
