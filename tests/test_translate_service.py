from app.services.translate_service import TranslateService
from app.tools.translation_agent import FakeTranslationAgent, TranslationResult


def test_translate_service_returns_adapter_success() -> None:
    """翻译 service 应封装翻译 workflow 并返回 adapter 成功结果。"""
    service = TranslateService(
        agent=FakeTranslationAgent(
            result=TranslationResult(translated_text="A control method.", terms={"控制方法": "control method"})
        )
    )

    result = service.translate("请翻译一种控制方法")

    assert result["status"] == "success"
    assert result["translated_text"] == "A control method."
    assert result["terms"] == {"控制方法": "control method"}


def test_translate_service_returns_adapter_failure() -> None:
    """翻译 service 应封装 adapter 失败结果。"""
    service = TranslateService(agent=FakeTranslationAgent(error="adapter_timeout"))

    result = service.translate("请翻译一种控制方法")

    assert result == {
        "status": "failed",
        "errors": ["translation_failed:adapter_timeout"],
        "message": "翻译服务暂时不可用,请稍后重试。",
    }
