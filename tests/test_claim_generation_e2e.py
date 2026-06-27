from fastapi.testclient import TestClient

from app.main import app


def test_claim_generation_e2e_returns_draft_report_and_trace() -> None:
    """权利要求生成 E2E 应返回初稿、校验报告和可审计 trace。"""
    client = TestClient(app)

    response = client.post("/claims/generate", json={"raw_input": "我有一个采集传感器数据并控制设备的方法，请生成权利要求"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["claims_draft"] == [{
        "number": 1,
        "claim_type": "independent",
        "text": "一种控制方法。",
        "references": [],
        "terms": [],
        "source_trace": [],
    }]
    assert payload["validation_report"]["passed"] is True
    assert [event["event"] for event in payload["trace"]] == [
        "normalize_input_completed",
        "feature_extract_completed",
        "claim_plan_completed",
        "claim_generate_completed",
        "claim_check_completed",
    ]
