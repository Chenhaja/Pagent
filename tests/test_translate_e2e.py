from fastapi.testclient import TestClient

from app.main import app


def test_translate_e2e_uses_fake_external_adapter() -> None:
    """翻译 E2E 应通过 fake external adapter 返回译文、术语和 trace。"""
    client = TestClient(app)

    response = client.post("/translate", json={"raw_input": "请翻译一种控制方法"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["translated_text"] == "A control method."
    assert payload["terms"] == {}
    assert payload["trace"] == [{"event": "fake_translation_completed"}]
    assert [event["event"] for event in payload["workflow_trace"]] == [
        "normalize_input_completed",
        "translate_completed",
    ]
