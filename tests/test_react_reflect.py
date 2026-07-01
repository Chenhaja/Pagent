from app.prompts.react_policy import REACT_REFLECT_SCHEMA, build_react_reflect_messages


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
