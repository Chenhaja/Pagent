import json
from typing import Any, Protocol
from urllib.parse import urlencode
from urllib.request import urlopen

from app.core.config import Settings, get_settings
from app.orchestrator.react_loop import ToolObservation


class SerpApiPatentProvider(Protocol):
    """SerpAPI 专利检索 provider 协议。"""

    def search(self, *, query: str, top_k: int, country: str, status: str, api_key: str) -> dict[str, Any]:
        """执行 SerpAPI 专利检索。

        Args:
            query: 检索关键词。
            top_k: 最大返回数量。
            country: 专利国家过滤条件。
            status: 专利状态过滤条件。
            api_key: SerpAPI Key。

        Returns:
            SerpAPI 原始 JSON 响应。
        """
        ...


class DefaultSerpApiPatentProvider:
    """基于 SerpAPI Google Patents 引擎的默认检索 provider。"""

    def search(self, *, query: str, top_k: int, country: str, status: str, api_key: str) -> dict[str, Any]:
        """调用 SerpAPI Google Patents 搜索接口。

        Args:
            query: 检索关键词。
            top_k: 最大返回数量。
            country: 专利国家过滤条件。
            status: 专利状态过滤条件。
            api_key: SerpAPI Key。

        Returns:
            SerpAPI 原始 JSON 响应。
        """
        params = {
            "engine": "google_patents",
            "q": query,
            "num": top_k,
            "api_key": api_key,
        }
        if country:
            params["country"] = country
        if status:
            params["status"] = status
        url = f"https://serpapi.com/search.json?{urlencode(params)}"
        with urlopen(url, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))


class PatentSearchTool:
    """受联网配置门控的 SerpAPI 专利检索工具。"""

    def __init__(self, settings: Settings | None = None, provider: SerpApiPatentProvider | None = None) -> None:
        """初始化专利检索工具。

        Args:
            settings: 应用配置,未传入时读取全局配置。
            provider: 可注入 SerpAPI provider,测试中用于避免真实网络。

        Returns:
            无返回值。
        """
        self.settings = settings or get_settings()
        self.provider = provider or DefaultSerpApiPatentProvider()

    def run(self, tool_input: dict) -> ToolObservation:
        """执行受门控的 SerpAPI 专利检索。

        Args:
            tool_input: 包含 query、top_k、country、status 的输入。

        Returns:
            规范化后的专利 evidence;未授权或异常时安全降级。
        """
        query = str(tool_input.get("query") or "").strip()
        if not query:
            return ToolObservation(tool_name="patent_search", error="invalid_input", external=True)
        top_k = self._parse_top_k(tool_input.get("top_k"))
        if top_k is None:
            return ToolObservation(tool_name="patent_search", error="invalid_input", external=True)
        if not self.settings.allow_network:
            return ToolObservation(tool_name="patent_search", error="network_disabled", external=True)
        api_key = self.settings.serpapi_api_key
        if not api_key:
            return ToolObservation(tool_name="patent_search", error="serpapi_key_missing", external=True)
        country = str(tool_input.get("country") or "CN").strip().upper()
        status = str(tool_input.get("status") or "GRANT").strip().upper()
        try:
            payload = self.provider.search(query=query, top_k=top_k, country=country, status=status, api_key=api_key)
        except Exception:
            return ToolObservation(tool_name="patent_search", error="patent_search_unavailable", external=True)
        evidence = [self._normalize_result(item, country=country, status=status) for item in self._extract_results(payload)[:top_k]]
        return ToolObservation(tool_name="patent_search", evidence=evidence, sufficient=bool(evidence), external=True)

    def _parse_top_k(self, value: object) -> int | None:
        """解析并校验 top_k。"""
        try:
            top_k = int(value) if value is not None else int(self.settings.patent_search_top_k)
        except (TypeError, ValueError):
            return None
        return top_k if top_k > 0 else None

    def _extract_results(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """从 SerpAPI 响应中提取专利结果列表。"""
        results = payload.get("patents_results") or payload.get("organic_results") or []
        return [item for item in results if isinstance(item, dict)]

    def _normalize_result(self, result: dict[str, Any], *, country: str, status: str) -> dict[str, Any]:
        """将 SerpAPI 单条结果规范化为 evidence。"""
        title = str(result.get("title") or "").strip()
        publication_number = str(result.get("publication_number") or result.get("patent_id") or "").strip()
        abstract = str(result.get("abstract") or result.get("snippet") or "").strip()
        url = str(result.get("link") or result.get("patent_link") or "").strip()
        return {
            "title": title,
            "publication_number": publication_number,
            "abstract": abstract,
            "url": url,
            "country": country,
            "status": status,
            "provenance": {
                "source": "serpapi://google_patents",
                "requires_official_check": True,
            },
        }
