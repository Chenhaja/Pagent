from app.models.schemas import WorkflowState
from app.nodes.claim_plan import ClaimPlanNode


def test_claim_plan_node_creates_independent_and_dependent_layout() -> None:
    """权利要求布局 node 应基于技术特征生成独权和从权布局。"""
    state = WorkflowState(
        raw_input="",
        technical_features=[
            {"name": "采集传感器数据", "required": True},
            {"name": "过滤异常数据", "required": False},
        ],
    )
    node = ClaimPlanNode()

    result = node.run(state)

    assert result.status == "success"
    assert state.claim_plan == {
        "claims": [
            {"number": 1, "claim_type": "independent", "features": ["采集传感器数据"]},
            {"number": 2, "claim_type": "dependent", "references": [1], "features": ["过滤异常数据"]},
        ]
    }


def test_claim_plan_node_fails_without_required_features() -> None:
    """权利要求布局 node 缺少必要技术特征时应失败。"""
    state = WorkflowState(raw_input="", technical_features=[{"name": "过滤异常数据", "required": False}])
    node = ClaimPlanNode()

    result = node.run(state)

    assert result.status == "failed"
    assert result.errors == ["missing_required_features"]
