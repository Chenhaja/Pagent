from typing import Any

from pydantic import ValidationError

from app.core.config import get_settings
from app.models.schemas import NodeResult, SkillContext, WorkflowState
from app.orchestrator.node_base import Node
from app.skills.patent_qa import PatentQASkill
from app.tools.retrieval import Retriever, RetrievalResult, build_retriever


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
        retrieval_tool: Retriever | None = None,
        max_steps: int = 1,
        token_budget: int = 1000,
        timeout_seconds: int = 10,
        top_k: int | None = None,
    ) -> None:
        super().__init__(name=self.name)
        settings = get_settings()
        self.skill = skill or PatentQASkill()
        self.retrieval_tool = retrieval_tool or build_retriever(settings)
        self.max_steps = max_steps
        self.token_budget = token_budget
        self.timeout_seconds = timeout_seconds
        self.top_k = top_k or settings.retrieval_top_k

    def run(self, state: WorkflowState) -> NodeResult:
        """生成专利问答结果。

        Args:
            state: 当前 workflow 状态。

        Returns:
            成功时返回 qa_result;skill 输出无效时返回结构化失败。
        """
        question = state.normalized_input or state.raw_input
        retrieval_results = self._retrieve(question)
        evidence = self._build_evidence(retrieval_results)
        state.dialog_context["qa_retrieval_results"] = evidence
        context = SkillContext(
            task_type="patent_qa",
            state_snapshot={
                "question": question,
                "claims_draft": state.claims_draft,
                "validation_report": state.validation_report,
                "retrieval_results": evidence,
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
                {
                    "event": "qa_completed",
                    "data": {"basis_count": len(qa_result.basis), "has_retrieval": bool(retrieval_results)},
                },
            ],
        )

    def _retrieve(self, question: str) -> list[RetrievalResult]:
        """在步数预算内执行本地检索。"""
        if self.max_steps <= 0 or self.token_budget <= 0 or self.timeout_seconds <= 0:
            return []
        try:
            return self.retrieval_tool.search(question, top_k=self.top_k)[: self.top_k]
        except Exception:
            return []

    def _build_evidence(self, retrieval_results: list[RetrievalResult]) -> list[dict[str, Any]]:
        """将检索结果转换为传给 skill 的受限 evidence。"""
        evidence = []
        for result in retrieval_results[:3]:
            provenance = {
                "source": result.provenance.get("source", "local://unknown"),
                "document_id": result.provenance.get("document_id", "unknown"),
            }
            for key in ("doc_type", "locator"):
                if result.provenance.get(key):
                    provenance[key] = result.provenance[key]
            evidence.append(
                {
                    "content": result.content[:1000],
                    "provenance": provenance,
                    "score": result.score,
                    "similarity": result.similarity,
                }
            )
        return evidence
