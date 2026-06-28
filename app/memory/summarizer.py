from pydantic import BaseModel, Field, ValidationError

from app.prompts.session_summary import (
    SESSION_SUMMARY_OUTPUT_SCHEMA,
    SESSION_SUMMARY_SYSTEM_PROMPT,
    build_session_summary_user_prompt,
)
from app.tools.llm import LLMClient, LLMMessage, build_llm_client


class SummaryResult(BaseModel):
    """会话摘要执行结果。

    Args:
        success: 摘要是否成功。
        summary: 成功时的摘要文本。
        covered_turn_index: 摘要覆盖到的最大 turn index。
        reason: 失败原因。

    Returns:
        可由 store 或 dispatch 消费的摘要结果。
    """

    success: bool
    summary: str | None = None
    covered_turn_index: int | None = None
    reason: str | None = None


class SessionSummaryPayload(BaseModel):
    """LLM 会话摘要响应结构。

    Args:
        summary: 摘要文本。
        confidence: 置信度。
        uncertain: 是否存在不确定信息。

    Returns:
        校验后的摘要响应。
    """

    summary: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    uncertain: bool


class SessionSummarizer:
    """会话滚动摘要器。

    Args:
        llm_client: 可注入 LLM client,测试中使用 fake 或 stub。
        model: 摘要模型名称。

    Returns:
        可将早期会话 turn 压缩为摘要的对象。
    """

    def __init__(self, llm_client: LLMClient | None = None, model: str | None = None) -> None:
        self.llm_client = llm_client or build_llm_client()
        self.model = model

    def summarize(
        self,
        session_id: str,
        previous_summary: str | None,
        turns: list[dict[str, str]],
        covered_turn_index: int | None = None,
    ) -> SummaryResult:
        """压缩会话 turn。

        Args:
            session_id: 会话标识。
            previous_summary: 已有摘要。
            turns: 新增待压缩 turn。
            covered_turn_index: 摘要覆盖到的最大 turn index。

        Returns:
            摘要成功或失败结果;失败不抛出阻断主流程。
        """
        if not turns:
            return SummaryResult(success=False, reason="no_turns_to_summarize")
        try:
            response = self.llm_client.generate(
                messages=[
                    LLMMessage(role="system", content=SESSION_SUMMARY_SYSTEM_PROMPT),
                    LLMMessage(role="user", content=build_session_summary_user_prompt(previous_summary, turns)),
                ],
                output_schema=SESSION_SUMMARY_OUTPUT_SCHEMA,
                model=self.model,
                trace_context={"task_type": "session_summary", "session_id": session_id},
            )
            if response.errors:
                return SummaryResult(success=False, reason=response.errors[0].get("code", "llm_error"))
            payload = SessionSummaryPayload.model_validate(response.content)
            return SummaryResult(
                success=True,
                summary=payload.summary,
                covered_turn_index=covered_turn_index,
            )
        except (RuntimeError, ValidationError, ValueError, TypeError):
            return SummaryResult(success=False, reason="invalid_summary_response")
