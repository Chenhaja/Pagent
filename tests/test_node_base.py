from app.models.schemas import NodeResult, WorkflowState
from app.orchestrator.node_base import Node


class FakeNode(Node):
    """用于测试 node 协议的 fake node。"""

    name = "fake_node"

    def run(self, state: WorkflowState) -> NodeResult:
        """返回固定成功结果。

        Args:
            state: 工作流状态。

        Returns:
            固定成功节点结果。
        """
        return NodeResult.success(output={"raw_input": state.raw_input})


def test_node_protocol_exposes_name_and_run() -> None:
    """Node 协议应统一暴露 name 和 run 方法。"""
    node = FakeNode()
    state = WorkflowState(raw_input="一种方法")

    result = node.run(state)

    assert node.name == "fake_node"
    assert result.status == "success"
    assert result.output == {"raw_input": "一种方法"}


def test_base_node_cannot_run_directly() -> None:
    """基础 Node 不应被直接执行。"""
    node = Node(name="base")
    state = WorkflowState(raw_input="一种方法")

    result = node.run(state)

    assert result.status == "failed"
    assert result.errors == ["node_not_implemented:base"]
