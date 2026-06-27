from app.orchestrator.workflow_defs import WorkflowDef, WorkflowRegistry


def test_workflow_registry_returns_known_intent_workflow_defs() -> None:
    """workflow registry 应按 known intent 返回预定义 workflow。"""
    registry = WorkflowRegistry()

    assert registry.get_workflow("claim_generation") == [
        "normalize_input",
        "completeness_gate",
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


def test_workflow_registry_returns_metadata_definitions() -> None:
    """workflow registry 应返回带元数据的 workflow 定义。"""
    registry = WorkflowRegistry()

    workflow_def = registry.get_workflow_def("claim_generation")

    assert isinstance(workflow_def, WorkflowDef)
    assert workflow_def.intent == "claim_generation"
    assert workflow_def.start_node == "normalize_input"
    assert workflow_def.max_loop_count == 2
    assert "completeness_gate" in workflow_def.nodes


def test_workflow_registry_registers_qa_workflow() -> None:
    """QA intent 应注册为可执行 workflow。"""
    registry = WorkflowRegistry()

    assert registry.get_workflow("qa") == ["normalize_input", "qa"]
    workflow_def = registry.get_workflow_def("qa")
    assert workflow_def.start_node == "normalize_input"
    assert workflow_def.nodes[-1] == "qa"
