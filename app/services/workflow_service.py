from typing import Any

from app.models.schemas import WorkflowState
from app.nodes.claim_check import ClaimCheckNode
from app.nodes.claim_generate import ClaimGenerateNode
from app.nodes.claim_plan import ClaimPlanNode
from app.nodes.completeness_gate import CompletenessGateNode
from app.nodes.feature_extract import FeatureExtractNode
from app.nodes.normalize_input import NormalizeInputNode
from app.orchestrator.engine import Orchestrator
from app.orchestrator.workflow_defs import WorkflowRegistry
from app.skills.claim_writing import ClaimWritingSkill
from app.skills.feature_extraction import FeatureExtractionSkill


class WorkflowService:
    """权利要求生成 workflow 服务。

    Returns:
        封装 node 编排细节的权利要求生成服务。
    """

    def __init__(self) -> None:
        self.orchestrator = Orchestrator(
            nodes={
                "normalize_input": NormalizeInputNode(),
                "completeness_gate": CompletenessGateNode(),
                "feature_extract": FeatureExtractNode(
                    skill=FeatureExtractionSkill(fake_output={"required_features": ["采集传感器数据"]})
                ),
                "claim_plan": ClaimPlanNode(),
                "claim_generate": ClaimGenerateNode(
                    skill=ClaimWritingSkill(
                        fake_outputs={
                            "claim_generate": {
                                "version": "v1",
                                "claims": [
                                    {"number": 1, "claim_type": "independent", "text": "一种控制方法。"}
                                ],
                            }
                        }
                    )
                ),
                "claim_check": ClaimCheckNode(),
            }
        )
        self.workflow_def = WorkflowRegistry().get_workflow_def("claim_generation")

    def generate_claims(
        self,
        raw_input: str,
        state: WorkflowState | None = None,
        workflow_def: list[str] | None = None,
    ) -> dict[str, Any]:
        """生成权利要求草稿。

        Args:
            raw_input: 用户输入的口语化技术方案。
            state: 可选的既有 workflow 状态,用于统一入口避免重复 normalize。
            workflow_def: 可选的节点序列,用于从已完成节点之后继续执行。

        Returns:
            成功时返回草稿、校验报告和下一步建议;失败时返回结构化错误。
        """
        state = state or WorkflowState(raw_input=raw_input)
        result = self.orchestrator.run(state, workflow_def or self.workflow_def)
        if result.status != "success":
            return {
                "status": result.status,
                "errors": result.errors,
                "message": "请补充技术方案内容。",
            }
        return {
            "status": "success",
            "claims_draft": state.claims_draft,
            "validation_report": state.validation_report,
            "next_steps": ["请审阅权利要求初稿并指出需要修改的权利要求编号。"],
            "trace": state.trace,
        }
