from typing import Any

from app.models.schemas import NodeResult, WorkflowState
from app.nodes.intent_router import IntentRouterNode
from app.services.agent_dispatch_service import AgentDispatchService
from app.tools.llm import FakeLLMClient


DRAFTING_RESULT = {
    "status": "success",
    "input_points_md": "# 输入要点",
    "prior_art_md": "# 现有技术",
    "outline_md": "# 文书提纲",
    "abstract_md": "# 摘要",
    "claims_md": "# 权利要求",
    "description_md": "# 说明书",
    "figures_md": "# 附图说明",
    "complete_patent_md": "# 完整专利文书",
    "drafting_incomplete": False,
}


class FixedRewriteNode:
    """测试用固定改写节点。"""

    def run(self, state: WorkflowState) -> NodeResult:
        """写入固定改写结果。"""
        state.normalized_input = "请翻译一种控制方法"
        return NodeResult.success(
            output={"normalized_input": state.normalized_input},
            trace_events=[{"event": "query_rewrite_completed", "data": {"confidence": 1.0, "uncertain": False}}],
        )


class FallbackRewriteNode:
    """测试用降级改写节点。"""

    def run(self, state: WorkflowState) -> NodeResult:
        """保留归一化结果并返回 fallback trace。"""
        return NodeResult.success(
            output={"normalized_input": state.normalized_input},
            trace_events=[{"event": "query_rewrite_failed_fallback", "data": {"reason": "llm_error"}}],
        )


class InspectingRewriteNode:
    """测试用改写节点,记录运行时收到的历史。"""

    def __init__(self) -> None:
        self.seen_history: list[dict[str, str]] = []

    def run(self, state: WorkflowState) -> NodeResult:
        """记录 history 并模拟有历史时完成改写。"""
        self.seen_history = list(state.dialog_context.get("history", []))
        if self.seen_history:
            state.normalized_input = "请翻译一种控制方法"
            return NodeResult.success(
                output={"normalized_input": state.normalized_input},
                trace_events=[{"event": "query_rewrite_completed", "data": {"confidence": 0.9, "uncertain": False}}],
            )
        return NodeResult.success(
            output={"normalized_input": state.normalized_input},
            trace_events=[{"event": "query_rewrite_skipped", "data": {"reason": "no_history"}}],
        )


class RecordingSessionStore:
    """测试用会话 store,记录读写调用。"""

    def __init__(self, context: dict[str, Any] | None = None, should_fail_load: bool = False) -> None:
        self.context = context or {"history": [], "session_summary": None}
        self.should_fail_load = should_fail_load
        self.appended: list[tuple[str, str, str]] = []
        self.summary_called = False

    def load_history(self, session_id: str, max_turns: int) -> list[dict[str, str]]:
        """返回测试历史。"""
        return list(self.context.get("history", []))

    def append_turn(self, session_id: str, role: str, content: str) -> None:
        """记录追加 turn。"""
        self.appended.append((session_id, role, content))

    def load_summary(self, session_id: str) -> str | None:
        """返回测试摘要。"""
        return self.context.get("session_summary")

    def upsert_summary(self, session_id: str, summary: str, covered_turn_index: int) -> None:
        """忽略摘要写入。"""
        return None

    def build_context(self, session_id: str) -> dict[str, Any]:
        """返回或抛出测试上下文。"""
        if self.should_fail_load:
            raise RuntimeError("db unavailable")
        return self.context

    def summarize_if_needed(self, session_id: str):
        """记录摘要触发并返回无需摘要。"""
        self.summary_called = True
        return SimpleSummaryResult(success=False, reason="no_summary_needed")


class SimpleSummaryResult:
    """测试用摘要结果。"""

    def __init__(self, success: bool, reason: str | None = None, covered_turn_index: int | None = None) -> None:
        self.success = success
        self.reason = reason
        self.covered_turn_index = covered_turn_index


def test_agent_dispatch_routes_translation_workflow() -> None:
    """统一 Agent 入口应路由到翻译 workflow。"""
    service = AgentDispatchService()

    result = service.dispatch("请翻译一种控制方法")

    assert result["status"] == "success"
    assert result["intent"] == "translation"
    assert result["workflow"] == "translation"
    assert result["translated_text"] == "A control method."


def test_agent_dispatch_routes_qa_workflow() -> None:
    """统一 Agent 入口应路由到 QA workflow。"""
    service = AgentDispatchService()
    service._run_qa = lambda state, workflow_def: {"status": "failed", "errors": ["qa_failed"], "message": "问答失败"}

    result = service.dispatch("请说明创造性的判断思路？")

    assert result["status"] == "failed"
    assert result["intent"] == "qa"
    assert result["workflow"] == "qa"
    assert result["errors"] == ["qa_failed"]


def test_agent_dispatch_uses_rewritten_input_for_intent_router() -> None:
    """query rewrite 的改写结果应影响后续 intent router。"""
    service = AgentDispatchService()
    service.query_rewrite_node = FixedRewriteNode()

    result = service.dispatch("处理它")

    assert result["status"] == "success"
    assert result["intent"] == "translation"
    assert [event["event"] for event in result["workflow_trace"]][:4] == [
        "session_memory_skipped",
        "normalize_input_completed",
        "query_rewrite_completed",
        "intent_router_completed",
    ]


def test_agent_dispatch_continues_after_query_rewrite_fallback() -> None:
    """query rewrite 降级后仍应继续路由。"""
    service = AgentDispatchService()
    service.query_rewrite_node = FallbackRewriteNode()

    result = service.dispatch("请翻译一种控制方法")

    assert result["status"] == "success"
    assert result["intent"] == "translation"
    assert [event["event"] for event in result["workflow_trace"]][:4] == [
        "session_memory_skipped",
        "normalize_input_completed",
        "query_rewrite_failed_fallback",
        "intent_router_completed",
    ]


def test_agent_dispatch_routes_patent_drafting_workflow() -> None:
    """统一 Agent 入口应路由到 patent_drafting workflow。"""
    service = AgentDispatchService()
    service._run_patent_drafting = lambda state, workflow_def: DRAFTING_RESULT

    result = service.dispatch("请根据技术方案生成权利要求")

    assert result["status"] == "success"
    assert result["intent"] == "patent_drafting"
    assert result["workflow"] == "patent_drafting"
    assert result["complete_patent_md"] == "# 完整专利文书"


def test_agent_dispatch_does_not_persist_unreviewed_complete_patent() -> None:
    """未人审的完整专利文书不应写入长期会话记忆。"""
    store = RecordingSessionStore()
    service = AgentDispatchService(session_store=store)
    service._run_patent_drafting = lambda state, workflow_def: DRAFTING_RESULT

    result = service.dispatch("请生成专利文书", session_id="s1")

    assert result["status"] == "success"
    assert store.appended == [("s1", "user", "请生成专利文书")]


def test_agent_dispatch_returns_user_input_request_for_unknown_intent() -> None:
    """统一 Agent 入口遇到未知意图时应返回补充输入提示。"""
    service = AgentDispatchService()
    service.intent_router_node = IntentRouterNode(llm_client=FakeLLMClient(response={"intent": "unknown", "confidence": 0.1}))

    result = service.dispatch("你好")

    assert result["status"] == "requires_user_input"
    assert result["errors"] == ["unknown_intent"]
    assert "您希望我处理哪类专利任务" in result["message"]
    assert "supported_intents" in result


def test_agent_dispatch_injects_session_history_before_query_rewrite() -> None:
    """有 session_id 时 dispatch 应在 query_rewrite 前注入会话历史。"""
    store = RecordingSessionStore(
        context={
            "history": [{"role": "user", "content": "我有一个夹爪方案"}],
            "session_summary": "用户讨论夹爪方案。",
        }
    )
    rewrite_node = InspectingRewriteNode()
    service = AgentDispatchService(session_store=store)
    service.query_rewrite_node = rewrite_node

    result = service.dispatch("翻译它", session_id="s1")

    assert result["status"] == "success"
    assert rewrite_node.seen_history == [{"role": "user", "content": "我有一个夹爪方案"}]
    assert result["workflow_trace"][0]["event"] == "session_memory_loaded"
    assert "query_rewrite_completed" in [event["event"] for event in result["workflow_trace"]]


def test_agent_dispatch_without_session_id_keeps_old_no_history_behavior() -> None:
    """无 session_id 时应跳过会话记忆并保持 no_history 行为。"""
    rewrite_node = InspectingRewriteNode()
    service = AgentDispatchService(session_store=RecordingSessionStore())
    service.query_rewrite_node = rewrite_node

    result = service.dispatch("请翻译一种控制方法")

    events = [event["event"] for event in result["workflow_trace"]]
    assert "session_memory_skipped" in events
    assert "query_rewrite_skipped" in events
    assert rewrite_node.seen_history == []


def test_agent_dispatch_appends_user_and_assistant_turns_after_success() -> None:
    """请求成功后应追加 user 与 assistant turn,且保留 raw_input。"""
    store = RecordingSessionStore()
    service = AgentDispatchService(session_store=store)

    result = service.dispatch("请翻译一种控制方法", session_id="s1")

    assert result["status"] == "success"
    assert store.appended[0] == ("s1", "user", "请翻译一种控制方法")
    assert store.appended[1] == ("s1", "assistant", "A control method.")
    assert store.summary_called is True


def test_agent_dispatch_continues_when_session_store_load_fails() -> None:
    """会话 store 读取失败时主流程应继续并记录降级 trace。"""
    store = RecordingSessionStore(should_fail_load=True)
    service = AgentDispatchService(session_store=store)

    result = service.dispatch("请翻译一种控制方法", session_id="s1")

    assert result["status"] == "success"
    events = [event["event"] for event in result["workflow_trace"]]
    assert "session_memory_unavailable" in events
