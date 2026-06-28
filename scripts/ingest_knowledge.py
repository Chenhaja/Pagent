import argparse
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.tools.embeddings import EmbeddingClient, OpenAICompatibleEmbeddingClient
from app.tools.retrieval import _QdrantHTTPClient


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

    Returns:
        可入库的知识切片。
    """

    content: str
    source: str
    document_id: str
    doc_type: str
    locator: str
    chunk_index: int


def build_point_id(document_id: str, chunk_index: int) -> str:
    """生成稳定 Qdrant point id。

    Args:
        document_id: 文档 ID。
        chunk_index: 切片序号。

    Returns:
        基于文档 ID 和切片序号的稳定哈希 ID。
    """
    return hashlib.sha256(f"{document_id}:{chunk_index}".encode("utf-8")).hexdigest()


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
    for doc_type in ("law", "template", "term"):
        doc_dir = root / doc_type
        if not doc_dir.exists():
            continue
        for file_path in sorted(path for path in doc_dir.rglob("*") if path.is_file() and path.name != ".gitkeep"):
            text = _clean_text(file_path.read_text(encoding="utf-8"))
            if not text:
                continue
            document_id = file_path.stem
            source = f"local://{doc_type}/{file_path.name}"
            for index, content in enumerate(_split_text(text)):
                chunks.append(
                    KnowledgeChunk(
                        content=content,
                        source=source,
                        document_id=document_id,
                        doc_type=doc_type,
                        locator=_infer_locator(doc_type, content, file_path.stem),
                        chunk_index=index,
                    )
                )
    return chunks


def ingest_knowledge(
    path: str | Path,
    collection_name: str,
    embedding_client: EmbeddingClient,
    qdrant_client: Any,
) -> list[dict[str, Any]]:
    """将本地知识切片 embedding 后 upsert 到 Qdrant。

    Args:
        path: knowledge 根目录。
        collection_name: Qdrant 集合名称。
        embedding_client: embedding 客户端。
        qdrant_client: Qdrant upsert 客户端。

    Returns:
        已构造的 point 列表;空目录返回空列表。
    """
    points = []
    for chunk in load_chunks(path):
        vector = embedding_client.embed(chunk.content)
        if not vector:
            continue
        points.append(
            {
                "id": build_point_id(chunk.document_id, chunk.chunk_index),
                "vector": vector,
                "payload": {
                    "content": chunk.content,
                    "source": chunk.source,
                    "document_id": chunk.document_id,
                    "doc_type": chunk.doc_type,
                    "locator": chunk.locator,
                    "chunk_index": str(chunk.chunk_index),
                },
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
    )


class _QdrantHTTPUpsertClient(_QdrantHTTPClient):
    """支持 upsert 的最小 Qdrant HTTP 客户端。

    Returns:
        可供入库脚本使用的 Qdrant 客户端。
    """

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
        with request.urlopen(http_request):
            return None


def _clean_text(text: str) -> str:
    """清洗文本首尾空白。"""
    return text.strip()


def _split_text(text: str) -> list[str]:
    """按空行切分文本,无空行时保留整体。"""
    parts = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    return parts or ([text] if text else [])


def _infer_locator(doc_type: str, content: str, fallback: str) -> str:
    """根据文档类型推断切片 locator。"""
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
