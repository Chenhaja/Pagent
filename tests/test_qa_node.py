from app.core.config import Settings
from app.models.schemas import PatentQAResult, WorkflowState
import app.nodes.qa as qa_module
from app.nodes.qa import INSUFFICIENT_EVIDENCE_WARNING, QANode
from app.orchestrator.react_loop import ReActOutcome
from app.skills.patent_qa import PatentQASkill
from app.tools.llm import FakeLLMClient, LLMResponse
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

    def search(self, query: str, top_k: int = 3, as_of: str | None = None, fetch_k: int | None = None):
        """记录检索调用并返回固定结果。"""
        self.calls.append({"query": query, "top_k": top_k, "as_of": as_of, "fetch_k": fetch_k})
        if self.should_raise:
            raise RuntimeError("retrieval failed")
        return self.results[:top_k]


class FakeReactLoop:
    """测试用 R7 主循环,记录调用并返回固定 outcome。"""

    def __init__(self, outcome: ReActOutcome) -> None:
        self.outcome = outcome
        self.calls = []

    def run(self, task_input: str, allowed_tools: list[str]) -> ReActOutcome:
        """记录调用并返回 outcome。"""
        self.calls.append({"task_input": task_input, "allowed_tools": allowed_tools})
        return self.outcome


class SequenceLLMClient:
    """测试用 LLM client,按顺序返回 ReAct 决策。"""

    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses
        self.calls = []

    def generate(self, **kwargs) -> LLMResponse:
        """记录调用并返回下一条结构化响应。"""
        self.calls.append(kwargs)
        index = len(self.calls) - 1
        response = self.responses[index] if index < len(self.responses) else self.responses[-1]
        return LLMResponse(content=response)


def make_outcome(evidence: list[dict] | None = None, reason: str = "sufficient") -> ReActOutcome:
    """构造测试用 ReActOutcome。"""
    items = evidence or []
    return ReActOutcome(
        evidence=items,
        reason=reason,
        steps_used=1 if items else 0,
        tool_calls=1 if items else 0,
        trace_events=[
            {
                "event": "react_main_converged",
                "data": {
                    "node_name": "qa",
                    "reason": reason,
                    "steps_used": 1 if items else 0,
                    "tool_calls": 1 if items else 0,
                    "total_evidence": len(items),
                    "external_tools_used": [],
                },
            }
        ],
    )


def trace_event(result, event: str) -> dict:
    """按事件名读取节点 trace。"""
    return next(item for item in result.trace_events if item["event"] == event)


def test_qa_node_uses_retriever_factory_by_default(monkeypatch) -> None:
    """QA node 未显式注入检索器时应通过工厂构建 agentic loop。"""
    retrieval_tool = CountingRetrievalTool()
    calls = []

    def fake_build_retriever(settings):
        calls.append(settings.retrieval_backend)
        return retrieval_tool

    monkeypatch.setattr(qa_module, "build_retriever", fake_build_retriever)

    node = QANode(skill=RecordingQASkill(), max_steps=1)

    assert node.retrieval_tool is retrieval_tool
    assert calls == ["qdrant"]


def test_qa_node_inherits_react_budget_values_from_settings(monkeypatch) -> None:
    """QA node 未显式传预算参数时应继承 ReAct 预算。"""
    settings = Settings(react_max_steps=2, react_token_budget=300, react_timeout_seconds=7, retrieval_top_k=4)
    retrieval_tool = CountingRetrievalTool([RetrievalResult(content="材料", provenance={"source": "local://doc", "document_id": "doc"}, score=1)])

    monkeypatch.setattr(qa_module, "get_settings", lambda: settings)
    monkeypatch.setattr(qa_module, "build_retriever", lambda settings: retrieval_tool)

    node = QANode(skill=RecordingQASkill())
    state = WorkflowState(raw_input="问题", normalized_input="问题")

    result = node.run(state)

    assert retrieval_tool.calls == [{"query": "问题", "top_k": 4, "as_of": None, "fetch_k": None}]
    converged = trace_event(result, "react_main_converged")["data"]
    assert converged["steps_used"] == 1
    assert trace_event(result, "qa_retrieval_completed")["data"] == {
        "steps_used": 1,
        "result_count": 1,
        "token_budget": 300,
        "timeout_seconds": 7,
    }


def test_qa_node_writes_structured_answer_to_state() -> None:
    """QA node 应写入结构化答案并返回可审计 trace。"""
    loop = FakeReactLoop(make_outcome([], reason="max_steps"))
    node = QANode(skill=RecordingQASkill(), react_loop=loop, max_steps=0)
    state = WorkflowState(raw_input="这个权利要求有什么风险？", normalized_input="这个权利要求有什么风险？")

    result = node.run(state)

    assert result.status == "success"
    assert result.output["qa_result"]["answer"] == "依据不足,请补充权利要求文本或相关材料。"
    assert state.dialog_context["qa_result"]["next_steps"] == ["补充材料"]
    assert loop.calls == [{"task_input": "这个权利要求有什么风险？", "allowed_tools": ["kb_retrieval"]}]
    assert trace_event(result, "qa_completed")["data"] == {
        "basis_count": 1,
        "has_retrieval": False,
        "evidence_versions": [],
        "history_msg_count": 0,
    }


def test_qa_node_passes_history_to_skill_and_trace() -> None:
    """QA node 应把 dialog_context 中的历史传给 skill 并记录计数。"""
    skill = RecordingQASkill()
    node = QANode(skill=skill, react_loop=FakeReactLoop(make_outcome([], reason="max_steps")), max_steps=0)
    history = [
        {"role": "user", "content": "上一轮问题"},
        {"role": "assistant", "content": "上一轮回答"},
        {"role": "assistant", "content": "  "},
    ]
    state = WorkflowState(raw_input="继续解释", normalized_input="继续解释", dialog_context={"history": history, "session_summary": "摘要"})

    result = node.run(state)

    assert skill.contexts[0].state_snapshot["history"] == history
    assert "session_summary" not in skill.contexts[0].state_snapshot
    assert trace_event(result, "qa_completed")["data"]["history_msg_count"] == 2
    assert "上一轮回答" not in str(trace_event(result, "qa_completed"))


def test_qa_node_defaults_missing_history_to_empty_list() -> None:
    """QA node 在缺少历史时应向 skill 传空列表。"""
    skill = RecordingQASkill()
    node = QANode(skill=skill, react_loop=FakeReactLoop(make_outcome([], reason="max_steps")), max_steps=0)

    result = node.run(WorkflowState(raw_input="问题", normalized_input="问题", dialog_context={"history": None}))

    assert skill.contexts[0].state_snapshot["history"] == []
    assert trace_event(result, "qa_completed")["data"]["history_msg_count"] == 0


def test_qa_node_preserves_explicit_zero_budget_over_settings(monkeypatch) -> None:
    """QA node 显式传入 0 预算时不应被 settings 默认值覆盖。"""
    settings = Settings(react_max_steps=3, react_token_budget=300, react_timeout_seconds=7)
    retrieval_tool = CountingRetrievalTool([RetrievalResult(content="材料", provenance={"source": "local://doc", "document_id": "doc"}, score=1)])

    monkeypatch.setattr(qa_module, "get_settings", lambda: settings)
    monkeypatch.setattr(qa_module, "build_retriever", lambda settings: retrieval_tool)

    node = QANode(skill=RecordingQASkill(), max_steps=0, token_budget=0, timeout_seconds=0)
    result = node.run(WorkflowState(raw_input="问题", normalized_input="问题"))

    assert retrieval_tool.calls == []
    assert trace_event(result, "react_main_converged")["data"]["reason"] == "max_steps"
    assert trace_event(result, "qa_retrieval_completed")["data"] == {
        "steps_used": 0,
        "result_count": 0,
        "token_budget": 0,
        "timeout_seconds": 0,
    }


def test_qa_node_passes_provenance_evidence_to_skill() -> None:
    """QA node 应把 agentic evidence 传给 skill 并回链到 basis。"""
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
    assert trace_event(result, "qa_retrieval_completed")["data"] == {
        "steps_used": 1,
        "result_count": 1,
        "token_budget": 200,
        "timeout_seconds": 5,
    }
    assert trace_event(result, "qa_completed")["data"] == {
        "basis_count": 1,
        "has_retrieval": True,
        "evidence_versions": [],
        "history_msg_count": 0,
    }


def test_qa_node_formats_law_evidence_and_records_versions() -> None:
    """QA evidence 应包含法规版本出处并在 trace 记录短元数据。"""
    skill = RecordingQASkill(answer="法规依据显示需具备创造性。")
    evidence = [
        {
            "content": "授予专利权的发明应当具备创造性。",
            "provenance": {
                "source": "local://law/zhuanli",
                "document_id": "zhuanli_fa_2020",
                "doc_type": "law",
                "locator": "第22条",
                "law_name": "中华人民共和国专利法",
                "version": "2020修正",
                "effective_date": "2021-06-01",
                "status": "current",
                "retrieved_at": "2026-06-01",
            },
            "score": 0,
            "similarity": 0.0,
        }
    ]
    node = QANode(skill=skill, react_loop=FakeReactLoop(make_outcome(evidence)))
    state = WorkflowState(raw_input="创造性要求？", normalized_input="创造性要求？")

    result = node.run(state)

    qa_evidence = skill.contexts[0].state_snapshot["retrieval_results"][0]
    assert qa_evidence["provenance"]["citation"] == "《中华人民共和国专利法(2020修正)》第22条(生效日:2021-06-01)"
    assert qa_evidence["provenance"]["status"] == "current"
    assert result.output["qa_result"]["risk_notes"] == ["仅供初步参考"]
    assert trace_event(result, "qa_completed")["data"]["evidence_versions"] == [
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
    evidence = [
        {
            "content": "旧法材料",
            "provenance": {"source": "local://law/old", "document_id": "old", "doc_type": "law", "locator": "第22条", "status": "superseded"},
        }
    ]
    node = QANode(skill=RecordingQASkill(), react_loop=FakeReactLoop(make_outcome(evidence)))
    state = WorkflowState(raw_input="创造性？", normalized_input="创造性？")

    result = node.run(state)

    assert "可能过时，建议核对官方最新版本" in result.output["qa_result"]["risk_notes"]


def test_qa_node_adds_warning_for_stale_law() -> None:
    """retrieved_at 超过 stale 阈值时应追加固定风险提示。"""
    evidence = [
        {
            "content": "现行但旧检索材料",
            "provenance": {"source": "local://law/current", "document_id": "current", "doc_type": "law", "locator": "第22条", "status": "current", "retrieved_at": "2020-01-01"},
        }
    ]
    node = QANode(skill=RecordingQASkill(), react_loop=FakeReactLoop(make_outcome(evidence)))
    state = WorkflowState(raw_input="创造性？", normalized_input="创造性？")

    result = node.run(state)

    assert "可能过时，建议核对官方最新版本" in result.output["qa_result"]["risk_notes"]


def test_qa_node_skips_retrieval_when_bounded_guard_blocks() -> None:
    """bounded 参数无效时主循环不应调用 retrieval tool。"""
    retrieval_tool = CountingRetrievalTool([RetrievalResult(content="材料", provenance={"source": "local://doc", "document_id": "doc"}, score=1)])
    node = QANode(skill=RecordingQASkill(), retrieval_tool=retrieval_tool, max_steps=0, token_budget=200, timeout_seconds=5)
    state = WorkflowState(raw_input="问题", normalized_input="问题")

    result = node.run(state)

    assert result.status == "success"
    assert retrieval_tool.calls == []
    retrieval_trace = trace_event(result, "qa_retrieval_completed")
    assert retrieval_trace["data"]["steps_used"] == 0
    assert retrieval_trace["data"]["result_count"] == 0


def test_qa_node_continues_when_retrieval_raises() -> None:
    """检索异常不应导致 QA node failed。"""
    retrieval_tool = CountingRetrievalTool(should_raise=True)
    node = QANode(skill=RecordingQASkill(), retrieval_tool=retrieval_tool)
    state = WorkflowState(raw_input="问题", normalized_input="问题")

    result = node.run(state)

    assert result.status == "success"
    assert result.output["qa_result"]["basis"] == ["依据不足: 未检索到可引用材料"]
    assert trace_event(result, "qa_retrieval_completed")["data"]["result_count"] == 0


def test_qa_node_passes_react_reflect_loop_settings(monkeypatch) -> None:
    """QA 默认 loop 应继承 reflect 阈值和 observation digest 长度配置。"""
    settings = Settings(react_sufficient_score_threshold=0.7, react_observation_digest_chars=123)
    retrieval_tool = CountingRetrievalTool()

    monkeypatch.setattr(qa_module, "get_settings", lambda: settings)
    monkeypatch.setattr(qa_module, "build_retriever", lambda settings: retrieval_tool)

    node = QANode(skill=RecordingQASkill())

    assert node.react_loop.sufficient_score_threshold == 0.7
    assert node.react_loop.observation_digest_chars == 123
    assert node.react_loop.heuristic_policy.sufficient_score_threshold == 0.7


def test_qa_node_uses_llm_react_policy_for_decision_sequence(monkeypatch) -> None:
    """QA 默认 loop 应按 react policy 配置使用 LLM 决策和改写 query。"""
    settings = Settings(
        llm_base_url="https://llm.example.test/v1",
        llm_model="base-model",
        llm_api_key="secret",
        llm_cheap_model="cheap-model",
        react_reflect_model="reflect-model",
        react_policy_driver="llm",
        react_policy_temperature=0.1,
        react_timeout_seconds=5,
        retrieval_top_k=3,
    )
    llm_client = SequenceLLMClient([
        {"thought": "先宽泛检索", "action": "kb_retrieval", "tool_input": {"query": "宽泛问题"}, "stop": False, "sufficient": False},
        {"sufficient": True, "reason": "证据充分", "next_query_hint": None},
    ])
    retrieval_tool = CountingRetrievalTool([
        RetrievalResult(content="材料", provenance={"source": "local://doc", "document_id": "doc", "locator": "doc"}, score=1)
    ])

    monkeypatch.setattr(qa_module, "get_settings", lambda: settings)
    monkeypatch.setattr(qa_module, "build_retriever", lambda settings: retrieval_tool)
    monkeypatch.setattr(qa_module, "build_llm_client", lambda settings: llm_client)

    node = QANode(skill=RecordingQASkill(), max_steps=2)
    result = node.run(WorkflowState(raw_input="原问题", normalized_input="原问题"))

    assert retrieval_tool.calls == [{"query": "宽泛问题", "top_k": 3, "as_of": None, "fetch_k": None}]
    assert len(llm_client.calls) == 2
    assert llm_client.calls[0]["model"] == "cheap-model"
    assert llm_client.calls[0]["temperature"] == 0.1
    assert llm_client.calls[1]["model"] == "reflect-model"
    assert llm_client.calls[1]["temperature"] == 0.0
    assert trace_event(result, "react_policy_step")["data"]["driver"] == "llm"
    assert trace_event(result, "react_reflect_step")["data"] == {
        "node_name": "qa",
        "step_index": 0,
        "sufficient": True,
        "reason_len": len("证据充分"),
        "next_query_hint_present": False,
        "driver": "llm",
    }
    assert trace_event(result, "react_main_converged")["data"]["driver"] == "llm"


def test_qa_node_reflect_false_then_true_converges_with_sufficient(monkeypatch) -> None:
    """QA 默认 loop 应在 reflect false 后继续并在 reflect true 后充分收敛。"""
    settings = Settings(
        llm_base_url="https://llm.example.test/v1",
        llm_model="base-model",
        llm_api_key="secret",
        react_policy_driver="llm",
        react_max_steps=2,
        retrieval_top_k=3,
    )
    unique_reason = "第二轮反思充分但不应进入 QA 输出"
    llm_client = SequenceLLMClient([
        {"thought": "先查", "action": "kb_retrieval", "tool_input": {"query": "第一问"}, "stop": False, "sufficient": False},
        {"sufficient": False, "reason": "第一轮不足", "next_query_hint": "第二问"},
        {"thought": "再查", "action": "kb_retrieval", "tool_input": {"query": "会被 hint 覆盖"}, "stop": False, "sufficient": False},
        {"sufficient": True, "reason": unique_reason, "next_query_hint": None},
    ])
    retrieval_tool = CountingRetrievalTool([
        RetrievalResult(content="材料", provenance={"source": "local://doc", "document_id": "doc", "locator": "doc"}, score=1)
    ])

    monkeypatch.setattr(qa_module, "get_settings", lambda: settings)
    monkeypatch.setattr(qa_module, "build_retriever", lambda settings: retrieval_tool)
    monkeypatch.setattr(qa_module, "build_llm_client", lambda settings: llm_client)

    result = QANode(skill=RecordingQASkill(answer="最终回答")).run(WorkflowState(raw_input="原问题", normalized_input="原问题"))

    assert retrieval_tool.calls == [
        {"query": "第一问", "top_k": 3, "as_of": None, "fetch_k": None},
        {"query": "第二问", "top_k": 3, "as_of": None, "fetch_k": None},
    ]
    reflect_events = [event for event in result.trace_events if event["event"] == "react_reflect_step"]
    assert [event["data"]["sufficient"] for event in reflect_events] == [False, True]
    assert trace_event(result, "react_main_converged")["data"]["reason"] == "sufficient"
    assert unique_reason not in str(result.output["qa_result"])
    assert unique_reason not in str(result.trace_events)


def test_qa_node_falls_back_to_heuristic_without_llm_config(monkeypatch) -> None:
    """无完整 LLM 配置时 QA 默认 loop 应自动 heuristic 且不构建 LLM client。"""
    settings = Settings(react_policy_driver="llm", react_max_steps=1)
    retrieval_tool = CountingRetrievalTool([RetrievalResult(content="材料", provenance={"source": "local://doc", "document_id": "doc"}, score=1)])

    monkeypatch.setattr(qa_module, "get_settings", lambda: settings)
    monkeypatch.setattr(qa_module, "build_retriever", lambda settings: retrieval_tool)
    monkeypatch.setattr(qa_module, "build_llm_client", lambda settings: (_ for _ in ()).throw(AssertionError("unexpected llm client")))

    node = QANode(skill=RecordingQASkill())
    result = node.run(WorkflowState(raw_input="问题", normalized_input="问题"))

    assert retrieval_tool.calls == [{"query": "问题", "top_k": 3, "as_of": None, "fetch_k": None}]
    assert trace_event(result, "react_main_converged")["data"]["driver"] == "heuristic"


def test_qa_node_rejects_disabled_external_policy_tool(monkeypatch) -> None:
    """外部工具关闭时 LLM 选择 websearch 也不应被调用,应降级到 KB 检索。"""
    settings = Settings(
        llm_base_url="https://llm.example.test/v1",
        llm_model="base-model",
        llm_api_key="secret",
        react_max_steps=1,
        agentic_default_tools="kb_retrieval,websearch",
        agentic_external_tools_enabled=False,
        websearch_enabled=True,
    )
    llm_client = SequenceLLMClient([
        {"thought": "尝试外部搜索", "action": "websearch", "tool_input": {"query": "外部问题"}, "stop": False, "sufficient": False},
    ])
    retrieval_tool = CountingRetrievalTool([RetrievalResult(content="材料", provenance={"source": "local://doc", "document_id": "doc"}, score=1)])

    monkeypatch.setattr(qa_module, "get_settings", lambda: settings)
    monkeypatch.setattr(qa_module, "build_retriever", lambda settings: retrieval_tool)
    monkeypatch.setattr(qa_module, "build_llm_client", lambda settings: llm_client)

    node = QANode(skill=RecordingQASkill())
    result = node.run(WorkflowState(raw_input="原问题", normalized_input="原问题"))

    assert retrieval_tool.calls == [{"query": "原问题", "top_k": 3, "as_of": None, "fetch_k": None}]
    converged = trace_event(result, "react_main_converged")["data"]
    assert converged["fallback_used"] is True
    assert converged["external_tools_used"] == []


def test_qa_node_keeps_basis_from_real_evidence_after_policy_rewrite(monkeypatch) -> None:
    """policy 改写 query 后最终 basis 仍应引用真实 evidence 来源。"""
    settings = Settings(llm_base_url="https://llm.example.test/v1", llm_model="base-model", llm_api_key="secret", react_max_steps=1)
    llm_client = SequenceLLMClient([
        {"thought": "改写", "action": "kb_retrieval", "tool_input": {"query": "改写问题"}, "stop": False, "sufficient": True},
    ])
    retrieval_tool = CountingRetrievalTool([
        RetrievalResult(content="材料", provenance={"source": "local://doc", "document_id": "doc", "locator": "真实出处"}, score=1)
    ])

    monkeypatch.setattr(qa_module, "get_settings", lambda: settings)
    monkeypatch.setattr(qa_module, "build_retriever", lambda settings: retrieval_tool)
    monkeypatch.setattr(qa_module, "build_llm_client", lambda settings: llm_client)

    result = QANode(skill=RecordingQASkill()).run(WorkflowState(raw_input="原问题", normalized_input="原问题"))

    assert retrieval_tool.calls[0]["query"] == "改写问题"
    assert result.output["qa_result"]["basis"] == ["真实出处"]


def test_qa_node_returns_failed_when_skill_output_invalid(caplog) -> None:
    """QA node 遇到无效 skill 输出时应结构化失败并记录原因。"""
    node = QANode(skill=PatentQASkill(llm_client=FakeLLMClient(response={"answer": "缺少字段"})))
    state = WorkflowState(raw_input="这个权利要求有什么风险？", normalized_input="这个权利要求有什么风险？")

    with caplog.at_level("WARNING", logger="app.nodes.qa"):
        result = node.run(state)

    assert result.status == "failed"
    assert result.errors == ["qa_failed"]
    record = next(item for item in caplog.records if getattr(item, "event", None) == "qa_failed")
    assert record.fields["error_type"] == "ValidationError"
    assert record.fields["react_reason"]
    assert "这个权利要求有什么风险" not in str(record.fields)
