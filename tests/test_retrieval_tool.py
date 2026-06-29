import json

from app.core.config import Settings
from app.tools.embeddings import FakeEmbedding, OpenAICompatibleEmbeddingClient
from app.tools.retrieval import LocalRetrievalTool, QdrantRetriever, RetrievalResult, Retriever, build_retriever


class FakeQdrantHit:
    """测试用 Qdrant 命中对象。"""

    def __init__(self, payload: dict, score: float) -> None:
        self.payload = payload
        self.score = score


class FakeQdrantClient:
    """测试用 Qdrant client。"""

    def __init__(self, hits: list[FakeQdrantHit] | None = None, should_raise: bool = False) -> None:
        self.hits = hits or []
        self.should_raise = should_raise
        self.calls = []

    def search(self, collection_name: str, query_vector: list[float], limit: int, query_filter: dict | None = None):
        """记录查询参数并返回固定命中。"""
        self.calls.append({"collection_name": collection_name, "query_vector": query_vector, "limit": limit, "query_filter": query_filter})
        if self.should_raise:
            raise RuntimeError("qdrant failed")
        return self.hits[:limit]


class RaisingEmbedding:
    """测试用异常 embedding。"""

    def embed(self, text: str) -> list[float]:
        """模拟 embedding 失败。"""
        raise RuntimeError("embedding failed")


class FakeHTTPResponse:
    """测试用 HTTP 响应。"""

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self) -> bytes:
        """返回 JSON 响应字节。"""
        return json.dumps(self.payload).encode("utf-8")


def test_retrieval_result_keeps_backward_compatibility_with_similarity_default() -> None:
    """检索结果新增 similarity 时不应破坏旧构造方式。"""
    result = RetrievalResult(content="材料", provenance={"source": "local://doc", "document_id": "doc"}, score=1)

    assert result.similarity == 0.0
    assert result.law_name is None
    assert result.version is None
    assert result.effective_date is None
    assert result.expiry_date is None
    assert result.status is None
    assert result.source_url is None
    assert result.retrieved_at is None


def test_local_retrieval_tool_satisfies_retriever_protocol() -> None:
    """本地检索工具应满足 Retriever 协议。"""
    retriever: Retriever = LocalRetrievalTool()

    assert retriever.search("任意问题") == []


def test_fake_embedding_returns_predictable_vector_and_records_text() -> None:
    """Fake embedding 应返回可预测向量并记录调用文本。"""
    embedding = FakeEmbedding(vector=[0.1, 0.2, 0.3])

    assert embedding.embed("测试文本") == [0.1, 0.2, 0.3]
    assert embedding.calls == ["测试文本"]


def test_openai_compatible_embedding_client_parses_vector_and_redacts_input() -> None:
    """OpenAI 兼容 embedding 客户端应解析向量并在发送前脱敏。"""
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeHTTPResponse({"data": [{"embedding": [0.4, 0.5]}]})

    settings = Settings(
        llm_base_url="https://llm.example.test/v1",
        llm_api_key="llm-secret",
        embedding_model="embedding-model",
    )
    client = OpenAICompatibleEmbeddingClient(settings=settings, urlopen=fake_urlopen)

    vector = client.embed("问题包含 sk-sensitive-secret")

    assert vector == [0.4, 0.5]
    assert captured["url"] == "https://llm.example.test/v1/embeddings"
    assert captured["timeout"] == settings.llm_timeout
    assert captured["payload"] == {"model": "embedding-model", "input": "问题包含 [REDACTED]"}
    assert captured["headers"]["Authorization"] == "Bearer llm-secret"


def test_openai_compatible_embedding_client_returns_empty_on_provider_error() -> None:
    """Embedding provider 异常时应返回空向量供上层降级。"""
    settings = Settings(embedding_base_url="https://embedding.example.test/v1", embedding_model="embedding-model", embedding_api_key="secret")
    client = OpenAICompatibleEmbeddingClient(settings=settings, urlopen=lambda request, timeout: (_ for _ in ()).throw(RuntimeError("boom secret")))

    assert client.embed("问题") == []


def test_qdrant_retriever_maps_hits_to_retrieval_results() -> None:
    """Qdrant 检索器应把命中 payload 映射为检索结果。"""
    embedding = FakeEmbedding(vector=[0.1, 0.2])
    qdrant = FakeQdrantClient(
        hits=[
            FakeQdrantHit(
                payload={
                    "content": "授予专利权的发明应具备创造性。",
                    "source": "local://law/patent_law.md",
                    "document_id": "patent_law",
                    "doc_type": "law",
                    "locator": "第22条",
                },
                score=0.87,
            )
        ]
    )
    retriever = QdrantRetriever(collection_name="patent_kb", embedding_client=embedding, qdrant_client=qdrant)

    results = retriever.search("创造性", top_k=1)

    assert embedding.calls == ["创造性"]
    assert qdrant.calls == [
        {
            "collection_name": "patent_kb",
            "query_vector": [0.1, 0.2],
            "limit": 1,
            "query_filter": {"should": [{"must_not": [{"key": "doc_type", "match": {"value": "law"}}]}, {"must": [{"key": "doc_type", "match": {"value": "law"}}, {"key": "status", "match": {"value": "current"}}]}]},
        }
    ]
    assert results == [
        RetrievalResult(
            content="授予专利权的发明应具备创造性。",
            provenance={
                "source": "local://law/patent_law.md",
                "document_id": "patent_law",
                "doc_type": "law",
                "locator": "第22条",
            },
            similarity=0.87,
        )
    ]


def test_qdrant_retriever_maps_procedure_provenance() -> None:
    """Qdrant procedure payload 应透传 doc_type 和 locator。"""
    embedding = FakeEmbedding(vector=[0.1])
    qdrant = FakeQdrantClient(
        hits=[
            FakeQdrantHit(
                payload={
                    "content": "【专利申请受理 / 材料】\n应提交请求书。",
                    "source": "local://procedure/专利.md",
                    "document_id": "procedure/专利/专利申请受理",
                    "doc_type": "procedure",
                    "locator": "办事指南·专利申请受理·材料",
                },
                score=0.91,
            )
        ]
    )

    results = QdrantRetriever("patent_kb", embedding, qdrant).search("请求书", top_k=1)

    assert results == [
        RetrievalResult(
            content="【专利申请受理 / 材料】\n应提交请求书。",
            provenance={
                "source": "local://procedure/专利.md",
                "document_id": "procedure/专利/专利申请受理",
                "doc_type": "procedure",
                "locator": "办事指南·专利申请受理·材料",
            },
            similarity=0.91,
        )
    ]


def test_qdrant_retriever_returns_empty_when_dependencies_fail() -> None:
    """Qdrant 检索器依赖失败时应返回空列表。"""
    assert QdrantRetriever("patent_kb", RaisingEmbedding(), FakeQdrantClient()).search("问题") == []
    assert QdrantRetriever("patent_kb", FakeEmbedding([0.1]), FakeQdrantClient(should_raise=True)).search("问题") == []


def test_build_retriever_returns_local_backend_by_default() -> None:
    """检索工厂默认应返回本地后端。"""
    retriever = build_retriever(Settings())

    assert isinstance(retriever, LocalRetrievalTool)


def test_build_retriever_returns_qdrant_backend_with_injected_dependencies() -> None:
    """检索工厂应能用注入依赖构建 Qdrant 后端。"""
    retriever = build_retriever(
        Settings(retrieval_backend="qdrant", qdrant_url="http://qdrant.example.test", embedding_model="embedding-model"),
        embedding_client=FakeEmbedding([0.1]),
        qdrant_client=FakeQdrantClient(),
    )

    assert isinstance(retriever, QdrantRetriever)


def test_build_retriever_falls_back_to_local_when_backend_unavailable() -> None:
    """检索工厂配置缺失或未知后端时应回退本地后端。"""
    assert isinstance(build_retriever(Settings(retrieval_backend="unknown")), LocalRetrievalTool)
    assert isinstance(build_retriever(Settings(retrieval_backend="qdrant")), LocalRetrievalTool)


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


def test_local_retrieval_tool_filters_law_by_current_status() -> None:
    """本地检索默认只返回 current 法规且不影响非 law。"""
    tool = LocalRetrievalTool(
        documents=[
            {
                "id": "law-2020",
                "text": "创造性 现行版本",
                "source": "local://law/current",
                "doc_type": "law",
                "status": "current",
                "effective_date": "2021-06-01",
                "law_name": "中华人民共和国专利法",
                "version": "2020修正",
            },
            {
                "id": "law-2008",
                "text": "创造性 历史版本",
                "source": "local://law/old",
                "doc_type": "law",
                "status": "superseded",
                "effective_date": "2009-10-01",
                "expiry_date": "2021-06-01",
            },
            {"id": "template-1", "text": "创造性 模板", "source": "local://template/1", "doc_type": "template"},
        ]
    )

    results = tool.search("创造性", top_k=3)

    assert [result.provenance["document_id"] for result in results] == ["law-2020", "template-1"]
    assert results[0].law_name == "中华人民共和国专利法"
    assert results[0].version == "2020修正"


def test_local_retrieval_tool_filters_law_by_as_of() -> None:
    """本地检索传入 as_of 时返回该日期有效法规版本。"""
    tool = LocalRetrievalTool(
        documents=[
            {
                "id": "law-2020",
                "text": "创造性 现行版本",
                "source": "local://law/current",
                "doc_type": "law",
                "status": "current",
                "effective_date": "2021-06-01",
            },
            {
                "id": "law-2008",
                "text": "创造性 历史版本",
                "source": "local://law/old",
                "doc_type": "law",
                "status": "superseded",
                "effective_date": "2009-10-01",
                "expiry_date": "2021-06-01",
            },
        ]
    )

    results = tool.search("创造性", top_k=2, as_of="2020-01-01")

    assert [result.provenance["document_id"] for result in results] == ["law-2008"]


def test_local_retrieval_tool_skips_time_filter_when_disabled() -> None:
    """关闭时间过滤时本地法规不按 status 过滤。"""
    tool = LocalRetrievalTool(
        documents=[
            {"id": "law-1", "text": "创造性", "source": "local://law/1", "doc_type": "law", "status": "superseded"},
        ],
        settings=Settings(retrieval_enable_time_filter=False),
    )

    assert [result.provenance["document_id"] for result in tool.search("创造性")] == ["law-1"]


def test_local_retrieval_tool_keeps_non_law_documents_under_time_filter() -> None:
    """法规时效过滤不应误伤 procedure、template 和 term。"""
    documents = [
        {"id": "procedure-1", "text": "创造性 办理材料", "source": "local://procedure/专利.md", "doc_type": "procedure", "locator": "办事指南·事项·材料"},
        {"id": "template-1", "text": "创造性 模板", "source": "local://template/1", "doc_type": "template"},
        {"id": "term-1", "text": "创造性 术语", "source": "local://term/1", "doc_type": "term"},
        {"id": "law-old", "text": "创造性 旧法", "source": "local://law/old", "doc_type": "law", "status": "superseded", "effective_date": "2009-10-01", "expiry_date": "2021-06-01"},
    ]
    tool = LocalRetrievalTool(documents=documents)

    default_results = tool.search("创造性", top_k=4)
    as_of_results = tool.search("创造性", top_k=4, as_of="2026-01-01")

    assert [result.provenance["document_id"] for result in default_results] == ["procedure-1", "template-1", "term-1"]
    assert [result.provenance["document_id"] for result in as_of_results] == ["procedure-1", "template-1", "term-1"]


def test_qdrant_retriever_builds_as_of_filter() -> None:
    """Qdrant 检索应传递非 law OR as_of 有效期过滤条件。"""
    embedding = FakeEmbedding(vector=[0.1])
    qdrant = FakeQdrantClient()
    retriever = QdrantRetriever("patent_kb", embedding, qdrant)

    assert retriever.search("创造性", as_of="2020-01-01") == []

    query_filter = qdrant.calls[0]["query_filter"]
    assert query_filter["should"][0] == {"must_not": [{"key": "doc_type", "match": {"value": "law"}}]}
    assert {"key": "effective_date", "range": {"lte": "2020-01-01"}} in query_filter["should"][1]["must"]
    assert {"key": "expiry_date", "range": {"gt": "2020-01-01"}} in query_filter["should"][1]["should"]


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
                "status": "current",
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
            status="current",
        )
    ]
