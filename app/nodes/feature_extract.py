from app.models.schemas import NodeResult, SkillContext, WorkflowState
from app.orchestrator.node_base import Node
from app.skills.feature_extraction import FeatureExtractionSkill


class FeatureExtractNode(Node):
    """技术特征提取节点。

    Args:
        skill: 技术特征提取 skill。

    Returns:
        将结构化技术特征写入 workflow state 的节点。
    """

    name = "feature_extract"

    def __init__(self, skill: FeatureExtractionSkill | None = None) -> None:
        super().__init__(name=self.name)
        self.skill = skill or FeatureExtractionSkill()

    def run(self, state: WorkflowState) -> NodeResult:
        """调用特征提取 skill 并写入技术特征。

        Args:
            state: 当前工作流状态。

        Returns:
            成功结果或特征提取失败结果。
        """
        context = SkillContext(
            task_type="feature_extract",
            state_snapshot={"normalized_input": state.normalized_input},
        )
        try:
            result = self.skill.run(context)
        except ValueError:
            return NodeResult.failed(errors=["feature_extract_failed"])
        state.technical_features = [
            {"name": feature, "required": True} for feature in result.required_features
        ] + [{"name": feature, "required": False} for feature in result.optional_features]
        return NodeResult.success(
            output={"technical_features": state.technical_features},
            trace_events=[{"event": "feature_extract_completed"}],
        )
