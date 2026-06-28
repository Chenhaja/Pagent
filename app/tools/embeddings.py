import json
from typing import Any, Callable, Protocol
from urllib import request

from app.core.config import Settings, get_settings
from app.core.security import redact_sensitive_text


class EmbeddingClient(Protocol):
    """文本向量化客户端协议。

    Returns:
        支持将文本转换为向量的客户端。
    """

    def embed(self, text: str) -> list[float]:
        """将文本转换为 embedding 向量。

        Args:
            text: 待向量化文本。

        Returns:
            embedding 浮点向量;失败时可返回空列表供上层降级。
        """
        ...


class FakeEmbedding:
    """测试用固定 embedding 客户端。

    Args:
        vector: 固定返回向量。

    Returns:
        可预测且不触网的 embedding 客户端。
    """

    def __init__(self, vector: list[float] | None = None) -> None:
        self.vector = vector or [0.0]
        self.calls: list[str] = []

    def embed(self, text: str) -> list[float]:
        """返回固定向量并记录输入文本。

        Args:
            text: 待向量化文本。

        Returns:
            固定 embedding 向量。
        """
        self.calls.append(text)
        return list(self.vector)


class OpenAICompatibleEmbeddingClient:
    """OpenAI 兼容 embedding 客户端。

    Args:
        settings: 应用配置,默认读取全局配置。
        urlopen: HTTP 调用函数,测试可注入 fake。

    Returns:
        可调用 OpenAI 兼容 embeddings 接口的客户端。
    """

    def __init__(self, settings: Settings | None = None, urlopen: Callable[..., Any] | None = None) -> None:
        self.settings = settings or get_settings()
        self.urlopen = urlopen or request.urlopen

    def embed(self, text: str) -> list[float]:
        """调用 embedding 接口生成向量。

        Args:
            text: 待向量化文本。

        Returns:
            embedding 浮点向量;配置缺失或 provider 失败时返回空列表。
        """
        base_url = self.settings.embedding_base_url or self.settings.llm_base_url
        api_key = self.settings.embedding_api_key or self.settings.llm_api_key
        model = self.settings.embedding_model
        if not base_url or not api_key or not model:
            return []

        payload = {"model": model, "input": redact_sensitive_text(text)}
        try:
            http_request = request.Request(
                url=f"{base_url.rstrip('/')}/embeddings",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with self.urlopen(http_request, timeout=self.settings.llm_timeout) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return []

        data = response_payload.get("data") or []
        if not data:
            return []
        embedding = data[0].get("embedding") or []
        return [float(value) for value in embedding]
