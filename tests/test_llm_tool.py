import json
import os

import pytest

from app.core.config import Settings
from app.tools.llm import FakeLLMClient, InMemoryLLMTraceSink, LLMMessage, OpenAICompatibleClient, build_llm_client


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


def test_llm_trace_sink_records_sanitized_trace_only() -> None:
    """LLM trace sink 应只持久化不含敏感正文和密钥的 trace。"""
    sink = InMemoryLLMTraceSink()
    client = FakeLLMClient(response={"answer": "ok"}, trace_sink=sink)

    client.generate(prompt="完整技术交底书内容", trace_context={"api_key": "sk-test-secret", "raw_input": "完整技术交底书内容", "node_name": "qa"})

    assert sink.records == [
        {
            "provider": "fake",
            "model": "fake",
            "input_chars": 9,
            "output_chars": 16,
            "fallback_used": False,
            "node_name": "qa",
        }
    ]
    assert "sk-test-secret" not in str(sink.records)
    assert "完整技术交底书内容" not in str(sink.records)


def test_fake_llm_can_simulate_empty_response_and_refusal() -> None:
    """Fake LLM 应能模拟空响应和模型拒答。"""
    empty_response = FakeLLMClient(error="empty_response").generate(prompt="test")
    refusal_response = FakeLLMClient(error="model_refusal").generate(prompt="test")

    assert empty_response.errors[0]["code"] == "empty_response"
    assert refusal_response.errors[0]["code"] == "model_refusal"


def test_build_llm_client_returns_openai_client_when_config_complete() -> None:
    """LLM client factory 应在配置完整时返回真实兼容 client。"""
    settings = Settings(llm_base_url="https://llm.example.test/v1", llm_model="test-model", llm_api_key="sk-test-secret")

    client = build_llm_client(settings)

    assert isinstance(client, OpenAICompatibleClient)


def test_build_llm_client_returns_fake_client_when_config_incomplete() -> None:
    """LLM client factory 应在配置缺失时返回 fake 避免默认触网。"""
    incomplete_settings = [
        Settings(llm_base_url=None, llm_model="test-model", llm_api_key="sk-test-secret"),
        Settings(llm_base_url="https://llm.example.test/v1", llm_model="", llm_api_key="sk-test-secret"),
        Settings(llm_base_url="https://llm.example.test/v1", llm_model="test-model", llm_api_key=None),
    ]

    for settings in incomplete_settings:
        assert isinstance(build_llm_client(settings), FakeLLMClient)


class FakeHTTPResponse:
    """测试用 HTTP 响应。"""

    def __init__(self, payload: dict, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class FakeURLOpener:
    """记录请求并返回固定响应的 urlopen 替身。"""

    def __init__(self, payload: dict, status: int = 200) -> None:
        self.payload = payload
        self.status = status
        self.requests = []

    def __call__(self, request, timeout: float):
        self.requests.append((request, timeout))
        return FakeHTTPResponse(self.payload, self.status)


def test_openai_compatible_client_posts_chat_completion_request() -> None:
    """OpenAI 兼容 client 应发送 chat completions 请求并解析结构化响应。"""
    opener = FakeURLOpener(
        {
            "choices": [{"message": {"content": '{"answer": "ok"}'}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }
    )
    client = OpenAICompatibleClient(
        settings=Settings(llm_base_url="https://llm.example.test/v1", llm_model="test-model", llm_api_key="sk-test-secret"),
        urlopen=opener,
    )

    response = client.generate(
        messages=[LLMMessage(role="user", content="你好")],
        output_schema={"type": "object"},
        trace_context={"node_name": "feature_extract"},
    )

    request, timeout = opener.requests[0]
    body = json.loads(request.data.decode("utf-8"))
    assert request.full_url == "https://llm.example.test/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer sk-test-secret"
    assert body["model"] == "test-model"
    assert body["response_format"]["type"] == "json_object"
    assert timeout == 30.0
    assert response.content == {"answer": "ok"}
    assert response.trace["token_usage"]["total_tokens"] == 5
    assert response.trace["node_name"] == "feature_extract"


def test_openai_compatible_client_returns_structured_provider_error() -> None:
    """OpenAI 兼容 client 应把 provider 异常转换为结构化错误。"""
    def failing_urlopen(request, timeout: float):
        raise TimeoutError("timeout")

    client = OpenAICompatibleClient(
        settings=Settings(llm_base_url="https://llm.example.test/v1", llm_model="test-model", llm_api_key="sk-test-secret"),
        urlopen=failing_urlopen,
    )

    response = client.generate(prompt="test")

    assert response.content == {}
    assert response.errors[0]["code"] == "timeout"
    assert response.trace["fallback_used"] is True


@pytest.mark.skipif(os.getenv("PAGENT_LLM_REAL_TEST") != "1", reason="真实 LLM 测试默认跳过")
def test_real_openai_compatible_client_can_be_enabled_manually() -> None:
    """真实 OpenAI 兼容调用只在显式开启时运行。"""
    client = OpenAICompatibleClient()

    response = client.generate(prompt='请返回 {"answer":"ok"}', output_schema={"type": "object"})

    assert response.content or response.errors
