from app.models.schemas import NodeResult, WorkflowState


class Node:
    """工作流节点基础协议。

    Args:
        name: 节点名称,用于 workflow_def、trace 和错误定位。

    Returns:
        可被 orchestrator 调度的节点对象。
    """

    name: str = "node"

    def __init__(self, name: str | None = None) -> None:
        self.name = name or self.name

    def run(self, state: WorkflowState) -> NodeResult:
        """执行节点逻辑。

        Args:
            state: 当前工作流状态。

        Returns:
            默认失败结果,子类应覆盖该方法。
        """
        return NodeResult.failed(errors=[f"node_not_implemented:{self.name}"])
