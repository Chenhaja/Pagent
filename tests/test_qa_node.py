from app.models.schemas import WorkflowState
from app.nodes.qa import QANode
from app.skills.patent_qa import PatentQASkill
from app.tools.llm import FakeLLMClient
from app.tools.retrieval import LocalRetrievalTool


def test_qa_node_writes_structured_answer_to_state() -> None:
    """QA node 应写入结构化答案并返回可审计 trace。"""
    node = QANode(
        skill=PatentQASkill(
            llm_client=FakeLLMClient(
                response={
                    "answer": "该权利要求需要补充技术效果。",
                    "basis": ["问题包含风险判断"],
                    "risk_notes": ["仅供初步参考"],
                    "next_steps": ["补充效果数据"],
                    "disclaimer_hint": "辅助问答，不等同于专利代理师法律意见。",
                }
            )
        )
    )
    state = WorkflowState(raw_input="这个权利要求有什么风险？", normalized_input="这个权利要求有什么风险？")

    result = node.run(state)

    assert result.status == "success"
    assert result.output["qa_result"]["answer"] == "该权利要求需要补充技术效果。"
    assert state.dialog_context["qa_result"]["next_steps"] == ["补充效果数据"]
    assert result.trace_events == [
        {
            "event": "qa_retrieval_completed",
            "data": {"steps_used": 0, "result_count": 0, "token_budget": 1000, "timeout_seconds": 10},
        },
        {"event": "qa_completed"},
    ]


def test_qa_node_runs_bounded_react_with_retrieval_trace() -> None:
    """QA node 应在步数预算内调用 retrieval 并输出 trace。"""
    node = QANode(
        skill=PatentQASkill(
            llm_client=FakeLLMClient(
                response={
                    "answer": "检索显示该方案涉及传感器控制。",
                    "basis": ["传感器数据采集与设备控制方案"],
                    "risk_notes": ["需复核权利要求支持性"],
                    "next_steps": ["补充控制步骤"],
                    "disclaimer_hint": "辅助问答，不等同于专利代理师法律意见。",
                }
            )
        ),
        retrieval_tool=LocalRetrievalTool(
            documents=[{"id": "doc-1", "text": "传感器数据采集与设备控制方案", "source": "local://case/doc-1"}]
        ),
        max_steps=1,
        token_budget=200,
        timeout_seconds=5,
    )
    state = WorkflowState(raw_input="传感器 控制 风险？", normalized_input="传感器 控制 风险？")

    result = node.run(state)

    assert result.status == "success"
    assert state.dialog_context["qa_retrieval_results"][0]["provenance"] == {
        "source": "local://case/doc-1",
        "document_id": "doc-1",
    }
    assert result.trace_events == [
        {
            "event": "qa_retrieval_completed",
            "data": {"steps_used": 1, "result_count": 1, "token_budget": 200, "timeout_seconds": 5},
        },
        {"event": "qa_completed"},
    ]


def test_qa_node_returns_failed_when_skill_output_invalid() -> None:
    """QA node 遇到无效 skill 输出时应结构化失败。"""
    node = QANode(skill=PatentQASkill(llm_client=FakeLLMClient(response={"answer": "缺少字段"})))
    state = WorkflowState(raw_input="这个权利要求有什么风险？", normalized_input="这个权利要求有什么风险？")

    result = node.run(state)

    assert result.status == "failed"
    assert result.errors == ["qa_failed"]
