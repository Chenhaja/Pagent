import logging
import time
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.core.log_context import bind_context, new_request_id, reset_context
from app.core.logging import log_event
from app.api.schemas import (
    AgentRequest,
    AttachmentUploadBatchResponse,
    CaseCreateResponse,
    TranslateRequest,
    TranslateResponse,
)
from app.services.agent_dispatch_service import AgentDispatchService
from app.services.attachment_service import AttachmentService, AttachmentServiceError
from app.services.case_service import CaseService
from app.services.translate_service import TranslateService

DISCLAIMER = "辅助初稿，不等同于专利代理师法律意见。"
logger = logging.getLogger(__name__)
router = APIRouter()


def build_error_detail(result: dict[str, Any]) -> dict[str, Any]:
    """构造统一 API 错误响应。

    Args:
        result: 服务层返回的结构化错误结果。

    Returns:
        包含状态、错误列表、面向用户消息和免责声明的错误详情。
    """
    return {
        "status": result["status"],
        "errors": result.get("errors", []),
        "message": result.get("message", "请求处理失败。"),
        "disclaimer": DISCLAIMER,
    }


@router.get("/health")
def health_check() -> dict[str, str]:
    """返回服务健康检查状态。

    Returns:
        固定健康状态,用于确认 API 服务已启动。
    """
    return {"status": "ok"}


@router.post("/agent/cases", response_model=CaseCreateResponse)
def create_agent_case() -> dict[str, Any]:
    """创建案件并绑定案件 workspace。

    Returns:
        包含案件 ID、workspace ID 和相对 workspace 路径的响应。
    """
    return CaseService().create_case()


@router.post("/agent/attachments", response_model=AttachmentUploadBatchResponse)
async def upload_agent_attachments(files: list[UploadFile] = File(...), case_id: str = Form(...), doc_type: str = Form("other")) -> dict[str, Any]:
    """上传并解析 Agent 附件。

    Args:
        files: multipart 上传文件列表。
        case_id: 已创建案件 ID,用于绑定附件归属。
        doc_type: 文档类型,默认 other。

    Returns:
        批量附件上传结果。

    Raises:
        HTTPException: 当附件校验或解析失败时抛出。
    """
    service = AttachmentService()
    try:
        service.validate_count(len(files))
        attachments = []
        for file in files:
            content = await file.read()
            attachments.append(service.save_upload(file.filename or "attachment", file.content_type, content, doc_type, case_id=case_id))
        log_event(
            logger,
            logging.INFO,
            "attachment_received",
            "附件上传完成",
            count=len(attachments),
            bytes=sum(item["bytes"] for item in attachments),
        )
        return {"attachments": attachments}
    except AttachmentServiceError as exc:
        log_event(logger, logging.WARNING, "attachment_rejected", "附件上传被拒绝", reason=exc.code, count=len(files))
        raise HTTPException(
            status_code=400,
            detail={"status": "failed", "errors": [exc.code], "message": exc.message, "disclaimer": DISCLAIMER},
        ) from exc


@router.post("/agent")
def dispatch_agent(request: AgentRequest) -> dict[str, Any]:
    """通过统一 Agent 入口处理专利任务。

    Args:
        request: 统一 Agent 请求。

    Returns:
        根据识别出的 workflow 返回对应结构化结果。

    Raises:
        HTTPException: 当分发服务返回非成功状态时抛出。
    """
    request_id = new_request_id()
    token = bind_context(request_id=request_id, session_id=request.session_id)
    started_at = time.perf_counter()
    log_event(logger, logging.INFO, "request_start", "请求开始", method="POST", path="/agent", session_id=request.session_id)
    try:
        result = AgentDispatchService().dispatch(
            request.raw_input,
            claims_draft=request.claims_draft,
            case_id=request.case_id,
            session_id=request.session_id,
            attachment_ids=request.attachment_ids,
        )
        if result["status"] != "success":
            log_event(
                logger,
                logging.WARNING,
                "request_end",
                "请求失败",
                method="POST",
                path="/agent",
                status=result["status"],
                status_code=400,
                duration_ms=int((time.perf_counter() - started_at) * 1000),
                session_id=request.session_id,
                errors=result.get("errors", []),
                error_summary=";".join(result.get("errors", [])[:3]),
                error_message=result.get("message"),
            )
            raise HTTPException(status_code=400, detail=build_error_detail(result))
        if "patch" in result:
            result["diff"] = result.pop("patch")
        result["disclaimer"] = DISCLAIMER
        log_event(
            logger,
            logging.INFO,
            "request_end",
            "请求完成",
            method="POST",
            path="/agent",
            status=result["status"],
            status_code=200,
            duration_ms=int((time.perf_counter() - started_at) * 1000),
            session_id=request.session_id,
        )
        return result
    finally:
        reset_context(token)



@router.post("/translate", response_model=TranslateResponse)
def translate(request: TranslateRequest) -> dict[str, Any]:
    """翻译专利文本。

    Args:
        request: 翻译请求。

    Returns:
        译文、术语表和 trace。

    Raises:
        HTTPException: 当翻译服务返回非成功状态时抛出。
    """
    result = TranslateService().translate(request.raw_input)
    if result["status"] != "success":
        raise HTTPException(status_code=400, detail=build_error_detail(result))
    result["disclaimer"] = DISCLAIMER
    return result
