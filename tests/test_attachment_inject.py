from fastapi.testclient import TestClient

from app.api import routes
from app.core.config import Settings
from app.models.schemas import NodeResult, WorkflowState
from app.services.agent_dispatch_service import AgentDispatchService
from app.services.attachment_service import AttachmentService
from app.services.case_service import CaseService
from app.main import app


class InspectingNormalizeNode:
    """测试用 normalize 节点,记录附件文档和短指令字段。"""

    def __init__(self) -> None:
        self.seen_state: WorkflowState | None = None

    def run(self, state: WorkflowState) -> NodeResult:
        """记录状态并让流程停止在补充输入。"""
        self.seen_state = state
        return NodeResult.need_user_input(output={"message": "stop"}, errors=["stop"])


def _make_attachment(tmp_path, text: str = "附件正文") -> str:
    """创建测试附件并返回 ID。"""
    service = AttachmentService(settings=Settings(attachment_storage_dir=str(tmp_path)))
    metadata = service.save_upload("交底书.txt", "text/plain", text.encode("utf-8"), "invention_disclosure")
    return metadata["attachment_id"]


def test_workflow_state_documents_defaults_to_empty_list() -> None:
    """WorkflowState.documents 应默认是独立空列表。"""
    first = WorkflowState(raw_input="a")
    second = WorkflowState(raw_input="b")

    first.documents.append({"text": "正文"})

    assert second.documents == []


def test_agent_dispatch_loads_attachments_into_documents(monkeypatch, tmp_path) -> None:
    """dispatch 应按 attachment_ids 加载附件并写入 documents。"""
    attachment_id = _make_attachment(tmp_path)
    settings = Settings(attachment_storage_dir=str(tmp_path), draft_workspace_dir=str(tmp_path / "drafts"), attachment_max_count=5)
    case_id = CaseService(settings=settings).create_case()["case_id"]
    monkeypatch.setattr(
        "app.services.agent_dispatch_service.get_settings",
        lambda: settings,
    )
    normalize_node = InspectingNormalizeNode()
    service = AgentDispatchService()
    service.normalize_node = normalize_node

    result = service.dispatch("请生成权利要求", case_id=case_id, attachment_ids=[attachment_id])

    assert result["status"] == "requires_user_input"
    assert normalize_node.seen_state is not None
    assert normalize_node.seen_state.raw_input == "请生成权利要求"
    assert normalize_node.seen_state.normalized_input is None
    assert normalize_node.seen_state.documents[0]["text"] == "附件正文"
    assert normalize_node.seen_state.documents[0]["doc_type"] == "invention_disclosure"
    injected = next(event for event in normalize_node.seen_state.trace if event["event"] == "attachment_injected")
    assert injected["data"] == {"doc_count": 1, "total_chars": 4}
    assert "附件正文" not in str(injected)


def test_agent_dispatch_rejects_invalid_attachment_id(monkeypatch, tmp_path) -> None:
    """dispatch 遇到无效附件 ID 时应返回可读错误。"""
    settings = Settings(attachment_storage_dir=str(tmp_path), draft_workspace_dir=str(tmp_path / "drafts"))
    case_id = CaseService(settings=settings).create_case()["case_id"]
    monkeypatch.setattr("app.services.agent_dispatch_service.get_settings", lambda: settings)
    service = AgentDispatchService()

    result = service.dispatch("请生成权利要求", case_id=case_id, attachment_ids=["missing"])

    assert result["status"] == "requires_user_input"
    assert result["errors"] == ["attachment_not_found"]
    assert result["trace"][0]["event"] == "attachment_rejected"


def test_agent_dispatch_rejects_too_many_attachment_ids(monkeypatch) -> None:
    """dispatch 应校验单次请求附件数量上限。"""
    settings = Settings(attachment_max_count=1)
    case_id = CaseService(settings=settings).create_case()["case_id"]
    monkeypatch.setattr("app.services.agent_dispatch_service.get_settings", lambda: settings)
    service = AgentDispatchService()

    result = service.dispatch("请生成权利要求", case_id=case_id, attachment_ids=["a", "b"])

    assert result["status"] == "requires_user_input"
    assert result["errors"] == ["attachment_count_exceeded"]


def test_agent_api_forwards_attachment_ids(monkeypatch) -> None:
    """统一 Agent API 应透传 attachment_ids。"""
    captured = {}

    class StubAgentDispatchService:
        """测试用 dispatch 服务。"""

        def dispatch(self, raw_input, claims_draft=None, case_id=None, session_id=None, attachment_ids=None):
            """记录请求参数并返回成功。"""
            captured["attachment_ids"] = attachment_ids
            return {"status": "success", "intent": "claim_generation", "workflow": "claim_generation", "trace": []}

    monkeypatch.setattr(routes, "AgentDispatchService", StubAgentDispatchService)
    client = TestClient(app)

    response = client.post("/agent", json={"raw_input": "继续", "case_id": "case_1", "attachment_ids": ["att-1"]})

    assert response.status_code == 200
    assert captured["attachment_ids"] == ["att-1"]
