from typing import Any

from pydantic import BaseModel, Field


class TranslationResult(BaseModel):
    """外部翻译 agent 返回结果。

    Args:
        translated_text: 译文。
        terms: 术语映射。
        trace: 外部 adapter 调用 trace。

    Returns:
        标准翻译结果。
    """

    translated_text: str
    terms: dict[str, str] = Field(default_factory=dict)
    trace: list[dict[str, Any]] = Field(default_factory=list)


class FakeTranslationAgent:
    """用于测试的外部翻译 agent fake adapter。

    Args:
        result: 固定翻译结果。
        error: 可选错误信息,用于模拟 adapter 失败。

    Returns:
        可替代真实外部翻译 agent 的 fake adapter。
    """

    def __init__(self, result: TranslationResult | None = None, error: str | None = None) -> None:
        self.result = result or TranslationResult(translated_text="")
        self.error = error

    def translate(
        self,
        text: str,
        source_language: str,
        target_language: str,
        terms: dict[str, str] | None = None,
    ) -> TranslationResult:
        """调用外部翻译 agent adapter。

        Args:
            text: 待翻译文本。
            source_language: 源语言。
            target_language: 目标语言。
            terms: 可选术语上下文。

        Returns:
            固定翻译结果。

        Raises:
            RuntimeError: 当初始化时配置 error 时抛出。
        """
        if self.error:
            raise RuntimeError(self.error)
        return self.result
