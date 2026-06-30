import argparse
import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib import error

from app.core.config import Settings, get_settings
from app.tools.embeddings import EmbeddingClient, OpenAICompatibleEmbeddingClient
from app.tools.retrieval import SparseEncoder, _QdrantHTTPClient, _build_sparse_encoder


@dataclass(frozen=True)
class KnowledgeChunk:
    """本地知识切片。

    Args:
        content: 切片文本。
        source: 本地来源 URI。
        document_id: 稳定文档 ID。
        doc_type: 文档类型。
        locator: 文档内定位。
        chunk_index: 切片序号。
        law_name: 法规名称。
        version: 法规版本。
        effective_date: 生效日期。
        expiry_date: 失效日期。
        status: 版本状态。
        source_url: 官方来源 URL。
        retrieved_at: 入库检索日期。
        content_hash: 切片正文 sha256。
        item_name: 办事指南事项名称。
        section: 办事指南规范化小节。
        category: 办事指南类别。

    Returns:
        可入库的知识切片。
    """

    content: str
    source: str
    document_id: str
    doc_type: str
    locator: str
    chunk_index: int
    law_name: str | None = None
    version: str | None = None
    effective_date: str | None = None
    expiry_date: str | None = None
    status: str | None = None
    source_url: str | None = None
    retrieved_at: str | None = None
    content_hash: str | None = None
    item_name: str | None = None
    section: str | None = None
    category: str | None = None


def build_point_id(document_id: str, chunk_index: int) -> str:
    """生成稳定 Qdrant point id。

    Args:
        document_id: 文档 ID。
        chunk_index: 切片序号。

    Returns:
        基于文档 ID 和切片序号的稳定哈希 ID。
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{document_id}:{chunk_index}"))


def load_chunks(root_path: str | Path) -> list[KnowledgeChunk]:
    """读取本地 knowledge 目录并切分语料。

    Args:
        root_path: knowledge 根目录。

    Returns:
        按路径顺序生成的知识切片列表。
    """
    root = Path(root_path)
    chunks: list[KnowledgeChunk] = []
    if not root.exists():
        return chunks
    for doc_type in ("law", "template", "term", "procedure"):
        doc_dir = root / doc_type
        if not doc_dir.exists():
            continue
        for file_path in sorted(path for path in doc_dir.rglob("*") if path.is_file() and path.name not in {".gitkeep", "meta.json"}):
            text = _clean_text(file_path.read_text(encoding="utf-8"))
            if not text:
                continue
            if doc_type == "procedure":
                chunks.extend(_load_procedure_chunks(file_path, doc_dir))
                continue
            metadata = _load_law_metadata(file_path.parent) if doc_type == "law" else {}
            document_id = str(metadata.get("document_id") or (file_path.parent.name if metadata else file_path.stem))
            source = f"local://{doc_type}/{file_path.relative_to(doc_dir).as_posix()}"
            for index, content in enumerate(_split_text(text)):
                locator = _infer_locator(doc_type, content, file_path.stem)
                chunks.append(
                    KnowledgeChunk(
                        content=content,
                        source=source,
                        document_id=document_id,
                        doc_type=doc_type,
                        locator=_format_law_locator(locator, metadata) if doc_type == "law" else locator,
                        chunk_index=index,
                        law_name=_optional_str(metadata.get("law_name")),
                        version=_optional_str(metadata.get("version")),
                        effective_date=_optional_str(metadata.get("effective_date")),
                        expiry_date=_optional_str(metadata.get("expiry_date")),
                        status=_optional_str(metadata.get("status")),
                        source_url=_optional_str(metadata.get("source_url")),
                        retrieved_at=date.today().isoformat() if doc_type == "law" else None,
                        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest() if doc_type == "law" else None,
                    )
                )
    return chunks


def ingest_knowledge(
    path: str | Path,
    collection_name: str,
    embedding_client: EmbeddingClient,
    qdrant_client: Any,
    vector_size: int | None = None,
    settings: Settings | None = None,
    sparse_encoder: SparseEncoder | None = None,
) -> list[dict[str, Any]]:
    """将本地知识切片 embedding 后 upsert 到 Qdrant。

    Args:
        path: knowledge 根目录。
        collection_name: Qdrant 集合名称。
        embedding_client: embedding 客户端。
        qdrant_client: Qdrant upsert 客户端。
        vector_size: 可选向量维度,传入时入库前确保集合存在。
        settings: 可选应用配置,用于判断是否写入 hybrid 向量。
        sparse_encoder: 可选稀疏编码器,hybrid 开启时使用。

    Returns:
        已构造的 point 列表;空目录返回空列表。
    """
    resolved_settings = settings or get_settings()
    resolved_sparse_encoder = sparse_encoder or _build_sparse_encoder(resolved_settings)
    if vector_size is not None and hasattr(qdrant_client, "ensure_collection"):
        if settings is None:
            qdrant_client.ensure_collection(collection_name=collection_name, vector_size=vector_size)
        else:
            qdrant_client.ensure_collection(collection_name=collection_name, vector_size=vector_size, settings=resolved_settings)
    points = []
    for chunk in load_chunks(path):
        vector = embedding_client.embed(chunk.content)
        if not vector:
            continue
        payload = {
            "content": chunk.content,
            "source": chunk.source,
            "document_id": chunk.document_id,
            "doc_type": chunk.doc_type,
            "locator": chunk.locator,
            "chunk_index": str(chunk.chunk_index),
        }
        for key in (
            "law_name",
            "version",
            "effective_date",
            "expiry_date",
            "status",
            "source_url",
            "retrieved_at",
            "content_hash",
            "item_name",
            "section",
            "category",
        ):
            value = getattr(chunk, key)
            if value is not None:
                payload[key] = value
        point_vector: list[float] | dict[str, Any] = vector
        if resolved_settings.retrieval_use_hybrid:
            point_vector = {"dense": vector, "sparse": resolved_sparse_encoder.encode(chunk.content)}
        points.append(
            {
                "id": build_point_id(chunk.document_id, chunk.chunk_index),
                "vector": point_vector,
                "payload": payload,
            }
        )
    if points:
        qdrant_client.upsert(collection_name=collection_name, points=points)
    return points


def main() -> None:
    """执行本地知识入库 CLI。

    Returns:
        无返回值。
    """
    parser = argparse.ArgumentParser(description="Ingest local patent knowledge into Qdrant.")
    parser.add_argument("--path", default="knowledge/", help="knowledge 根目录")
    args = parser.parse_args()
    settings = get_settings()
    qdrant_client = _QdrantHTTPUpsertClient(settings.qdrant_url or "", settings.qdrant_api_key)
    ingest_knowledge(
        path=args.path,
        collection_name=settings.qdrant_collection,
        embedding_client=OpenAICompatibleEmbeddingClient(settings=settings),
        qdrant_client=qdrant_client,
        vector_size=settings.embedding_vector_size,
        settings=settings,
    )


class _QdrantHTTPUpsertClient(_QdrantHTTPClient):
    """支持 upsert 的最小 Qdrant HTTP 客户端。

    Returns:
        可供入库脚本使用的 Qdrant 客户端。
    """

    def ensure_collection(self, collection_name: str, vector_size: int, settings: Settings | None = None) -> None:
        """确保 Qdrant 集合存在。

        Args:
            collection_name: 集合名称。
            vector_size: 向量维度。
            settings: 可选应用配置,开启 hybrid 时创建 named dense + sparse schema。

        Returns:
            无返回值。
        """
        if not self.url:
            return
        import json
        from urllib import error, request

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["api-key"] = self.api_key
        get_request = request.Request(
            url=f"{self.url}/collections/{collection_name}",
            headers=headers,
            method="GET",
        )
        try:
            with request.urlopen(get_request):
                return
        except error.HTTPError as exc:
            if exc.code != 404:
                raise

        schema = {"vectors": {"size": vector_size, "distance": "Cosine"}}
        if settings is not None and settings.retrieval_use_hybrid:
            schema = {"vectors": {"dense": {"size": vector_size, "distance": "Cosine"}}, "sparse_vectors": {"sparse": {}}}
        create_request = request.Request(
            url=f"{self.url}/collections/{collection_name}",
            data=json.dumps(schema).encode("utf-8"),
            headers=headers,
            method="PUT",
        )
        with request.urlopen(create_request):
            return None

    def upsert(self, collection_name: str, points: list[dict[str, Any]]) -> None:
        """调用 Qdrant points upsert 接口。

        Args:
            collection_name: 集合名称。
            points: 待写入 points。

        Returns:
            无返回值。
        """
        if not self.url:
            return
        import json
        from urllib import request

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["api-key"] = self.api_key
        http_request = request.Request(
            url=f"{self.url}/collections/{collection_name}/points?wait=true",
            data=json.dumps({"points": points}).encode("utf-8"),
            headers=headers,
            method="PUT",
        )
        try:
            with request.urlopen(http_request):
                return None
        except error.HTTPError as exc:
            print(exc.read().decode("utf-8"))
            raise


def _load_law_metadata(version_dir: Path) -> dict[str, Any]:
    """读取法规版本目录的 meta.json。"""
    meta_path = version_dir / "meta.json"
    if not meta_path.exists():
        return {}
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _optional_str(value: Any) -> str | None:
    """将可选 metadata 值转换为字符串。"""
    if value is None:
        return None
    return str(value)


def _format_law_locator(locator: str, metadata: dict[str, Any]) -> str:
    """为法规 locator 增加版本前缀。"""
    law_name = _optional_str(metadata.get("law_name"))
    version = _optional_str(metadata.get("version"))
    if law_name and version:
        return f"{law_name}({version})·{locator}"
    if law_name:
        return f"{law_name}·{locator}"
    return locator


def _clean_text(text: str) -> str:
    """清洗文本首尾空白。"""
    return text.strip()


def _split_text(text: str) -> list[str]:
    """按空行切分文本,无空行时保留整体。"""
    parts = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    return parts or ([text] if text else [])


def _load_procedure_chunks(file_path: Path, doc_dir: Path) -> list[KnowledgeChunk]:
    """按办事指南 H2/H3 结构生成 procedure 切片。

    Args:
        file_path: procedure Markdown 文件路径。
        doc_dir: procedure 根目录。

    Returns:
        按事项和小节生成的知识切片列表。
    """
    category = file_path.stem
    source = f"local://procedure/{file_path.relative_to(doc_dir).as_posix()}"
    chunks: list[KnowledgeChunk] = []
    item_name: str | None = None
    section: str | None = None
    lines: list[str] = []
    indexes: dict[str, int] = {}

    def flush_section() -> None:
        """提交当前事项小节。"""
        if not item_name or not section:
            return
        cleaned_text = _clean_procedure_text("\n".join(lines))
        if not cleaned_text:
            return
        document_id = f"procedure/{category}/{item_name}"
        chunk_index = indexes.get(document_id, 0)
        indexes[document_id] = chunk_index + 1
        chunks.append(
            KnowledgeChunk(
                content=f"【{item_name} / {section}】\n{cleaned_text}",
                source=source,
                document_id=document_id,
                doc_type="procedure",
                locator=f"办事指南·{item_name}·{section}",
                chunk_index=chunk_index,
                item_name=item_name,
                section=section,
                category=category,
            )
        )

    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        h2_match = re.match(r"^##\s+(.+?)\s*$", raw_line)
        h3_match = re.match(r"^###\s+(.+?)\s*$", raw_line)
        if h2_match:
            flush_section()
            item_name = h2_match.group(1).strip()
            section = None
            lines = []
            continue
        if h3_match:
            flush_section()
            section = _normalize_procedure_section(h3_match.group(1))
            lines = []
            continue
        lines.append(raw_line)
    flush_section()
    return chunks


def _normalize_procedure_section(section: str) -> str:
    """规范化办事指南小节名称。"""
    name = section.strip()
    aliases = {
        "受理条件": "条件",
        "获取途径": "渠道",
        "申请材料": "材料",
        "办理流程": "流程",
        "收费标准": "费用",
        "费用": "费用",
        "办理时限": "时限",
        "办理结果": "结果",
        "相关表格": "结果",
    }
    return aliases.get(name, name)


def _clean_procedure_text(text: str) -> str:
    """清洗办事指南中的联系方式类噪声行。"""
    noise_pattern = re.compile(r"(电话|手机号|邮编|网址|地址|https?://)")
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line and not noise_pattern.search(line))


def _infer_locator(doc_type: str, content: str, fallback: str) -> str:
    """根据文档类型推断切片 locator。"""
    if doc_type == "procedure":
        return fallback
    if doc_type == "law":
        match = re.search(r"第\s*[^\s，。；:：]+\s*条", content)
        return match.group(0).replace(" ", "") if match else fallback
    if doc_type == "template":
        match = re.search(r"权利要求\s*\d+", content)
        return match.group(0).replace(" ", "") if match else fallback
    if doc_type == "term":
        first_line = content.splitlines()[0].strip()
        return re.split(r"[:：]", first_line, maxsplit=1)[0].strip() or fallback
    return fallback


if __name__ == "__main__":
    main()
