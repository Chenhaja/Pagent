import logging
from datetime import date
from typing import Any

from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.logging import log_event
from app.models.schemas import NodeResult, SkillContext, WorkflowState
from app.orchestrator.node_base import Node
from app.orchestrator.react_loop import BoundedReActLoop, ReActBudget, ReActOutcome
from app.orchestrator.react_policy import HeuristicReActPolicy, LLMReActPolicy, ReActPolicy
from app.orchestrator.tool_registry import build_default_tool_registry
from app.skills.patent_qa import PatentQASkill
from app.tools.llm import build_llm_client
from app.tools.retrieval import Retriever, build_retriever


INSUFFICIENT_EVIDENCE_WARNING = "依据可能不足，建议补充材料或核对官方来源"
logger = logging.getLogger(__name__)


def _react_llm_settings(settings: Settings) -> Settings:
    """为 ReAct LLM 调用构造局部配置。"""
    if not settings.react_thinking_enabled:
        return settings
    return settings.model_copy(
        update={
            "llm_reasoning_enabled": True,
            "llm_reasoning_effort": settings.llm_reasoning_effort,
            "llm_max_tokens":4096,
            "llm_timeout": 180
            }
        )


class QANode(Node):
    """专利问答节点。

    Args:
        skill: 专利问答 skill。
        retrieval_tool: 可注入检索工具。
        max_steps: QA 内部检索最大轮数。
        token_budget: QA evidence token 预算。
        timeout_seconds: QA 检索循环超时时间。
        top_k: 每轮检索结果数量。
        react_loop: 可注入 R7 主循环。

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
        react_loop: BoundedReActLoop | None = None,
    ) -> None:
        super().__init__(name=self.name)
        settings = get_settings()
        self.settings = settings
        self.skill = skill or PatentQASkill()
        self.retrieval_tool = retrieval_tool or build_retriever(settings)
        self.max_steps = settings.react_max_steps if max_steps is None else max_steps
        self.token_budget = settings.react_token_budget if token_budget is None else token_budget
        self.timeout_seconds = settings.react_timeout_seconds if timeout_seconds is None else timeout_seconds
        self.top_k = settings.retrieval_top_k if top_k is None else top_k
        self.react_loop = react_loop or self._build_react_loop()

    def _build_react_loop(self) -> BoundedReActLoop:
        """构建 QA 默认使用的 R7 主循环。"""
        registry = build_default_tool_registry(self.settings, retriever=self.retrieval_tool)
        allowed_tools = self._allowed_tools()
        return BoundedReActLoop(
            tools=registry.available_tools(),
            budget=ReActBudget(
                max_steps=self.max_steps,
                token_budget=self.token_budget,
                timeout_seconds=self.timeout_seconds,
            ),
            node_name=self.name,
            policy=self._build_react_policy(),
            tool_cards=registry.tool_cards(allowed_tools),
            use_llm_judge=self.settings.react_use_llm_judge,
            sufficient_score_threshold=self.settings.react_sufficient_score_threshold,
            observation_digest_chars=self.settings.react_observation_digest_chars,
        )

    def _build_react_policy(self) -> ReActPolicy:
        """按配置构建 QA ReAct policy,配置不完整时安全降级。"""
        if self.settings.react_policy_driver != "llm" or not self._has_llm_config():
            return HeuristicReActPolicy()
        model = self.settings.react_policy_model or self.settings.llm_cheap_model or self.settings.llm_model
        reflect_model = self.settings.react_reflect_model or model
        return LLMReActPolicy(
            llm_client=build_llm_client(_react_llm_settings(self.settings)),
            node_name=self.name,
            model=model,
            reflect_model=reflect_model,
            temperature=self.settings.react_policy_temperature,
            timeout=self.settings.react_timeout_seconds,
        )

    def _has_llm_config(self) -> bool:
        """判断是否具备真实 LLM 调用所需配置。"""
        return bool(self.settings.llm_base_url and self.settings.llm_model and self.settings.llm_api_key)

    def run(self, state: WorkflowState) -> NodeResult:
        """生成专利问答结果。

        Args:
            state: 当前 workflow 状态。

        Returns:
            成功时返回 qa_result;skill 输出无效时返回结构化失败。
        """
        question = state.normalized_input or state.raw_input
        outcome = self.react_loop.run(question, allowed_tools=self._allowed_tools())
        evidence = self._build_evidence(outcome.evidence)
        history = state.dialog_context.get("history") or []
        state.dialog_context["qa_retrieval_results"] = evidence
        context = SkillContext(
            task_type="patent_qa",
            state_snapshot={
                "question": question,
                "claims_draft": state.claims_draft,
                "validation_report": state.validation_report,
                "retrieval_results": evidence,
                "history": history,
            },
        )
        try:
            qa_result = self.skill.run(context)
        except (ValueError, ValidationError) as error:
            log_event(
                logger,
                logging.WARNING,
                "qa_failed",
                "QA 生成失败",
                error_type=type(error).__name__,
                evidence_count=len(evidence),
                react_reason=outcome.reason,
                steps_used=outcome.steps_used,
                tool_calls=outcome.tool_calls,
                fallback_used=outcome.fallback_used,
            )
            return NodeResult.failed(errors=["qa_failed"])

        qa_result = self._apply_law_stale_warnings(qa_result, evidence)
        qa_result = self._apply_insufficient_evidence_warning(qa_result, outcome)
        output = qa_result.model_dump()
        state.dialog_context["qa_result"] = output
        return NodeResult.success(
            output={"qa_result": output},
            trace_events=[
                *outcome.trace_events,
                {
                    "event": "qa_retrieval_completed",
                    "data": {
                        "steps_used": outcome.steps_used,
                        "result_count": len(evidence),
                        "token_budget": self.token_budget,
                        "timeout_seconds": self.timeout_seconds,
                    },
                },
                {
                    "event": "qa_completed",
                    "data": {
                        "basis_count": len(qa_result.basis),
                        "has_retrieval": bool(evidence),
                        "evidence_versions": self._build_evidence_versions(evidence),
                        "history_msg_count": self._count_history_messages(history),
                    },
                },
            ],
        )

    def _allowed_tools(self) -> list[str]:
        """返回 QA 默认允许使用的 agentic 工具。"""
        return [item.strip() for item in self.settings.agentic_default_tools.split(",") if item.strip()]

    def _count_history_messages(self, history: list[dict]) -> int:
        """统计会注入回答模型的有效历史消息数。"""
        return sum(1 for turn in history if str(turn.get("content", "")).strip())

    def _apply_insufficient_evidence_warning(self, qa_result: Any, outcome: ReActOutcome) -> Any:
        """在非充分收敛时追加 evidence 不足风险提示。"""
        if outcome.reason == "sufficient" and outcome.evidence:
            return qa_result
        if INSUFFICIENT_EVIDENCE_WARNING not in qa_result.risk_notes:
            qa_result.risk_notes.append(INSUFFICIENT_EVIDENCE_WARNING)
        return qa_result

    def _build_evidence(self, raw_evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """将主循环 evidence 转换为传给 skill 的受限 evidence。"""
        evidence = []
        for item in raw_evidence[:3]:
            provenance = dict(item.get("provenance") or {})
            if not provenance.get("source"):
                continue
            if provenance.get("doc_type") == "law":
                provenance["citation"] = self._format_law_citation(provenance)
            evidence.append(
                {
                    "content": str(item.get("content") or "")[:1000],
                    "provenance": provenance,
                    "score": item.get("score", 0),
                    "similarity": item.get("similarity", 0.0),
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
