import logging

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


class JumpNode(Node):
    """固定跳转到指定节点的 fake node。"""

    def __init__(self, name: str, next_node: str) -> None:
        super().__init__(name=name)
        self.target = next_node

    def run(self, state: WorkflowState) -> NodeResult:
        """返回带 next_node 的成功结果。

        Args:
            state: 工作流状态。

        Returns:
            带局部跳转目标的成功结果。
        """
        return NodeResult.success(next_node=self.target, trace_events=[{"event": f"{self.name}_completed"}])


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


def test_orchestrator_logs_node_lifecycle_events(caplog) -> None:
    """Orchestrator 应输出节点开始和完成事件日志。"""
    state = WorkflowState(raw_input="一种方法")
    orchestrator = Orchestrator(nodes={"first": RecordingNode("first", "first_done")})

    with caplog.at_level(logging.INFO, logger="app.orchestrator.engine"):
        result = orchestrator.run(state, workflow_def=["first"])

    assert result.status == "success"
    events = [record for record in caplog.records if getattr(record, "event", None) in {"node_start", "node_end"}]
    assert [record.event for record in events] == ["node_start", "node_end"]
    assert events[0].fields["node_name"] == "first"
    assert events[1].fields["node_name"] == "first"
    assert events[1].fields["status"] == "success"


def test_orchestrator_logs_node_error_event(caplog) -> None:
    """节点失败时 Orchestrator 应输出 node_error 事件。"""
    state = WorkflowState(raw_input="一种方法")
    orchestrator = Orchestrator(nodes={"fail": FailingNode("fail")})

    with caplog.at_level(logging.WARNING, logger="app.orchestrator.engine"):
        result = orchestrator.run(state, workflow_def=["fail"])

    assert result.status == "failed"
    error_record = next(record for record in caplog.records if getattr(record, "event", None) == "node_error")
    assert error_record.fields["node_name"] == "fail"
    assert error_record.fields["status"] == "failed"
    assert error_record.fields["error_count"] == 1


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


def test_orchestrator_honors_next_node_jump() -> None:
    """节点返回 next_node 时 orchestrator 应跳转到 workflow 内合法节点。"""
    state = WorkflowState(raw_input="一种方法")
    orchestrator = Orchestrator(
        nodes={
            "first": JumpNode("first", "third"),
            "second": RecordingNode("second", "second_done"),
            "third": RecordingNode("third", "third_done"),
        }
    )

    result = orchestrator.run(state, workflow_def=["first", "second", "third"])

    assert result.status == "success"
    assert [event["event"] for event in state.trace] == ["first_completed", "third_completed"]


def test_orchestrator_rejects_illegal_next_node() -> None:
    """next_node 不在 workflow 内时应结构化失败。"""
    state = WorkflowState(raw_input="一种方法")
    orchestrator = Orchestrator(nodes={"first": JumpNode("first", "missing")})

    result = orchestrator.run(state, workflow_def=["first"])

    assert result.status == "failed"
    assert result.errors == ["illegal_next_node:missing"]


def test_orchestrator_stops_when_loop_limit_exceeded() -> None:
    """局部回环超过上限时应结构化失败。"""
    state = WorkflowState(raw_input="一种方法")
    orchestrator = Orchestrator(nodes={"first": JumpNode("first", "first")})

    result = orchestrator.run(state, workflow_def=["first"], max_loop_count=1)

    assert result.status == "failed"
    assert result.errors == ["loop_limit_exceeded:first"]
