import pytest
from pydantic import ValidationError

from app.models.schemas import SkillContext
from app.skills.feature_extraction import FeatureExtractionResult, FeatureExtractionSkill


def test_feature_extraction_skill_returns_structured_features() -> None:
    """技术特征提取 skill 应返回必要特征和附加特征。"""
    skill = FeatureExtractionSkill(
        fake_output={
            "required_features": ["采集传感器数据", "生成控制指令"],
            "optional_features": ["过滤异常数据"],
        }
    )

    result = skill.run(SkillContext(task_type="feature_extract"))

    assert isinstance(result, FeatureExtractionResult)
    assert result.required_features == ["采集传感器数据", "生成控制指令"]
    assert result.optional_features == ["过滤异常数据"]


def test_feature_extraction_skill_rejects_invalid_fake_output() -> None:
    """技术特征提取 skill 应拒绝缺少必要特征字段的输出。"""
    skill = FeatureExtractionSkill(fake_output={"optional_features": ["过滤异常数据"]})

    with pytest.raises(ValidationError):
        skill.run(SkillContext(task_type="feature_extract"))
