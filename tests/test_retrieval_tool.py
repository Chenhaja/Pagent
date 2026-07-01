import json

from app.core.config import Settings
from app.prompts.query_expand import QUERY_EXPAND_OUTPUT_SCHEMA, QUERY_EXPAND_SYSTEM_PROMPT, build_query_expand_user_prompt
from app.tools.embeddings import FakeEmbedding, OpenAICompatibleEmbeddingClient
from app.tools.llm import FakeLLMClient, LLMResponse, InMemoryLLMTraceSink
from app.tools.retrieval import FakeQueryRewriter, FakeReranker, FakeSparseEncoder, HTTPQueryRewriter, HTTPReranker, LLMQueryRewriter, LocalLexicalSparseEncoder, LocalRetrievalTool, MultiQueryRetriever, QdrantRetriever, RerankingRetriever, RetrievalResult, Retriever, ServiceSparseEncoder, _QdrantHTTPClient, _build_query_rewriter, _build_sparse_encoder, build_retriever


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

    def query_hybrid(self, collection_name: str, dense_vector: list[float], sparse_vector: dict, limit: int, query_filter: dict | None = None):
        """记录 hybrid 查询参数并返回固定命中。"""
        self.calls.append({"collection_name": collection_name, "dense_vector": dense_vector, "sparse_vector": sparse_vector, "limit": limit, "query_filter": query_filter})
        if self.should_raise:
            raise RuntimeError("qdrant failed")
        return self.hits[:limit]


class RaisingEmbedding:
    """测试用异常 embedding。"""

    def embed(self, text: str) -> list[float]:
        """模拟 embedding 失败。"""
        raise RuntimeError("embedding failed")


class FakeInnerRetriever:
    """测试用内层检索器。"""

    def __init__(self, results: list[RetrievalResult]) -> None:
        self.results = results
        self.calls = []

    def search(self, query: str, top_k: int = 3, as_of: str | None = None, fetch_k: int | None = None) -> list[RetrievalResult]:
        """记录 search 调用并返回截断结果。"""
        self.calls.append({"method": "search", "query": query, "top_k": top_k, "as_of": as_of, "fetch_k": fetch_k})
        return self.results[:top_k]

    def recall(self, query: str, fetch_k: int, as_of: str | None = None) -> list[RetrievalResult]:
        """记录 recall 调用并返回候选结果。"""
        self.calls.append({"method": "recall", "query": query, "fetch_k": fetch_k, "as_of": as_of})
        return self.results[:fetch_k]


class RaisingReranker:
    """测试用异常 reranker。"""

    def rerank(self, query: str, documents: list[RetrievalResult], top_n: int | None = None) -> list[RetrievalResult]:
        """模拟 rerank 失败。"""
        raise RuntimeError("rerank failed sk-secret")


class RaisingQueryRewriter:
    """测试用异常查询改写器。"""

    def expand(self, query: str) -> list[str]:
        """模拟查询改写失败。"""
        raise RuntimeError("rewrite failed")


class RecordingLLMClient(FakeLLMClient):
    """记录 generate 调用参数的测试 LLM。"""

    def __init__(self, response: dict | None = None, error: str | None = None) -> None:
        super().__init__(response=response, error=error)
        self.calls = []

    def generate(self, **kwargs) -> LLMResponse:
        """记录调用参数并返回固定响应。"""
        self.calls.append(kwargs)
        return super().generate(**kwargs)


class NonDictContentLLMClient:
    """返回非 dict content 的测试 LLM。"""

    def generate(self, **kwargs):
        """模拟非法 LLM 响应结构。"""
        return type("Response", (), {"content": [], "errors": []})()


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


def test_qdrant_retriever_uses_fetch_k_for_candidate_recall() -> None:
    """Qdrant 宽召回应使用 fetch_k 扩大候选池并保留 as_of 过滤。"""
    embedding = FakeEmbedding(vector=[0.1])
    qdrant = FakeQdrantClient(
        hits=[
            FakeQdrantHit(payload={"content": "创造性 A", "source": "local://a", "document_id": "a"}, score=0.9),
            FakeQdrantHit(payload={"content": "创造性 B", "source": "local://b", "document_id": "b"}, score=0.8),
            FakeQdrantHit(payload={"content": "创造性 C", "source": "local://c", "document_id": "c"}, score=0.7),
        ]
    )
    retriever = QdrantRetriever("patent_kb", embedding, qdrant)

    results = retriever.search("创造性", top_k=1, fetch_k=3, as_of="2020-01-01")

    assert [result.provenance["document_id"] for result in results] == ["a"]
    assert qdrant.calls[0]["limit"] == 3
    assert {"key": "effective_date", "range": {"lte": "2020-01-01"}} in qdrant.calls[0]["query_filter"]["should"][1]["must"]


def test_qdrant_retriever_recall_returns_fetch_k_candidates() -> None:
    """Qdrant recall 应返回 fetch_k 个候选供后续重排使用。"""
    qdrant = FakeQdrantClient(
        hits=[
            FakeQdrantHit(payload={"content": "创造性 A", "source": "local://a", "document_id": "a"}, score=0.9),
            FakeQdrantHit(payload={"content": "创造性 B", "source": "local://b", "document_id": "b"}, score=0.8),
        ]
    )

    results = QdrantRetriever("patent_kb", FakeEmbedding([0.1]), qdrant).recall("创造性", fetch_k=2)

    assert [result.provenance["document_id"] for result in results] == ["a", "b"]
    assert qdrant.calls[0]["limit"] == 2


def test_qdrant_retriever_uses_hybrid_query_when_sparse_encoder_exists() -> None:
    """Qdrant hybrid 检索应传递 dense、sparse 和时间过滤。"""
    qdrant = FakeQdrantClient([FakeQdrantHit(payload={"content": "创造性", "source": "local://a", "document_id": "a"}, score=0.9)])
    sparse_encoder = FakeSparseEncoder({"indices": [1], "values": [0.5]})
    retriever = QdrantRetriever("patent_kb_hybrid", FakeEmbedding([0.1]), qdrant, settings=Settings(retrieval_use_hybrid=True), sparse_encoder=sparse_encoder)

    results = retriever.search("创造性", top_k=1, fetch_k=3, as_of="2020-01-01")

    assert [result.provenance["document_id"] for result in results] == ["a"]
    assert sparse_encoder.calls == ["创造性"]
    assert qdrant.calls[0]["collection_name"] == "patent_kb_hybrid"
    assert qdrant.calls[0]["dense_vector"] == [0.1]
    assert qdrant.calls[0]["sparse_vector"] == {"indices": [1], "values": [0.5]}
    assert qdrant.calls[0]["limit"] == 3
    assert {"key": "effective_date", "range": {"lte": "2020-01-01"}} in qdrant.calls[0]["query_filter"]["should"][1]["must"]


def test_qdrant_http_client_builds_hybrid_query_request() -> None:
    """Qdrant HTTP hybrid 查询应使用 points/query 和 RRF prefetch。"""
    captured = {}

    def fake_urlopen(request):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeHTTPResponse({"result": {"points": [{"payload": {"content": "创造性", "source": "local://a", "document_id": "a"}, "score": 0.8}]}})

    client = _QdrantHTTPClient("http://qdrant.local", "secret", urlopen=fake_urlopen)

    hits = client.query_hybrid("patent_kb_hybrid", [0.1], {"indices": [1], "values": [0.5]}, limit=2, query_filter={"must": []})

    assert captured["url"] == "http://qdrant.local/collections/patent_kb_hybrid/points/query"
    assert captured["headers"]["Api-key"] == "secret"
    assert captured["payload"] == {
        "prefetch": [
            {"query": [0.1], "using": "dense", "limit": 2, "filter": {"must": []}},
            {"query": {"indices": [1], "values": [0.5]}, "using": "sparse", "limit": 2, "filter": {"must": []}},
        ],
        "query": {"fusion": "rrf"},
        "limit": 2,
        "with_payload": True,
    }
    assert hits[0].payload["document_id"] == "a"
    assert hits[0].score == 0.8


def test_qdrant_retriever_allows_empty_sparse_vector_in_hybrid_query() -> None:
    """hybrid sparse 为空时仍应携带 dense、空 sparse 和时间过滤。"""
    qdrant = FakeQdrantClient([FakeQdrantHit(payload={"content": "创造性", "source": "local://a", "document_id": "a"}, score=0.9)])
    sparse_encoder = FakeSparseEncoder({"indices": [], "values": []})
    retriever = QdrantRetriever("patent_kb_hybrid", FakeEmbedding([0.1]), qdrant, settings=Settings(retrieval_use_hybrid=True), sparse_encoder=sparse_encoder)

    results = retriever.search("创造性", top_k=1, fetch_k=3, as_of="2020-01-01")

    assert [result.provenance["document_id"] for result in results] == ["a"]
    assert qdrant.calls[0]["dense_vector"] == [0.1]
    assert qdrant.calls[0]["sparse_vector"] == {"indices": [], "values": []}
    assert qdrant.calls[0]["limit"] == 3
    assert {"key": "effective_date", "range": {"lte": "2020-01-01"}} in qdrant.calls[0]["query_filter"]["should"][1]["must"]


def test_qdrant_retriever_returns_empty_when_dependencies_fail() -> None:
    """Qdrant 检索器依赖失败时应返回空列表。"""
    assert QdrantRetriever("patent_kb", RaisingEmbedding(), FakeQdrantClient()).search("问题") == []
    assert QdrantRetriever("patent_kb", FakeEmbedding([0.1]), FakeQdrantClient(should_raise=True)).search("问题") == []


def test_fake_reranker_sorts_by_injected_scores() -> None:
    """Fake reranker 应按注入分数重排候选。"""
    documents = [
        RetrievalResult(content="A", provenance={"document_id": "a"}),
        RetrievalResult(content="B", provenance={"document_id": "b"}),
    ]

    results = FakeReranker(scores={"b": 0.9, "a": 0.1}).rerank("问题", documents)

    assert [result.provenance["document_id"] for result in results] == ["b", "a"]
    assert [result.similarity for result in results] == [0.9, 0.1]


def test_reranking_retriever_recalls_then_reranks_and_truncates() -> None:
    """重排包装器应先宽召回再重排并截断。"""
    inner = FakeInnerRetriever(
        [
            RetrievalResult(content="A", provenance={"document_id": "a"}),
            RetrievalResult(content="B", provenance={"document_id": "b"}),
            RetrievalResult(content="C", provenance={"document_id": "c"}),
        ]
    )
    retriever = RerankingRetriever(inner, FakeReranker(scores={"c": 0.9, "b": 0.8, "a": 0.1}), settings=Settings(retrieval_fetch_k=3, rerank_top_k=2))

    results = retriever.search("问题", top_k=1, as_of="2020-01-01")

    assert inner.calls == [{"method": "recall", "query": "问题", "fetch_k": 3, "as_of": "2020-01-01"}]
    assert [result.provenance["document_id"] for result in results] == ["c", "b"]


def test_reranking_retriever_falls_back_to_recall_on_error() -> None:
    """重排失败时应降级返回宽召回前 top_k。"""
    inner = FakeInnerRetriever(
        [
            RetrievalResult(content="A", provenance={"document_id": "a"}),
            RetrievalResult(content="B", provenance={"document_id": "b"}),
        ]
    )

    results = RerankingRetriever(inner, RaisingReranker(), settings=Settings(retrieval_fetch_k=2)).search("问题", top_k=1)

    assert [result.provenance["document_id"] for result in results] == ["a"]


def test_http_reranker_redacts_documents_and_builds_request() -> None:
    """HTTP reranker 请求体应包含必要字段且外发文档已脱敏。"""
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeHTTPResponse({"results": [{"index": 1, "score": 0.9}, {"index": 0, "score": 0.4}]})

    reranker = HTTPReranker(
        Settings(rerank_base_url="https://rerank.example.test/v1", rerank_model="rerank-model", rerank_api_key="rerank-secret", retrieval_timeout_seconds=6),
        urlopen=fake_urlopen,
    )
    documents = [
        RetrievalResult(content="普通文本", provenance={"document_id": "a"}),
        RetrievalResult(content="包含 sk-sensitive-secret 的文本", provenance={"document_id": "b"}),
    ]

    results = reranker.rerank("问题", documents, top_n=2)

    assert captured["url"] == "https://rerank.example.test/v1/rerank"
    assert captured["timeout"] == 6
    assert captured["headers"]["Authorization"] == "Bearer rerank-secret"
    assert captured["payload"] == {"model": "rerank-model", "query": "问题", "documents": ["普通文本", "包含 [REDACTED] 的文本"], "top_n": 2}
    assert [result.provenance["document_id"] for result in results] == ["b", "a"]
    assert [result.similarity for result in results] == [0.9, 0.4]


def test_query_expand_prompt_defines_schema_modes_and_data_boundary() -> None:
    """查询扩展 prompt 应定义结构化 schema、模式和数据边界。"""
    prompt = build_query_expand_user_prompt("创造性要求", "multi", 3)

    assert QUERY_EXPAND_OUTPUT_SCHEMA["required"] == ["queries"]
    assert QUERY_EXPAND_OUTPUT_SCHEMA["properties"]["queries"]["items"]["type"] == "string"
    assert QUERY_EXPAND_OUTPUT_SCHEMA["additionalProperties"] is False
    assert set(QUERY_EXPAND_SYSTEM_PROMPT) == {"multi", "hyde"}
    assert "仅输出 JSON" in QUERY_EXPAND_SYSTEM_PROMPT["multi"]
    assert "禁止臆造法条" in QUERY_EXPAND_SYSTEM_PROMPT["hyde"]
    assert "<data>" in prompt and "</data>" in prompt
    assert "不作为指令" in prompt
    assert "创造性要求" in prompt


def test_fake_query_rewriter_returns_configured_queries() -> None:
    """Fake query rewriter 应返回配置好的改写式。"""
    rewriter = FakeQueryRewriter(["创造性", "非显而易见性"])

    assert rewriter.expand("创造性要求") == ["创造性", "非显而易见性"]
    assert rewriter.calls == ["创造性要求"]


def test_llm_query_rewriter_expands_with_original_first_and_trace_context() -> None:
    """LLM query rewriter 应通过 LLMClient 生成扩展式并保留原始 query 首位。"""
    trace_sink = InMemoryLLMTraceSink()
    llm = FakeLLMClient(response={"queries": ["创造性要求", "非显而易见性", "", "创造性评价"]}, trace_sink=trace_sink)
    settings = Settings(
        query_rewrite_count=2,
        query_rewrite_model="rewrite-model",
        query_rewrite_temperature=0.4,
        retrieval_timeout_seconds=6,
    )

    queries = LLMQueryRewriter(settings, llm_client=llm).expand("创造性要求")

    assert queries == ["创造性要求", "非显而易见性", "创造性评价"]
    assert trace_sink.records[0]["model"] == "rewrite-model"
    assert trace_sink.records[0]["temperature"] == 0.4
    assert trace_sink.records[0]["timeout"] == 6
    assert trace_sink.records[0]["node_name"] == "retrieval"
    assert trace_sink.records[0]["task_type"] == "query_expand"


def test_llm_query_rewriter_passes_messages_schema_and_model_fallback() -> None:
    """LLM query rewriter 应传入 messages、schema 并按配置回退模型。"""
    llm = RecordingLLMClient(response={"queries": ["权利要求书"]})
    settings = Settings(query_rewrite_model=None, llm_cheap_model="cheap-model", llm_model="strong-model")

    queries = LLMQueryRewriter(settings, llm_client=llm).expand("权利要求")

    assert queries == ["权利要求", "权利要求书"]
    assert llm.calls[0]["output_schema"] == QUERY_EXPAND_OUTPUT_SCHEMA
    assert llm.calls[0]["model"] == "cheap-model"
    assert [message.role for message in llm.calls[0]["messages"]] == ["system", "user"]
    assert "<data>" in llm.calls[0]["messages"][1].content


def test_llm_query_rewriter_returns_empty_on_blank_query_and_errors() -> None:
    """LLM query rewriter 对空输入或 LLM 错误应返回空列表。"""
    llm = RecordingLLMClient(response={"queries": ["不应调用"]})

    assert LLMQueryRewriter(Settings(), llm_client=llm).expand("  ") == []
    assert llm.calls == []
    assert LLMQueryRewriter(Settings(), llm_client=FakeLLMClient(error="provider_error")).expand("创造性") == []


def test_llm_query_rewriter_returns_empty_on_invalid_content() -> None:
    """LLM query rewriter 对非法响应结构应返回空列表。"""
    assert LLMQueryRewriter(Settings(), llm_client=NonDictContentLLMClient()).expand("创造性") == []
    assert LLMQueryRewriter(Settings(), llm_client=FakeLLMClient(response={})).expand("创造性") == []
    assert LLMQueryRewriter(Settings(), llm_client=FakeLLMClient(response={"queries": []})).expand("创造性") == []


def test_multi_query_retriever_expands_merges_and_deduplicates() -> None:
    """多查询检索应对改写式分别召回并按 key 去重。"""
    inner = FakeInnerRetriever(
        [
            RetrievalResult(content="重复内容" * 10, provenance={"document_id": "a", "locator": "第1条"}),
            RetrievalResult(content="唯一内容", provenance={"document_id": "b", "locator": "第2条"}),
        ]
    )
    rewriter = FakeQueryRewriter(["创造性", "非显而易见性"])

    results = MultiQueryRetriever(inner, rewriter, settings=Settings(retrieval_fetch_k=2)).search("创造性要求", top_k=3, as_of="2020-01-01")

    assert inner.calls == [
        {"method": "recall", "query": "创造性", "fetch_k": 2, "as_of": "2020-01-01"},
        {"method": "recall", "query": "非显而易见性", "fetch_k": 2, "as_of": "2020-01-01"},
    ]
    assert [result.provenance["document_id"] for result in results] == ["a", "b"]


def test_multi_query_retriever_falls_back_to_original_query_on_expand_error() -> None:
    """查询改写失败时应降级为原始 query。"""
    inner = FakeInnerRetriever([RetrievalResult(content="A", provenance={"document_id": "a"})])

    results = MultiQueryRetriever(inner, RaisingQueryRewriter(), settings=Settings(retrieval_fetch_k=2)).search("原始问题", top_k=1)

    assert inner.calls == [{"method": "recall", "query": "原始问题", "fetch_k": 2, "as_of": None}]
    assert [result.provenance["document_id"] for result in results] == ["a"]


def test_http_query_rewriter_builds_request() -> None:
    """HTTP query rewriter 应按配置请求改写服务。"""
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeHTTPResponse({"queries": ["创造性", "非显而易见性"]})

    rewriter = HTTPQueryRewriter(Settings(llm_base_url="https://llm.example.test/v1", llm_model="rewrite-model", query_rewrite_mode="hyde", query_rewrite_count=2, retrieval_timeout_seconds=6), urlopen=fake_urlopen)

    assert rewriter.expand("创造性要求") == ["创造性", "非显而易见性"]
    assert captured["url"] == "https://llm.example.test/v1/query-rewrite"
    assert captured["timeout"] == 6
    assert captured["payload"] == {"model": "rewrite-model", "query": "创造性要求", "mode": "hyde", "count": 2}


def test_build_query_rewriter_dispatches_configured_backends() -> None:
    """查询改写器工厂应按配置分发后端。"""
    assert isinstance(_build_query_rewriter(Settings(query_rewrite_backend="llm")), LLMQueryRewriter)
    assert isinstance(_build_query_rewriter(Settings(query_rewrite_backend="service")), HTTPQueryRewriter)
    assert isinstance(_build_query_rewriter(Settings(query_rewrite_backend="unknown")), LLMQueryRewriter)


def test_build_sparse_encoder_dispatches_configured_backends() -> None:
    """稀疏编码器工厂应按配置分发后端。"""
    assert _build_sparse_encoder(Settings(retrieval_use_hybrid=False)) is None
    assert isinstance(_build_sparse_encoder(Settings(retrieval_use_hybrid=True, sparse_encoder="local")), LocalLexicalSparseEncoder)
    assert isinstance(_build_sparse_encoder(Settings(retrieval_use_hybrid=True, sparse_encoder="unknown")), LocalLexicalSparseEncoder)
    assert isinstance(_build_sparse_encoder(Settings(retrieval_use_hybrid=True, sparse_encoder="service")), ServiceSparseEncoder)


def test_build_sparse_encoder_dispatches_fastembed_backend(monkeypatch) -> None:
    """fastembed 模式应延迟导入并返回 FastEmbed 适配器。"""
    created = {}

    class FakeFastEmbedSparseEncoder:
        """测试用 FastEmbed sparse 适配器。"""

        def __init__(self, model_name: str | None = None) -> None:
            created["model_name"] = model_name

    monkeypatch.setattr("app.tools.adapters.fastembed_sparse.FastEmbedSparseEncoder", FakeFastEmbedSparseEncoder)

    encoder = _build_sparse_encoder(Settings(retrieval_use_hybrid=True, sparse_encoder="fastembed", sparse_model="Qdrant/bm42"))

    assert isinstance(encoder, FakeFastEmbedSparseEncoder)
    assert created == {"model_name": "Qdrant/bm42"}


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


def test_build_retriever_uses_llm_query_rewriter_by_default_when_enabled() -> None:
    """开启查询改写时默认应使用 LLM 查询改写器。"""
    retriever = build_retriever(Settings(retrieval_use_query_rewrite=True))

    assert isinstance(retriever, MultiQueryRetriever)
    assert isinstance(retriever.query_rewriter, LLMQueryRewriter)


def test_build_retriever_uses_service_query_rewriter_when_configured() -> None:
    """service backend 应保留旧 HTTP 查询改写器。"""
    retriever = build_retriever(Settings(retrieval_use_query_rewrite=True, query_rewrite_backend="service"))

    assert isinstance(retriever, MultiQueryRetriever)
    assert isinstance(retriever.query_rewriter, HTTPQueryRewriter)


def test_build_retriever_composes_hybrid_query_rewrite_then_rerank() -> None:
    """检索工厂应按 base/hybrid -> multi-query -> rerank 装配。"""
    retriever = build_retriever(
        Settings(
            retrieval_backend="qdrant",
            qdrant_url="http://qdrant.example.test",
            embedding_model="embedding-model",
            retrieval_use_hybrid=True,
            retrieval_use_query_rewrite=True,
            retrieval_use_rerank=True,
        ),
        embedding_client=FakeEmbedding([0.1]),
        qdrant_client=FakeQdrantClient(),
        reranker=FakeReranker(),
        sparse_encoder=FakeSparseEncoder(),
        query_rewriter=FakeQueryRewriter(["创造性"]),
    )

    assert isinstance(retriever, RerankingRetriever)
    assert isinstance(retriever.inner, MultiQueryRetriever)
    assert isinstance(retriever.inner.inner, QdrantRetriever)
    assert retriever.inner.inner.sparse_encoder is not None


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


def test_local_retrieval_tool_uses_fetch_k_for_candidate_recall() -> None:
    """本地检索 search 应用 top_k 截断,recall 应用 fetch_k 截断。"""
    tool = LocalRetrievalTool(
        documents=[
            {"id": "doc-1", "text": "创造性 传感器 控制", "source": "local://doc-1"},
            {"id": "doc-2", "text": "创造性 传感器", "source": "local://doc-2"},
            {"id": "doc-3", "text": "创造性", "source": "local://doc-3"},
        ]
    )

    search_results = tool.search("创造性 传感器 控制", top_k=1, fetch_k=3)
    recall_results = tool.recall("创造性 传感器 控制", fetch_k=3)

    assert [result.provenance["document_id"] for result in search_results] == ["doc-1"]
    assert [result.provenance["document_id"] for result in recall_results] == ["doc-1", "doc-2", "doc-3"]


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
