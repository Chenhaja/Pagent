import json

from app.core.config import Settings
from app.tools.embeddings import FakeEmbedding, OpenAICompatibleEmbeddingClient
from app.tools.retrieval import LocalRetrievalTool, RetrievalResult, Retriever


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
