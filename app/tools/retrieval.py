from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.tools.embeddings import EmbeddingClient


class RetrievalResult(BaseModel):
    """本地检索结果。

    Args:
        content: 命中的文本片段。
        provenance: 来源信息,包含 source、document_id、doc_type、locator 等字段。
        score: 简单关键词命中分数。
        similarity: 向量相似度,本地后端默认为 0。

    Returns:
        可供 QA / ReAct 使用的检索结果。
    """

    content: str
    provenance: dict[str, str] = Field(default_factory=dict)
    score: int = 0
    similarity: float = 0.0


class Retriever(Protocol):
    """可替换检索器协议。

    Returns:
        支持按 query 和 top_k 返回检索结果的检索器。
    """

    def search(self, query: str, top_k: int = 3) -> list[RetrievalResult]:
        """检索与 query 相关的知识片段。

        Args:
            query: 检索查询文本。
            top_k: 最多返回结果数。

        Returns:
            检索结果列表。
        """
        ...


class QdrantRetriever:
    """Qdrant 向量检索器。

    Args:
        collection_name: Qdrant 集合名称。
        embedding_client: 文本向量化客户端。
        qdrant_client: Qdrant 客户端,测试可注入 fake。

    Returns:
        基于向量召回的检索器。
    """

    def __init__(self, collection_name: str, embedding_client: EmbeddingClient, qdrant_client: Any) -> None:
        self.collection_name = collection_name
        self.embedding_client = embedding_client
        self.qdrant_client = qdrant_client

    def search(self, query: str, top_k: int = 3) -> list[RetrievalResult]:
        """执行单轮 Qdrant 向量检索。

        Args:
            query: 检索查询文本。
            top_k: 最多返回结果数。

        Returns:
            按 Qdrant 相似度排序的检索结果;依赖失败时返回空列表。
        """
        try:
            query_vector = self.embedding_client.embed(query)
            if not query_vector:
                return []
            hits = self.qdrant_client.search(collection_name=self.collection_name, query_vector=query_vector, limit=top_k)
        except Exception:
            return []

        results = []
        for hit in hits:
            payload = getattr(hit, "payload", {}) or {}
            content = str(payload.get("content", ""))
            if not content:
                continue
            provenance = {
                "source": str(payload.get("source", "local://unknown")),
                "document_id": str(payload.get("document_id", "unknown")),
            }
            for key in ("doc_type", "locator"):
                if payload.get(key):
                    provenance[key] = str(payload[key])
            results.append(
                RetrievalResult(
                    content=content,
                    provenance=provenance,
                    similarity=float(getattr(hit, "score", 0.0) or 0.0),
                )
            )
        return results[:top_k]


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
            provenance = {
                "source": document.get("source", "local://unknown"),
                "document_id": document.get("id", "unknown"),
            }
            for key in ("doc_type", "locator"):
                if document.get(key):
                    provenance[key] = document[key]
            results.append(
                RetrievalResult(
                    content=text,
                    provenance=provenance,
                    score=score,
                )
            )
        return sorted(results, key=lambda result: result.score, reverse=True)[:top_k]
