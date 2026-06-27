import pytest

from app.tools.translation_agent import FakeTranslationAgent, TranslationResult


def test_fake_translation_agent_returns_fixed_result() -> None:
    """Fake 翻译 adapter 应返回固定翻译结果。"""
    agent = FakeTranslationAgent(
        result=TranslationResult(
            translated_text="A control method.",
            terms={"控制方法": "control method"},
            trace=[{"event": "translation_completed"}],
        )
    )

    result = agent.translate(text="一种控制方法", source_language="zh", target_language="en")

    assert result.translated_text == "A control method."
    assert result.terms == {"控制方法": "control method"}
    assert result.trace == [{"event": "translation_completed"}]


def test_fake_translation_agent_can_simulate_error() -> None:
    """Fake 翻译 adapter 应能模拟外部 agent 失败。"""
    agent = FakeTranslationAgent(error="adapter_timeout")

    with pytest.raises(RuntimeError, match="adapter_timeout"):
        agent.translate(text="一种控制方法", source_language="zh", target_language="en")
