from app.models.schemas import ClaimSet, NodeResult, ValidationReport, WorkflowState
from app.orchestrator.node_base import Node
from app.tools.validators import validate_claim_references, validate_terminology_consistency


class ClaimCheckNode(Node):
    """权利要求基础校验节点。

    Returns:
        调用 validators 并写入 validation_report 的节点。
    """

    name = "claim_check"

    def run(self, state: WorkflowState) -> NodeResult:
        """校验当前权利要求草稿。

        Args:
            state: 当前工作流状态。

        Returns:
            包含 validation_report 的成功结果。
        """
        claim_set = ClaimSet(version="current", claims=state.claims_draft)
        reference_errors = validate_claim_references(claim_set)
        terminology_errors = validate_terminology_consistency(self._extract_terms_by_claim(claim_set))
        report = ValidationReport(
            passed=not reference_errors and not terminology_errors,
            reference_errors=reference_errors,
            terminology_errors=terminology_errors,
        )
        state.validation_report = report.model_dump()
        return NodeResult.success(
            output={"validation_report": state.validation_report},
            trace_events=[{"event": "claim_check_completed"}],
        )

    def _extract_terms_by_claim(self, claim_set: ClaimSet) -> dict[int, dict[str, str]]:
        """从权利要求 terms 字段提取术语映射。

        Args:
            claim_set: 待提取术语的权利要求集合。

        Returns:
            按权利要求编号组织的术语映射。
        """
        terms_by_claim: dict[int, dict[str, str]] = {}
        for claim in claim_set.claims:
            terms: dict[str, str] = {}
            for term in claim.terms:
                if "=" in term:
                    raw_term, normalized_value = term.split("=", maxsplit=1)
                    terms[raw_term] = normalized_value
            terms_by_claim[claim.number] = terms
        return terms_by_claim
