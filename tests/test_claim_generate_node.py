from app.models.schemas import WorkflowState
from app.nodes.claim_generate import ClaimGenerateNode
from app.skills.claim_writing import ClaimWritingSkill


def test_claim_generate_node_writes_claims_draft() -> None:
    """权利要求生成 node 应调用 claim_writing skill 并写入草稿。"""
    skill = ClaimWritingSkill(
        fake_outputs={
            "claim_generate": {
                "version": "v1",
                "claims": [
                    {"number": 1, "claim_type": "independent", "text": "一种控制方法。"},
                ],
            }
        }
    )
    state = WorkflowState(raw_input="", claim_plan={"claims": [{"number": 1}]})
    node = ClaimGenerateNode(skill=skill)

    result = node.run(state)

    assert result.status == "success"
    assert state.claims_draft == [
        {
            "number": 1,
            "claim_type": "independent",
            "text": "一种控制方法。",
            "references": [],
            "terms": [],
            "source_trace": [],
        }
    ]
    assert state.claim_versions == [{"version": "v1", "claims": state.claims_draft}]


def test_claim_generate_node_returns_failed_when_schema_invalid() -> None:
    """权利要求生成 node 应在 skill 输出 schema 错误时失败。"""
    skill = ClaimWritingSkill(fake_outputs={"claim_generate": {"version": "v1", "claims": [{"number": 1}]}})
    state = WorkflowState(raw_input="", claim_plan={"claims": [{"number": 1}]})
    node = ClaimGenerateNode(skill=skill)

    result = node.run(state)

    assert result.status == "failed"
    assert result.errors == ["claim_generate_failed"]
