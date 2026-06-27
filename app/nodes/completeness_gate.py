from app.models.schemas import NodeResult, WorkflowState
from app.orchestrator.node_base import Node


class CompletenessGateNode(Node):
    """信息完整性检查节点。

    Returns:
        当前阶段默认放行的完整性 gate,后续任务会补充追问规则。
    """

    name = "completeness_gate"

    def __init__(self) -> None:
        super().__init__(name=self.name)

    def run(self, state: WorkflowState) -> NodeResult:
        """检查输入是否可继续进入特征抽取。

        Args:
            state: 当前工作流状态。

        Returns:
            当前实现默认返回 success,保持 workflow 可回归。
        """
        return NodeResult.success(trace_events=[{"event": "completeness_gate_completed"}])
