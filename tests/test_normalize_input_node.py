from app.models.schemas import WorkflowState
from app.nodes.normalize_input import NormalizeInputNode


def test_normalize_input_node_preserves_raw_input_and_normalizes_text() -> None:
    """输入归一化 node 应保留原文并生成轻量归一化文本。"""
    state = WorkflowState(raw_input="  一种\n控制方法  ")
    node = NormalizeInputNode()

    result = node.run(state)

    assert result.status == "success"
    assert state.raw_input == "  一种\n控制方法  "
    assert state.normalized_input == "一种 控制方法"


def test_normalize_input_node_uses_dialog_context_without_guessing_content() -> None:
    """输入归一化 node 可拼接多轮指代上下文但不臆测技术内容。"""
    state = WorkflowState(raw_input="把它写成权利要求", dialog_context={"last_user_input": "一种控制方法"})
    node = NormalizeInputNode()

    result = node.run(state)

    assert result.status == "success"
    assert state.normalized_input == "一种控制方法 把它写成权利要求"


def test_normalize_input_node_requires_user_input_when_empty() -> None:
    """输入归一化 node 遇到空输入时应请求用户补充。"""
    state = WorkflowState(raw_input="   ")
    node = NormalizeInputNode()

    result = node.run(state)

    assert result.status == "requires_user_input"
    assert result.requires_user_input is True
    assert result.errors == ["empty_raw_input"]
