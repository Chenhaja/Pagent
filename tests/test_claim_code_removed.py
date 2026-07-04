from pathlib import Path

import pytest

from app.models.schemas import IntentClassification
from app.nodes.intent_router import IntentRouterNode
from app.orchestrator.workflow_defs import WorkflowRegistry
from app.services.agent_dispatch_service import AgentDispatchService


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"


def test_old_claim_workflows_are_removed() -> None:
    """旧权利要求 workflow 不再注册。"""
    registry = WorkflowRegistry()

    assert registry.get_workflow("claim_generation") == []
    assert registry.get_workflow("claim_revision") == []
    assert registry.get_workflow_def("claim_generation").nodes == []
    assert registry.get_workflow_def("claim_revision").nodes == []


@pytest.mark.parametrize("intent", ["claim_generation", "claim_revision"])
def test_old_claim_intents_are_rejected_by_schema(intent: str) -> None:
    """旧权利要求 intent 不能通过结构化分类校验。"""
    with pytest.raises(Exception):
        IntentClassification(intent=intent, confidence=0.95)


def test_intent_router_no_longer_advertises_old_claim_intents() -> None:
    """意图路由澄清信息不再暴露旧 claim intent。"""
    result = IntentRouterNode(llm_client=object())._clarify("test")

    assert "claim_generation" not in result.output["supported_intents"]
    assert "claim_revision" not in result.output["supported_intents"]
    assert "patent_drafting" in result.output["supported_intents"]


def test_agent_dispatch_service_does_not_import_old_claim_services() -> None:
    """统一 dispatch 不再依赖旧 claim service。"""
    import app.services.agent_dispatch_service as module

    assert not hasattr(module, "WorkflowService")
    assert not hasattr(module, "RevisionService")
    assert AgentDispatchService().workflow_registry.get_workflow("claim_generation") == []


def test_old_claim_specific_modules_are_removed() -> None:
    """旧 claim 专用模块文件已删除。"""
    removed_paths = [
        APP_DIR / "services" / "workflow_service.py",
        APP_DIR / "services" / "revision_service.py",
        APP_DIR / "nodes" / "completeness_gate.py",
        APP_DIR / "nodes" / "feature_extract.py",
        APP_DIR / "nodes" / "claim_plan.py",
        APP_DIR / "nodes" / "claim_generate.py",
        APP_DIR / "nodes" / "claim_check.py",
        APP_DIR / "nodes" / "claim_revise.py",
        APP_DIR / "skills" / "claim_writing.py",
        APP_DIR / "skills" / "feature_extraction.py",
    ]

    assert [path for path in removed_paths if path.exists()] == []
