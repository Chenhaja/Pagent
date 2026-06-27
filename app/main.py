from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.services.translate_service import TranslateService
from app.services.workflow_service import WorkflowService

app = FastAPI(title="Patent Agent")


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


@app.get("/health")
def health_check() -> dict[str, str]:
    """返回服务健康检查状态。

    Returns:
        固定健康状态,用于确认 API 服务已启动。
    """
    return {"status": "ok"}


@app.post("/claims/generate", response_model=ClaimGenerationResponse)
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
        result["message"] = f"{result['message']}辅助初稿，不等同于专利代理师法律意见。"
        raise HTTPException(status_code=400, detail=result)
    result["disclaimer"] = "辅助初稿，不等同于专利代理师法律意见。"
    return result


@app.post("/translate", response_model=TranslateResponse)
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
        result["message"] = f"{result['message']}辅助初稿，不等同于专利代理师法律意见。"
        raise HTTPException(status_code=400, detail=result)
    result["disclaimer"] = "辅助初稿，不等同于专利代理师法律意见。"
    return result
