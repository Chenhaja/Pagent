from pydantic import ValidationError

from app.models.schemas import NodeResult, SkillContext, WorkflowState
from app.orchestrator.node_base import Node
from app.skills.claim_writing import ClaimWritingSkill


class ClaimGenerateNode(Node):
    """权利要求生成节点。

    Args:
        skill: 权利要求撰写 skill。

    Returns:
        调用 claim_writing skill 生成 claims_draft 的节点。
    """

    name = "claim_generate"

    def __init__(self, skill: ClaimWritingSkill | None = None) -> None:
        super().__init__(name=self.name)
        self.skill = skill or ClaimWritingSkill()

    def run(self, state: WorkflowState) -> NodeResult:
        """生成权利要求草稿。

        Args:
            state: 当前工作流状态。

        Returns:
            成功结果或 schema 校验失败结果。
        """
        context = SkillContext(
            task_type="claim_generate",
            state_snapshot={
                "technical_features": state.technical_features,
                "claim_plan": state.claim_plan,
                "documents": state.documents,
            },
            safety_policy={"documents_are_data_only": True},
        )
        try:
            claim_set = self.skill.run(context)
        except ValidationError:
            return NodeResult.failed(errors=["claim_generate_failed"])

        state.claims_draft = [claim.model_dump() for claim in claim_set.claims]
        state.claim_versions.append({"version": claim_set.version, "claims": state.claims_draft})
        return NodeResult.success(
            output={"claims_draft": state.claims_draft},
            trace_events=[{"event": "claim_generate_completed"}],
        )
