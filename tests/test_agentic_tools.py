from app.core.config import Settings
from app.orchestrator.tool_registry import ToolRegistry, build_default_tool_registry
from app.tools.retrieval import RetrievalResult


class RecordingRetriever:
    """测试用检索器,记录调用并返回固定结果。"""

    def __init__(self, results: list[RetrievalResult] | None = None, should_raise: bool = False) -> None:
        self.results = results or []
        self.should_raise = should_raise
        self.calls = []

    def search(self, query: str, top_k: int = 3, as_of: str | None = None, fetch_k: int | None = None):
        """记录 search 参数并返回固定结果。"""
        self.calls.append({"query": query, "top_k": top_k, "as_of": as_of, "fetch_k": fetch_k})
        if self.should_raise:
            raise RuntimeError("retrieval failed")
        return self.results[:top_k]


def make_result() -> RetrievalResult:
    """构造包含完整 provenance 的 KB 检索结果。"""
    return RetrievalResult(
        content="法规证据",
        provenance={"source": "local://law", "document_id": "doc-1", "locator": "第1条", "doc_type": "law"},
        score=2,
        similarity=0.7,
        law_name="专利法",
        version="2020",
        effective_date="2021-06-01",
        expiry_date=None,
        status="current",
        source_url="https://example.test/law",
        retrieved_at="2026-06-01",
    )


def test_tool_registry_rejects_unknown_tool() -> None:
    """未注册工具不能被动态调用。"""
    registry = ToolRegistry(settings=Settings())

    observation = registry.run("missing", {"query": "问题"})

    assert observation.error == "tool_unavailable"
    assert observation.evidence == []


def test_kb_retrieval_tool_normalizes_evidence() -> None:
    """kb_retrieval 应复用 retriever 并归一化 provenance。"""
    retriever = RecordingRetriever([make_result()])
    registry = build_default_tool_registry(Settings(retrieval_top_k=2), retriever=retriever)

    observation = registry.run("kb_retrieval", {"query": "创造性", "top_k": 2})

    assert retriever.calls == [{"query": "创造性", "top_k": 2, "as_of": None, "fetch_k": None}]
    assert observation.tool_name == "kb_retrieval"
    assert observation.error is None
    assert observation.sufficient is True
    assert observation.top_score == 0.7
    assert observation.evidence == [
        {
            "content": "法规证据",
            "provenance": {
                "source": "local://law",
                "document_id": "doc-1",
                "locator": "第1条",
                "doc_type": "law",
                "law_name": "专利法",
                "version": "2020",
                "effective_date": "2021-06-01",
                "status": "current",
                "source_url": "https://example.test/law",
                "retrieved_at": "2026-06-01",
            },
            "score": 2,
            "similarity": 0.7,
        }
    ]


def test_kb_retrieval_tool_handles_invalid_input_and_errors() -> None:
    """非法输入和检索异常应返回安全 observation。"""
    registry = build_default_tool_registry(Settings(), retriever=RecordingRetriever(should_raise=True))

    invalid = registry.run("kb_retrieval", {"query": ""})
    failed = registry.run("kb_retrieval", {"query": "问题"})

    assert invalid.error == "invalid_input"
    assert failed.error == "tool_unavailable"


def test_external_tools_are_disabled_by_default() -> None:
    """外部工具默认关闭,即使注册也不可调用。"""
    registry = build_default_tool_registry(Settings())

    for tool_name in ["websearch", "legal_status", "official_fee"]:
        observation = registry.run(tool_name, {"query": "问题"})
        assert observation.tool_name == tool_name
        assert observation.error == "tool_unavailable"
        assert observation.external is True


def test_external_stub_tools_return_provenance_when_enabled() -> None:
    """显式启用外部工具时 stub 应返回可核对 provenance。"""
    settings = Settings(
        agentic_external_tools_enabled=True,
        websearch_enabled=True,
        legal_status_enabled=True,
        official_fee_enabled=True,
    )
    registry = build_default_tool_registry(settings)

    web = registry.run("websearch", {"query": "最新案例"})
    legal = registry.run("legal_status", {"query": "CN123"})
    fee = registry.run("official_fee", {"query": "发明专利官费"})

    for observation in [web, legal, fee]:
        assert observation.error is None
        assert observation.external is True
        assert observation.evidence
        provenance = observation.evidence[0]["provenance"]
        assert provenance["source"]
        assert provenance["retrieved_at"]
        assert provenance["requires_official_check"] is True
