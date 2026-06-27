from app.models.schemas import WorkflowState
from app.nodes.claim_check import ClaimCheckNode
from app.nodes.claim_generate import ClaimGenerateNode
from app.nodes.claim_plan import ClaimPlanNode
from app.nodes.claim_revise import ClaimReviseNode
from app.nodes.feature_extract import FeatureExtractNode
from app.nodes.intent_router import IntentRouterNode
from app.nodes.normalize_input import NormalizeInputNode
from app.nodes.translate import TranslateNode
from app.orchestrator.engine import Orchestrator
from app.skills.claim_writing import ClaimWritingSkill
from app.skills.feature_extraction import FeatureExtractionSkill
from app.tools.translation_agent import FakeTranslationAgent, TranslationResult


def test_claim_generation_workflow_runs_through_orchestrator() -> None:
    """权利要求生成链路应能通过 orchestrator 跑通。"""
    state = WorkflowState(raw_input="请根据技术方案生成权利要求")
    orchestrator = Orchestrator(
        nodes={
            "normalize_input": NormalizeInputNode(),
            "intent_router": IntentRouterNode(),
            "feature_extract": FeatureExtractNode(
                skill=FeatureExtractionSkill(fake_output={"required_features": ["采集传感器数据"]})
            ),
            "claim_plan": ClaimPlanNode(),
            "claim_generate": ClaimGenerateNode(
                skill=ClaimWritingSkill(
                    fake_outputs={
                        "claim_generate": {
                            "version": "v1",
                            "claims": [{"number": 1, "claim_type": "independent", "text": "一种控制方法。"}],
                        }
                    }
                )
            ),
            "claim_check": ClaimCheckNode(),
        }
    )

    result = orchestrator.run(
        state,
        ["normalize_input", "intent_router", "feature_extract", "claim_plan", "claim_generate", "claim_check"],
    )

    assert result.status == "success"
    assert state.validation_report["passed"] is True


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


def test_claim_revision_workflow_runs_through_orchestrator() -> None:
    """单条权利要求修改链路应能通过 orchestrator 跑通。"""
    state = WorkflowState(
        raw_input="",
        user_feedback="修改权利要求1",
        claims_draft=[{"number": 1, "claim_type": "independent", "text": "一种控制方法。"}],
    )
    orchestrator = Orchestrator(
        nodes={
            "claim_revise": ClaimReviseNode(
                skill=ClaimWritingSkill(
                    fake_outputs={
                        "claim_revise": {
                            "version": "v2",
                            "claims": [{"number": 1, "claim_type": "independent", "text": "一种改进的控制方法。"}],
                        }
                    }
                )
            ),
            "claim_check": ClaimCheckNode(),
        }
    )

    result = orchestrator.run(state, ["claim_revise", "claim_check"])

    assert result.status == "success"
    assert state.claim_patches[0]["after_text"] == "一种改进的控制方法。"
    assert state.validation_report["passed"] is True
