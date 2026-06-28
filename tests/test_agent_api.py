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
    """统一 Agent API 应支持 QA,默认无真实 LLM 时返回结构化失败。"""
    client = TestClient(app)

    response = client.post("/agent", json={"raw_input": "请说明创造性的判断思路？"})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["status"] == "failed"
    assert detail["errors"] == ["qa_failed"]
    assert detail["disclaimer"] == DISCLAIMER


def test_agent_api_returns_common_error_for_unknown_intent() -> None:
    """统一 Agent API 遇到未知意图时应返回统一错误结构。"""
    client = TestClient(app)

    response = client.post("/agent", json={"raw_input": "你好"})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail == {
        "status": "requires_user_input",
        "errors": ["unknown_intent"],
        "message": "您希望我处理哪类专利任务？可以选择撰写权利要求、修改权利要求、翻译专利文本，或咨询专利问答。",
        "disclaimer": DISCLAIMER,
    }
