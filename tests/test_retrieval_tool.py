from app.tools.retrieval import LocalRetrievalTool, RetrievalResult, Retriever


def test_retrieval_result_keeps_backward_compatibility_with_similarity_default() -> None:
    """检索结果新增 similarity 时不应破坏旧构造方式。"""
    result = RetrievalResult(content="材料", provenance={"source": "local://doc", "document_id": "doc"}, score=1)

    assert result.similarity == 0.0


def test_local_retrieval_tool_satisfies_retriever_protocol() -> None:
    """本地检索工具应满足 Retriever 协议。"""
    retriever: Retriever = LocalRetrievalTool()

    assert retriever.search("任意问题") == []


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


def test_local_retrieval_tool_passes_extended_provenance() -> None:
    """本地检索工具应透传文档中的扩展 provenance。"""
    tool = LocalRetrievalTool(
        documents=[
            {
                "id": "law-22",
                "text": "授予专利权的发明应当具备新颖性、创造性和实用性。",
                "source": "local://law/patent_law.md",
                "doc_type": "law",
                "locator": "第22条",
            }
        ]
    )

    results = tool.search("创造性", top_k=1)

    assert results == [
        RetrievalResult(
            content="授予专利权的发明应当具备新颖性、创造性和实用性。",
            provenance={
                "source": "local://law/patent_law.md",
                "document_id": "law-22",
                "doc_type": "law",
                "locator": "第22条",
            },
            score=1,
        )
    ]
