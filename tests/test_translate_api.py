from fastapi.testclient import TestClient

from app.main import app


def test_translate_api_returns_text_terms_and_trace() -> None:
    """翻译 API 应返回译文、术语表和 trace。"""
    client = TestClient(app)

    response = client.post("/translate", json={"raw_input": "请翻译一种控制方法"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["translated_text"] == "A control method."
    assert payload["terms"] == {}
    assert "workflow_trace" in payload
    assert payload["disclaimer"] == "辅助初稿，不等同于专利代理师法律意见。"


def test_translate_api_rejects_missing_field() -> None:
    """翻译 API 应拒绝缺少输入字段的请求。"""
    client = TestClient(app)

    response = client.post("/translate", json={})

    assert response.status_code == 422


def test_translate_api_accepts_valid_request() -> None:
    """翻译 API 应接受有效请求并返回成功状态。"""
    client = TestClient(app)

    response = client.post("/translate", json={"raw_input": "请翻译"})

    assert response.status_code == 200
    assert response.json()["status"] == "success"
