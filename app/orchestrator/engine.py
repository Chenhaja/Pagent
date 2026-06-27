from app.models.schemas import NodeResult, WorkflowState
from app.orchestrator.node_base import Node


class Orchestrator:
    """轻量工作流编排器。

    Args:
        nodes: 可调度节点字典,key 为 workflow_def 中使用的节点名。

    Returns:
        可按预定义 workflow 顺序执行 node 的编排器。
    """

    def __init__(self, nodes: dict[str, Node]) -> None:
        self.nodes = nodes

    def run(self, state: WorkflowState, workflow_def: list[str]) -> NodeResult:
        """按 workflow_def 顺序执行节点。

        Args:
            state: 当前工作流状态。
            workflow_def: 预定义节点名称序列。

        Returns:
            最后一个成功节点结果,或第一个失败 / 需要用户输入的节点结果。
        """
        last_result = NodeResult.success()
        for node_name in workflow_def:
            node = self.nodes.get(node_name)
            if node is None:
                return NodeResult.failed(errors=[f"unknown_node:{node_name}"])

            result = node.run(state)
            for trace_event in result.trace_events:
                state.add_trace_event(
                    event=str(trace_event.get("event", "node_event")),
                    data=trace_event.get("data", {}),
                )

            if result.status != "success":
                return result
            last_result = result

        return last_result
