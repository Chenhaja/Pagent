import pytest
from pydantic import ValidationError

from app.models.schemas import PatentQAResult, SkillContext
from app.skills.patent_qa import PatentQASkill
from app.tools.llm import FakeLLMClient


def test_patent_qa_skill_returns_structured_answer_with_prompt_layers() -> None:
    """patent_qa skill 应通过 LLM 抽象返回结构化问答结果。"""
    skill = PatentQASkill(
        llm_client=FakeLLMClient(
            response={
                "answer": "该方案的主要风险是技术效果描述不足。",
                "basis": ["用户问题涉及权利要求风险"],
                "risk_notes": ["需由专利代理师复核"],
                "next_steps": ["补充技术效果和实施例"],
                "disclaimer_hint": "辅助问答，不等同于专利代理师法律意见。",
            }
        )
    )
    context = SkillContext(task_type="patent_qa", state_snapshot={"question": "这个权利要求有什么风险？"})

    result = skill.run(context)

    assert result.answer == "该方案的主要风险是技术效果描述不足。"
    assert result.basis == ["用户问题涉及权利要求风险"]
    assert result.risk_notes == ["需由专利代理师复核"]
    assert result.next_steps == ["补充技术效果和实施例"]
    assert result.disclaimer_hint == "辅助问答，不等同于专利代理师法律意见。"
    assert "system" in context.prompt_layers
    assert context.safety_policy == {"separate_instruction_and_data": True}


def test_patent_qa_skill_rejects_invalid_llm_output() -> None:
    """patent_qa skill 应拒绝不符合 QA schema 的 LLM 输出。"""
    skill = PatentQASkill(llm_client=FakeLLMClient(response={"answer": "缺少字段"}))
    context = SkillContext(task_type="patent_qa", state_snapshot={"question": "这个权利要求有什么风险？"})

    with pytest.raises(ValidationError):
        skill.run(context)


def test_patent_qa_result_requires_disclaimer_hint() -> None:
    """QA schema 应要求法律意见免责声明提示。"""
    with pytest.raises(ValidationError):
        PatentQAResult(answer="答复", basis=[], risk_notes=[], next_steps=[])
