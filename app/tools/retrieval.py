import json
import logging
from datetime import date
from typing import Any, Protocol
from urllib import request

from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.core.security import redact_sensitive_text
from app.tools.embeddings import EmbeddingClient, OpenAICompatibleEmbeddingClient


class RetrievalResult(BaseModel):
    """本地检索结果。

    Args:
        content: 命中的文本片段。
        provenance: 来源信息,包含 source、document_id、doc_type、locator 等字段。
        score: 简单关键词命中分数。
        similarity: 向量相似度,本地后端默认为 0。
        law_name: 法规名称。
        version: 法规版本。
        effective_date: 生效日期。
        expiry_date: 失效日期。
        status: 版本状态。
        source_url: 官方来源 URL。
        retrieved_at: 入库检索日期。

    Returns:
        可供 QA / ReAct 使用的检索结果。
    """

    content: str
    provenance: dict[str, str] = Field(default_factory=dict)
    score: int = 0
    similarity: float = 0.0
    law_name: str | None = None
    version: str | None = None
    effective_date: str | None = None
    expiry_date: str | None = None
    status: str | None = None
    source_url: str | None = None
    retrieved_at: str | None = None


class Retriever(Protocol):
    """可替换检索器协议。

    Returns:
        支持按 query 和 top_k 返回检索结果的检索器。
    """

    def search(self, query: str, top_k: int = 3, as_of: str | None = None, fetch_k: int | None = None) -> list[RetrievalResult]:
        """检索与 query 相关的知识片段。

        Args:
            query: 检索查询文本。
            top_k: 最多返回结果数。
            as_of: 可选历史追溯日期。
            fetch_k: 可选候选召回数量,供重排或融合使用。

        Returns:
            检索结果列表。
        """
        ...

    def recall(self, query: str, fetch_k: int, as_of: str | None = None) -> list[RetrievalResult]:
        """召回候选结果供后续排序层使用。

        Args:
            query: 检索查询文本。
            fetch_k: 候选召回数量。
            as_of: 可选历史追溯日期。

        Returns:
            候选检索结果列表。
        """
        ...


class _QdrantHTTPHit:
    """Qdrant HTTP 命中结果。

    Args:
        payload: Qdrant payload。
        score: 相似度分数。

    Returns:
        兼容 QdrantRetriever 的命中对象。
    """

    def __init__(self, payload: dict[str, Any], score: float) -> None:
        self.payload = payload
        self.score = score


class _QdrantHTTPClient:
    """最小 Qdrant HTTP 客户端。

    Args:
        url: Qdrant 服务地址。
        api_key: 可选 API Key。

    Returns:
        支持 search 方法的 Qdrant 客户端。
    """

    def __init__(self, url: str, api_key: str | None = None) -> None:
        self.url = url.rstrip("/")
        self.api_key = api_key

    def search(
        self,
        collection_name: str,
        query_vector: list[float],
        limit: int,
        query_filter: dict[str, Any] | None = None,
    ) -> list[_QdrantHTTPHit]:
        """调用 Qdrant points search 接口。

        Args:
            collection_name: 集合名称。
            query_vector: 查询向量。
            limit: 最多返回数量。
            query_filter: 可选 Qdrant 过滤条件。

        Returns:
            Qdrant 命中列表。
        """
        payload = {"vector": query_vector, "limit": limit, "with_payload": True}
        if query_filter:
            payload["filter"] = query_filter
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["api-key"] = self.api_key
        http_request = request.Request(
            url=f"{self.url}/collections/{collection_name}/points/search",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with request.urlopen(http_request) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
        return [
            _QdrantHTTPHit(payload=item.get("payload") or {}, score=float(item.get("score") or 0.0))
            for item in response_payload.get("result", [])
        ]


def _payload_is_law(payload: dict[str, Any]) -> bool:
    """判断 payload 是否为法规材料。"""
    return payload.get("doc_type") == "law" or any(payload.get(key) for key in ("law_name", "effective_date", "status"))


def _parse_iso_date(value: Any) -> date | None:
    """安全解析 ISO 日期。"""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _law_matches_time(payload: dict[str, Any], settings: Settings, as_of: str | None = None) -> bool:
    """判断法规 payload 是否满足时间过滤条件。"""
    if not settings.retrieval_enable_time_filter or not _payload_is_law(payload):
        return True
    if as_of:
        target_date = _parse_iso_date(as_of)
        effective_date = _parse_iso_date(payload.get("effective_date"))
        expiry_date = _parse_iso_date(payload.get("expiry_date"))
        if target_date is None or effective_date is None:
            return False
        return effective_date <= target_date and (expiry_date is None or expiry_date > target_date)
    return payload.get("status") == settings.retrieval_default_status


def _build_qdrant_time_filter(settings: Settings, as_of: str | None = None) -> dict[str, Any] | None:
    """构造非 law 或法规时间匹配的 Qdrant 过滤条件。"""
    if not settings.retrieval_enable_time_filter:
        return None
    non_law = {"must_not": [{"key": "doc_type", "match": {"value": "law"}}]}
    if as_of:
        law_filter = {
            "must": [
                {"key": "doc_type", "match": {"value": "law"}},
                {"key": "effective_date", "range": {"lte": as_of}},
            ],
            "should": [
                {"key": "expiry_date", "is_null": True},
                {"key": "expiry_date", "range": {"gt": as_of}},
            ],
        }
    else:
        law_filter = {
            "must": [
                {"key": "doc_type", "match": {"value": "law"}},
                {"key": "status", "match": {"value": settings.retrieval_default_status}},
            ]
        }
    return {"should": [non_law, law_filter]}


def _result_time_fields(payload: dict[str, Any]) -> dict[str, str | None]:
    """从 payload 提取法规时效字段。"""
    return {key: str(payload[key]) if payload.get(key) is not None else None for key in _TIME_FIELD_KEYS}


_TIME_FIELD_KEYS = ("law_name", "version", "effective_date", "expiry_date", "status", "source_url", "retrieved_at")
logger = logging.getLogger(__name__)


class QdrantRetriever:
    """Qdrant 向量检索器。

    Args:
        collection_name: Qdrant 集合名称。
        embedding_client: 文本向量化客户端。
        qdrant_client: Qdrant 客户端,测试可注入 fake。

    Returns:
        基于向量召回的检索器。
    """

    def __init__(
        self,
        collection_name: str,
        embedding_client: EmbeddingClient,
        qdrant_client: Any,
        settings: Settings | None = None,
    ) -> None:
        self.collection_name = collection_name
        self.embedding_client = embedding_client
        self.qdrant_client = qdrant_client
        self.settings = settings or get_settings()

    def search(self, query: str, top_k: int = 3, as_of: str | None = None, fetch_k: int | None = None) -> list[RetrievalResult]:
        """执行单轮 Qdrant 向量检索。

        Args:
            query: 检索查询文本。
            top_k: 最多返回结果数。
            as_of: 可选历史追溯日期。
            fetch_k: 可选候选召回数量,未配置时等于 top_k。

        Returns:
            按 Qdrant 相似度排序的检索结果;依赖失败时返回空列表。
        """
        return self.recall(query, fetch_k or top_k, as_of)[:top_k]

    def recall(self, query: str, fetch_k: int, as_of: str | None = None) -> list[RetrievalResult]:
        """执行 Qdrant 候选召回。

        Args:
            query: 检索查询文本。
            fetch_k: 候选召回数量。
            as_of: 可选历史追溯日期。

        Returns:
            按 Qdrant 相似度排序的候选结果;依赖失败时返回空列表。
        """
        try:
            query_vector = self.embedding_client.embed(query)
            if not query_vector:
                return []
            query_filter = _build_qdrant_time_filter(self.settings, as_of)
            hits = self.qdrant_client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=fetch_k,
                query_filter=query_filter,
            )
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
                    **_result_time_fields(payload),
                )
            )
        return results[:fetch_k]


class LocalRetrievalTool:
    """本地 mock 检索工具。

    Args:
        documents: 本地文档列表,每条包含 id、text、source。

    Returns:
        基于关键词匹配的可预测检索工具。
    """

    def __init__(self, documents: list[dict[str, str]] | None = None, settings: Settings | None = None) -> None:
        self.documents = documents or []
        self.settings = settings or get_settings()

    def search(self, query: str, top_k: int = 3, as_of: str | None = None, fetch_k: int | None = None) -> list[RetrievalResult]:
        """按关键词检索本地文档。

        Args:
            query: 检索查询文本。
            top_k: 最多返回结果数。
            as_of: 可选历史追溯日期。
            fetch_k: 可选候选召回数量,未配置时等于 top_k。

        Returns:
            按命中分数降序排列的检索结果列表。
        """
        return self.recall(query, fetch_k or top_k, as_of)[:top_k]

    def recall(self, query: str, fetch_k: int, as_of: str | None = None) -> list[RetrievalResult]:
        """按关键词召回本地候选文档。

        Args:
            query: 检索查询文本。
            fetch_k: 候选召回数量。
            as_of: 可选历史追溯日期。

        Returns:
            按命中分数降序排列的候选结果列表。
        """
        keywords = [keyword for keyword in query.split() if keyword]
        results = []
        for document in self.documents:
            text = document.get("text", "")
            score = sum(1 for keyword in keywords if keyword in text)
            if score <= 0 or not _law_matches_time(document, self.settings, as_of):
                continue
            provenance = {
                "source": document.get("source", "local://unknown"),
                "document_id": document.get("id", "unknown"),
            }
            for key in ("doc_type", "locator"):
                if document.get(key):
                    provenance[key] = document[key]
            payload = dict(document)
            payload.setdefault("document_id", provenance["document_id"])
            payload.setdefault("source", provenance["source"])
            results.append(
                RetrievalResult(
                    content=text,
                    provenance=provenance,
                    score=score,
                    **_result_time_fields(payload),
                )
            )
        return sorted(results, key=lambda result: result.score, reverse=True)[:fetch_k]


class Reranker(Protocol):
    """检索结果重排器协议。

    Returns:
        支持按 query 对候选文档重排的组件。
    """

    def rerank(self, query: str, documents: list[RetrievalResult], top_n: int | None = None) -> list[RetrievalResult]:
        """对候选检索结果重排。

        Args:
            query: 原始检索问题。
            documents: 待重排候选文档。
            top_n: 可选返回数量。

        Returns:
            重排后的检索结果列表。
        """
        ...


class FakeReranker:
    """测试用重排器。

    Args:
        scores: 按 document_id 注入的重排分数。

    Returns:
        可预测排序的重排器。
    """

    def __init__(self, scores: dict[str, float] | None = None) -> None:
        self.scores = scores or {}

    def rerank(self, query: str, documents: list[RetrievalResult], top_n: int | None = None) -> list[RetrievalResult]:
        """按注入分数重排候选文档。

        Args:
            query: 原始检索问题。
            documents: 待重排候选文档。
            top_n: 可选返回数量。

        Returns:
            按分数降序排列的检索结果。
        """
        ranked = []
        for document in documents:
            document_id = document.provenance.get("document_id", "")
            ranked.append(document.model_copy(update={"similarity": self.scores.get(document_id, document.similarity)}))
        return sorted(ranked, key=lambda result: result.similarity, reverse=True)[: top_n or len(ranked)]


class HTTPReranker:
    """HTTP 重排器。

    Args:
        settings: 应用配置。
        urlopen: 可注入 HTTP 调用函数,便于测试。

    Returns:
        调用外部 rerank 服务的重排器。
    """

    def __init__(self, settings: Settings, urlopen: Any | None = None) -> None:
        self.settings = settings
        self.urlopen = urlopen or request.urlopen

    def rerank(self, query: str, documents: list[RetrievalResult], top_n: int | None = None) -> list[RetrievalResult]:
        """调用 HTTP 服务对候选文档重排。

        Args:
            query: 原始检索问题。
            documents: 待重排候选文档。
            top_n: 可选返回数量。

        Returns:
            重排后的检索结果列表;未配置服务时返回原候选截断结果。
        """
        if not self.settings.rerank_base_url or not self.settings.rerank_model:
            return documents[: top_n or len(documents)]
        payload = {
            "model": self.settings.rerank_model,
            "query": query,
            "documents": [redact_sensitive_text(document.content) for document in documents],
            "top_n": top_n,
        }
        headers = {"Content-Type": "application/json"}
        if self.settings.rerank_api_key:
            headers["Authorization"] = f"Bearer {self.settings.rerank_api_key}"
        http_request = request.Request(
            url=f"{self.settings.rerank_base_url.rstrip('/')}/rerank",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with self.urlopen(http_request, timeout=self.settings.retrieval_timeout_seconds) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
        ranked = []
        for item in response_payload.get("results", []):
            index = int(item.get("index", -1))
            if 0 <= index < len(documents):
                ranked.append(documents[index].model_copy(update={"similarity": float(item.get("score") or 0.0)}))
        return ranked[: top_n or len(ranked)]


class RerankingRetriever:
    """重排检索包装器。

    Args:
        inner: 内层候选召回器。
        reranker: 重排器。
        settings: 应用配置。

    Returns:
        先宽召回再重排的检索器。
    """

    def __init__(self, inner: Retriever, reranker: Reranker, settings: Settings | None = None) -> None:
        self.inner = inner
        self.reranker = reranker
        self.settings = settings or get_settings()

    def search(self, query: str, top_k: int = 3, as_of: str | None = None, fetch_k: int | None = None) -> list[RetrievalResult]:
        """宽召回后执行重排检索。

        Args:
            query: 检索查询文本。
            top_k: 最多返回结果数。
            as_of: 可选历史追溯日期。
            fetch_k: 可选候选召回数量。

        Returns:
            重排后的检索结果;重排失败时返回宽召回前 top_k。
        """
        candidates = self.inner.recall(query, fetch_k or self.settings.retrieval_fetch_k, as_of)
        if not candidates:
            return []
        final_top_k = self.settings.rerank_top_k or top_k
        try:
            return self.reranker.rerank(query, candidates, final_top_k)[:final_top_k]
        except Exception:
            logger.warning(
                "重排失败,已降级为宽召回结果",
                extra={"event": "rerank_failed", "error": redact_sensitive_text("rerank provider failed")},
            )
            return candidates[:top_k]

    def recall(self, query: str, fetch_k: int, as_of: str | None = None) -> list[RetrievalResult]:
        """召回重排前候选结果。

        Args:
            query: 检索查询文本。
            fetch_k: 候选召回数量。
            as_of: 可选历史追溯日期。

        Returns:
            内层召回候选结果。
        """
        return self.inner.recall(query, fetch_k, as_of)


def build_retriever(
    settings: Settings | None = None,
    embedding_client: EmbeddingClient | None = None,
    qdrant_client: Any | None = None,
) -> Retriever:
    """根据配置构建检索器。

    Args:
        settings: 应用配置,未传入时读取全局配置。
        embedding_client: 可选 embedding 客户端,测试可注入 fake。
        qdrant_client: 可选 Qdrant 客户端,测试可注入 fake。

    Returns:
        配置可用时返回对应后端;不可用时回退本地检索器。
    """
    resolved_settings = settings or get_settings()
    backend = resolved_settings.retrieval_backend.strip().lower()
    if backend != "qdrant":
        return LocalRetrievalTool()
    if not resolved_settings.qdrant_url and qdrant_client is None:
        return LocalRetrievalTool()
    if not resolved_settings.embedding_model and embedding_client is None:
        return LocalRetrievalTool()
    try:
        resolved_embedding = embedding_client or OpenAICompatibleEmbeddingClient(settings=resolved_settings)
        resolved_qdrant = qdrant_client or _QdrantHTTPClient(resolved_settings.qdrant_url or "", resolved_settings.qdrant_api_key)
        return QdrantRetriever(
            collection_name=resolved_settings.qdrant_collection,
            embedding_client=resolved_embedding,
            qdrant_client=resolved_qdrant,
            settings=resolved_settings,
        )
    except Exception:
        return LocalRetrievalTool()
