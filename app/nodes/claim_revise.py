import re

from pydantic import ValidationError

from app.models.schemas import ClaimPatch, NodeResult, SkillContext, WorkflowState
from app.orchestrator.node_base import Node
from app.skills.claim_writing import ClaimWritingSkill


class ClaimReviseNode(Node):
    """单条权利要求修改节点。

    Args:
        skill: 权利要求撰写 skill。

    Returns:
        复用 claim_writing skill 生成结构化 patch 的节点。
    """

    name = "claim_revise"

    def __init__(self, skill: ClaimWritingSkill | None = None) -> None:
        super().__init__(name=self.name)
        self.skill = skill or ClaimWritingSkill()

    def run(self, state: WorkflowState) -> NodeResult:
        """修改目标权利要求并记录 patch。

        Args:
            state: 当前工作流状态。

        Returns:
            修改成功结果或失败结果。
        """
        target_claim_number = self._parse_target_claim_number(state.user_feedback or "")
        target_claim = self._find_claim(state, target_claim_number)
        if target_claim is None:
            return NodeResult.failed(errors=[f"target_claim_not_found:{target_claim_number}"])

        context = SkillContext(
            task_type="claim_revise",
            state_snapshot={"claims_draft": state.claims_draft, "user_feedback": state.user_feedback},
        )
        try:
            revised_claim_set = self.skill.run(context)
        except ValidationError:
            return NodeResult.failed(errors=["claim_revise_failed"])

        revised_claim = next(
            (claim for claim in revised_claim_set.claims if claim.number == target_claim_number),
            None,
        )
        if revised_claim is None:
            return NodeResult.failed(errors=[f"target_claim_not_found:{target_claim_number}"])

        before_text = str(target_claim["text"])
        after_claim = revised_claim.model_dump()
        target_claim.update(after_claim)
        impact_scope = self._impact_scope(state, target_claim_number)
        risk_notes = ["linked_claims_may_need_review"] if len(impact_scope) > 1 else []
        patch = ClaimPatch(
            target_claim_number=target_claim_number,
            operation="revise",
            before_text=before_text,
            after_text=revised_claim.text,
            impact_scope=impact_scope,
            risk_notes=risk_notes,
        )
        state.claim_patches.append(patch.model_dump())
        state.claim_versions.append({"version": revised_claim_set.version, "claims": state.claims_draft})
        return NodeResult.success(
            output={"claim_patch": patch.model_dump()},
            trace_events=[{"event": "claim_revise_completed"}],
        )

    def _parse_target_claim_number(self, feedback: str) -> int:
        """从用户反馈中提取目标权利要求编号。

        Args:
            feedback: 用户修改意见。

        Returns:
            目标权利要求编号,未显式指定时默认返回 1。
        """
        match = re.search(r"权利要求\s*(\d+)", feedback)
        return int(match.group(1)) if match else 1

    def _find_claim(self, state: WorkflowState, claim_number: int) -> dict | None:
        """查找目标权利要求草稿。

        Args:
            state: 当前工作流状态。
            claim_number: 目标权利要求编号。

        Returns:
            找到的权利要求字典,不存在时返回 None。
        """
        return next((claim for claim in state.claims_draft if claim.get("number") == claim_number), None)

    def _impact_scope(self, state: WorkflowState, claim_number: int) -> list[int]:
        """计算修改目标权利要求的影响范围。

        Args:
            state: 当前工作流状态。
            claim_number: 目标权利要求编号。

        Returns:
            目标权利要求及直接引用它的权利要求编号列表。
        """
        impacted = [claim_number]
        impacted.extend(
            claim["number"]
            for claim in state.claims_draft
            if claim_number in claim.get("references", []) and claim.get("number") != claim_number
        )
        return impacted
