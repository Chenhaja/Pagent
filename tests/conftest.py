import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def isolate_external_model_env(monkeypatch):
    """测试默认不读取本机真实模型配置,避免误调外部 API。"""
    for name in (
        "PAGENT_LLM_BASE_URL",
        "PAGENT_LLM_MODEL",
        "PAGENT_LLM_API_KEY",
        "PAGENT_LLM_CHEAP_MODEL",
        "PAGENT_LLM_STRONG_MODEL",
        "PAGENT_REACT_POLICY_MODEL",
        "PAGENT_REACT_REFLECT_MODEL",
        "PAGENT_QUERY_REWRITE_MODEL",
        "PAGENT_EMBEDDING_BASE_URL",
        "PAGENT_EMBEDDING_MODEL",
        "PAGENT_EMBEDDING_API_KEY",
        "PAGENT_RERANK_BASE_URL",
        "PAGENT_RERANK_MODEL",
        "PAGENT_RERANK_API_KEY",
        "PAGENT_SPARSE_BASE_URL",
        "PAGENT_SPARSE_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
