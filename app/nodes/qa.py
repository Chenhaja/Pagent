from pydantic import ValidationError

from app.models.schemas import NodeResult, SkillContext, WorkflowState
from app.orchestrator.node_base import Node
from app.skills.patent_qa import PatentQASkill


class QANode(Node):
    """专利问答节点。

    Args:
        skill: 专利问答 skill。

    Returns:
        调用 patent_qa skill 并写入结构化答案的节点。
    """

    name = "qa"

    def __init__(self, skill: PatentQASkill | None = None) -> None:
        super().__init__(name=self.name)
        self.skill = skill or PatentQASkill()

    def run(self, state: WorkflowState) -> NodeResult:
        """生成专利问答结果。

        Args:
            state: 当前 workflow 状态。

        Returns:
            成功时返回 qa_result;skill 输出无效时返回结构化失败。
        """
        context = SkillContext(
            task_type="patent_qa",
            state_snapshot={
                "question": state.normalized_input or state.raw_input,
                "claims_draft": state.claims_draft,
                "validation_report": state.validation_report,
            },
        )
        try:
            qa_result = self.skill.run(context)
        except (ValueError, ValidationError):
            return NodeResult.failed(errors=["qa_failed"])

        output = qa_result.model_dump()
        state.dialog_context["qa_result"] = output
        return NodeResult.success(
            output={"qa_result": output},
            trace_events=[{"event": "qa_completed"}],
        )
