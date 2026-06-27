from fastapi.testclient import TestClient

from app.main import app


def test_revision_e2e_updates_patch_version_and_revalidates_claims() -> None:
    """单条修改 E2E 应完成 patch、版本更新和重新校验。"""
    client = TestClient(app)

    response = client.post(
        "/claims/revise",
        json={
            "claims_draft": [
                {"number": 1, "claim_type": "independent", "text": "一种控制方法。"},
                {"number": 2, "claim_type": "dependent", "text": "根据权利要求1所述的方法。", "references": [1]},
            ],
            "user_feedback": "修改权利要求1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["claim"]["text"] == "一种改进的控制方法。"
    assert payload["diff"]["target_claim_number"] == 1
    assert payload["diff"]["impact_scope"] == [1, 2]
    assert payload["risk_notes"] == ["linked_claims_may_need_review"]
    assert payload["version"] == "v2"
    assert payload["validation_report"]["passed"] is True
