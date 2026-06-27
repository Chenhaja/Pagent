from app.models.schemas import SkillContext
from app.skills.patent_translation import PatentTranslationSkill, TranslationAdapterRequest


def test_patent_translation_skill_builds_adapter_request() -> None:
    """专利翻译 skill 应只组织术语上下文并生成 adapter 请求。"""
    skill = PatentTranslationSkill()
    context = SkillContext(
        task_type="patent_translate",
        state_snapshot={"text": "一种控制方法", "source_language": "zh", "target_language": "en"},
        domain_rules={"terms": {"控制方法": "control method"}},
    )

    request = skill.build_request(context)

    assert isinstance(request, TranslationAdapterRequest)
    assert request.text == "一种控制方法"
    assert request.source_language == "zh"
    assert request.target_language == "en"
    assert request.terms == {"控制方法": "control method"}


def test_patent_translation_skill_uses_safe_defaults() -> None:
    """专利翻译 skill 缺少语言配置时应使用安全默认值。"""
    skill = PatentTranslationSkill()

    request = skill.build_request(SkillContext(task_type="patent_translate", state_snapshot={"text": "一种控制方法"}))

    assert request.source_language == "zh"
    assert request.target_language == "en"
    assert request.terms == {}
