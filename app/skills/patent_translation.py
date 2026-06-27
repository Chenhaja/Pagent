from pydantic import BaseModel, Field

from app.models.schemas import SkillContext


class TranslationAdapterRequest(BaseModel):
    """外部翻译 adapter 请求。

    Args:
        text: 待翻译文本。
        source_language: 源语言。
        target_language: 目标语言。
        terms: 翻译术语上下文。

    Returns:
        传递给外部翻译 adapter 的标准请求。
    """

    text: str
    source_language: str = "zh"
    target_language: str = "en"
    terms: dict[str, str] = Field(default_factory=dict)


class PatentTranslationSkill:
    """专利翻译 skill 上下文占位实现。

    Returns:
        只负责组织术语上下文的翻译 skill。
    """

    def build_request(self, context: SkillContext) -> TranslationAdapterRequest:
        """构造外部翻译 adapter 请求。

        Args:
            context: Skill 调用上下文,从状态快照和领域规则读取翻译参数。

        Returns:
            外部翻译 adapter 请求对象。
        """
        return TranslationAdapterRequest(
            text=str(context.state_snapshot.get("text", "")),
            source_language=str(context.state_snapshot.get("source_language", "zh")),
            target_language=str(context.state_snapshot.get("target_language", "en")),
            terms=context.domain_rules.get("terms", {}),
        )
