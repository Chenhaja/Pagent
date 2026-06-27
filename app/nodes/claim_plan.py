from app.models.schemas import NodeResult, WorkflowState
from app.orchestrator.node_base import Node


class ClaimPlanNode(Node):
    """权利要求布局规划节点。

    Returns:
        根据技术特征生成最小权利要求布局的节点。
    """

    name = "claim_plan"

    def run(self, state: WorkflowState) -> NodeResult:
        """生成独权 / 从权最小布局。

        Args:
            state: 当前工作流状态。

        Returns:
            成功结果或缺少必要技术特征的失败结果。
        """
        required_features = [feature["name"] for feature in state.technical_features if feature.get("required")]
        optional_features = [feature["name"] for feature in state.technical_features if not feature.get("required")]
        if not required_features:
            return NodeResult.failed(errors=["missing_required_features"])

        claims = [{"number": 1, "claim_type": "independent", "features": required_features}]
        for index, feature in enumerate(optional_features, start=2):
            claims.append(
                {
                    "number": index,
                    "claim_type": "dependent",
                    "references": [1],
                    "features": [feature],
                }
            )
        state.claim_plan = {"claims": claims}
        return NodeResult.success(
            output={"claim_plan": state.claim_plan},
            trace_events=[{"event": "claim_plan_completed"}],
        )
