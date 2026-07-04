from app.services.translate_service import TranslateService


def test_explicit_translation_service_uses_known_intent_workflow_without_intent_router() -> None:
    """显式翻译 service 应使用 known intent workflow,不包含通用 intent_router。"""
    service = TranslateService()

    assert "intent_router" not in service.workflow_def.nodes
    assert service.workflow_def.intent == "translation"
