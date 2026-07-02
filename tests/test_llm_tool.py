import json
import logging
import os

import pytest

from app.core.config import Settings
from app.core.logging import JsonLineFormatter
from app.tools.llm import FakeLLMClient, InMemoryLLMTraceSink, LLMMessage, LoggingLLMTraceSink, OpenAICompatibleClient, build_llm_client


def test_fake_llm_returns_fixed_response() -> None:
    """Fake LLM 应返回固定结构化响应。"""
    client = FakeLLMClient(response={"answer": "ok"})

    response = client.generate(prompt="test", output_schema={"type": "object"})

    assert response.content == {"answer": "ok"}
    assert response.raw_text is None
    assert response.errors == []
    assert response.trace["provider"] == "fake"
    assert response.reasoning_text is None
    assert response.trace["has_reasoning"] is False
    assert response.trace["reasoning_chars"] == 0


def test_fake_llm_returns_structured_error_without_raising() -> None:
    """Fake LLM 应用结构化错误模拟外部调用失败。"""
    client = FakeLLMClient(error="timeout")

    response = client.generate(prompt="test")

    assert response.content == {}
    assert response.errors[0]["code"] == "timeout"
    assert response.trace["fallback_used"] is True


def test_fake_llm_injects_reasoning_text_without_trace_body() -> None:
    """Fake LLM 应支持注入 reasoning_text 且 trace 不含正文。"""
    client = FakeLLMClient(response={"answer": "ok"}, reasoning_text="内部推理正文")

    response = client.generate(prompt="test")

    assert response.reasoning_text == "内部推理正文"
    assert response.trace["has_reasoning"] is True
    assert response.trace["reasoning_chars"] == len("内部推理正文")
    assert "内部推理正文" not in str(response.trace)


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
            "has_reasoning": False,
            "reasoning_chars": 0,
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


def test_logging_llm_trace_sink_writes_llm_call_event(caplog) -> None:
    """LoggingLLMTraceSink 应输出 llm_call 结构化事件。"""
    sink = LoggingLLMTraceSink()

    with caplog.at_level(logging.INFO, logger="app.tools.llm"):
        sink.write({"provider": "fake", "model": "fake", "input_chars": 4, "output_chars": 2, "fallback_used": False, "duration_ms": 10})

    record = caplog.records[-1]
    assert record.event == "llm_call"
    assert record.levelname == "INFO"
    assert record.fields["provider"] == "fake"
    assert record.fields["model"] == "fake"
    assert record.fields["input_chars"] == 4
    assert record.fields["output_chars"] == 2
    assert record.fields["fallback_used"] is False


def test_logging_llm_trace_sink_warns_on_fallback(caplog) -> None:
    """LLM 降级 trace 应升级为 WARNING 日志。"""
    sink = LoggingLLMTraceSink()

    with caplog.at_level(logging.WARNING, logger="app.tools.llm"):
        sink.write({"provider": "fake", "model": "fake", "input_chars": 4, "output_chars": 0, "fallback_used": True})

    assert caplog.records[-1].event == "llm_call"
    assert caplog.records[-1].levelname == "WARNING"


def test_logging_llm_trace_sink_does_not_emit_sensitive_trace_fields() -> None:
    """LLM 日志 sink 不应输出 api_key、raw_input 或完整正文。"""
    logger = logging.getLogger("test.llm_trace")
    logger.handlers.clear()
    logger.propagate = False
    handler = logging.StreamHandler()
    formatter = JsonLineFormatter(service="patent-agent", environment="prod")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    sink = LoggingLLMTraceSink(logger=logger)

    sink.write({"provider": "fake", "model": "fake", "api_key": "sk-secret", "raw_input": "完整技术交底书内容", "prompt": "完整提示词"})

    record = logging.LogRecord("test.llm_trace", logging.INFO, __file__, 1, "LLM 调用完成", (), None)
    record.event = "llm_call"
    record.fields = {"api_key": "sk-secret", "raw_input": "完整技术交底书内容", "prompt": "完整提示词"}
    payload = json.loads(formatter.format(record))
    assert "api_key" not in payload
    assert "raw_input" not in payload
    assert "prompt" not in payload


def test_logging_llm_trace_sink_swallows_logger_errors() -> None:
    """LLM 日志 sink 失败时不应影响调用方。"""
    class FailingLogger:
        def log(self, *args, **kwargs):
            raise RuntimeError("boom")

    LoggingLLMTraceSink(logger=FailingLogger()).write({"fallback_used": False})


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


def test_openai_compatible_client_extracts_reasoning_content() -> None:
    """OpenAI 兼容 client 应提取 reasoning_content 且 trace 只含元数据。"""
    opener = FakeURLOpener(
        {
            "choices": [{"message": {"content": '{"answer": "ok"}', "reasoning_content": "原生推理正文"}}],
            "usage": {"total_tokens": 5},
        }
    )
    client = OpenAICompatibleClient(
        settings=Settings(llm_base_url="https://llm.example.test/v1", llm_model="test-model", llm_api_key="sk-test-secret"),
        urlopen=opener,
    )

    response = client.generate(prompt="test", output_schema={"type": "object"})

    assert response.content == {"answer": "ok"}
    assert response.reasoning_text == "原生推理正文"
    assert response.trace["has_reasoning"] is True
    assert response.trace["reasoning_chars"] == len("原生推理正文")
    assert "原生推理正文" not in str(response.trace)


def test_openai_compatible_client_extracts_reasoning_field() -> None:
    """OpenAI 兼容 client 应兼容 reasoning 字段。"""
    opener = FakeURLOpener({"choices": [{"message": {"content": '{"answer": "ok"}', "reasoning": "推理摘要"}}]})
    client = OpenAICompatibleClient(
        settings=Settings(llm_base_url="https://llm.example.test/v1", llm_model="test-model", llm_api_key="sk-test-secret"),
        urlopen=opener,
    )

    response = client.generate(prompt="test", output_schema={"type": "object"})

    assert response.reasoning_text == "推理摘要"
    assert response.trace["has_reasoning"] is True
    assert response.trace["reasoning_chars"] == len("推理摘要")


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
