from app.models.schemas import WorkflowState
from app.nodes.claim_check import ClaimCheckNode


def test_claim_check_node_passes_valid_claim_set() -> None:
    """权利要求校验 node 应对合法 claim set 返回通过报告。"""
    state = WorkflowState(
        raw_input="",
        claims_draft=[
            {"number": 1, "claim_type": "independent", "text": "一种控制方法。"},
            {"number": 2, "claim_type": "dependent", "text": "根据权利要求1所述的方法。", "references": [1]},
        ],
    )
    node = ClaimCheckNode()

    result = node.run(state)

    assert result.status == "success"
    assert state.validation_report == {
        "passed": True,
        "reference_errors": [],
        "terminology_errors": [],
        "missing_required_features": [],
        "clarity_warnings": [],
        "risk_notes": [],
    }


def test_claim_check_node_reports_invalid_reference() -> None:
    """权利要求校验 node 应报告非法引用。"""
    state = WorkflowState(
        raw_input="",
        claims_draft=[
            {"number": 1, "claim_type": "independent", "text": "一种控制方法。"},
            {"number": 2, "claim_type": "dependent", "text": "根据权利要求3所述的方法。", "references": [3]},
        ],
    )
    node = ClaimCheckNode()

    result = node.run(state)

    assert result.status == "success"
    assert state.validation_report["passed"] is False
    assert state.validation_report["reference_errors"] == ["claim_2_references_missing_claim_3"]


def test_claim_check_node_reports_terminology_conflict() -> None:
    """权利要求校验 node 应报告术语不一致。"""
    state = WorkflowState(
        raw_input="",
        claims_draft=[
            {"number": 1, "claim_type": "independent", "text": "一种控制方法。", "terms": ["传感器=sensor"]},
            {"number": 2, "claim_type": "dependent", "text": "根据权利要求1所述的方法。", "terms": ["传感器=sensing unit"]},
        ],
    )
    node = ClaimCheckNode()

    result = node.run(state)

    assert result.status == "success"
    assert state.validation_report["passed"] is False
    assert state.validation_report["terminology_errors"] == [
        "term_conflict:传感器:claim_1=sensor,claim_2=sensing unit"
    ]
