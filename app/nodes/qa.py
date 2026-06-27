from pydantic import ValidationError

from app.models.schemas import NodeResult, SkillContext, WorkflowState
from app.orchestrator.node_base import Node
from app.skills.patent_qa import PatentQASkill
from app.tools.retrieval import LocalRetrievalTool


class QANode(Node):
    """专利问答节点。

    Args:
        skill: 专利问答 skill。

    Returns:
        调用 patent_qa skill 并写入结构化答案的节点。
    """

    name = "qa"

    def __init__(
        self,
        skill: PatentQASkill | None = None,
        retrieval_tool: LocalRetrievalTool | None = None,
        max_steps: int = 1,
        token_budget: int = 1000,
        timeout_seconds: int = 10,
    ) -> None:
        super().__init__(name=self.name)
        self.skill = skill or PatentQASkill()
        self.retrieval_tool = retrieval_tool or LocalRetrievalTool()
        self.max_steps = max_steps
        self.token_budget = token_budget
        self.timeout_seconds = timeout_seconds

    def run(self, state: WorkflowState) -> NodeResult:
        """生成专利问答结果。

        Args:
            state: 当前 workflow 状态。

        Returns:
            成功时返回 qa_result;skill 输出无效时返回结构化失败。
        """
        question = state.normalized_input or state.raw_input
        retrieval_results = self._retrieve(question)
        state.dialog_context["qa_retrieval_results"] = [result.model_dump() for result in retrieval_results]
        context = SkillContext(
            task_type="patent_qa",
            state_snapshot={
                "question": question,
                "claims_draft": state.claims_draft,
                "validation_report": state.validation_report,
                "retrieval_results": state.dialog_context["qa_retrieval_results"],
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
            trace_events=[
                {
                    "event": "qa_retrieval_completed",
                    "data": {
                        "steps_used": 1 if retrieval_results else 0,
                        "result_count": len(retrieval_results),
                        "token_budget": self.token_budget,
                        "timeout_seconds": self.timeout_seconds,
                    },
                },
                {"event": "qa_completed"},
            ],
        )

    def _retrieve(self, question: str) -> list:
        """在步数预算内执行本地检索。"""
        if self.max_steps <= 0 or self.token_budget <= 0 or self.timeout_seconds <= 0:
            return []
        return self.retrieval_tool.search(question, top_k=3)
