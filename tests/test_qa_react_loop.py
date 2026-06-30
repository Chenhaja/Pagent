from app.models.schemas import PatentQAResult, WorkflowState
from app.nodes.qa import INSUFFICIENT_EVIDENCE_WARNING, QANode
from app.tools.retrieval import RetrievalResult


class RecordingQASkill:
    """测试用 QA skill,记录上下文并返回固定结果。"""

    def __init__(self) -> None:
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
        self.batches = batches
        self.should_raise = should_raise
        self.calls = []

    def search(self, query: str, top_k: int = 3):
        """记录检索调用并返回下一批结果。"""
        self.calls.append({"query": query, "top_k": top_k})
        if self.should_raise:
            raise RuntimeError("retrieval failed")
        index = len(self.calls) - 1
        if index >= len(self.batches):
            return []
        return self.batches[index][:top_k]


class RecordingQueryRewriter:
    """测试用查询改写器,记录调用并返回固定 query。"""

    def __init__(self, queries: list[str], should_raise: bool = False) -> None:
        self.queries = queries
        self.should_raise = should_raise
        self.calls = []

    def expand(self, query: str) -> list[str]:
        """记录 query 并返回固定改写结果。"""
        self.calls.append(query)
        if self.should_raise:
            raise RuntimeError("rewrite failed")
        return self.queries


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


def test_guarded_paths_do_not_call_retriever_or_rewriter() -> None:
    """预算 guard 命中时不应触发检索或改写。"""
    for kwargs, reason in [
        ({"max_steps": 0, "token_budget": 100, "timeout_seconds": 5}, "max_steps"),
        ({"max_steps": 1, "token_budget": 0, "timeout_seconds": 5}, "token_budget"),
        ({"max_steps": 1, "token_budget": 100, "timeout_seconds": 0}, "timeout"),
    ]:
        retriever = SequenceRetrievalTool([[make_result("doc", score=1)]])
        rewriter = RecordingQueryRewriter(["改写问题"])
        node = QANode(skill=RecordingQASkill(), retrieval_tool=retriever, query_rewriter=rewriter, **kwargs)
        state = WorkflowState(raw_input="原始问题", normalized_input="规范问题")

        result = node.run(state)

        assert result.status == "success"
        assert retriever.calls == []
        assert rewriter.calls == []
        assert state.raw_input == "原始问题"
        assert trace_event(result, "qa_react_converged")["data"]["reason"] == reason
        assert trace_event(result, "qa_retrieval_completed")["data"]["steps_used"] == 0
        assert trace_event(result, "qa_retrieval_completed")["data"]["result_count"] == 0


def test_sufficient_evidence_calls_retriever_once_without_rewrite() -> None:
    """首轮 evidence 充分时应单步收敛且不改写。"""
    retriever = SequenceRetrievalTool([[make_result("doc-1", score=1)]])
    rewriter = RecordingQueryRewriter(["改写问题"])
    node = QANode(
        skill=RecordingQASkill(),
        retrieval_tool=retriever,
        query_rewriter=rewriter,
        max_steps=3,
        react_min_results=1,
        react_min_score=0.3,
    )

    result = node.run(WorkflowState(raw_input="问题", normalized_input="问题"))

    assert retriever.calls == [{"query": "问题", "top_k": 3}]
    assert rewriter.calls == []
    step = trace_event(result, "qa_react_step")["data"]
    assert step["query_len"] == 2
    assert step["result_count"] == 1
    assert step["top_score"] == 1.0
    assert step["sufficient"] is True
    assert "问题" not in str(step)
    assert "证据" not in str(step)
    assert trace_event(result, "qa_react_converged")["data"]["reason"] == "sufficient"
    assert trace_event(result, "qa_completed")["event"] == "qa_completed"


def test_multi_step_rewrites_and_dedupes_higher_score_result() -> None:
    """首轮不足时应改写再检索,并保留重复文档高分结果。"""
    low = make_result("doc-1", content="低分证据", score=0)
    high = make_result("doc-1", content="高分证据", score=2)
    retriever = SequenceRetrievalTool([[low], [high, make_result("doc-2", content="新增证据", score=1)]])
    rewriter = RecordingQueryRewriter(["改写问题"])
    skill = RecordingQASkill()
    node = QANode(
        skill=skill,
        retrieval_tool=retriever,
        query_rewriter=rewriter,
        max_steps=2,
        react_min_results=2,
        react_min_score=1.0,
    )

    result = node.run(WorkflowState(raw_input="问题", normalized_input="问题"))

    assert retriever.calls == [{"query": "问题", "top_k": 3}, {"query": "改写问题", "top_k": 3}]
    assert rewriter.calls == ["问题"]
    evidence = skill.contexts[0].state_snapshot["retrieval_results"]
    assert [item["provenance"]["document_id"] for item in evidence] == ["doc-1", "doc-2"]
    assert evidence[0]["content"] == "高分证据"
    assert trace_event(result, "qa_react_converged")["data"]["total_evidence"] == 2
    assert trace_event(result, "qa_react_converged")["data"]["reason"] == "sufficient"


def test_max_steps_adds_insufficient_evidence_warning() -> None:
    """步数耗尽仍不足时应追加固定风险提示。"""
    retriever = SequenceRetrievalTool([[make_result("doc-1", score=0)]])
    node = QANode(skill=RecordingQASkill(), retrieval_tool=retriever, max_steps=1, react_min_results=2, react_min_score=1.0)

    result = node.run(WorkflowState(raw_input="问题", normalized_input="问题"))

    assert trace_event(result, "qa_react_converged")["data"]["reason"] == "max_steps"
    assert INSUFFICIENT_EVIDENCE_WARNING in result.output["qa_result"]["risk_notes"]


def test_token_budget_stops_before_rewrite() -> None:
    """token 预算耗尽时应停止后续改写和检索。"""
    retriever = SequenceRetrievalTool([[make_result("doc-1", content="x" * 20, score=0)], [make_result("doc-2", score=2)]])
    rewriter = RecordingQueryRewriter(["改写问题"])
    node = QANode(
        skill=RecordingQASkill(),
        retrieval_tool=retriever,
        query_rewriter=rewriter,
        max_steps=2,
        token_budget=5,
        react_min_results=2,
        react_min_score=1.0,
    )

    result = node.run(WorkflowState(raw_input="问题", normalized_input="问题"))

    assert len(retriever.calls) == 1
    assert rewriter.calls == []
    assert trace_event(result, "qa_react_converged")["data"]["reason"] == "token_budget"
    assert INSUFFICIENT_EVIDENCE_WARNING in result.output["qa_result"]["risk_notes"]


def test_timeout_stops_gracefully(monkeypatch) -> None:
    """超时时应优雅停止并返回不足提示。"""
    times = iter([0.0, 0.0, 0.0, 2.0])
    monkeypatch.setattr("app.nodes.qa.time.monotonic", lambda: next(times))
    retriever = SequenceRetrievalTool([[make_result("doc-1", score=0)], [make_result("doc-2", score=2)]])
    rewriter = RecordingQueryRewriter(["改写问题"])
    node = QANode(
        skill=RecordingQASkill(),
        retrieval_tool=retriever,
        query_rewriter=rewriter,
        max_steps=2,
        timeout_seconds=1,
        react_min_results=2,
        react_min_score=1.0,
    )

    result = node.run(WorkflowState(raw_input="问题", normalized_input="问题"))

    assert len(retriever.calls) == 1
    assert rewriter.calls == []
    assert trace_event(result, "qa_react_converged")["data"]["reason"] == "timeout"
    assert INSUFFICIENT_EVIDENCE_WARNING in result.output["qa_result"]["risk_notes"]


def test_retrieval_and_rewrite_failures_fallback_without_exception() -> None:
    """检索或改写异常不应裸抛。"""
    retrieval_failed = QANode(skill=RecordingQASkill(), retrieval_tool=SequenceRetrievalTool([], should_raise=True), max_steps=1)
    retrieval_result = retrieval_failed.run(WorkflowState(raw_input="问题", normalized_input="问题"))
    assert retrieval_result.status == "success"
    assert trace_event(retrieval_result, "qa_retrieval_completed")["data"]["result_count"] == 0

    retriever = SequenceRetrievalTool([[make_result("doc-1", score=0)], [make_result("doc-2", score=0)]])
    rewriter = RecordingQueryRewriter(["改写问题"], should_raise=True)
    rewrite_failed = QANode(
        skill=RecordingQASkill(),
        retrieval_tool=retriever,
        query_rewriter=rewriter,
        max_steps=2,
        react_min_results=2,
        react_min_score=1.0,
    )
    rewrite_result = rewrite_failed.run(WorkflowState(raw_input="问题", normalized_input="问题"))

    assert rewrite_result.status == "success"
    assert retriever.calls == [{"query": "问题", "top_k": 3}, {"query": "问题", "top_k": 3}]
    assert trace_events(rewrite_result, "qa_react_step")
