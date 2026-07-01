import pytest

from app.orchestrator.react_policy import HeuristicReActPolicy, LLMReActPolicy, ReActDecision, ReActPolicyError
from app.orchestrator.tool_registry import ToolCard
from app.tools.llm import FakeLLMClient, InMemoryLLMTraceSink


def tool_card(name: str = "kb_retrieval") -> ToolCard:
    """构造测试用工具卡片。"""
    return ToolCard(
        name=name,
        description="检索知识库证据",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    )


def test_llm_react_policy_parses_valid_decision() -> None:
    """LLM policy 应解析合法结构化决策。"""
    trace_sink = InMemoryLLMTraceSink()
    client = FakeLLMClient(
        response={
            "thought": "需要先检索本地知识库",
            "action": "kb_retrieval",
            "tool_input": {"query": "改写后的问题"},
            "stop": False,
            "sufficient": False,
        },
        trace_sink=trace_sink,
    )
    policy = LLMReActPolicy(llm_client=client, node_name="qa", model="cheap", temperature=0.0, timeout=3)

    decision = policy.decide("敏感原问题", [tool_card()], [], 0)

    assert decision == ReActDecision(
        thought="需要先检索本地知识库",
        action="kb_retrieval",
        tool_input={"query": "改写后的问题"},
        stop=False,
        sufficient=False,
    )
    trace = trace_sink.records[0]
    assert trace["task_type"] == "react_policy"
    assert trace["node_name"] == "qa"
    assert trace["model"] == "cheap"
    assert trace["temperature"] == 0.0
    assert trace["timeout"] == 3
    assert "api_key" not in trace
    assert "raw_input" not in trace
    assert "敏感原问题" not in str(trace)


@pytest.mark.parametrize(
    "response",
    [
        {"action": "kb_retrieval", "stop": False, "sufficient": False},
        {"thought": "x", "action": "kb_retrieval", "stop": "no", "sufficient": False},
        {"thought": "x", "action": "kb_retrieval", "tool_input": [], "stop": False, "sufficient": False},
    ],
)
def test_llm_react_policy_rejects_invalid_decision(response: dict) -> None:
    """LLM policy 遇到非法结构时应抛出可降级错误。"""
    policy = LLMReActPolicy(llm_client=FakeLLMClient(response=response), node_name="qa")

    with pytest.raises(ReActPolicyError):
        policy.decide("问题", [tool_card()], [], 0)


def test_llm_react_policy_rejects_llm_error() -> None:
    """LLM 调用失败时应抛出可降级错误。"""
    policy = LLMReActPolicy(llm_client=FakeLLMClient(error="provider_error"), node_name="qa")

    with pytest.raises(ReActPolicyError):
        policy.decide("问题", [tool_card()], [], 0)


def test_heuristic_policy_keeps_old_deterministic_decision() -> None:
    """heuristic policy 应保留旧的按顺序选工具行为。"""
    policy = HeuristicReActPolicy()

    first = policy.decide("原问题", [tool_card("a"), tool_card("b")], [], 0)
    second = policy.decide("原问题", [tool_card("a"), tool_card("b")], [], 2)

    assert first.action == "a"
    assert first.tool_input == {"query": "原问题", "step_index": 0}
    assert first.stop is False
    assert first.sufficient is False
    assert second.action == "b"
    assert second.tool_input == {"query": "原问题", "step_index": 2}


def test_heuristic_policy_stops_without_tools() -> None:
    """无可用工具时 heuristic policy 应保守停止。"""
    policy = HeuristicReActPolicy()

    decision = policy.decide("问题", [], [], 0)

    assert decision.action is None
    assert decision.stop is True
    assert decision.sufficient is False
