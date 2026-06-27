from app.models.schemas import WorkflowState
from app.nodes.feature_extract import FeatureExtractNode
from app.skills.feature_extraction import FeatureExtractionSkill


def test_feature_extract_node_writes_technical_features() -> None:
    """技术特征提取 node 应调用 skill 并写入 workflow state。"""
    skill = FeatureExtractionSkill(
        fake_output={
            "required_features": ["采集传感器数据"],
            "optional_features": ["过滤异常数据"],
        }
    )
    node = FeatureExtractNode(skill=skill)
    state = WorkflowState(raw_input="", normalized_input="一种控制方法")

    result = node.run(state)

    assert result.status == "success"
    assert state.technical_features == [
        {"name": "采集传感器数据", "required": True},
        {"name": "过滤异常数据", "required": False},
    ]


def test_feature_extract_node_returns_failed_when_skill_output_invalid() -> None:
    """技术特征提取 node 应捕获 fake skill 输出 schema 错误。"""
    skill = FeatureExtractionSkill(fake_output={"optional_features": ["过滤异常数据"]})
    node = FeatureExtractNode(skill=skill)
    state = WorkflowState(raw_input="", normalized_input="一种控制方法")

    result = node.run(state)

    assert result.status == "failed"
    assert result.errors == ["feature_extract_failed"]
