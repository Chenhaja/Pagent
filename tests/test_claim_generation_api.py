from fastapi.testclient import TestClient

from app.main import app


def test_claim_generation_api_returns_draft_report_and_next_steps() -> None:
    """权利要求生成 API 应返回初稿、校验报告和下一步建议。"""
    client = TestClient(app)

    response = client.post("/claims/generate", json={"raw_input": "请根据技术方案生成权利要求"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["claims_draft"][0]["text"] == "一种控制方法。"
    assert payload["validation_report"]["passed"] is True
    assert payload["next_steps"] == ["请审阅权利要求初稿并指出需要修改的权利要求编号。"]
    assert payload["disclaimer"] == "辅助初稿，不等同于专利代理师法律意见。"


def test_claim_generation_api_rejects_missing_field() -> None:
    """权利要求生成 API 应拒绝缺少输入字段的请求。"""
    client = TestClient(app)

    response = client.post("/claims/generate", json={})

    assert response.status_code == 422


def test_claim_generation_api_returns_structured_validation_failure() -> None:
    """权利要求生成 API 应返回结构化失败提示。"""
    client = TestClient(app)

    response = client.post("/claims/generate", json={"raw_input": "   "})

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "status": "requires_user_input",
        "errors": ["empty_raw_input"],
        "message": "请补充技术方案内容。辅助初稿，不等同于专利代理师法律意见。",
    }
