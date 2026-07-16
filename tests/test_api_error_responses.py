from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.services.case_service import CaseService

DISCLAIMER = "辅助初稿，不等同于专利代理师法律意见。"


def test_agent_error_response_uses_common_shape_for_unknown_intent(monkeypatch, tmp_path) -> None:
    """统一 Agent 错误响应应使用统一结构。"""
    settings = Settings(draft_workspace_dir=str(tmp_path / "drafts"))
    case_id = CaseService(settings=settings).create_case()["case_id"]
    monkeypatch.setattr("app.services.agent_dispatch_service.get_settings", lambda: settings)
    client = TestClient(app)

    response = client.post("/agent", json={"raw_input": "你好", "case_id": case_id})

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "status": "requires_user_input",
        "errors": ["unknown_intent"],
        "message": "您希望我处理哪类专利任务？可以选择撰写专利文书、翻译专利文本，或咨询专利问答。",
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


def test_old_claim_routes_are_removed() -> None:
    """旧 claim 专用 API 路由应删除。"""
    client = TestClient(app)

    assert client.post("/claims/generate", json={"raw_input": "内容"}).status_code == 404
    assert client.post("/claims/revise", json={"claims_draft": [], "user_feedback": "修改"}).status_code == 404
