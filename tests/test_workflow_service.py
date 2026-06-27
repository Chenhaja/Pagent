from app.services.workflow_service import WorkflowService


def test_workflow_service_generates_claim_draft() -> None:
    """权利要求生成 service 应封装生成 workflow 并返回草稿和校验报告。"""
    service = WorkflowService()

    result = service.generate_claims("请根据技术方案生成权利要求")

    assert result["claims_draft"][0]["text"] == "一种控制方法。"
    assert result["validation_report"]["passed"] is True
    assert result["next_steps"] == ["请审阅权利要求初稿并指出需要修改的权利要求编号。"]


def test_workflow_service_returns_structured_failure() -> None:
    """权利要求生成 service 应封装 workflow 失败结果。"""
    service = WorkflowService()

    result = service.generate_claims("   ")

    assert result == {
        "status": "requires_user_input",
        "errors": ["empty_raw_input"],
        "message": "请补充技术方案内容。",
    }
