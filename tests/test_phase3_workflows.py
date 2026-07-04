from app.models.schemas import WorkflowState
from app.nodes.intent_router import IntentRouterNode
from app.nodes.normalize_input import NormalizeInputNode
from app.nodes.translate import TranslateNode
from app.orchestrator.engine import Orchestrator
from app.tools.translation_agent import FakeTranslationAgent, TranslationResult


def test_translation_workflow_runs_through_orchestrator() -> None:
    """翻译链路应能通过 orchestrator 跑通。"""
    state = WorkflowState(raw_input="请翻译一种控制方法")
    orchestrator = Orchestrator(
        nodes={
            "normalize_input": NormalizeInputNode(),
            "intent_router": IntentRouterNode(),
            "translate": TranslateNode(
                agent=FakeTranslationAgent(result=TranslationResult(translated_text="A control method."))
            ),
        }
    )

    result = orchestrator.run(state, ["normalize_input", "intent_router", "translate"])

    assert result.status == "success"
    assert result.output["translated_text"] == "A control method."
