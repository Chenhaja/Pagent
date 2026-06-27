from app.models.schemas import NodeResult, WorkflowState
from app.orchestrator.node_base import Node


class CompletenessGateNode(Node):
    """信息完整性检查节点。

    Returns:
        根据信息完整性决定追问或进入特征抽取的 workflow 节点。
    """

    name = "completeness_gate"
    sufficient_keywords = ("方法", "装置", "系统", "步骤", "部件", "模块", "采集", "控制", "生成", "检测", "处理")

    def __init__(self) -> None:
        super().__init__(name=self.name)

    def run(self, state: WorkflowState) -> NodeResult:
        """检查输入是否可继续进入特征抽取。

        Args:
            state: 当前 workflow 状态。

        Returns:
            信息缺失时返回追问结果;信息充足时跳转到 feature_extract。
        """
        normalized_input = state.normalized_input or state.raw_input
        if not any(keyword in normalized_input for keyword in self.sufficient_keywords):
            return NodeResult.need_user_input(
                output={"question": "请补充技术方案的核心步骤、组成部件或技术效果。"},
                errors=["missing_technical_solution"],
            )
        return NodeResult.success(
            output={"completeness": "sufficient"},
            next_node="feature_extract",
            trace_events=[{"event": "completeness_gate_completed", "data": {"completeness": "sufficient"}}],
        )
