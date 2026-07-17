from urllib.error import HTTPError

import pytest

from app.core.config import Settings
from app.orchestrator.tool_registry import build_default_tool_registry
from app.tools.patent_search import PatentSearchTool


class FakeErrorBody:
    """测试用 HTTPError body。"""

    def __init__(self, body: bytes) -> None:
        """初始化错误响应正文。"""
        self.body = body

    def read(self, size: int = -1) -> bytes:
        """返回截断后的错误响应正文。"""
        return self.body if size < 0 else self.body[:size]


class FakeSerpApiProvider:
    """测试用 SerpAPI provider,避免真实网络调用。"""

    def __init__(self, payload: dict | None = None, error: Exception | None = None) -> None:
        """初始化 fake provider。

        Args:
            payload: 要返回的 SerpAPI 响应。
            error: 调用时要抛出的异常。

        Returns:
            无返回值。
        """
        self.payload = payload or {}
        self.error = error
        self.calls: list[dict] = []

    def search(self, *, query: str, top_k: int, country: str, status: str, api_key: str) -> dict:
        """记录调用参数并返回预设响应。"""
        self.calls.append({"query": query, "top_k": top_k, "country": country, "status": status, "api_key": api_key})
        if self.error:
            raise self.error
        return self.payload


def test_patent_search_rejects_empty_query() -> None:
    """patent_search 应拒绝空 query。"""
    tool = PatentSearchTool(Settings(allow_network=True, serpapi_api_key="secret"), provider=FakeSerpApiProvider())

    observation = tool.run({"query": ""})

    assert observation.error == "invalid_input"
    assert observation.external is True


def test_patent_search_is_skipped_without_network() -> None:
    """patent_search 关闭联网时应安全降级且不触发 provider。"""
    provider = FakeSerpApiProvider()
    tool = PatentSearchTool(Settings(allow_network=False, serpapi_api_key="secret"), provider=provider)

    observation = tool.run({"query": "夹爪"})

    assert observation.error == "network_disabled"
    assert observation.external is True
    assert observation.evidence == []
    assert provider.calls == []


def test_patent_search_degrades_without_serpapi_key() -> None:
    """patent_search 缺少 SerpAPI Key 时应降级且不触网。"""
    provider = FakeSerpApiProvider()
    tool = PatentSearchTool(Settings(allow_network=True, serpapi_api_key=None), provider=provider)

    observation = tool.run({"query": "夹爪"})

    assert observation.error == "serpapi_key_missing"
    assert observation.external is True
    assert observation.evidence == []
    assert provider.calls == []


def test_patent_search_normalizes_serpapi_results_and_top_k() -> None:
    """patent_search 应规范化 SerpAPI 结果并按 top_k 截断。"""
    provider = FakeSerpApiProvider(
        {
            "patents_results": [
                {
                    "title": "自适应夹爪",
                    "publication_number": "CN123456A",
                    "snippet": "一种用于夹持工件的夹爪。",
                    "link": "https://patents.example/CN123456A",
                },
                {
                    "title": "夹持机构",
                    "patent_id": "CN654321B",
                    "abstract": "夹持机构包括基座和夹持臂。",
                    "patent_link": "https://patents.example/CN654321B",
                },
            ]
        }
    )
    tool = PatentSearchTool(Settings(allow_network=True, serpapi_api_key="secret", patent_search_top_k=5), provider=provider)

    observation = tool.run({"query": "夹爪", "top_k": 1, "country": "US", "status": "APPLICATION"})

    assert observation.error is None
    assert observation.external is True
    assert observation.sufficient is True
    assert provider.calls == [{"query": "夹爪", "top_k": 1, "country": "US", "status": "APPLICATION", "api_key": "secret"}]
    assert len(observation.evidence) == 1
    assert observation.evidence[0]["title"] == "自适应夹爪"
    assert observation.evidence[0]["publication_number"] == "CN123456A"
    assert observation.evidence[0]["abstract"] == "一种用于夹持工件的夹爪。"
    assert observation.evidence[0]["url"] == "https://patents.example/CN123456A"
    assert observation.evidence[0]["country"] == "US"
    assert observation.evidence[0]["status"] == "APPLICATION"
    assert observation.evidence[0]["provenance"]["source"] == "serpapi://google_patents"


def test_patent_search_provider_error_degrades_safely() -> None:
    """SerpAPI provider 异常时 patent_search 应安全降级。"""
    tool = PatentSearchTool(
        Settings(allow_network=True, serpapi_api_key="secret"),
        provider=FakeSerpApiProvider(error=RuntimeError("boom")),
    )

    observation = tool.run({"query": "夹爪"})

    assert observation.error == "patent_search_unavailable"
    assert observation.external is True
    assert observation.evidence == []


def test_patent_search_http_error_degrades_safely(caplog) -> None:
    """SerpAPI HTTPError 时 patent_search 应记录响应摘要并安全降级。"""
    error = HTTPError("https://serpapi.example/search", 400, "Bad Request", {}, FakeErrorBody(b'{"error":"bad request"}'))
    tool = PatentSearchTool(
        Settings(allow_network=True, serpapi_api_key="secret"),
        provider=FakeSerpApiProvider(error=error),
    )

    with caplog.at_level("ERROR"):
        observation = tool.run({"query": "夹爪"})

    assert observation.error == "patent_search_unavailable"
    assert observation.external is True
    assert observation.evidence == []
    record = next(item for item in caplog.records if item.event == "patent_search_failed")
    assert record.fields["http_status"] == 400
    assert record.fields["response_excerpt"] == '{"error":"bad request"}'


def test_default_tool_registry_describes_serpapi_patent_search() -> None:
    """默认 ToolRegistry 应描述 SerpAPI patent_search 参数。"""
    registry = build_default_tool_registry(Settings(allow_network=False))
    spec = registry.tool_specs()["patent_search"]

    assert "SerpAPI" in spec.description
    assert "top_k" in spec.input_schema["properties"]
    assert "country" in spec.input_schema["properties"]
    assert "status" in spec.input_schema["properties"]


@pytest.mark.parametrize("top_k", [0, -1, "bad"])
def test_patent_search_rejects_invalid_top_k(top_k: object) -> None:
    """patent_search 应拒绝非法 top_k。"""
    tool = PatentSearchTool(Settings(allow_network=True, serpapi_api_key="secret"), provider=FakeSerpApiProvider())

    observation = tool.run({"query": "夹爪", "top_k": top_k})

    assert observation.error == "invalid_input"
