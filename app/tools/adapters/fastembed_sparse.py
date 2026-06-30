import logging
from typing import Any

logger = logging.getLogger(__name__)
_EMPTY_SPARSE_VECTOR: dict[str, list[int] | list[float]] = {"indices": [], "values": []}
_DEFAULT_MODEL_NAME = "Qdrant/bm25"


class FastEmbedSparseEncoder:
    """FastEmbed 本地稀疏向量编码器。

    Args:
        model_name: FastEmbed sparse 模型名,为空时使用默认 BM25。
        model: 可选已初始化模型,用于测试注入或外部复用。
        model_factory: 可选模型工厂,用于测试替换 `SparseTextEmbedding`。

    Returns:
        实现 SparseEncoder 协议的本地 sparse 编码器。
    """

    def __init__(self, model_name: str | None = None, model: Any | None = None, model_factory: Any | None = None) -> None:
        self.model_name = model_name or _DEFAULT_MODEL_NAME
        self.model = model
        if self.model is not None:
            return
        try:
            factory = model_factory or self._load_model_factory()
            self.model = factory(model_name=self.model_name)
        except Exception:
            logger.warning("FastEmbed sparse 模型加载失败,将降级为空 sparse 向量", extra={"event": "fastembed_sparse_load_failed"}, exc_info=True)
            self.model = None

    def encode(self, text: str) -> dict[str, list[int] | list[float]]:
        """编码文本为 Qdrant sparse vector。

        Args:
            text: 待编码文本。

        Returns:
            包含 indices 和 values 的稀疏向量;失败时返回空向量。
        """
        if self.model is None:
            return _empty_sparse_vector()
        try:
            result = next(iter(self.model.embed([text])))
            return _normalize_sparse_result(result)
        except Exception:
            logger.warning("FastEmbed sparse 编码失败,将降级为空 sparse 向量", extra={"event": "fastembed_sparse_encode_failed"}, exc_info=True)
            return _empty_sparse_vector()

    def _load_model_factory(self) -> Any:
        """延迟导入 FastEmbed sparse 模型工厂。"""
        from fastembed import SparseTextEmbedding

        return SparseTextEmbedding


def _empty_sparse_vector() -> dict[str, list[int] | list[float]]:
    """返回新的空 sparse 向量。"""
    return {"indices": [], "values": []}


def _normalize_sparse_result(result: Any) -> dict[str, list[int] | list[float]]:
    """将 FastEmbed sparse 输出归一为 Qdrant sparse dict。"""
    if isinstance(result, dict):
        indices = result.get("indices") or []
        values = result.get("values") or []
    else:
        indices = getattr(result, "indices", []) or []
        values = getattr(result, "values", []) or []
    if len(indices) != len(values):
        return _empty_sparse_vector()
    return {"indices": [int(index) for index in indices], "values": [float(value) for value in values]}
