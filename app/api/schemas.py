from typing import Any

from pydantic import BaseModel


class ClaimGenerationRequest(BaseModel):
    """权利要求生成请求。

    Args:
        raw_input: 用户输入的技术方案文本。

    Returns:
        权利要求生成 API 请求体。
    """

    raw_input: str


class ClaimGenerationResponse(BaseModel):
    """权利要求生成响应。

    Args:
        status: 处理状态。
        claims_draft: 权利要求初稿。
        validation_report: 校验报告。
        next_steps: 下一步建议。
        trace: workflow 执行轨迹。
        disclaimer: 法律意见免责声明。

    Returns:
        权利要求生成 API 响应体。
    """

    status: str
    claims_draft: list[dict[str, Any]]
    validation_report: dict[str, Any]
    next_steps: list[str]
    trace: list[dict[str, Any]]
    disclaimer: str


class TranslateRequest(BaseModel):
    """翻译请求。

    Args:
        raw_input: 用户输入的待翻译文本。

    Returns:
        翻译 API 请求体。
    """

    raw_input: str


class TranslateResponse(BaseModel):
    """翻译响应。

    Args:
        status: 处理状态。
        translated_text: 译文。
        terms: 术语表。
        trace: adapter trace。
        workflow_trace: workflow trace。
        disclaimer: 法律意见免责声明。

    Returns:
        翻译 API 响应体。
    """

    status: str
    translated_text: str
    terms: dict[str, str]
    trace: list[dict[str, Any]]
    workflow_trace: list[dict[str, Any]]
    disclaimer: str


class ClaimRevisionRequest(BaseModel):
    """单条权利要求修改请求。

    Args:
        claims_draft: 当前权利要求草稿。
        user_feedback: 用户修改意见。

    Returns:
        单条权利要求修改 API 请求体。
    """

    claims_draft: list[dict[str, Any]]
    user_feedback: str


class ClaimRevisionResponse(BaseModel):
    """单条权利要求修改响应。

    Args:
        status: 处理状态。
        claim: 修改后的目标权利要求。
        diff: 修改前后差异。
        risk_notes: 风险提示。
        version: 新版本号。
        validation_report: 校验报告。
        disclaimer: 法律意见免责声明。

    Returns:
        单条权利要求修改 API 响应体。
    """

    status: str
    claim: dict[str, Any]
    diff: dict[str, Any]
    risk_notes: list[str]
    version: str
    validation_report: dict[str, Any]
    disclaimer: str


class AgentRequest(BaseModel):
    """统一 Agent 请求。

    Args:
        raw_input: 用户原始输入。
        claims_draft: 可选的当前权利要求草稿,用于修改路径。
        session_id: 可选会话标识,用于跨请求会话记忆。

    Returns:
        统一 Agent API 请求体。
    """

    raw_input: str
    claims_draft: list[dict[str, Any]] = []
    session_id: str | None = None
