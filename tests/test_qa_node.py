from app.models.schemas import PatentQAResult, WorkflowState
import app.nodes.qa as qa_module
from app.nodes.qa import QANode
from app.skills.patent_qa import PatentQASkill
from app.tools.llm import FakeLLMClient
from app.tools.retrieval import LocalRetrievalTool, RetrievalResult


class RecordingQASkill:
    """测试用 QA skill,记录上下文并回显 basis。"""

    def __init__(self, answer: str = "结构化回答") -> None:
        self.contexts = []
        self.answer = answer

    def run(self, context):
        """记录上下文并返回固定 QA 结果。"""
        self.contexts.append(context)
        retrieval_results = context.state_snapshot.get("retrieval_results") or []
        if retrieval_results:
            provenance = retrieval_results[0]["provenance"]
            basis = [provenance.get("locator") or provenance["source"]]
        else:
            basis = ["依据不足: 未检索到可引用材料"]
        return PatentQAResult(
            answer=self.answer if retrieval_results else "依据不足,请补充权利要求文本或相关材料。",
            basis=basis,
            risk_notes=["仅供初步参考"],
            next_steps=["补充材料"],
            disclaimer_hint="辅助问答，不等同于专利代理师法律意见。",
        )


class CountingRetrievalTool:
    """测试用检索工具,统计调用次数。"""

    def __init__(self, results: list[RetrievalResult] | None = None, should_raise: bool = False) -> None:
        self.results = results or []
        self.should_raise = should_raise
        self.calls = []

    def search(self, query: str, top_k: int = 3):
        """记录检索调用并返回固定结果。"""
        self.calls.append({"query": query, "top_k": top_k})
        if self.should_raise:
            raise RuntimeError("retrieval failed")
        return self.results[:top_k]


def test_qa_node_uses_retriever_factory_by_default(monkeypatch) -> None:
    """QA node 未显式注入检索器时应通过工厂构建。"""
    retrieval_tool = CountingRetrievalTool()
    calls = []

    def fake_build_retriever(settings):
        calls.append(settings.retrieval_backend)
        return retrieval_tool

    monkeypatch.setattr(qa_module, "build_retriever", fake_build_retriever)

    node = QANode(skill=RecordingQASkill(), max_steps=1)

    assert node.retrieval_tool is retrieval_tool
    assert calls == ["local"]


def test_qa_node_writes_structured_answer_to_state() -> None:
    """QA node 应写入结构化答案并返回可审计 trace。"""
    node = QANode(skill=RecordingQASkill(), max_steps=0)
    state = WorkflowState(raw_input="这个权利要求有什么风险？", normalized_input="这个权利要求有什么风险？")

    result = node.run(state)

    assert result.status == "success"
    assert result.output["qa_result"]["answer"] == "依据不足,请补充权利要求文本或相关材料。"
    assert state.dialog_context["qa_result"]["next_steps"] == ["补充材料"]
    assert result.trace_events == [
        {
            "event": "qa_retrieval_completed",
            "data": {"steps_used": 0, "result_count": 0, "token_budget": 1000, "timeout_seconds": 10},
        },
        {"event": "qa_completed", "data": {"basis_count": 1, "has_retrieval": False, "evidence_versions": []}},
    ]


def test_qa_node_passes_provenance_evidence_to_skill() -> None:
    """QA node 应把检索 provenance evidence 传给 skill 并回链到 basis。"""
    skill = RecordingQASkill(answer="检索显示该方案涉及传感器控制。")
    node = QANode(
        skill=skill,
        retrieval_tool=LocalRetrievalTool(
            documents=[
                {
                    "id": "doc-1",
                    "text": "传感器数据采集与设备控制方案",
                    "source": "local://case/doc-1",
                    "doc_type": "template",
                    "locator": "权利要求1",
                }
            ]
        ),
        max_steps=1,
        token_budget=200,
        timeout_seconds=5,
    )
    state = WorkflowState(raw_input="传感器 控制 风险？", normalized_input="传感器 控制 风险？")

    result = node.run(state)

    assert result.status == "success"
    evidence = skill.contexts[0].state_snapshot["retrieval_results"][0]
    assert evidence == {
        "content": "传感器数据采集与设备控制方案",
        "provenance": {"source": "local://case/doc-1", "document_id": "doc-1", "doc_type": "template", "locator": "权利要求1"},
        "score": 2,
        "similarity": 0.0,
    }
    assert result.output["qa_result"]["basis"] == ["权利要求1"]
    assert result.trace_events == [
        {
            "event": "qa_retrieval_completed",
            "data": {"steps_used": 1, "result_count": 1, "token_budget": 200, "timeout_seconds": 5},
        },
        {"event": "qa_completed", "data": {"basis_count": 1, "has_retrieval": True, "evidence_versions": []}},
    ]


def test_qa_node_formats_law_evidence_and_records_versions() -> None:
    """QA evidence 应包含法规版本出处并在 trace 记录短元数据。"""
    skill = RecordingQASkill(answer="法规依据显示需具备创造性。")
    node = QANode(
        skill=skill,
        retrieval_tool=CountingRetrievalTool(
            [
                RetrievalResult(
                    content="授予专利权的发明应当具备创造性。",
                    provenance={"source": "local://law/zhuanli", "document_id": "zhuanli_fa_2020", "doc_type": "law", "locator": "第22条"},
                    law_name="中华人民共和国专利法",
                    version="2020修正",
                    effective_date="2021-06-01",
                    status="current",
                    retrieved_at="2026-06-01",
                )
            ]
        ),
    )
    state = WorkflowState(raw_input="创造性要求？", normalized_input="创造性要求？")

    result = node.run(state)

    evidence = skill.contexts[0].state_snapshot["retrieval_results"][0]
    assert evidence["provenance"]["citation"] == "《中华人民共和国专利法(2020修正)》第22条(生效日:2021-06-01)"
    assert evidence["provenance"]["status"] == "current"
    assert result.output["qa_result"]["risk_notes"] == ["仅供初步参考"]
    assert result.trace_events[1]["data"]["evidence_versions"] == [
        {
            "document_id": "zhuanli_fa_2020",
            "law_name": "中华人民共和国专利法",
            "version": "2020修正",
            "effective_date": "2021-06-01",
            "status": "current",
            "retrieved_at": "2026-06-01",
        }
    ]


def test_qa_node_adds_warning_for_superseded_law() -> None:
    """命中过时法规版本时应追加固定风险提示。"""
    node = QANode(
        skill=RecordingQASkill(),
        retrieval_tool=CountingRetrievalTool(
            [
                RetrievalResult(
                    content="旧法材料",
                    provenance={"source": "local://law/old", "document_id": "old", "doc_type": "law", "locator": "第22条"},
                    status="superseded",
                )
            ]
        ),
    )
    state = WorkflowState(raw_input="创造性？", normalized_input="创造性？")

    result = node.run(state)

    assert "可能过时，建议核对官方最新版本" in result.output["qa_result"]["risk_notes"]


def test_qa_node_adds_warning_for_stale_law() -> None:
    """retrieved_at 超过 stale 阈值时应追加固定风险提示。"""
    node = QANode(
        skill=RecordingQASkill(),
        retrieval_tool=CountingRetrievalTool(
            [
                RetrievalResult(
                    content="现行但旧检索材料",
                    provenance={"source": "local://law/current", "document_id": "current", "doc_type": "law", "locator": "第22条"},
                    status="current",
                    retrieved_at="2020-01-01",
                )
            ]
        ),
    )
    state = WorkflowState(raw_input="创造性？", normalized_input="创造性？")

    result = node.run(state)

    assert "可能过时，建议核对官方最新版本" in result.output["qa_result"]["risk_notes"]


def test_qa_node_skips_retrieval_when_bounded_guard_blocks() -> None:
    """bounded 参数无效时不应调用 retrieval tool。"""
    retrieval_tool = CountingRetrievalTool([RetrievalResult(content="材料", provenance={"source": "local://doc", "document_id": "doc"}, score=1)])
    node = QANode(skill=RecordingQASkill(), retrieval_tool=retrieval_tool, max_steps=0, token_budget=200, timeout_seconds=5)
    state = WorkflowState(raw_input="问题", normalized_input="问题")

    result = node.run(state)

    assert result.status == "success"
    assert retrieval_tool.calls == []
    assert result.trace_events[0]["data"]["steps_used"] == 0
    assert result.trace_events[0]["data"]["result_count"] == 0


def test_qa_node_continues_when_retrieval_raises() -> None:
    """检索异常不应导致 QA node failed。"""
    retrieval_tool = CountingRetrievalTool(should_raise=True)
    node = QANode(skill=RecordingQASkill(), retrieval_tool=retrieval_tool)
    state = WorkflowState(raw_input="问题", normalized_input="问题")

    result = node.run(state)

    assert result.status == "success"
    assert result.output["qa_result"]["basis"] == ["依据不足: 未检索到可引用材料"]
    assert result.trace_events[0]["data"]["result_count"] == 0


def test_qa_node_returns_failed_when_skill_output_invalid() -> None:
    """QA node 遇到无效 skill 输出时应结构化失败。"""
    node = QANode(skill=PatentQASkill(llm_client=FakeLLMClient(response={"answer": "缺少字段"})))
    state = WorkflowState(raw_input="这个权利要求有什么风险？", normalized_input="这个权利要求有什么风险？")

    result = node.run(state)

    assert result.status == "failed"
    assert result.errors == ["qa_failed"]
