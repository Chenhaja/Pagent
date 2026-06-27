from typing import Any

from pydantic import BaseModel


class LLMResponse(BaseModel):
    """LLM 调用响应。

    Args:
        content: 结构化响应内容。
        raw_text: 可选原始文本,测试默认不依赖。

    Returns:
        LLM tool 的标准响应。
    """

    content: dict[str, Any]
    raw_text: str | None = None


class FakeLLMClient:
    """用于测试的固定响应 LLM client。

    Args:
        response: 固定结构化响应。
        error: 可选错误信息,用于模拟调用失败。

    Returns:
        可替代真实 LLM 的 fake client。
    """

    def __init__(self, response: dict[str, Any] | None = None, error: str | None = None) -> None:
        self.response = response or {}
        self.error = error

    def generate(
        self,
        prompt: str,
        output_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """生成固定 LLM 响应。

        Args:
            prompt: 输入 prompt,仅用于保持接口一致。
            output_schema: 期望输出 schema,仅用于保持接口一致。

        Returns:
            固定 LLMResponse。

        Raises:
            RuntimeError: 当初始化时配置 error 时抛出。
        """
        if self.error:
            raise RuntimeError(self.error)
        return LLMResponse(content=self.response)
