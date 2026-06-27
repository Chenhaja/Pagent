from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


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

    def __init__(self, response: dict[str, Any] | None = None, error: str | None = None) -> None:
        self.response = response or {}
        self.error = error

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

        if self.error:
            return LLMResponse(
                content={},
                errors=[LLMError(code=self.error, message=f"LLM 调用失败:{self.error}", retryable=_is_retryable(self.error)).model_dump()],
                trace=trace,
            )
        return LLMResponse(content=self.response, trace=trace)


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
