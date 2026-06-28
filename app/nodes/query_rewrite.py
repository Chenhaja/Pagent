from typing import Any

from app.models.schemas import NodeResult, WorkflowState
from app.orchestrator.node_base import Node
from app.prompts.query_rewrite import QUERY_REWRITE_OUTPUT_SCHEMA, QUERY_REWRITE_SYSTEM_PROMPT, build_query_rewrite_user_prompt
from app.tools.llm import LLMClient, LLMMessage, build_llm_client


class QueryRewriteNode(Node):
    """基于对话历史改写当前查询的节点。

    Args:
        llm_client: 可选 LLM client,测试可注入 fake 或 stub。

    Returns:
        在有历史时尝试写入自包含 normalized_input 的工作流节点。
    """

    name = "query_rewrite"

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        super().__init__()
        self.llm_client = llm_client or build_llm_client()

    def run(self, state: WorkflowState) -> NodeResult:
        """执行查询改写。

        Args:
            state: 当前工作流状态。

        Returns:
            成功结果。无历史或 LLM 失败时安全降级为原始 base query。
        """
        base_query = " ".join((state.normalized_input or state.raw_input).split())
        history = state.dialog_context.get("history", [])
        if not isinstance(history, list) or not history:
            state.normalized_input = base_query
            return NodeResult.success(
                output={"normalized_input": base_query},
                trace_events=[{"event": "query_rewrite_skipped", "data": {"reason": "no_history"}}],
            )

        messages = [
            LLMMessage(role="system", content=QUERY_REWRITE_SYSTEM_PROMPT),
            LLMMessage(role="user", content=build_query_rewrite_user_prompt(base_query, history)),
        ]
        try:
            response = self.llm_client.generate(
                messages=messages,
                output_schema=QUERY_REWRITE_OUTPUT_SCHEMA,
                trace_context={"node_name": "query_rewrite", "task_type": "query_rewrite"},
            )
        except Exception:
            return self._fallback(state, base_query, "exception")

        if response.errors:
            return self._fallback(state, base_query, "llm_error")
        content = response.content
        if not isinstance(content, dict):
            return self._fallback(state, base_query, "invalid_response")
        rewritten_query = content.get("rewritten_query")
        if not isinstance(rewritten_query, str) or not rewritten_query.strip():
            return self._fallback(state, base_query, "invalid_response")

        state.normalized_input = rewritten_query.strip()
        return NodeResult.success(
            output={"normalized_input": state.normalized_input},
            trace_events=[
                {
                    "event": "query_rewrite_completed",
                    "data": {
                        "confidence": content.get("confidence"),
                        "uncertain": content.get("uncertain"),
                    },
                }
            ],
        )

    def _fallback(self, state: WorkflowState, base_query: str, reason: str) -> NodeResult:
        """生成查询改写降级结果。

        Args:
            state: 当前工作流状态。
            base_query: 降级时保留的当前问题。
            reason: 稳定英文降级原因。

        Returns:
            状态为 success 的降级节点结果。
        """
        state.normalized_input = base_query
        return NodeResult.success(
            output={"normalized_input": base_query},
            trace_events=[{"event": "query_rewrite_failed_fallback", "data": {"reason": reason}}],
        )
