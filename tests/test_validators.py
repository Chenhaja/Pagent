from app.models.schemas import Claim, ClaimSet
from app.tools.validators import (
    validate_claim_references,
    validate_required_fields,
    validate_terminology_consistency,
)


def test_validate_claim_references_reports_missing_reference() -> None:
    """引用关系校验应发现不存在的被引用权利要求。"""
    claim_set = ClaimSet(
        version="v1",
        claims=[
            Claim(number=1, claim_type="independent", text="一种控制方法。"),
            Claim(number=2, claim_type="dependent", text="根据权利要求3所述的方法。", references=[3]),
        ],
    )

    errors = validate_claim_references(claim_set)

    assert errors == ["claim_2_references_missing_claim_3"]


def test_validate_terminology_consistency_reports_conflict() -> None:
    """术语一致性校验应发现同一术语的不同规范表达。"""
    errors = validate_terminology_consistency(
        terms_by_claim={
            1: {"传感器": "sensor"},
            2: {"传感器": "sensing unit"},
        }
    )

    assert errors == ["term_conflict:传感器:claim_1=sensor,claim_2=sensing unit"]


def test_validate_required_fields_reports_missing_values() -> None:
    """基础字段完整性校验应发现缺失字段。"""
    errors = validate_required_fields(
        payload={"raw_input": "一种控制方法", "technical_features": []},
        required_fields=["raw_input", "technical_features", "claim_plan"],
    )

    assert errors == ["missing_required_field:technical_features", "missing_required_field:claim_plan"]
