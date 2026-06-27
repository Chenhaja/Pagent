from fastapi.testclient import TestClient

from app.main import app

DISCLAIMER = "辅助初稿，不等同于专利代理师法律意见。"


def test_claim_generation_error_response_uses_common_shape() -> None:
    """权利要求生成错误响应应使用统一结构。"""
    client = TestClient(app)

    response = client.post("/claims/generate", json={"raw_input": "   "})

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "status": "requires_user_input",
        "errors": ["empty_raw_input"],
        "message": "请补充技术方案内容。",
        "disclaimer": DISCLAIMER,
    }


def test_translate_error_response_uses_common_shape() -> None:
    """翻译错误响应应使用统一结构。"""
    client = TestClient(app)

    response = client.post("/translate", json={"raw_input": "   "})

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "status": "requires_user_input",
        "errors": ["empty_raw_input"],
        "message": "请补充待翻译文本。",
        "disclaimer": DISCLAIMER,
    }


def test_revision_error_response_uses_common_shape() -> None:
    """修改错误响应应使用统一结构。"""
    client = TestClient(app)

    response = client.post("/claims/revise", json={"claims_draft": [], "user_feedback": "修改权利要求2"})

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "status": "failed",
        "errors": ["target_claim_not_found:2"],
        "message": "未找到要修改的权利要求。",
        "disclaimer": DISCLAIMER,
    }
