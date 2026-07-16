from app.orchestrator.workflow_defs import WorkflowDef, WorkflowRegistry


EXPECTED_PATENT_DRAFTING_NODES = [
    "normalize_input",
    "drafting_parse_input",
    "drafting_patent_search",
    "drafting_generate_outline",
    "drafting_claims_writer",
    "drafting_description_writer",
    "drafting_diagram_generator",
    "drafting_abstract_writer",
    "drafting_merge_document",
    "drafting_finalize",
]


def test_workflow_registry_returns_known_intent_workflow_defs() -> None:
    """workflow registry 应按 known intent 返回预定义 workflow。"""
    registry = WorkflowRegistry()

    assert registry.get_workflow("translation") == ["normalize_input", "translate"]
    assert registry.get_workflow("qa") == ["normalize_input", "qa"]
    assert registry.get_workflow("patent_drafting") == EXPECTED_PATENT_DRAFTING_NODES


def test_workflow_registry_returns_empty_for_unknown_intent() -> None:
    """workflow registry 遇到未知 intent 应返回空 workflow。"""
    registry = WorkflowRegistry()

    assert registry.get_workflow("unknown") == []


def test_workflow_registry_returns_empty_for_removed_claim_intents() -> None:
    """旧 claim intent 被删除后应返回空 workflow。"""
    registry = WorkflowRegistry()

    assert registry.get_workflow("claim_generation") == []
    assert registry.get_workflow("claim_revision") == []


def test_workflow_registry_returns_metadata_definitions() -> None:
    """workflow registry 应返回带元数据的 workflow 定义。"""
    registry = WorkflowRegistry()

    workflow_def = registry.get_workflow_def("translation")

    assert isinstance(workflow_def, WorkflowDef)
    assert workflow_def.intent == "translation"
    assert workflow_def.start_node == "normalize_input"
    assert workflow_def.max_loop_count == 0
    assert workflow_def.nodes == ["normalize_input", "translate"]


def test_workflow_registry_registers_qa_workflow() -> None:
    """QA intent 应注册为可执行 workflow。"""
    registry = WorkflowRegistry()

    assert registry.get_workflow("qa") == ["normalize_input", "qa"]
    workflow_def = registry.get_workflow_def("qa")
    assert workflow_def.start_node == "normalize_input"
    assert workflow_def.nodes[-1] == "qa"


def test_workflow_registry_registers_patent_drafting_workflow() -> None:
    """patent_drafting intent 应注册为顶层文书生成流程。"""
    registry = WorkflowRegistry()

    workflow_def = registry.get_workflow_def("patent_drafting")

    assert workflow_def.intent == "patent_drafting"
    assert workflow_def.start_node == "normalize_input"
    assert workflow_def.max_loop_count == 0
    assert workflow_def.nodes == EXPECTED_PATENT_DRAFTING_NODES
