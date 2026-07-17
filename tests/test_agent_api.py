import logging

from fastapi.testclient import TestClient

from app.api import routes
from app.core.config import Settings
from app.main import app
from app.orchestrator.react_loop import ToolObservation
from app.services.case_service import CaseService
from app.tools.subagents.agent_runner import LangChainAgentRunner

DISCLAIMER = "辅助初稿，不等同于专利代理师法律意见。"
_ORIGINAL_RUNNER_RUN = LangChainAgentRunner.run


def _create_case_id(tmp_path, monkeypatch) -> str:
    """创建测试案件并让 dispatch 读取同一 workspace 配置。"""
    settings = Settings(draft_workspace_dir=str(tmp_path / "drafts"))
    case_id = CaseService(settings=settings).create_case()["case_id"]
    monkeypatch.setattr("app.services.agent_dispatch_service.get_settings", lambda: settings)
    return case_id


def _patch_patent_searcher_runner(monkeypatch) -> None:
    """替换 patent_searcher 测试 runner,显式写入必需 markdown 产物。"""
    def fake_run(self, tool_input: dict | None = None) -> ToolObservation:
        """仅拦截 patent_searcher,其他 runner 沿用原行为。"""
        if self.agent_name == "markdown_merger_agent":
            complete = self.fallback_builder("test", self.workspace)
            self.workspace.run({"action": "write", "artifact_key": "05_final/complete_patent.md", "content": complete})
            self.workspace.run({"action": "write", "artifact_key": "05_final/review_report.md", "content": "# 终稿评审报告\n\nLLM 评审结论"})
            return ToolObservation(tool_name=self.agent_name, evidence=[{"artifact_key": "05_final/complete_patent.md", "done": True}], sufficient=True)
        if self.agent_name != "patent_searcher_agent":
            return _ORIGINAL_RUNNER_RUN(self, tool_input)
        self.workspace.run({"action": "write", "artifact_key": "02_research/patent_search_results.json", "content": '{"queries":[],"results":[],"sufficient":false,"skipped":true}'})
        self.workspace.run({"action": "write", "artifact_key": "02_research/prior_art_analysis.md", "content": "# 现有技术分析\n\n检索结果不足。"})
        self.workspace.run({"action": "write", "artifact_key": "02_research/abstract_writing_style.md", "content": "# 摘要写作风格指南"})
        self.workspace.run({"action": "write", "artifact_key": "02_research/claims_writing_style.md", "content": "# 权利要求书写作风格指南"})
        self.workspace.run({"action": "write", "artifact_key": "02_research/description_writing_style.md", "content": "# 说明书写作风格指南"})
        return ToolObservation(tool_name=self.agent_name, evidence=[{"artifact_key": key, "done": True} for key in self.output_artifact_keys], sufficient=True)

    monkeypatch.setattr(LangChainAgentRunner, "run", fake_run)


def test_agent_cases_api_creates_case(monkeypatch, tmp_path) -> None:
    """案件创建 API 应返回稳定 ID 和相对 workspace 路径。"""
    monkeypatch.setattr("app.services.case_service.get_settings", lambda: Settings(draft_workspace_dir=str(tmp_path / "drafts")))
    client = TestClient(app)

    response = client.post("/agent/cases")

    assert response.status_code == 200
    payload = response.json()
    assert payload["case_id"]
    assert payload["workspace_id"]
    assert payload["workspace_path"] == f".draft_workspace/tmp_{payload['workspace_id']}"
    assert not payload["workspace_path"].startswith(str(tmp_path))


def test_agent_api_routes_translation(monkeypatch, tmp_path) -> None:
    """统一 Agent API 应支持翻译。"""
    client = TestClient(app)
    case_id = _create_case_id(tmp_path, monkeypatch)

    response = client.post("/agent", json={"raw_input": "请翻译一种控制方法", "case_id": case_id})

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "translation"
    assert payload["workflow"] == "translation"
    assert payload["translated_text"] == "A control method."
    assert payload["disclaimer"] == DISCLAIMER


def test_agent_api_routes_patent_drafting(monkeypatch, tmp_path) -> None:
    """统一 Agent API 应返回 drafting Markdown 产物。"""
    client = TestClient(app)
    case_id = _create_case_id(tmp_path, monkeypatch)
    _patch_patent_searcher_runner(monkeypatch)

    response = client.post("/agent", json={"raw_input": "请生成专利文书", "case_id": case_id})

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "patent_drafting"
    assert payload["workflow"] == "patent_drafting"
    assert payload["complete_patent_md"].startswith("# 完整专利文书")
    assert payload["drafting_incomplete"] is False
    assert payload["disclaimer"] == DISCLAIMER


def test_agent_api_routes_qa(monkeypatch) -> None:
    """统一 Agent API 应支持 QA 失败响应。"""

    class StubAgentDispatchService:
        """测试用 QA 失败 dispatch 服务。"""

        def dispatch(self, raw_input, claims_draft=None, case_id=None, session_id=None, attachment_ids=None):
            """返回 QA 失败响应。"""
            return {"status": "failed", "errors": ["qa_failed"], "intent": "qa", "workflow": "qa"}

    monkeypatch.setattr(routes, "AgentDispatchService", StubAgentDispatchService)
    client = TestClient(app)

    response = client.post("/agent", json={"raw_input": "请说明创造性的判断思路？", "case_id": "case_1"})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["status"] == "failed"
    assert detail["errors"] == ["qa_failed"]
    assert detail["disclaimer"] == DISCLAIMER


def test_agent_api_returns_common_error_for_unknown_intent(monkeypatch, tmp_path) -> None:
    """统一 Agent API 遇到未知意图时应返回统一错误结构。"""
    client = TestClient(app)
    case_id = _create_case_id(tmp_path, monkeypatch)

    response = client.post("/agent", json={"raw_input": "你好", "case_id": case_id})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail == {
        "status": "requires_user_input",
        "errors": ["unknown_intent"],
        "message": "您希望我处理哪类专利任务？可以选择撰写专利文书、翻译专利文本，或咨询专利问答。",
        "disclaimer": DISCLAIMER,
    }


def test_agent_api_rejects_unknown_case_id(monkeypatch, tmp_path) -> None:
    """统一 Agent API 应拒绝不存在的 case_id。"""
    monkeypatch.setattr("app.services.agent_dispatch_service.get_settings", lambda: Settings(draft_workspace_dir=str(tmp_path / "drafts")))
    client = TestClient(app)

    response = client.post("/agent", json={"raw_input": "请翻译一种控制方法", "case_id": "missing_case"})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["status"] == "requires_user_input"
    assert detail["errors"] == ["case_not_found"]
    assert detail["message"] == "请先创建案件并携带有效 case_id。"


def test_agent_api_requires_case_id() -> None:
    """统一 Agent API 缺少 case_id 时应返回请求校验错误。"""
    client = TestClient(app)

    response = client.post("/agent", json={"raw_input": "请翻译一种控制方法"})

    assert response.status_code == 422
    assert any(error["loc"][-1] == "case_id" for error in response.json()["detail"])


def test_agent_api_logs_request_lifecycle_with_session_context(monkeypatch, caplog) -> None:
    """统一 Agent API 应输出请求生命周期日志并绑定 session_id。"""

    class StubAgentDispatchService:
        """测试用 dispatch 服务。"""

        def dispatch(self, raw_input, claims_draft=None, case_id=None, session_id=None, attachment_ids=None):
            """返回成功响应。"""
            return {"status": "success", "intent": "translation", "workflow": "translation", "trace": []}

    monkeypatch.setattr(routes, "AgentDispatchService", StubAgentDispatchService)
    client = TestClient(app)

    with caplog.at_level(logging.INFO, logger="app.api.routes"):
        response = client.post("/agent", json={"raw_input": "继续", "case_id": "case_1", "session_id": "s1"})

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

        def dispatch(self, raw_input, claims_draft=None, case_id=None, session_id=None, attachment_ids=None):
            """返回失败响应。"""
            return {"status": "failed", "errors": ["qa_failed:ValidationError"], "message": "QA 失败"}

    monkeypatch.setattr(routes, "AgentDispatchService", StubAgentDispatchService)
    client = TestClient(app)

    with caplog.at_level(logging.WARNING, logger="app.api.routes"):
        response = client.post("/agent", json={"raw_input": "继续", "case_id": "case_1", "session_id": "s1"})

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

        def dispatch(self, raw_input, claims_draft=None, case_id=None, session_id=None, attachment_ids=None):
            """记录请求参数并返回成功响应。"""
            captured["raw_input"] = raw_input
            captured["claims_draft"] = claims_draft
            captured["case_id"] = case_id
            captured["session_id"] = session_id
            return {"status": "success", "intent": "translation", "workflow": "translation", "trace": []}

    monkeypatch.setattr(routes, "AgentDispatchService", StubAgentDispatchService)
    client = TestClient(app)

    response = client.post("/agent", json={"raw_input": "继续", "case_id": "case_1", "session_id": "s1"})

    assert response.status_code == 200
    assert captured["case_id"] == "case_1"
    assert captured["session_id"] == "s1"
    assert captured["raw_input"] == "继续"
