from app.models.schemas import WorkflowState
from app.nodes.completeness_gate import CompletenessGateNode


def test_completeness_gate_requires_user_input_when_core_info_missing() -> None:
    """信息缺失时 completeness gate 应追问并中断 workflow。"""
    state = WorkflowState(raw_input="请帮我写权利要求", normalized_input="请帮我写权利要求")
    node = CompletenessGateNode()

    result = node.run(state)

    assert result.status == "requires_user_input"
    assert result.requires_user_input is True
    assert result.errors == ["missing_technical_solution"]
    assert result.output == {"question": "请补充技术方案的核心步骤、组成部件或技术效果。"}


def test_completeness_gate_continues_to_feature_extract_when_info_sufficient() -> None:
    """信息充足时 completeness gate 应进入特征抽取节点。"""
    state = WorkflowState(raw_input="一种采集传感器数据并控制设备的方法", normalized_input="一种采集传感器数据并控制设备的方法")
    node = CompletenessGateNode()

    result = node.run(state)

    assert result.status == "success"
    assert result.next_node == "feature_extract"
    assert result.output == {"completeness": "sufficient"}
    assert result.trace_events == [{"event": "completeness_gate_completed", "data": {"completeness": "sufficient"}}]
