from pydantic import BaseModel, Field


class RetrievalResult(BaseModel):
    """本地检索结果。

    Args:
        content: 命中的文本片段。
        provenance: 来源信息,包含 source 和 document_id。
        score: 简单关键词命中分数。

    Returns:
        可供 QA / ReAct 使用的检索结果。
    """

    content: str
    provenance: dict[str, str] = Field(default_factory=dict)
    score: int = 0


class LocalRetrievalTool:
    """本地 mock 检索工具。

    Args:
        documents: 本地文档列表,每条包含 id、text、source。

    Returns:
        基于关键词匹配的可预测检索工具。
    """

    def __init__(self, documents: list[dict[str, str]] | None = None) -> None:
        self.documents = documents or []

    def search(self, query: str, top_k: int = 3) -> list[RetrievalResult]:
        """按关键词检索本地文档。

        Args:
            query: 检索查询文本。
            top_k: 最多返回结果数。

        Returns:
            按命中分数降序排列的检索结果列表。
        """
        keywords = [keyword for keyword in query.split() if keyword]
        results = []
        for document in self.documents:
            text = document.get("text", "")
            score = sum(1 for keyword in keywords if keyword in text)
            if score <= 0:
                continue
            results.append(
                RetrievalResult(
                    content=text,
                    provenance={
                        "source": document.get("source", "local://unknown"),
                        "document_id": document.get("id", "unknown"),
                    },
                    score=score,
                )
            )
        return sorted(results, key=lambda result: result.score, reverse=True)[:top_k]
