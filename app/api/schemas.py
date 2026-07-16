from typing import Any, Literal

from pydantic import BaseModel, Field


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



class AttachmentUploadResponse(BaseModel):
    """附件上传响应。

    Args:
        attachment_id: 附件 ID。
        filename: 原始文件名。
        content_type: 上传内容类型。
        bytes: 附件字节数。
        chars: 抽取后正文字符数。
        truncated: 是否发生截断。
        doc_type: 文档类型。
        format: 抽取正文格式。
        media: 媒体元数据列表。
        case_id: 归属案件 ID。
        workspace_artifact_key: 导入案件 workspace 的正文 artifact key。

    Returns:
        单个附件上传结果。
    """

    attachment_id: str
    filename: str
    content_type: str | None
    bytes: int
    chars: int
    truncated: bool
    doc_type: str
    format: Literal["markdown", "text"]
    media: list[dict[str, Any]] = Field(default_factory=list)
    case_id: str
    workspace_artifact_key: str


class AttachmentUploadBatchResponse(BaseModel):
    """批量附件上传响应。

    Args:
        attachments: 附件上传结果列表。

    Returns:
        批量附件上传结果。
    """

    attachments: list[AttachmentUploadResponse]


class CaseCreateResponse(BaseModel):
    """案件创建响应。

    Args:
        case_id: 案件 ID。
        workspace_id: 案件 workspace ID。
        workspace_path: 面向调用方展示的相对 workspace 路径。

    Returns:
        案件创建 API 响应体。
    """

    case_id: str
    workspace_id: str
    workspace_path: str


class AgentRequest(BaseModel):
    """统一 Agent 请求。

    Args:
        raw_input: 用户原始输入。
        case_id: 已创建案件 ID,用于绑定案件 workspace。
        claims_draft: 可选的当前权利要求草稿,用于修改路径。
        session_id: 可选会话标识,用于跨请求会话记忆。
        attachment_ids: 可选附件 ID 列表。

    Returns:
        统一 Agent API 请求体。
    """

    raw_input: str
    case_id: str
    claims_draft: list[dict[str, Any]] = Field(default_factory=list)
    session_id: str | None = None
    attachment_ids: list[str] = Field(default_factory=list)
