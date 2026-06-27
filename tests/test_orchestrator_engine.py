from app.models.schemas import NodeResult, WorkflowState
from app.orchestrator.engine import Orchestrator
from app.orchestrator.node_base import Node


class RecordingNode(Node):
    """记录执行顺序的 fake node。"""

    def __init__(self, name: str, marker: str) -> None:
        super().__init__(name=name)
        self.marker = marker

    def run(self, state: WorkflowState) -> NodeResult:
        """追加 trace 并返回成功结果。

        Args:
            state: 工作流状态。

        Returns:
            成功节点结果。
        """
        return NodeResult.success(
            output={self.marker: True},
            trace_events=[{"event": f"{self.name}_completed"}],
        )


class FailingNode(Node):
    """固定失败的 fake node。"""

    def run(self, state: WorkflowState) -> NodeResult:
        """返回失败结果。

        Args:
            state: 工作流状态。

        Returns:
            失败节点结果。
        """
        return NodeResult.failed(errors=["boom"])


class UserInputNode(Node):
    """固定要求用户输入的 fake node。"""

    def run(self, state: WorkflowState) -> NodeResult:
        """返回需要用户输入的结果。

        Args:
            state: 工作流状态。

        Returns:
            需要用户输入的节点结果。
        """
        return NodeResult.need_user_input(output={"question": "请补充信息"})


def test_orchestrator_runs_nodes_in_order_and_records_trace() -> None:
    """Orchestrator 应按 workflow_def 顺序执行节点并写入 trace。"""
    state = WorkflowState(raw_input="一种方法")
    orchestrator = Orchestrator(
        nodes={
            "first": RecordingNode("first", "first_done"),
            "second": RecordingNode("second", "second_done"),
        }
    )

    result = orchestrator.run(state, workflow_def=["first", "second"])

    assert result.status == "success"
    assert state.trace == [
        {"event": "first_completed", "data": {}},
        {"event": "second_completed", "data": {}},
    ]


def test_orchestrator_stops_on_failed_node() -> None:
    """节点失败时 orchestrator 应中断并返回失败结果。"""
    state = WorkflowState(raw_input="一种方法")
    orchestrator = Orchestrator(nodes={"fail": FailingNode("fail")})

    result = orchestrator.run(state, workflow_def=["fail"])

    assert result.status == "failed"
    assert result.errors == ["boom"]


def test_orchestrator_stops_when_user_input_required() -> None:
    """节点需要用户输入时 orchestrator 应中断并返回该结果。"""
    state = WorkflowState(raw_input="一种方法")
    orchestrator = Orchestrator(nodes={"ask": UserInputNode("ask")})

    result = orchestrator.run(state, workflow_def=["ask"])

    assert result.status == "requires_user_input"
    assert result.requires_user_input is True
    assert result.output == {"question": "请补充信息"}


def test_orchestrator_fails_on_unknown_node() -> None:
    """workflow_def 引用未知节点时应返回明确错误。"""
    state = WorkflowState(raw_input="一种方法")
    orchestrator = Orchestrator(nodes={})

    result = orchestrator.run(state, workflow_def=["missing"])

    assert result.status == "failed"
    assert result.errors == ["unknown_node:missing"]
