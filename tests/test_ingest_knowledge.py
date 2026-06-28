from scripts.ingest_knowledge import build_point_id, ingest_knowledge, load_chunks


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

    points = ingest_knowledge(tmp_path, collection_name="patent_kb", embedding_client=embedding, qdrant_client=qdrant)

    assert embedding.calls == ["第22条\n授予专利权的发明应具备创造性。"]
    assert len(points) == 1
    assert qdrant.calls == [{"collection_name": "patent_kb", "points": points}]
    assert points[0]["vector"] == [0.1, 0.2]
    assert points[0]["payload"] == {
        "content": "第22条\n授予专利权的发明应具备创造性。",
        "source": "local://law/patent_law.md",
        "document_id": "patent_law",
        "doc_type": "law",
        "locator": "第22条",
        "chunk_index": "0",
    }


def test_ingest_knowledge_empty_directory_is_safe(tmp_path) -> None:
    """空语料目录应安全退出。"""
    embedding = FakeEmbedding()
    qdrant = FakeQdrant()

    assert ingest_knowledge(tmp_path, "patent_kb", embedding, qdrant) == []
    assert qdrant.calls == []
