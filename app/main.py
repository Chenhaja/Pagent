from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.services.agent_dispatch_service import AgentDispatchService
from app.services.revision_service import RevisionService
from app.services.translate_service import TranslateService
from app.services.workflow_service import WorkflowService

app = FastAPI(title="Patent Agent")
DISCLAIMER = "辅助初稿，不等同于专利代理师法律意见。"


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


class AgentRequest(BaseModel):
    """统一 Agent 请求。

    Args:
        raw_input: 用户原始输入。
        claims_draft: 可选的当前权利要求草稿,用于修改路径。

    Returns:
        统一 Agent API 请求体。
    """

    raw_input: str
    claims_draft: list[dict[str, Any]] = []


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


@app.post("/agent")
def dispatch_agent(request: AgentRequest) -> dict[str, Any]:
    """通过统一 Agent 入口处理专利任务。

    Args:
        request: 统一 Agent 请求。

    Returns:
        根据识别出的 workflow 返回对应结构化结果。

    Raises:
        HTTPException: 当分发服务返回非成功状态时抛出。
    """
    result = AgentDispatchService().dispatch(request.raw_input, claims_draft=request.claims_draft)
    if result["status"] != "success":
        raise HTTPException(status_code=400, detail=build_error_detail(result))
    if "patch" in result:
        result["diff"] = result.pop("patch")
    result["disclaimer"] = DISCLAIMER
    return result


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
        raise HTTPException(status_code=400, detail=build_error_detail(result))
    result["disclaimer"] = DISCLAIMER
    return result


@app.post("/claims/revise", response_model=ClaimRevisionResponse)
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
        raise HTTPException(status_code=400, detail=build_error_detail(result))
    result["disclaimer"] = DISCLAIMER
    return result
