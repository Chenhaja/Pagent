from typing import Any

from app.models.schemas import ClaimSet


def validate_claim_references(claim_set: ClaimSet) -> list[str]:
    """校验权利要求引用关系。

    Args:
        claim_set: 待校验的权利要求集合。

    Returns:
        引用不存在或引用顺序异常的错误列表。
    """
    claim_numbers = {claim.number for claim in claim_set.claims}
    errors: list[str] = []
    for claim in claim_set.claims:
        for reference in claim.references:
            if reference not in claim_numbers:
                errors.append(f"claim_{claim.number}_references_missing_claim_{reference}")
            elif reference >= claim.number:
                errors.append(f"claim_{claim.number}_references_later_claim_{reference}")
    return errors


def validate_terminology_consistency(terms_by_claim: dict[int, dict[str, str]]) -> list[str]:
    """校验不同权利要求中的术语表达是否一致。

    Args:
        terms_by_claim: 按权利要求编号组织的术语规范表达。

    Returns:
        同一术语存在多个规范表达时的错误列表。
    """
    first_seen: dict[str, tuple[int, str]] = {}
    errors: list[str] = []
    for claim_number, terms in terms_by_claim.items():
        for term, normalized_value in terms.items():
            previous = first_seen.get(term)
            if previous is None:
                first_seen[term] = (claim_number, normalized_value)
            elif previous[1] != normalized_value:
                errors.append(
                    f"term_conflict:{term}:claim_{previous[0]}={previous[1]},"
                    f"claim_{claim_number}={normalized_value}"
                )
    return errors


def validate_required_fields(payload: dict[str, Any], required_fields: list[str]) -> list[str]:
    """校验结构化载荷的基础必填字段。

    Args:
        payload: 待校验的结构化载荷。
        required_fields: 必须存在且非空的字段名列表。

    Returns:
        缺失或为空的字段错误列表。
    """
    errors: list[str] = []
    for field_name in required_fields:
        value = payload.get(field_name)
        if value is None or value == "" or value == [] or value == {}:
            errors.append(f"missing_required_field:{field_name}")
    return errors
