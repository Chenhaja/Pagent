from app.tools.llm import FakeLLMClient, LLMMessage


def test_fake_llm_returns_fixed_response() -> None:
    """Fake LLM 应返回固定结构化响应。"""
    client = FakeLLMClient(response={"answer": "ok"})

    response = client.generate(prompt="test", output_schema={"type": "object"})

    assert response.content == {"answer": "ok"}
    assert response.raw_text is None
    assert response.errors == []
    assert response.trace["provider"] == "fake"


def test_fake_llm_returns_structured_error_without_raising() -> None:
    """Fake LLM 应用结构化错误模拟外部调用失败。"""
    client = FakeLLMClient(error="timeout")

    response = client.generate(prompt="test")

    assert response.content == {}
    assert response.errors[0]["code"] == "timeout"
    assert response.trace["fallback_used"] is True


def test_fake_llm_accepts_openai_style_messages() -> None:
    """Fake LLM 应支持 OpenAI messages 调用形态。"""
    client = FakeLLMClient(response={"answer": "ok"})

    response = client.generate(
        messages=[
            LLMMessage(role="system", content="你是专利助手"),
            LLMMessage(role="user", content="解释权利要求"),
        ],
        output_schema={"type": "object"},
        model="fake-model",
        temperature=0.1,
        timeout=3.0,
        trace_context={"node_name": "qa", "task_type": "patent_qa"},
    )

    assert response.content == {"answer": "ok"}
    assert response.errors == []
    assert response.trace["model"] == "fake-model"
    assert response.trace["node_name"] == "qa"
    assert response.trace["input_chars"] > 0


def test_fake_llm_can_simulate_empty_response_and_refusal() -> None:
    """Fake LLM 应能模拟空响应和模型拒答。"""
    empty_response = FakeLLMClient(error="empty_response").generate(prompt="test")
    refusal_response = FakeLLMClient(error="model_refusal").generate(prompt="test")

    assert empty_response.errors[0]["code"] == "empty_response"
    assert refusal_response.errors[0]["code"] == "model_refusal"
