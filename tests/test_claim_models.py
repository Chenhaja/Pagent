import pytest
from pydantic import ValidationError

from app.models.schemas import Claim, ClaimPatch, ClaimSet, ValidationReport


def test_claim_models_represent_claim_set_and_versions() -> None:
    """权利要求模型应表达草稿、引用关系和版本信息。"""
    independent = Claim(number=1, claim_type="independent", text="一种节能控制方法。")
    dependent = Claim(
        number=2,
        claim_type="dependent",
        text="根据权利要求1所述的方法。",
        references=[1],
        terms=["节能控制"],
    )

    claim_set = ClaimSet(version="v1", claims=[independent, dependent])

    assert claim_set.version == "v1"
    assert claim_set.claims[1].references == [1]
    assert claim_set.claims[1].terms == ["节能控制"]


def test_claim_patch_represents_revision_result() -> None:
    """ClaimPatch 应表达单条权利要求修改前后和影响范围。"""
    patch = ClaimPatch(
        target_claim_number=2,
        operation="replace_text",
        before_text="根据权利要求1所述的方法。",
        after_text="根据权利要求1所述的节能控制方法。",
        impact_scope=[2],
        risk_notes=["术语范围变窄"],
    )

    assert patch.target_claim_number == 2
    assert patch.impact_scope == [2]
    assert patch.risk_notes == ["术语范围变窄"]


def test_validation_report_represents_check_results() -> None:
    """ValidationReport 应表达基础校验结果和风险提示。"""
    report = ValidationReport(
        passed=False,
        reference_errors=["权利要求3引用不存在"],
        terminology_errors=["术语不一致"],
        missing_required_features=["控制阈值"],
        clarity_warnings=["表述过宽"],
        risk_notes=["需要人工复核"],
    )

    assert report.passed is False
    assert report.reference_errors == ["权利要求3引用不存在"]
    assert report.risk_notes == ["需要人工复核"]


def test_claim_requires_positive_number_and_non_empty_text() -> None:
    """Claim 应拒绝无效编号和空文本。"""
    with pytest.raises(ValidationError):
        Claim(number=0, claim_type="independent", text="一种方法。")

    with pytest.raises(ValidationError):
        Claim(number=1, claim_type="independent", text="")
