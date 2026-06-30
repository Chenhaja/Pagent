from app.models.schemas import PatentQAResult, WorkflowState
from app.nodes.qa import INSUFFICIENT_EVIDENCE_WARNING, QANode
from app.tools.retrieval import RetrievalResult


class RecordingQASkill:
    """测试用 QA skill,记录上下文并返回固定结果。"""

    def __init__(self) -> None:
        """初始化上下文记录列表。"""
        self.contexts = []

    def run(self, context):
        """记录上下文并返回固定 QA 结果。"""
        self.contexts.append(context)
        return PatentQAResult(
            answer="测试回答",
            basis=["测试依据"],
            risk_notes=["仅供初步参考"],
            next_steps=["继续核对"],
            disclaimer_hint="辅助问答，不等同于专利代理师法律意见。",
        )


class SequenceRetrievalTool:
    """测试用序列检索器,按调用顺序返回结果。"""

    def __init__(self, batches: list[list[RetrievalResult]], should_raise: bool = False) -> None:
        """初始化固定批次和调用记录。"""
        self.batches = batches
        self.should_raise = should_raise
        self.calls = []

    def search(self, query: str, top_k: int = 3, as_of: str | None = None, fetch_k: int | None = None):
        """记录检索调用并返回下一批结果。"""
        self.calls.append({"query": query, "top_k": top_k, "as_of": as_of, "fetch_k": fetch_k})
        if self.should_raise:
            raise RuntimeError("retrieval failed")
        index = len(self.calls) - 1
        if index >= len(self.batches):
            return []
        return self.batches[index][:top_k]


def make_result(document_id: str, content: str = "证据", score: int = 0, similarity: float = 0.0) -> RetrievalResult:
    """构造测试用检索结果。"""
    return RetrievalResult(
        content=content,
        provenance={"source": f"local://{document_id}", "document_id": document_id, "locator": document_id},
        score=score,
        similarity=similarity,
    )


def trace_event(result, event: str) -> dict:
    """按事件名读取节点 trace。"""
    return next(item for item in result.trace_events if item["event"] == event)


def trace_events(result, event: str) -> list[dict]:
    """按事件名读取多个节点 trace。"""
    return [item for item in result.trace_events if item["event"] == event]


def test_guarded_paths_do_not_call_retriever() -> None:
    """预算 guard 命中时不应触发检索。"""
    for kwargs, reason in [
        ({"max_steps": 0, "token_budget": 100, "timeout_seconds": 5}, "max_steps"),
        ({"max_steps": 1, "token_budget": 0, "timeout_seconds": 5}, "token_budget"),
        ({"max_steps": 1, "token_budget": 100, "timeout_seconds": 0}, "timeout"),
    ]:
        retriever = SequenceRetrievalTool([[make_result("doc", score=1)]])
        node = QANode(skill=RecordingQASkill(), retrieval_tool=retriever, **kwargs)
        state = WorkflowState(raw_input="原始问题", normalized_input="规范问题")

        result = node.run(state)

        assert result.status == "success"
        assert retriever.calls == []
        assert state.raw_input == "原始问题"
        assert trace_event(result, "react_main_converged")["data"]["reason"] == reason
        assert trace_event(result, "qa_retrieval_completed")["data"]["steps_used"] == 0
        assert trace_event(result, "qa_retrieval_completed")["data"]["result_count"] == 0


def test_sufficient_evidence_calls_agentic_retrieval_once() -> None:
    """首轮 evidence 充分时应通过 R7 主循环单步收敛。"""
    retriever = SequenceRetrievalTool([[make_result("doc-1", score=1)]])
    skill = RecordingQASkill()
    node = QANode(skill=skill, retrieval_tool=retriever, max_steps=3)

    result = node.run(WorkflowState(raw_input="问题", normalized_input="问题"))

    assert retriever.calls == [{"query": "问题", "top_k": 3, "as_of": None, "fetch_k": None}]
    step = trace_event(result, "react_main_step")["data"]
    assert step["input_len"] == 2
    assert step["observation_count"] == 1
    assert step["top_score"] == 1.0
    assert step["tool_name"] == "kb_retrieval"
    assert "问题" not in str(step)
    assert "证据" not in str(step)
    assert trace_event(result, "react_main_converged")["data"]["reason"] == "sufficient"
    evidence = skill.contexts[0].state_snapshot["retrieval_results"]
    assert evidence[0]["provenance"]["document_id"] == "doc-1"


def test_max_steps_without_evidence_adds_insufficient_warning() -> None:
    """步数耗尽仍无 evidence 时应追加固定风险提示。"""
    retriever = SequenceRetrievalTool([[]])
    node = QANode(skill=RecordingQASkill(), retrieval_tool=retriever, max_steps=1)

    result = node.run(WorkflowState(raw_input="问题", normalized_input="问题"))

    assert trace_event(result, "react_main_converged")["data"]["reason"] == "max_steps"
    assert INSUFFICIENT_EVIDENCE_WARNING in result.output["qa_result"]["risk_notes"]


def test_retrieval_failure_fallbacks_without_exception() -> None:
    """检索异常不应裸抛,QA 仍返回结构化结果。"""
    retrieval_failed = QANode(skill=RecordingQASkill(), retrieval_tool=SequenceRetrievalTool([], should_raise=True), max_steps=1)

    result = retrieval_failed.run(WorkflowState(raw_input="问题", normalized_input="问题"))

    assert result.status == "success"
    assert trace_event(result, "qa_retrieval_completed")["data"]["result_count"] == 0
    assert trace_events(result, "react_main_step")
    assert trace_event(result, "react_main_converged")["data"]["reason"] == "tool_unavailable"
