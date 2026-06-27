from app.models.schemas import NodeResult, WorkflowState
from app.orchestrator.node_base import Node


class NormalizeInputNode(Node):
    """用户输入归一化节点。

    Returns:
        保留 raw_input 并写入 normalized_input 的工作流节点。
    """

    name = "normalize_input"

    def run(self, state: WorkflowState) -> NodeResult:
        """归一化用户输入文本。

        Args:
            state: 当前工作流状态。

        Returns:
            成功结果或需要用户补充输入的结果。
        """
        raw_input = " ".join(state.raw_input.split())
        if not raw_input:
            return NodeResult.need_user_input(errors=["empty_raw_input"])

        previous_input = state.dialog_context.get("last_user_input")
        if previous_input:
            state.normalized_input = f"{' '.join(str(previous_input).split())} {raw_input}"
        else:
            state.normalized_input = raw_input
        return NodeResult.success(
            output={"normalized_input": state.normalized_input},
            trace_events=[{"event": "normalize_input_completed"}],
        )
