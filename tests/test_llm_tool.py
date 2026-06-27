import pytest

from app.tools.llm import FakeLLMClient, LLMResponse


def test_fake_llm_returns_fixed_response() -> None:
    """Fake LLM 应返回固定结构化响应。"""
    client = FakeLLMClient(response={"answer": "ok"})

    response = client.generate(prompt="test", output_schema={"type": "object"})

    assert response == LLMResponse(content={"answer": "ok"}, raw_text=None)


def test_fake_llm_can_raise_configured_error() -> None:
    """Fake LLM 应能模拟外部调用失败。"""
    client = FakeLLMClient(error="timeout")

    with pytest.raises(RuntimeError, match="timeout"):
        client.generate(prompt="test")
