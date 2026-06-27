from app.tools.terminology import TerminologyTool


def test_terminology_tool_returns_matched_terms() -> None:
    """术语工具应返回文本中命中的固定术语。"""
    tool = TerminologyTool(terms={"控制方法": "control method", "传感器": "sensor"})

    result = tool.normalize("一种控制方法")

    assert result == {"控制方法": "control method"}


def test_terminology_tool_returns_empty_when_no_match() -> None:
    """术语未命中时应返回空字典。"""
    tool = TerminologyTool(terms={"控制方法": "control method"})

    assert tool.normalize("一种装置") == {}
