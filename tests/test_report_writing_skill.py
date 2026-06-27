import pytest

from app.models.schemas import SkillContext
from app.skills.report_writing import ReportWritingSkill


def test_report_writing_skill_builds_report_from_required_inputs() -> None:
    """报告撰写 skill 应复用技术特征、权利要求和校验报告生成摘要。"""
    skill = ReportWritingSkill()
    context = SkillContext(
        task_type="report_write",
        state_snapshot={
            "technical_features": [{"name": "采集传感器数据"}],
            "claims_draft": [{"number": 1, "text": "一种控制方法。"}],
            "validation_report": {"passed": True},
        },
    )

    result = skill.run(context)

    assert result["technical_features"] == [{"name": "采集传感器数据"}]
    assert result["claims_draft"] == [{"number": 1, "text": "一种控制方法。"}]
    assert result["validation_report"] == {"passed": True}


def test_report_writing_skill_reports_missing_required_input() -> None:
    """报告撰写 skill 缺少关键输入时应返回明确错误。"""
    skill = ReportWritingSkill()
    context = SkillContext(
        task_type="report_write",
        state_snapshot={
            "technical_features": [{"name": "采集传感器数据"}],
            "claims_draft": [],
        },
    )

    with pytest.raises(ValueError, match="missing_report_input:claims_draft,validation_report"):
        skill.run(context)
