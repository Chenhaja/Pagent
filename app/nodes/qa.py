import time
from datetime import date
from typing import Any

from pydantic import ValidationError

from app.core.config import get_settings
from app.models.schemas import NodeResult, SkillContext, WorkflowState
from app.orchestrator.node_base import Node
from app.skills.patent_qa import PatentQASkill
from app.tools.retrieval import QueryRewriter, Retriever, RetrievalResult, build_retriever


INSUFFICIENT_EVIDENCE_WARNING = "依据可能不足，建议补充材料或核对官方来源"


class QANode(Node):
    """专利问答节点。

    Args:
        skill: 专利问答 skill。
        retrieval_tool: 可注入检索工具。
        max_steps: QA 内部检索最大轮数。
        token_budget: QA evidence token 预算。
        timeout_seconds: QA 检索循环超时时间。
        top_k: 每轮检索结果数量。
        react_min_results: 判定 evidence 充分的最少结果数。
        react_min_score: 判定 evidence 充分的最低分数。
        react_use_llm_judge: 是否启用 LLM evidence 充分性评估。
        query_rewriter: 可注入查询改写器。

    Returns:
        调用 patent_qa skill 并写入结构化答案的节点。
    """

    name = "qa"

    def __init__(
        self,
        skill: PatentQASkill | None = None,
        retrieval_tool: Retriever | None = None,
        max_steps: int | None = None,
        token_budget: int | None = None,
        timeout_seconds: int | None = None,
        top_k: int | None = None,
        react_min_results: int | None = None,
        react_min_score: float | None = None,
        react_use_llm_judge: bool | None = None,
        query_rewriter: QueryRewriter | None = None,
    ) -> None:
        super().__init__(name=self.name)
        settings = get_settings()
        self.settings = settings
        self.skill = skill or PatentQASkill()
        self.retrieval_tool = retrieval_tool or build_retriever(settings)
        self.max_steps = settings.retrieval_max_steps if max_steps is None else max_steps
        self.token_budget = settings.retrieval_token_budget if token_budget is None else token_budget
        self.timeout_seconds = settings.retrieval_timeout_seconds if timeout_seconds is None else timeout_seconds
        self.top_k = settings.retrieval_top_k if top_k is None else top_k
        self.react_min_results = settings.retrieval_react_min_results if react_min_results is None else react_min_results
        self.react_min_score = settings.retrieval_react_min_score if react_min_score is None else react_min_score
        self.react_use_llm_judge = settings.retrieval_react_use_llm_judge if react_use_llm_judge is None else react_use_llm_judge
        self.query_rewriter = query_rewriter

    def run(self, state: WorkflowState) -> NodeResult:
        """生成专利问答结果。

        Args:
            state: 当前 workflow 状态。

        Returns:
            成功时返回 qa_result;skill 输出无效时返回结构化失败。
        """
        question = state.normalized_input or state.raw_input
        retrieval_results, react_trace_events, convergence = self._retrieve_loop(question)
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

        qa_result = self._apply_law_stale_warnings(qa_result, evidence)
        qa_result = self._apply_insufficient_evidence_warning(qa_result, convergence)
        output = qa_result.model_dump()
        state.dialog_context["qa_result"] = output
        return NodeResult.success(
            output={"qa_result": output},
            trace_events=[
                *react_trace_events,
                {
                    "event": "qa_retrieval_completed",
                    "data": {
                        "steps_used": convergence["steps_used"],
                        "result_count": len(retrieval_results),
                        "token_budget": self.token_budget,
                        "timeout_seconds": self.timeout_seconds,
                    },
                },
                {
                    "event": "qa_completed",
                    "data": {
                        "basis_count": len(qa_result.basis),
                        "has_retrieval": bool(retrieval_results),
                        "evidence_versions": self._build_evidence_versions(evidence),
                    },
                },
            ],
        )

    def _retrieve(self, question: str) -> list[RetrievalResult]:
        """执行单轮本地检索,异常时安全回退空结果。"""
        if self.max_steps <= 0 or self.token_budget <= 0 or self.timeout_seconds <= 0:
            return []
        try:
            return self.retrieval_tool.search(question, top_k=self.top_k)[: self.top_k]
        except Exception:
            return []

    def _retrieve_loop(self, question: str) -> tuple[list[RetrievalResult], list[dict[str, Any]], dict[str, Any]]:
        """执行 QA 节点内部受限 ReAct 检索循环。

        Args:
            question: 规范化后的用户问题。

        Returns:
            (累积检索结果, trace 事件, 收敛元数据)。
        """
        trace_events: list[dict[str, Any]] = []
        if self.max_steps <= 0:
            return [], self._build_converged_trace("max_steps", 0, 0, False), self._build_convergence("max_steps", 0, 0, False)
        if self.token_budget <= 0:
            return [], self._build_converged_trace("token_budget", 0, 0, False), self._build_convergence("token_budget", 0, 0, False)
        if self.timeout_seconds <= 0:
            return [], self._build_converged_trace("timeout", 0, 0, False), self._build_convergence("timeout", 0, 0, False)

        started_at = time.monotonic()
        deadline = started_at + self.timeout_seconds
        current_query = question
        accumulated: list[RetrievalResult] = []
        steps_used = 0
        reason = "max_steps"
        sufficient = False

        for step_index in range(self.max_steps):
            if time.monotonic() >= deadline:
                reason = "timeout"
                break
            new_results = self._retrieve(current_query)
            steps_used += 1
            accumulated = self._accumulate_results(accumulated, new_results)
            sufficient = self._is_evidence_sufficient(accumulated)
            trace_events.append(
                {
                    "event": "qa_react_step",
                    "data": {
                        "node_name": self.name,
                        "step_index": step_index,
                        "query_len": len(current_query),
                        "result_count": len(new_results),
                        "top_score": self._top_score(new_results),
                        "sufficient": sufficient,
                    },
                }
            )
            if sufficient:
                reason = "sufficient"
                break
            if time.monotonic() >= deadline:
                reason = "timeout"
                break
            if self._estimate_evidence_tokens(accumulated) >= self.token_budget:
                reason = "token_budget"
                break
            if step_index >= self.max_steps - 1:
                reason = "max_steps"
                break
            if time.monotonic() >= deadline:
                reason = "timeout"
                break
            current_query = self._rewrite_query(question, current_query, accumulated, step_index + 1)

        convergence = self._build_convergence(reason, steps_used, len(accumulated), sufficient)
        trace_events.extend(self._build_converged_trace(reason, steps_used, len(accumulated), sufficient))
        return accumulated, trace_events, convergence

    def _build_converged_trace(self, reason: str, steps_used: int, total_evidence: int, sufficient: bool) -> list[dict[str, Any]]:
        """构造 ReAct 收敛 trace 事件。"""
        return [
            {
                "event": "qa_react_converged",
                "data": {
                    "node_name": self.name,
                    "reason": reason,
                    "steps_used": steps_used,
                    "total_evidence": total_evidence,
                    "sufficient": sufficient,
                },
            }
        ]

    def _build_convergence(self, reason: str, steps_used: int, total_evidence: int, sufficient: bool) -> dict[str, Any]:
        """构造后续回答阶段使用的收敛元数据。"""
        return {"reason": reason, "steps_used": steps_used, "total_evidence": total_evidence, "sufficient": sufficient}

    def _get_result_score(self, result: RetrievalResult) -> float:
        """读取检索结果分数,优先使用非零 similarity。"""
        if result.similarity:
            return float(result.similarity)
        if result.score:
            return float(result.score)
        return 0.0

    def _top_score(self, results: list[RetrievalResult]) -> float:
        """返回当前结果集最高分数。"""
        if not results:
            return 0.0
        return max(self._get_result_score(result) for result in results)

    def _is_evidence_sufficient(self, results: list[RetrievalResult]) -> bool:
        """用启发式阈值判断 evidence 是否充分。"""
        if len(results) < self.react_min_results:
            return False
        return self._top_score(results) >= self.react_min_score

    def _rewrite_query(
        self,
        original_question: str,
        current_query: str,
        accumulated_results: list[RetrievalResult],
        step_index: int,
    ) -> str:
        """生成下一轮检索 query,失败时安全回退当前 query。

        Args:
            original_question: 原始问题。
            current_query: 当前检索 query。
            accumulated_results: 已累积 evidence。
            step_index: 即将执行的检索轮次。

        Returns:
            下一轮检索 query。
        """
        del original_question, accumulated_results, step_index
        if self.query_rewriter is None:
            return current_query
        try:
            queries = [item for item in self.query_rewriter.expand(current_query) if item.strip()]
        except Exception:
            return current_query
        return queries[0] if queries else current_query

    def _accumulate_results(self, existing: list[RetrievalResult], new_results: list[RetrievalResult]) -> list[RetrievalResult]:
        """累积并按来源去重检索结果,重复项保留高分版本。"""
        merged: dict[tuple[Any, ...], RetrievalResult] = {}
        for result in [*existing, *new_results]:
            key = self._result_key(result)
            current = merged.get(key)
            if current is None or self._get_result_score(result) > self._get_result_score(current):
                merged[key] = result
        return sorted(merged.values(), key=self._get_result_score, reverse=True)

    def _result_key(self, result: RetrievalResult) -> tuple[Any, ...]:
        """构造稳定去重 key,优先使用 document_id。"""
        document_id = result.provenance.get("document_id")
        if document_id:
            return ("document_id", document_id)
        return (
            "fallback",
            result.provenance.get("source"),
            result.provenance.get("locator"),
            result.content[:128],
        )

    def _estimate_evidence_tokens(self, results: list[RetrievalResult]) -> int:
        """用字符长度确定性估算 evidence token 数。"""
        total = 0
        for result in results:
            if result.content:
                total += max(1, len(result.content) // 4)
        return total

    def _apply_insufficient_evidence_warning(self, qa_result: Any, convergence: dict[str, Any]) -> Any:
        """在非充分收敛时追加 evidence 不足风险提示。"""
        if convergence.get("reason") == "sufficient" and convergence.get("total_evidence", 0) > 0:
            return qa_result
        if INSUFFICIENT_EVIDENCE_WARNING not in qa_result.risk_notes:
            qa_result.risk_notes.append(INSUFFICIENT_EVIDENCE_WARNING)
        return qa_result

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
            for key in ("law_name", "version", "effective_date", "expiry_date", "status", "source_url", "retrieved_at"):
                value = getattr(result, key)
                if value:
                    provenance[key] = value
            if provenance.get("doc_type") == "law":
                provenance["citation"] = self._format_law_citation(provenance)
            evidence.append(
                {
                    "content": result.content[:1000],
                    "provenance": provenance,
                    "score": result.score,
                    "similarity": result.similarity,
                }
            )
        return evidence

    def _format_law_citation(self, provenance: dict[str, Any]) -> str | None:
        """按法规元数据格式化可回链引用。"""
        law_name = provenance.get("law_name")
        version = provenance.get("version")
        locator = provenance.get("locator")
        if law_name and version and locator:
            article = str(locator).split("·")[-1]
            citation = f"《{law_name}({version})》{article}"
            if provenance.get("effective_date"):
                citation = f"{citation}(生效日:{provenance['effective_date']})"
            return citation
        return None

    def _apply_law_stale_warnings(self, qa_result: Any, evidence: list[dict[str, Any]]) -> Any:
        """根据 evidence 中的法规版本状态追加过时风险提示。"""
        warning = "可能过时，建议核对官方最新版本"
        if not any(self._is_stale_law_evidence(item.get("provenance", {})) for item in evidence):
            return qa_result
        if warning not in qa_result.risk_notes:
            qa_result.risk_notes.append(warning)
        return qa_result

    def _is_stale_law_evidence(self, provenance: dict[str, Any]) -> bool:
        """判断单条法规 evidence 是否存在过时风险。"""
        if provenance.get("doc_type") != "law":
            return False
        if provenance.get("status") == "superseded":
            return True
        retrieved_at = provenance.get("retrieved_at")
        if not retrieved_at:
            return False
        try:
            retrieved_date = date.fromisoformat(str(retrieved_at))
        except ValueError:
            return False
        return (date.today() - retrieved_date).days > self.settings.law_stale_days

    def _build_evidence_versions(self, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """构造 trace 用法规版本摘要。"""
        versions = []
        for item in evidence:
            provenance = item.get("provenance", {})
            if provenance.get("doc_type") != "law":
                continue
            versions.append(
                {
                    key: provenance[key]
                    for key in ("document_id", "law_name", "version", "effective_date", "expiry_date", "status", "retrieved_at")
                    if provenance.get(key)
                }
            )
        return versions
