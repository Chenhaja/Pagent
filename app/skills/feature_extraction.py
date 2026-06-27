from pydantic import BaseModel, Field

from app.models.schemas import SkillContext


class FeatureExtractionResult(BaseModel):
    """技术特征提取结果。

    Args:
        required_features: 必要技术特征列表。
        optional_features: 附加技术特征列表。

    Returns:
        结构化技术特征集合。
    """

    required_features: list[str]
    optional_features: list[str] = Field(default_factory=list)


class FeatureExtractionSkill:
    """技术特征提取 skill 占位实现。

    Args:
        fake_output: 固定技术特征输出,用于测试 node 与 skill 边界。

    Returns:
        可替代真实特征提取 prompt 的 fake skill。
    """

    def __init__(self, fake_output: dict[str, list[str]] | None = None) -> None:
        self.fake_output = fake_output or {"required_features": [], "optional_features": []}

    def run(self, context: SkillContext) -> FeatureExtractionResult:
        """返回结构化技术特征。

        Args:
            context: Skill 调用上下文,保留与后续真实 skill 一致的接口。

        Returns:
            解析后的技术特征提取结果。

        Raises:
            pydantic.ValidationError: 当固定输出不符合 FeatureExtractionResult schema 时抛出。
        """
        return FeatureExtractionResult.model_validate(self.fake_output)
