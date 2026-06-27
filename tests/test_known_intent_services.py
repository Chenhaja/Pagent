from app.services.revision_service import RevisionService
from app.services.translate_service import TranslateService
from app.services.workflow_service import WorkflowService


def test_explicit_services_use_known_intent_workflows_without_intent_router() -> None:
    """显式业务 service 应使用 known intent workflow,不包含通用 intent_router。"""
    services = [WorkflowService(), TranslateService(), RevisionService()]

    for service in services:
        assert "intent_router" not in service.workflow_def.nodes
        assert service.workflow_def.intent in {"claim_generation", "translation", "claim_revision"}
