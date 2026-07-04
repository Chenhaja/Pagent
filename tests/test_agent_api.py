import logging

from fastapi.testclient import TestClient

from app.api import routes
from app.main import app

DISCLAIMER = "辅助初稿，不等同于专利代理师法律意见。"


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


def test_agent_api_routes_qa(monkeypatch) -> None:
    """统一 Agent API 应支持 QA 失败响应。"""

    class StubAgentDispatchService:
        """测试用 QA 失败 dispatch 服务。"""

        def dispatch(self, raw_input, claims_draft=None, session_id=None, attachment_ids=None):
            """返回 QA 失败响应。"""
            return {"status": "failed", "errors": ["qa_failed"], "intent": "qa", "workflow": "qa"}

    monkeypatch.setattr(routes, "AgentDispatchService", StubAgentDispatchService)
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
        "message": "您希望我处理哪类专利任务？可以选择撰写专利文书、翻译专利文本，或咨询专利问答。",
        "disclaimer": DISCLAIMER,
    }


def test_agent_api_logs_request_lifecycle_with_session_context(monkeypatch, caplog) -> None:
    """统一 Agent API 应输出请求生命周期日志并绑定 session_id。"""

    class StubAgentDispatchService:
        """测试用 dispatch 服务。"""

        def dispatch(self, raw_input, claims_draft=None, session_id=None, attachment_ids=None):
            """返回成功响应。"""
            return {"status": "success", "intent": "translation", "workflow": "translation", "trace": []}

    monkeypatch.setattr(routes, "AgentDispatchService", StubAgentDispatchService)
    client = TestClient(app)

    with caplog.at_level(logging.INFO, logger="app.api.routes"):
        response = client.post("/agent", json={"raw_input": "继续", "session_id": "s1"})

    assert response.status_code == 200
    events = [record for record in caplog.records if getattr(record, "event", None) in {"request_start", "request_end"}]
    assert [record.event for record in events] == ["request_start", "request_end"]
    assert events[0].fields["path"] == "/agent"
    assert events[0].fields["session_id"] == "s1"
    assert events[1].fields["status"] == "success"
    assert events[1].fields["status_code"] == 200
    assert events[0].request_id


def test_agent_api_logs_failure_reason(monkeypatch, caplog) -> None:
    """统一 Agent API 失败日志应包含可定位错误原因。"""

    class StubAgentDispatchService:
        """测试用失败 dispatch 服务。"""

        def dispatch(self, raw_input, claims_draft=None, session_id=None, attachment_ids=None):
            """返回失败响应。"""
            return {"status": "failed", "errors": ["qa_failed:ValidationError"], "message": "QA 失败"}

    monkeypatch.setattr(routes, "AgentDispatchService", StubAgentDispatchService)
    client = TestClient(app)

    with caplog.at_level(logging.WARNING, logger="app.api.routes"):
        response = client.post("/agent", json={"raw_input": "继续", "session_id": "s1"})

    assert response.status_code == 400
    record = next(item for item in caplog.records if getattr(item, "event", None) == "request_end")
    assert record.fields["errors"] == ["qa_failed:ValidationError"]
    assert record.fields["error_summary"] == "qa_failed:ValidationError"
    assert record.fields["error_message"] == "QA 失败"


def test_agent_api_accepts_and_forwards_session_id(monkeypatch) -> None:
    """统一 Agent API 应接收并透传可选 session_id。"""
    captured = {}

    class StubAgentDispatchService:
        """测试用 dispatch 服务。"""

        def dispatch(self, raw_input, claims_draft=None, session_id=None, attachment_ids=None):
            """记录请求参数并返回成功响应。"""
            captured["raw_input"] = raw_input
            captured["claims_draft"] = claims_draft
            captured["session_id"] = session_id
            return {"status": "success", "intent": "translation", "workflow": "translation", "trace": []}

    monkeypatch.setattr(routes, "AgentDispatchService", StubAgentDispatchService)
    client = TestClient(app)

    response = client.post("/agent", json={"raw_input": "继续", "session_id": "s1"})

    assert response.status_code == 200
    assert captured["session_id"] == "s1"
    assert captured["raw_input"] == "继续"
