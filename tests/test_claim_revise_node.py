from app.models.schemas import WorkflowState
from app.nodes.claim_revise import ClaimReviseNode
from app.skills.claim_writing import ClaimWritingSkill


def test_claim_revise_node_updates_target_claim() -> None:
    """权利要求修改 node 默认应只修改目标权利要求并输出 patch。"""
    skill = ClaimWritingSkill(
        fake_outputs={
            "claim_revise": {
                "version": "v2",
                "claims": [{"number": 1, "claim_type": "independent", "text": "一种改进的控制方法。"}],
            }
        }
    )
    state = WorkflowState(
        raw_input="",
        user_feedback="修改权利要求1",
        claims_draft=[{"number": 1, "claim_type": "independent", "text": "一种控制方法。"}],
    )
    node = ClaimReviseNode(skill=skill)

    result = node.run(state)

    assert result.status == "success"
    assert state.claims_draft[0]["text"] == "一种改进的控制方法。"
    assert state.claim_patches == [
        {
            "target_claim_number": 1,
            "operation": "revise",
            "before_text": "一种控制方法。",
            "after_text": "一种改进的控制方法。",
            "impact_scope": [1],
            "risk_notes": [],
        }
    ]


def test_claim_revise_node_fails_when_target_missing() -> None:
    """权利要求修改 node 目标权利要求不存在时应失败。"""
    node = ClaimReviseNode(skill=ClaimWritingSkill())
    state = WorkflowState(raw_input="", user_feedback="修改权利要求2", claims_draft=[])

    result = node.run(state)

    assert result.status == "failed"
    assert result.errors == ["target_claim_not_found:2"]


def test_claim_revise_node_marks_linked_impact_scope() -> None:
    """权利要求修改 node 应提示从属权利要求联动影响范围。"""
    skill = ClaimWritingSkill(
        fake_outputs={
            "claim_revise": {
                "version": "v2",
                "claims": [{"number": 1, "claim_type": "independent", "text": "一种改进的控制方法。"}],
            }
        }
    )
    state = WorkflowState(
        raw_input="",
        user_feedback="修改权利要求1",
        claims_draft=[
            {"number": 1, "claim_type": "independent", "text": "一种控制方法。"},
            {"number": 2, "claim_type": "dependent", "text": "根据权利要求1所述的方法。", "references": [1]},
        ],
    )
    node = ClaimReviseNode(skill=skill)

    result = node.run(state)

    assert result.status == "success"
    assert state.claim_patches[0]["impact_scope"] == [1, 2]
    assert state.claim_patches[0]["risk_notes"] == ["linked_claims_may_need_review"]
