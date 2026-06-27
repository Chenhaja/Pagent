import pytest
from pydantic import ValidationError

from app.models.schemas import SkillContext
from app.skills.feature_extraction import FeatureExtractionResult, FeatureExtractionSkill
from app.tools.llm import FakeLLMClient


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


def test_feature_extraction_skill_calls_llm_with_layered_prompt() -> None:
    """技术特征提取 skill 应构造分层 prompt 并调用 LLM 抽象。"""
    llm_client = FakeLLMClient(
        response={
            "required_features": ["采集传感器数据"],
            "optional_features": ["过滤异常数据"],
        }
    )
    skill = FeatureExtractionSkill(llm_client=llm_client)
    context = SkillContext(
        task_type="feature_extract",
        state_snapshot={"normalized_input": "一种根据传感器数据生成控制指令的方法"},
    )

    result = skill.run(context)

    assert result.required_features == ["采集传感器数据"]
    assert result.optional_features == ["过滤异常数据"]
    assert skill.last_prompt_layers["system"].startswith("你是专利技术特征抽取助手")
    assert "normalized_input" in skill.last_prompt_layers["user_data"]
    assert skill.last_safety_policy["separate_instruction_and_data"] is True


def test_feature_extraction_skill_raises_value_error_on_llm_error() -> None:
    """LLM 返回结构化错误时 skill 应抛出可由 node 捕获的 ValueError。"""
    skill = FeatureExtractionSkill(llm_client=FakeLLMClient(error="empty_response"))

    with pytest.raises(ValueError, match="empty_response"):
        skill.run(SkillContext(task_type="feature_extract"))
