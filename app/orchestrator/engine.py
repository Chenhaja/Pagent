import logging
import time

from app.core.log_context import bind_context, reset_context
from app.core.logging import log_event
from app.models.schemas import NodeResult, WorkflowState
from app.orchestrator.node_base import Node
from app.orchestrator.workflow_defs import WorkflowDef


logger = logging.getLogger(__name__)


class Orchestrator:
    """轻量工作流编排器。

    Args:
        nodes: 可调度节点字典,key 为 workflow_def 中使用的节点名。

    Returns:
        可按预定义 workflow 顺序执行 node 的编排器。
    """

    def __init__(self, nodes: dict[str, Node]) -> None:
        self.nodes = nodes

    def run(self, state: WorkflowState, workflow_def: list[str] | WorkflowDef, max_loop_count: int | None = None) -> NodeResult:
        """按 workflow_def 顺序执行节点。

        Args:
            state: 当前工作流状态。
            workflow_def: 预定义节点名称序列或带元数据的 workflow 定义。
            max_loop_count: 局部回环最大次数,不传时读取 workflow_def 元数据。

        Returns:
            最后一个成功节点结果,或第一个失败 / 需要用户输入的节点结果。
        """
        node_names = workflow_def.nodes if isinstance(workflow_def, WorkflowDef) else workflow_def
        loop_limit = workflow_def.max_loop_count if isinstance(workflow_def, WorkflowDef) else (max_loop_count or 0)
        node_positions = {node_name: index for index, node_name in enumerate(node_names)}
        loop_counts: dict[str, int] = {}
        current_index = 0
        last_result = NodeResult.success()

        while current_index < len(node_names):
            node_name = node_names[current_index]
            node = self.nodes.get(node_name)
            if node is None:
                return NodeResult.failed(errors=[f"unknown_node:{node_name}"])

            token = bind_context(node_name=node_name)
            started_at = time.perf_counter()
            log_event(logger, logging.INFO, "node_start", "节点开始", node_name=node_name)
            try:
                result = node.run(state)
            finally:
                reset_context(token)
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            self._record_trace_events(state, result)
            if result.status == "success":
                log_event(logger, logging.INFO, "node_end", "节点完成", node_name=node_name, status=result.status, duration_ms=duration_ms)
            else:
                log_event(
                    logger,
                    logging.WARNING,
                    "node_error",
                    "节点失败",
                    node_name=node_name,
                    status=result.status,
                    duration_ms=duration_ms,
                    error_count=len(result.errors),
                )

            if result.status != "success":
                return result
            last_result = result

            if result.next_node is not None:
                if result.next_node not in node_positions:
                    return NodeResult.failed(errors=[f"illegal_next_node:{result.next_node}"])
                next_index = node_positions[result.next_node]
                if next_index <= current_index:
                    loop_counts[result.next_node] = loop_counts.get(result.next_node, 0) + 1
                    if loop_counts[result.next_node] > loop_limit:
                        return NodeResult.failed(errors=[f"loop_limit_exceeded:{result.next_node}"])
                current_index = next_index
                continue

            current_index += 1

        return last_result

    def _record_trace_events(self, state: WorkflowState, result: NodeResult) -> None:
        """把节点 trace 写入 workflow state。

        Args:
            state: 当前工作流状态。
            result: 节点执行结果。

        Returns:
            无返回值,会原地更新 state.trace。
        """
        for trace_event in result.trace_events:
            state.add_trace_event(
                event=str(trace_event.get("event", "node_event")),
                data=trace_event.get("data", {}),
            )
