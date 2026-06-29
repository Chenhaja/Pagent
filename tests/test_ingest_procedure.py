from scripts.ingest_knowledge import build_point_id, ingest_knowledge, load_chunks


class FakeEmbedding:
    """测试用 embedding 客户端。"""

    def embed(self, text: str) -> list[float]:
        """返回固定向量。"""
        return [0.1, 0.2]


class FakeQdrant:
    """测试用 Qdrant upsert 客户端。"""

    def __init__(self) -> None:
        self.points = []

    def upsert(self, collection_name: str, points: list[dict]) -> None:
        """记录写入 points。"""
        self.points = points


def test_load_chunks_parses_procedure_sections_and_filters_contact_noise(tmp_path) -> None:
    """procedure 入库应按事项和小节切片并过滤联系方式噪声。"""
    procedure_dir = tmp_path / "procedure"
    procedure_dir.mkdir()
    (procedure_dir / "专利.md").write_text(
        """## 专利权评价报告请求

### 受理条件
请求人应当符合《专利法实施细则》第四十四条规定。
咨询电话：010-12345678
办理地址：北京市海淀区示例路 1 号

### 收费标准
费用为 2400 元。
网址：https://example.test/noise

### 申请材料
应提交专利权评价报告请求书。
邮编：100088

### 办理时限
自请求日起 2 个月内作出。
手机号：13800138000
""",
        encoding="utf-8",
    )

    chunks = load_chunks(tmp_path)

    assert [chunk.doc_type for chunk in chunks] == ["procedure", "procedure", "procedure", "procedure"]
    assert chunks[0].item_name == "专利权评价报告请求"
    assert chunks[0].section == "条件"
    assert chunks[0].category == "专利"
    assert chunks[0].document_id == "procedure/专利/专利权评价报告请求"
    assert chunks[0].source == "local://procedure/专利.md"
    assert chunks[0].locator == "办事指南·专利权评价报告请求·条件"
    assert "第四十四条" in chunks[0].content
    assert "第" not in chunks[0].locator
    assert chunks[0].content.startswith("【专利权评价报告请求 / 条件】")
    assert "咨询电话" not in chunks[0].content
    assert "办理地址" not in chunks[0].content
    assert chunks[1].section == "费用"
    assert "2400 元" in chunks[1].content
    assert "https://example.test/noise" not in chunks[1].content
    assert chunks[2].section == "材料"
    assert "专利权评价报告请求书" in chunks[2].content
    assert "邮编" not in chunks[2].content
    assert chunks[3].section == "时限"
    assert "2 个月" in chunks[3].content
    assert "手机号" not in chunks[3].content


def test_ingest_knowledge_passes_procedure_payload_and_stable_point_id(tmp_path) -> None:
    """procedure point payload 应包含结构化字段且 point id 稳定。"""
    procedure_dir = tmp_path / "procedure"
    procedure_dir.mkdir()
    (procedure_dir / "专利.md").write_text(
        """## 专利申请受理

### 申请材料
应提交请求书、说明书和权利要求书。
""",
        encoding="utf-8",
    )
    qdrant = FakeQdrant()

    first_points = ingest_knowledge(tmp_path, "patent_kb", FakeEmbedding(), qdrant)
    second_points = ingest_knowledge(tmp_path, "patent_kb", FakeEmbedding(), FakeQdrant())

    assert len(first_points) == 1
    assert first_points[0]["id"] == second_points[0]["id"]
    assert first_points[0]["id"] == build_point_id("procedure/专利/专利申请受理", 0)
    assert qdrant.points == first_points
    assert first_points[0]["payload"] == {
        "content": "【专利申请受理 / 材料】\n应提交请求书、说明书和权利要求书。",
        "source": "local://procedure/专利.md",
        "document_id": "procedure/专利/专利申请受理",
        "doc_type": "procedure",
        "locator": "办事指南·专利申请受理·材料",
        "chunk_index": "0",
        "item_name": "专利申请受理",
        "section": "材料",
        "category": "专利",
    }
