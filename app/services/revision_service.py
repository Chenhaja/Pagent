from typing import Any

from app.models.schemas import WorkflowState
from app.nodes.claim_check import ClaimCheckNode
from app.nodes.claim_revise import ClaimReviseNode
from app.orchestrator.engine import Orchestrator
from app.orchestrator.workflow_defs import WorkflowRegistry
from app.skills.claim_writing import ClaimWritingSkill


class RevisionService:
    """单条权利要求修改 workflow 服务。

    Returns:
        封装 claim_revise 和 claim_check 链路的服务。
    """

    def __init__(self) -> None:
        self.orchestrator = Orchestrator(
            nodes={
                "claim_revise": ClaimReviseNode(
                    skill=ClaimWritingSkill(
                        fake_outputs={
                            "claim_revise": {
                                "version": "v2",
                                "claims": [
                                    {"number": 1, "claim_type": "independent", "text": "一种改进的控制方法。"}
                                ],
                            }
                        }
                    )
                ),
                "claim_check": ClaimCheckNode(),
            }
        )
        self.workflow_def = WorkflowRegistry().get_workflow("claim_revision")

    def revise_claim(self, claims_draft: list[dict[str, Any]], user_feedback: str) -> dict[str, Any]:
        """修改单条权利要求。

        Args:
            claims_draft: 当前权利要求草稿。
            user_feedback: 用户修改意见。

        Returns:
            成功时返回修改后 claim、patch、风险提示和版本号;失败时返回结构化错误。
        """
        state = WorkflowState(raw_input="", claims_draft=claims_draft, user_feedback=user_feedback)
        result = self.orchestrator.run(state, self.workflow_def)
        if result.status != "success":
            return {
                "status": result.status,
                "errors": result.errors,
                "message": "未找到要修改的权利要求。",
            }

        patch = state.claim_patches[-1]
        target_claim = next(claim for claim in state.claims_draft if claim["number"] == patch["target_claim_number"])
        return {
            "status": "success",
            "claim": target_claim,
            "patch": patch,
            "risk_notes": patch["risk_notes"],
            "version": state.claim_versions[-1]["version"],
            "validation_report": state.validation_report,
        }
