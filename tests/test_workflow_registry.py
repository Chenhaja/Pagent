from app.orchestrator.workflow_defs import WorkflowRegistry


def test_workflow_registry_returns_known_intent_workflow_defs() -> None:
    """workflow registry 应按 known intent 返回预定义 workflow。"""
    registry = WorkflowRegistry()

    assert registry.get_workflow("claim_generation") == [
        "normalize_input",
        "feature_extract",
        "claim_plan",
        "claim_generate",
        "claim_check",
    ]
    assert registry.get_workflow("translation") == ["normalize_input", "translate"]
    assert registry.get_workflow("claim_revision") == ["claim_revise", "claim_check"]


def test_workflow_registry_returns_empty_for_unknown_intent() -> None:
    """workflow registry 遇到未知 intent 应返回空 workflow。"""
    registry = WorkflowRegistry()

    assert registry.get_workflow("unknown") == []
