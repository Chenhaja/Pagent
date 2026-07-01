import json
import logging
import time
from typing import Any, Callable, Literal, Protocol
from urllib import error, request

from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.core.logging import log_event


logger = logging.getLogger(__name__)
_DROPPED_TRACE_FIELDS = {"api_key", "raw_input", "prompt", "raw_output", "response"}


class LLMMessage(BaseModel):
    """OpenAI 兼容消息。

    Args:
        role: 消息角色,支持 system、user、assistant。
        content: 消息内容。

    Returns:
        可传入 Chat Completions 兼容接口的消息。
    """

    role: Literal["system", "user", "assistant"]
    content: str


class LLMError(BaseModel):
    """LLM 结构化错误。

    Args:
        code: 稳定错误码。
        message: 面向调用方的错误说明。
        retryable: 是否可重试。

    Returns:
        可由上层节点消费的结构化错误。
    """

    code: str
    message: str
    retryable: bool = False


class LLMResponse(BaseModel):
    """LLM 调用响应。

    Args:
        content: 结构化响应内容。
        raw_text: 可选原始文本,测试默认不依赖。
        errors: 结构化错误列表。
        trace: 不含敏感正文和密钥的调用摘要。

    Returns:
        LLM tool 的标准响应。
    """

    content: dict[str, Any]
    raw_text: str | None = None
    errors: list[dict[str, Any]] = Field(default_factory=list)
    trace: dict[str, Any] = Field(default_factory=dict)


class LLMTraceSink(Protocol):
    """LLM trace 持久化接口。

    Returns:
        可替换的 LLM trace sink 协议。
    """

    def write(self, trace: dict[str, Any]) -> None:
        """写入一条已脱敏 trace。

        Args:
            trace: 不含密钥和完整输入输出正文的 trace。

        Returns:
            无返回值。
        """
        ...


class InMemoryLLMTraceSink:
    """内存版 LLM trace sink。

    Returns:
        用于测试和本地调试的 trace sink。
    """

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def write(self, trace: dict[str, Any]) -> None:
        """写入一条 LLM trace。

        Args:
            trace: 已脱敏的 LLM trace。

        Returns:
            无返回值。
        """
        self.records.append(dict(trace))


class LoggingLLMTraceSink:
    """将 LLM trace 写入统一结构化日志。

    Args:
        logger: 可选 logger,测试可注入替身。

    Returns:
        LLM trace 日志 sink。
    """

    def __init__(self, logger: logging.Logger | Any | None = None) -> None:
        self.logger = logger or logging.getLogger(__name__)

    def write(self, trace: dict[str, Any]) -> None:
        """写入一条 llm_call 结构化日志。

        Args:
            trace: 不含密钥和完整输入输出正文的 trace。

        Returns:
            无返回值。
        """
        try:
            safe_trace = {str(key): value for key, value in trace.items() if str(key) not in _DROPPED_TRACE_FIELDS}
            level = logging.WARNING if bool(safe_trace.get("fallback_used")) else logging.INFO
            log_event(self.logger, level, "llm_call", "LLM 调用完成", **safe_trace)
        except Exception:
            return


class LLMClient(Protocol):
    """LLM 客户端协议。

    Returns:
        Fake 与真实 OpenAI 兼容 client 共同实现的调用协议。
    """

    def generate(
        self,
        prompt: str | None = None,
        output_schema: dict[str, Any] | None = None,
        messages: list[LLMMessage] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        trace_context: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """生成 LLM 响应。

        Args:
            prompt: 兼容旧接口的单字符串 prompt。
            output_schema: 期望输出 schema。
            messages: OpenAI 兼容 messages。
            model: 本次调用模型名。
            temperature: 本次调用温度。
            max_tokens: 本次调用最大 token 数。
            timeout: 本次调用超时时间。
            trace_context: 节点、任务等审计上下文。

        Returns:
            结构化 LLM 响应。
        """
        ...


class FakeLLMClient:
    """用于测试的固定响应 LLM client。

    Args:
        response: 固定结构化响应。
        error: 可选错误码,用于模拟调用失败。

    Returns:
        可替代真实 LLM 的 fake client。
    """

    def __init__(
        self,
        response: dict[str, Any] | None = None,
        error: str | None = None,
        trace_sink: LLMTraceSink | None = None,
    ) -> None:
        self.response = response or {}
        self.error = error
        self.trace_sink = trace_sink

    def generate(
        self,
        prompt: str | None = None,
        output_schema: dict[str, Any] | None = None,
        messages: list[LLMMessage] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        trace_context: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """生成固定 LLM 响应。

        Args:
            prompt: 输入 prompt,用于兼容旧接口。
            output_schema: 期望输出 schema,仅用于保持接口一致。
            messages: OpenAI 兼容 messages。
            model: 本次调用模型名。
            temperature: 本次调用温度。
            max_tokens: 本次调用最大 token 数。
            timeout: 本次调用超时时间。
            trace_context: 节点、任务等审计上下文。

        Returns:
            固定 LLMResponse,失败场景返回结构化错误而不是抛裸异常。
        """
        input_chars = _count_input_chars(prompt=prompt, messages=messages)
        trace = {
            "provider": "fake",
            "model": model or "fake",
            "input_chars": input_chars,
            "output_chars": len(str(self.response)),
            "fallback_used": bool(self.error),
        }
        if temperature is not None:
            trace["temperature"] = temperature
        if max_tokens is not None:
            trace["max_tokens"] = max_tokens
        if timeout is not None:
            trace["timeout"] = timeout
        if trace_context:
            trace.update({key: value for key, value in trace_context.items() if key not in {"api_key", "raw_input"}})

        if self.trace_sink is not None:
            self.trace_sink.write(trace)
        if self.error:
            return LLMResponse(
                content={},
                errors=[LLMError(code=self.error, message=f"LLM 调用失败:{self.error}", retryable=_is_retryable(self.error)).model_dump()],
                trace=trace,
            )
        return LLMResponse(content=self.response, trace=trace)


class OpenAICompatibleClient:
    """OpenAI Chat Completions 兼容客户端。

    Args:
        settings: LLM 配置,默认读取应用配置。
        urlopen: HTTP 调用函数,测试可注入 fake。

    Returns:
        可调用任意 OpenAI 兼容端点的 LLM client。
    """

    def __init__(self, settings: Settings | None = None, urlopen: Callable[..., Any] | None = None) -> None:
        self.settings = settings or get_settings()
        self.urlopen = urlopen or request.urlopen

    def generate(
        self,
        prompt: str | None = None,
        output_schema: dict[str, Any] | None = None,
        messages: list[LLMMessage] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        trace_context: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """调用 OpenAI 兼容 Chat Completions 接口。

        Args:
            prompt: 兼容旧接口的单字符串 prompt。
            output_schema: 期望输出 schema。
            messages: OpenAI 兼容 messages。
            model: 本次调用模型名。
            temperature: 本次调用温度。
            max_tokens: 本次调用最大 token 数。
            timeout: 本次调用超时时间。
            trace_context: 节点、任务等审计上下文。

        Returns:
            解析后的结构化响应或结构化错误。
        """
        started_at = time.perf_counter()
        call_messages = messages or [LLMMessage(role="user", content=prompt or "")]
        call_model = model or self.settings.llm_model
        call_timeout = timeout or self.settings.llm_timeout
        trace = self._build_trace(
            model=call_model,
            messages=call_messages,
            trace_context=trace_context,
            fallback_used=False,
        )
        if not self.settings.llm_base_url or not call_model or not self.settings.llm_api_key:
            trace["fallback_used"] = True
            return LLMResponse(
                content={},
                errors=[LLMError(code="provider_error", message="LLM 配置不完整", retryable=False).model_dump()],
                trace=trace,
            )

        payload = {
            "model": call_model,
            "messages": [message.model_dump() for message in call_messages],
            "temperature": temperature if temperature is not None else self.settings.llm_temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.settings.llm_max_tokens,
        }
        if output_schema is not None:
            payload["response_format"] = {"type": "json_object"}

        try:
            http_request = request.Request(
                url=self._chat_completions_url(),
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.settings.llm_api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with self.urlopen(http_request, timeout=call_timeout) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except TimeoutError:
            return self._error_response("timeout", "LLM 调用超时", trace, started_at)
        except error.HTTPError as exc:
            code = "rate_limited" if exc.code == 429 else "provider_error"
            return self._error_response(code, f"LLM provider HTTP 错误:{exc.code}", trace, started_at)
        except Exception as exc:
            return self._error_response("provider_error", f"LLM provider 调用失败:{exc}", trace, started_at)

        trace["duration_ms"] = int((time.perf_counter() - started_at) * 1000)
        usage = response_payload.get("usage", {})
        trace["token_usage"] = usage
        raw_text = _extract_openai_text(response_payload)
        if not raw_text:
            return self._error_response("empty_response", "LLM 返回空内容", trace, started_at)
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            return self._error_response("json_parse_failed", "LLM 返回内容不是合法 JSON", trace, started_at, raw_text=raw_text)
        trace["output_chars"] = len(raw_text)
        return LLMResponse(content=parsed, raw_text=raw_text, trace=trace)

    def _chat_completions_url(self) -> str:
        """生成 chat completions 请求地址。

        Returns:
            OpenAI 兼容 chat completions URL。
        """
        base_url = self.settings.llm_base_url or ""
        return f"{base_url.rstrip('/')}/chat/completions"

    def _build_trace(
        self,
        model: str,
        messages: list[LLMMessage],
        trace_context: dict[str, Any] | None,
        fallback_used: bool,
    ) -> dict[str, Any]:
        """构造不含敏感正文的 trace。

        Args:
            model: 本次调用模型名。
            messages: 本次调用消息列表。
            trace_context: 节点、任务等审计上下文。
            fallback_used: 是否命中降级。

        Returns:
            可安全记录的 trace 字典。
        """
        trace = {
            "provider": "openai_compatible",
            "model": model,
            "input_chars": _count_input_chars(prompt=None, messages=messages),
            "output_chars": 0,
            "fallback_used": fallback_used,
        }
        if trace_context:
            trace.update({key: value for key, value in trace_context.items() if key not in {"api_key", "raw_input"}})
        return trace

    def _error_response(
        self,
        code: str,
        message: str,
        trace: dict[str, Any],
        started_at: float,
        raw_text: str | None = None,
    ) -> LLMResponse:
        """构造结构化错误响应。

        Args:
            code: 稳定错误码。
            message: 错误说明。
            trace: 调用 trace。
            started_at: 调用开始时间。
            raw_text: 可选原始响应文本。

        Returns:
            包含结构化错误的 LLMResponse。
        """
        trace["fallback_used"] = True
        trace["duration_ms"] = int((time.perf_counter() - started_at) * 1000)
        return LLMResponse(
            content={},
            raw_text=raw_text,
            errors=[LLMError(code=code, message=message, retryable=_is_retryable(code)).model_dump()],
            trace=trace,
        )


def build_llm_client(settings: Settings | None = None) -> LLMClient:
    """根据配置构建 LLM client。

    Args:
        settings: 可选应用配置,未传入时读取全局配置。

    Returns:
        配置完整时返回 OpenAI 兼容 client;配置缺失时返回 Fake client,避免默认路径触发网络请求。
    """
    resolved_settings = settings or get_settings()
    if resolved_settings.llm_base_url and resolved_settings.llm_model and resolved_settings.llm_api_key:
        return OpenAICompatibleClient(settings=resolved_settings)
    return FakeLLMClient()


def _extract_openai_text(payload: dict[str, Any]) -> str:
    """从 OpenAI 兼容响应中提取文本。

    Args:
        payload: provider 返回的 JSON 响应。

    Returns:
        第一条 choice 的 message.content,缺失时返回空字符串。
    """
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return str(message.get("content") or "")


def _count_input_chars(prompt: str | None, messages: list[LLMMessage] | None) -> int:
    """统计输入字符数。

    Args:
        prompt: 单字符串 prompt。
        messages: OpenAI 兼容消息列表。

    Returns:
        输入总字符数。
    """
    if messages is not None:
        return sum(len(message.content) for message in messages)
    return len(prompt or "")


def _is_retryable(error_code: str) -> bool:
    """判断 LLM 错误是否可重试。

    Args:
        error_code: LLM 结构化错误码。

    Returns:
        超时、限流和 provider 错误视为可重试。
    """
    return error_code in {"timeout", "rate_limited", "provider_error"}
