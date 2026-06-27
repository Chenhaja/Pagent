import pytest
from pydantic import ValidationError

from app.models.schemas import ClaimSet, SkillContext
from app.skills.claim_writing import ClaimWritingSkill


def test_claim_writing_skill_generates_claim_set_from_fake_output() -> None:
    """权利要求撰写 skill 应支持生成任务并返回权利要求集合。"""
    skill = ClaimWritingSkill(
        fake_outputs={
            "claim_generate": {
                "version": "v1",
                "claims": [
                    {
                        "number": 1,
                        "claim_type": "independent",
                        "text": "一种控制方法。",
                        "references": [],
                        "terms": ["控制方法"],
                    }
                ],
            }
        }
    )
    context = SkillContext(task_type="claim_generate")

    result = skill.run(context)

    assert isinstance(result, ClaimSet)
    assert result.version == "v1"
    assert result.claims[0].text == "一种控制方法。"


def test_claim_writing_skill_revises_claim_set_from_fake_output() -> None:
    """权利要求撰写 skill 应支持修改任务并复用相同输出 schema。"""
    skill = ClaimWritingSkill(
        fake_outputs={
            "claim_revise": {
                "version": "v2",
                "claims": [
                    {
                        "number": 1,
                        "claim_type": "independent",
                        "text": "一种改进的控制方法。",
                    }
                ],
            }
        }
    )
    context = SkillContext(task_type="claim_revise")

    result = skill.run(context)

    assert result.version == "v2"
    assert result.claims[0].text == "一种改进的控制方法。"


def test_claim_writing_skill_rejects_invalid_fake_output() -> None:
    """权利要求撰写 skill 应拒绝不符合权利要求 schema 的输出。"""
    skill = ClaimWritingSkill(fake_outputs={"claim_generate": {"version": "v1", "claims": [{"number": 1}]}})

    with pytest.raises(ValidationError):
        skill.run(SkillContext(task_type="claim_generate"))
