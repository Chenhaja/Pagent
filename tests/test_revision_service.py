from app.services.revision_service import RevisionService


def test_revision_service_applies_patch_and_updates_version() -> None:
    """权利要求修改 service 应应用 patch 并更新版本号。"""
    service = RevisionService()
    claims_draft = [{"number": 1, "claim_type": "independent", "text": "一种控制方法。"}]

    result = service.revise_claim(claims_draft=claims_draft, user_feedback="修改权利要求1")

    assert result["status"] == "success"
    assert result["claim"]["text"] == "一种改进的控制方法。"
    assert result["patch"]["after_text"] == "一种改进的控制方法。"
    assert result["version"] == "v2"


def test_revision_service_returns_failure_when_target_missing() -> None:
    """权利要求修改 service 应返回目标不存在错误。"""
    service = RevisionService()

    result = service.revise_claim(claims_draft=[], user_feedback="修改权利要求2")

    assert result == {
        "status": "failed",
        "errors": ["target_claim_not_found:2"],
        "message": "未找到要修改的权利要求。",
    }
