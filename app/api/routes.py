import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException

from app.core.log_context import bind_context, new_request_id, reset_context
from app.core.logging import log_event
from app.api.schemas import (
    AgentRequest,
    ClaimGenerationRequest,
    ClaimGenerationResponse,
    ClaimRevisionRequest,
    ClaimRevisionResponse,
    TranslateRequest,
    TranslateResponse,
)
from app.services.agent_dispatch_service import AgentDispatchService
from app.services.revision_service import RevisionService
from app.services.translate_service import TranslateService
from app.services.workflow_service import WorkflowService

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
        result = AgentDispatchService().dispatch(request.raw_input, claims_draft=request.claims_draft, session_id=request.session_id)
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


@router.post("/claims/generate", response_model=ClaimGenerationResponse)
def generate_claims(request: ClaimGenerationRequest) -> dict[str, Any]:
    """生成权利要求初稿。

    Args:
        request: 权利要求生成请求。

    Returns:
        权利要求初稿、校验报告、下一步建议和 trace。

    Raises:
        HTTPException: 当服务层返回非成功状态时抛出。
    """
    result = WorkflowService().generate_claims(request.raw_input)
    if result["status"] != "success":
        raise HTTPException(status_code=400, detail=build_error_detail(result))
    result["disclaimer"] = DISCLAIMER
    return result


@router.post("/claims/revise", response_model=ClaimRevisionResponse)
def revise_claim(request: ClaimRevisionRequest) -> dict[str, Any]:
    """修改单条权利要求。

    Args:
        request: 单条权利要求修改请求。

    Returns:
        修改后的权利要求、差异、风险提示、新版本号和校验报告。

    Raises:
        HTTPException: 当服务层返回非成功状态或校验失败时抛出。
    """
    result = RevisionService().revise_claim(request.claims_draft, request.user_feedback)
    if result["status"] != "success":
        raise HTTPException(status_code=400, detail=build_error_detail(result))
    if result["validation_report"]["reference_errors"]:
        raise HTTPException(
            status_code=400,
            detail=build_error_detail(
                {
                    "status": "failed",
                    "errors": result["validation_report"]["reference_errors"],
                    "message": "权利要求引用关系需要修正。",
                }
            ),
        )
    result["diff"] = result.pop("patch")
    result["disclaimer"] = DISCLAIMER
    return result


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
