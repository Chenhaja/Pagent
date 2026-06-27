from fastapi.testclient import TestClient

from app.main import app


def test_revision_api_returns_revised_claim_diff_risks_and_version() -> None:
    """单条权利要求修改 API 应返回修改结果、差异、风险提示和版本号。"""
    client = TestClient(app)

    response = client.post(
        "/claims/revise",
        json={
            "claims_draft": [{"number": 1, "claim_type": "independent", "text": "一种控制方法。"}],
            "user_feedback": "修改权利要求1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["claim"]["text"] == "一种改进的控制方法。"
    assert payload["diff"]["before_text"] == "一种控制方法。"
    assert payload["diff"]["after_text"] == "一种改进的控制方法。"
    assert payload["risk_notes"] == []
    assert payload["version"] == "v2"
    assert payload["disclaimer"] == "辅助初稿，不等同于专利代理师法律意见。"


def test_revision_api_returns_structured_error_when_target_missing() -> None:
    """单条权利要求修改 API 应返回目标不存在错误。"""
    client = TestClient(app)

    response = client.post(
        "/claims/revise",
        json={"claims_draft": [], "user_feedback": "修改权利要求2"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "status": "failed",
        "errors": ["target_claim_not_found:2"],
        "message": "未找到要修改的权利要求。",
        "disclaimer": "辅助初稿，不等同于专利代理师法律意见。",
    }


def test_revision_api_returns_structured_error_when_reference_invalid() -> None:
    """单条权利要求修改 API 应返回引用关系错误。"""
    client = TestClient(app)

    response = client.post(
        "/claims/revise",
        json={
            "claims_draft": [
                {"number": 1, "claim_type": "independent", "text": "一种控制方法。"},
                {"number": 2, "claim_type": "dependent", "text": "根据权利要求3所述的方法。", "references": [3]},
            ],
            "user_feedback": "修改权利要求1",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "status": "failed",
        "errors": ["claim_2_references_missing_claim_3"],
        "message": "权利要求引用关系需要修正。",
        "disclaimer": "辅助初稿，不等同于专利代理师法律意见。",
    }
