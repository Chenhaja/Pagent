from app.tools.retrieval import LocalRetrievalTool, RetrievalResult


def test_local_retrieval_tool_returns_predictable_results_with_provenance() -> None:
    """本地检索工具应返回可预测结果并附带 provenance。"""
    tool = LocalRetrievalTool(
        documents=[
            {"id": "doc-1", "text": "传感器数据采集与设备控制方案", "source": "local://case/doc-1"},
            {"id": "doc-2", "text": "电池管理系统", "source": "local://case/doc-2"},
        ]
    )

    results = tool.search("传感器 控制", top_k=2)

    assert results == [
        RetrievalResult(
            content="传感器数据采集与设备控制方案",
            provenance={"source": "local://case/doc-1", "document_id": "doc-1"},
            score=2,
        )
    ]


def test_local_retrieval_tool_returns_empty_when_no_match() -> None:
    """本地检索工具无命中时应返回空列表。"""
    tool = LocalRetrievalTool(documents=[{"id": "doc-1", "text": "传感器数据采集", "source": "local://case/doc-1"}])

    assert tool.search("电池", top_k=1) == []
