import pytest

from app.orchestrator.react_policy import HeuristicReActPolicy, LLMReActPolicy, ReActPolicyError, ReflectResult, ReflectResultEnvelope
from app.prompts.react_policy import REACT_REFLECT_SCHEMA, build_react_reflect_messages
from app.tools.llm import FakeLLMClient, InMemoryLLMTraceSink


def test_react_reflect_schema_requires_sufficient_and_reason() -> None:
    """reflect schema 应约束充分性、原因和下一步 query 提示。"""
    assert REACT_REFLECT_SCHEMA["properties"]["sufficient"] == {"type": "boolean"}
    assert REACT_REFLECT_SCHEMA["properties"]["reason"] == {"type": "string"}
    assert REACT_REFLECT_SCHEMA["properties"]["next_query_hint"] == {"type": ["string", "null"]}
    assert REACT_REFLECT_SCHEMA["required"] == ["sufficient", "reason"]
    assert REACT_REFLECT_SCHEMA["additionalProperties"] is False


def test_build_react_reflect_messages_is_data_separated() -> None:
    """reflect prompt 应隔离 observation 和 scratchpad 数据。"""
    observation_digest = {
        "evidence_count": 1,
        "top_score": 0.72,
        "items": [{"content": "观察正文", "provenance": {"source": "local://doc"}}],
    }

    messages = build_react_reflect_messages("原始问题", observation_digest, [{"step_index": 0}], 1)

    assert [message.role for message in messages] == ["system", "user"]
    system_prompt = messages[0].content
    user_prompt = messages[1].content
    assert "# 任务目标" in system_prompt
    assert "# 上下文/判定规则" in system_prompt
    assert "# 角色" in system_prompt
    assert "# 受众" in system_prompt
    assert "# 样例" in system_prompt
    assert "# 输出格式" in system_prompt
    assert "禁止臆造" in system_prompt
    assert "数据区" in system_prompt
    assert "<data>" in user_prompt and "</data>" in user_prompt
    assert "原始问题" in user_prompt
    assert "观察正文" in user_prompt
    assert "step_index" in user_prompt


def test_llm_react_policy_reflect_parses_valid_result() -> None:
    """LLM reflect 应解析合法结构化反思结果。"""
    trace_sink = InMemoryLLMTraceSink()
    policy = LLMReActPolicy(
        llm_client=FakeLLMClient(
            response={"sufficient": False, "reason": "证据不足", "next_query_hint": "缩小问题"},
            trace_sink=trace_sink,
        ),
        node_name="qa",
        model="policy-model",
        reflect_model="reflect-model",
        timeout=3,
    )

    result = policy.reflect("原问题", {"evidence_count": 0, "top_score": 0.0}, [], 0)

    assert isinstance(result, ReflectResultEnvelope)
    assert result.result == ReflectResult(sufficient=False, reason="证据不足", next_query_hint="缩小问题")
    trace = trace_sink.records[0]
    assert trace["task_type"] == "react_reflect"
    assert trace["node_name"] == "qa"
    assert trace["model"] == "reflect-model"
    assert trace["temperature"] == 0.0
    assert trace["timeout"] == 3
    assert "原问题" not in str(trace)


@pytest.mark.parametrize(
    "response",
    [
        {"reason": "缺充分性"},
        {"sufficient": "no", "reason": "类型错误"},
        {"sufficient": True, "reason": 123},
        {"sufficient": False, "reason": "x", "next_query_hint": []},
    ],
)
def test_llm_react_policy_reflect_rejects_invalid_result(response: dict) -> None:
    """LLM reflect 输出非法结构时应抛出可降级错误。"""
    policy = LLMReActPolicy(llm_client=FakeLLMClient(response=response), node_name="qa")

    with pytest.raises(ReActPolicyError):
        policy.reflect("问题", {"evidence_count": 0}, [], 0)


def test_llm_react_policy_reflect_rejects_llm_error() -> None:
    """LLM reflect 调用失败时应抛出可降级错误。"""
    policy = LLMReActPolicy(llm_client=FakeLLMClient(error="provider_error"), node_name="qa")

    with pytest.raises(ReActPolicyError):
        policy.reflect("问题", {"evidence_count": 0}, [], 0)


def test_heuristic_policy_reflect_uses_score_threshold() -> None:
    """heuristic reflect 应使用 top_score 阈值判断充分性。"""
    policy = HeuristicReActPolicy(sufficient_score_threshold=0.7)

    low = policy.reflect("问题", {"evidence_count": 1, "top_score": 0.6}, [], 0)
    high = policy.reflect("问题", {"evidence_count": 1, "top_score": 0.7}, [], 0)
    empty = policy.reflect("问题", {"evidence_count": 0, "top_score": 0.9}, [], 0)
    error = policy.reflect("问题", {"evidence_count": 1, "top_score": 0.9, "error": "failed"}, [], 0)

    assert low.sufficient is False
    assert high.sufficient is True
    assert empty.sufficient is False
    assert error.sufficient is False
    assert high.next_query_hint is None
