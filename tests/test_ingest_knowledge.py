import hashlib
import json
from datetime import date
from urllib import error

from scripts.ingest_knowledge import _QdrantHTTPUpsertClient, build_point_id, ingest_knowledge, load_chunks


class FakeEmbedding:
    """测试用 embedding 客户端。"""

    def __init__(self) -> None:
        self.calls = []

    def embed(self, text: str) -> list[float]:
        """记录文本并返回固定向量。"""
        self.calls.append(text)
        return [0.1, 0.2]


class FakeQdrant:
    """测试用 Qdrant upsert 客户端。"""

    def __init__(self) -> None:
        self.calls = []

    def ensure_collection(self, collection_name: str, vector_size: int) -> None:
        """记录建集合参数。"""
        self.calls.append({"collection_name": collection_name, "vector_size": vector_size})

    def upsert(self, collection_name: str, points: list[dict]) -> None:
        """记录 upsert 参数。"""
        self.calls.append({"collection_name": collection_name, "points": points})


def test_load_chunks_infers_doc_type_and_locator(tmp_path) -> None:
    """本地语料切分应推断 doc_type 和 locator。"""
    (tmp_path / "law").mkdir()
    (tmp_path / "template").mkdir()
    (tmp_path / "term").mkdir()
    (tmp_path / "law" / "patent_law.md").write_text("第22条\n授予专利权的发明应具备创造性。", encoding="utf-8")
    (tmp_path / "template" / "claim.md").write_text("权利要求1\n一种传感器控制系统。", encoding="utf-8")
    (tmp_path / "term" / "ipc.md").write_text("IPC: 国际专利分类。", encoding="utf-8")

    chunks = load_chunks(tmp_path)

    assert [chunk.doc_type for chunk in chunks] == ["law", "template", "term"]
    assert chunks[0].locator == "第22条"
    assert chunks[1].locator == "权利要求1"
    assert chunks[2].locator == "IPC"
    assert chunks[0].source == "local://law/patent_law.md"


def test_load_chunks_reads_law_version_metadata(tmp_path) -> None:
    """法规版本目录应读取 meta.json 并生成时效元数据。"""
    version_dir = tmp_path / "law" / "zhuanli_fa_2020"
    version_dir.mkdir(parents=True)
    (version_dir / "meta.json").write_text(
        json.dumps(
            {
                "document_id": "patent_law_2020",
                "law_name": "中华人民共和国专利法",
                "version": "2020修正",
                "effective_date": "2021-06-01",
                "expiry_date": None,
                "status": "current",
                "source_url": "https://example.test/patent-law",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (version_dir / "law.txt").write_text("第22条\n授予专利权的发明应具备创造性。", encoding="utf-8")

    chunks = load_chunks(tmp_path)

    assert len(chunks) == 1
    assert chunks[0].document_id == "patent_law_2020"
    assert chunks[0].source == "local://law/zhuanli_fa_2020/law.txt"
    assert chunks[0].locator == "中华人民共和国专利法(2020修正)·第22条"
    assert chunks[0].law_name == "中华人民共和国专利法"
    assert chunks[0].version == "2020修正"
    assert chunks[0].effective_date == "2021-06-01"
    assert chunks[0].expiry_date is None
    assert chunks[0].status == "current"
    assert chunks[0].source_url == "https://example.test/patent-law"
    assert chunks[0].retrieved_at == date.today().isoformat()
    assert chunks[0].content_hash == hashlib.sha256(chunks[0].content.encode("utf-8")).hexdigest()


def test_build_point_id_is_stable() -> None:
    """相同文档和 chunk 序号应生成稳定 point id。"""
    assert build_point_id("patent_law", 0) == build_point_id("patent_law", 0)
    assert build_point_id("patent_law", 0) != build_point_id("patent_law", 1)


def test_ingest_knowledge_embeds_and_upserts_payload(tmp_path) -> None:
    """入库应生成 vector 和完整 provenance payload。"""
    (tmp_path / "law").mkdir()
    (tmp_path / "law" / "patent_law.md").write_text("第22条\n授予专利权的发明应具备创造性。", encoding="utf-8")
    embedding = FakeEmbedding()
    qdrant = FakeQdrant()

    points = ingest_knowledge(
        tmp_path,
        collection_name="patent_kb",
        embedding_client=embedding,
        qdrant_client=qdrant,
        vector_size=1024,
    )

    assert embedding.calls == ["第22条\n授予专利权的发明应具备创造性。"]
    assert len(points) == 1
    assert qdrant.calls == [
        {"collection_name": "patent_kb", "vector_size": 1024},
        {"collection_name": "patent_kb", "points": points},
    ]
    assert points[0]["vector"] == [0.1, 0.2]
    assert points[0]["payload"] == {
        "content": "第22条\n授予专利权的发明应具备创造性。",
        "source": "local://law/patent_law.md",
        "document_id": "patent_law",
        "doc_type": "law",
        "locator": "第22条",
        "chunk_index": "0",
        "retrieved_at": date.today().isoformat(),
        "content_hash": hashlib.sha256("第22条\n授予专利权的发明应具备创造性。".encode("utf-8")).hexdigest(),
    }


def test_ingest_knowledge_empty_directory_is_safe(tmp_path) -> None:
    """空语料目录应安全退出。"""
    embedding = FakeEmbedding()
    qdrant = FakeQdrant()

    assert ingest_knowledge(tmp_path, "patent_kb", embedding, qdrant) == []
    assert qdrant.calls == []


def test_qdrant_http_client_creates_missing_collection(monkeypatch) -> None:
    """Qdrant 集合不存在时应按 embedding 维度创建。"""
    calls = []

    def fake_urlopen(http_request):
        """模拟 Qdrant 查询集合 404 后创建成功。"""
        calls.append(http_request)
        if http_request.get_method() == "GET":
            raise error.HTTPError(http_request.full_url, 404, "not found", {}, None)
        return _FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    _QdrantHTTPUpsertClient("http://qdrant.local", "secret").ensure_collection("patent_kb", 1024)

    assert [request.get_method() for request in calls] == ["GET", "PUT"]
    assert calls[1].full_url == "http://qdrant.local/collections/patent_kb"
    assert calls[1].headers["Api-key"] == "secret"
    assert json.loads(calls[1].data.decode("utf-8")) == {"vectors": {"size": 1024, "distance": "Cosine"}}


class _FakeResponse:
    """测试用 urlopen 响应上下文。"""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None
