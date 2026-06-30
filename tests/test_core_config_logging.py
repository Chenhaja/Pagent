import json
import logging

from app.core.config import Settings, get_settings
from app.core.logging import JsonLineFormatter, configure_logging


def test_default_settings_use_safe_local_values() -> None:
    """默认配置应使用安全的本地占位值。"""
    settings = get_settings()

    assert settings.service_name == "patent-agent"
    assert settings.environment == "local"
    assert settings.llm_api_key is None
    assert settings.llm_base_url is None
    assert settings.llm_model == ""
    assert settings.llm_temperature == 0.2
    assert settings.llm_max_tokens == 2048
    assert settings.llm_timeout == 30.0
    assert settings.llm_retry_count == 2
    assert settings.llm_retry_backoff == 0.5
    assert settings.allow_cloud_sensitive_content is False
    assert settings.redaction_enabled is True
    assert settings.external_translation_agent_url is None
    assert settings.memory_enabled is True
    assert settings.memory_db_path == "./pagent_memory.db"
    assert settings.memory_history_window == 6
    assert settings.memory_token_budget == 1500
    assert settings.memory_summary_model is None
    assert settings.retrieval_backend == "qdrant"
    assert settings.retrieval_top_k == 3
    assert settings.retrieval_max_steps == 1
    assert settings.retrieval_token_budget == 1000
    assert settings.retrieval_timeout_seconds == 10
    assert settings.retrieval_default_status == "current"
    assert settings.retrieval_enable_time_filter is True
    assert settings.retrieval_fetch_k == 30
    assert settings.retrieval_use_rerank is False
    assert settings.rerank_base_url is None
    assert settings.rerank_model == ""
    assert settings.rerank_api_key is None
    assert settings.rerank_top_k is None
    assert settings.retrieval_use_hybrid is False
    assert settings.sparse_encoder == "local"
    assert settings.sparse_base_url is None
    assert settings.sparse_model == ""
    assert settings.hybrid_fusion == "rrf"
    assert settings.retrieval_use_query_rewrite is False
    assert settings.query_rewrite_mode == "multi"
    assert settings.query_rewrite_count == 3
    assert settings.law_stale_days == 365
    assert settings.qdrant_url is None
    assert settings.qdrant_api_key is None
    assert settings.qdrant_collection == "patent_kb"
    assert settings.embedding_base_url is None
    assert settings.embedding_vector_size == 1024
    assert settings.embedding_model == ""
    assert settings.embedding_api_key is None


def test_settings_read_llm_values_from_dotenv_when_not_testing(monkeypatch, tmp_path) -> None:
    """本地 .env 应能提供 LLM 配置,便于开发时保存私有 API Key。"""
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "PAGENT_LLM_BASE_URL=https://llm.example.test/v1\n"
        "PAGENT_LLM_MODEL=test-model\n"
        "PAGENT_LLM_API_KEY=sk-test-secret\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("PAGENT_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("PAGENT_LLM_MODEL", raising=False)
    monkeypatch.delenv("PAGENT_LLM_API_KEY", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.llm_base_url == "https://llm.example.test/v1"
    assert settings.llm_model == "test-model"
    assert settings.llm_api_key == "sk-test-secret"
    get_settings.cache_clear()


def test_settings_read_llm_values_from_environment(monkeypatch) -> None:
    """LLM 配置应从环境变量读取。"""
    monkeypatch.setenv("PAGENT_LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("PAGENT_LLM_MODEL", "test-model")
    monkeypatch.setenv("PAGENT_LLM_API_KEY", "sk-test-secret")
    monkeypatch.setenv("PAGENT_LLM_TEMPERATURE", "0.3")
    monkeypatch.setenv("PAGENT_LLM_MAX_TOKENS", "1024")
    monkeypatch.setenv("PAGENT_LLM_TIMEOUT", "12.5")
    monkeypatch.setenv("PAGENT_LLM_RETRY_COUNT", "4")
    monkeypatch.setenv("PAGENT_LLM_RETRY_BACKOFF", "0.75")
    monkeypatch.setenv("PAGENT_LLM_CHEAP_MODEL", "cheap-model")
    monkeypatch.setenv("PAGENT_LLM_STRONG_MODEL", "strong-model")
    monkeypatch.setenv("PAGENT_ALLOW_CLOUD_SENSITIVE_CONTENT", "true")
    monkeypatch.setenv("PAGENT_MEMORY_ENABLED", "false")
    monkeypatch.setenv("PAGENT_MEMORY_DB_PATH", "./custom_memory.sqlite3")
    monkeypatch.setenv("PAGENT_MEMORY_HISTORY_WINDOW", "8")
    monkeypatch.setenv("PAGENT_MEMORY_TOKEN_BUDGET", "2000")
    monkeypatch.setenv("PAGENT_MEMORY_SUMMARY_MODEL", "summary-model")
    monkeypatch.setenv("PAGENT_RETRIEVAL_BACKEND", "qdrant")
    monkeypatch.setenv("PAGENT_RETRIEVAL_TOP_K", "5")
    monkeypatch.setenv("PAGENT_RETRIEVAL_MAX_STEPS", "2")
    monkeypatch.setenv("PAGENT_RETRIEVAL_TOKEN_BUDGET", "300")
    monkeypatch.setenv("PAGENT_RETRIEVAL_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("PAGENT_RETRIEVAL_DEFAULT_STATUS", "superseded")
    monkeypatch.setenv("PAGENT_RETRIEVAL_ENABLE_TIME_FILTER", "false")
    monkeypatch.setenv("PAGENT_RETRIEVAL_FETCH_K", "40")
    monkeypatch.setenv("PAGENT_RETRIEVAL_USE_RERANK", "true")
    monkeypatch.setenv("PAGENT_RERANK_BASE_URL", "https://rerank.example.test")
    monkeypatch.setenv("PAGENT_RERANK_MODEL", "rerank-model")
    monkeypatch.setenv("PAGENT_RERANK_API_KEY", "rerank-secret")
    monkeypatch.setenv("PAGENT_RERANK_TOP_K", "4")
    monkeypatch.setenv("PAGENT_RETRIEVAL_USE_HYBRID", "true")
    monkeypatch.setenv("PAGENT_SPARSE_ENCODER", "service")
    monkeypatch.setenv("PAGENT_SPARSE_BASE_URL", "https://sparse.example.test")
    monkeypatch.setenv("PAGENT_SPARSE_MODEL", "sparse-model")
    monkeypatch.setenv("PAGENT_HYBRID_FUSION", "rrf")
    monkeypatch.setenv("PAGENT_RETRIEVAL_USE_QUERY_REWRITE", "true")
    monkeypatch.setenv("PAGENT_QUERY_REWRITE_MODE", "hyde")
    monkeypatch.setenv("PAGENT_QUERY_REWRITE_COUNT", "5")
    monkeypatch.setenv("PAGENT_LAW_STALE_DAYS", "180")
    monkeypatch.setenv("PAGENT_QDRANT_URL", "http://qdrant.example.test")
    monkeypatch.setenv("PAGENT_QDRANT_API_KEY", "qdrant-secret")
    monkeypatch.setenv("PAGENT_QDRANT_COLLECTION", "custom_kb")
    monkeypatch.setenv("PAGENT_EMBEDDING_BASE_URL", "https://embedding.example.test/v1")
    monkeypatch.setenv("PAGENT_EMBEDDING_VECTOR_SIZE", "1536")
    monkeypatch.setenv("PAGENT_EMBEDDING_MODEL", "embedding-model")
    monkeypatch.setenv("PAGENT_EMBEDDING_API_KEY", "embedding-secret")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.llm_base_url == "https://llm.example.test/v1"
    assert settings.llm_model == "test-model"
    assert settings.llm_api_key == "sk-test-secret"
    assert settings.llm_temperature == 0.3
    assert settings.llm_max_tokens == 1024
    assert settings.llm_timeout == 12.5
    assert settings.llm_retry_count == 4
    assert settings.llm_retry_backoff == 0.75
    assert settings.llm_cheap_model == "cheap-model"
    assert settings.llm_strong_model == "strong-model"
    assert settings.allow_cloud_sensitive_content is True
    assert settings.memory_enabled is False
    assert settings.memory_db_path == "./custom_memory.sqlite3"
    assert settings.memory_history_window == 8
    assert settings.memory_token_budget == 2000
    assert settings.memory_summary_model == "summary-model"
    assert settings.retrieval_backend == "qdrant"
    assert settings.retrieval_top_k == 5
    assert settings.retrieval_max_steps == 2
    assert settings.retrieval_token_budget == 300
    assert settings.retrieval_timeout_seconds == 7
    assert settings.retrieval_default_status == "superseded"
    assert settings.retrieval_enable_time_filter is False
    assert settings.retrieval_fetch_k == 40
    assert settings.retrieval_use_rerank is True
    assert settings.rerank_base_url == "https://rerank.example.test"
    assert settings.rerank_model == "rerank-model"
    assert settings.rerank_api_key == "rerank-secret"
    assert settings.rerank_top_k == 4
    assert settings.retrieval_use_hybrid is True
    assert settings.sparse_encoder == "service"
    assert settings.sparse_base_url == "https://sparse.example.test"
    assert settings.sparse_model == "sparse-model"
    assert settings.hybrid_fusion == "rrf"
    assert settings.retrieval_use_query_rewrite is True
    assert settings.query_rewrite_mode == "hyde"
    assert settings.query_rewrite_count == 5
    assert settings.law_stale_days == 180
    assert settings.qdrant_url == "http://qdrant.example.test"
    assert settings.qdrant_api_key == "qdrant-secret"
    assert settings.qdrant_collection == "custom_kb"
    assert settings.embedding_base_url == "https://embedding.example.test/v1"
    assert settings.embedding_vector_size == 1536
    assert settings.embedding_model == "embedding-model"
    assert settings.embedding_api_key == "embedding-secret"
    get_settings.cache_clear()


def test_settings_do_not_expose_secret_values() -> None:
    """配置序列化结果不应暴露密钥字段。"""
    settings = Settings(
        llm_api_key="secret-value",
        qdrant_api_key="qdrant-secret",
        embedding_api_key="embedding-secret",
        rerank_api_key="rerank-secret",
    )

    public_values = settings.to_public_dict()

    assert "llm_api_key" not in public_values
    assert "qdrant_api_key" not in public_values
    assert "embedding_api_key" not in public_values
    assert "rerank_api_key" not in public_values
    assert "secret-value" not in str(public_values)
    assert "qdrant-secret" not in str(public_values)
    assert "embedding-secret" not in str(public_values)
    assert "rerank-secret" not in str(public_values)
    assert public_values["memory_enabled"] == "True"
    assert public_values["memory_db_path"] == "./pagent_memory.db"
    assert public_values["memory_history_window"] == "6"
    assert public_values["memory_token_budget"] == "1500"
    assert public_values["memory_summary_model"] is None
    assert public_values["retrieval_backend"] == "qdrant"
    assert public_values["retrieval_top_k"] == "3"
    assert public_values["retrieval_max_steps"] == "1"
    assert public_values["retrieval_token_budget"] == "1000"
    assert public_values["retrieval_timeout_seconds"] == "10"
    assert public_values["retrieval_default_status"] == "current"
    assert public_values["retrieval_enable_time_filter"] == "True"
    assert public_values["retrieval_fetch_k"] == "30"
    assert public_values["retrieval_use_rerank"] == "False"
    assert public_values["rerank_base_url"] is None
    assert public_values["rerank_model"] == ""
    assert public_values["rerank_top_k"] is None
    assert public_values["retrieval_use_hybrid"] == "False"
    assert public_values["sparse_encoder"] == "local"
    assert public_values["sparse_base_url"] is None
    assert public_values["sparse_model"] == ""
    assert public_values["hybrid_fusion"] == "rrf"
    assert public_values["retrieval_use_query_rewrite"] == "False"
    assert public_values["query_rewrite_mode"] == "multi"
    assert public_values["query_rewrite_count"] == "3"
    assert public_values["law_stale_days"] == "365"
    assert public_values["qdrant_url"] is None
    assert public_values["qdrant_collection"] == "patent_kb"
    assert public_values["embedding_base_url"] is None
    assert public_values["embedding_vector_size"] == "1024"
    assert public_values["embedding_model"] == ""


def test_json_line_formatter_outputs_required_fields() -> None:
    """JSON Lines 日志格式应包含稳定基础字段。"""
    formatter = JsonLineFormatter(service="patent-agent", environment="local")
    record = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="服务已启动",
        args=(),
        exc_info=None,
    )
    record.event = "service_started"

    payload = json.loads(formatter.format(record))

    assert payload["level"] == "INFO"
    assert payload["service"] == "patent-agent"
    assert payload["environment"] == "local"
    assert payload["logger"] == "app.test"
    assert payload["event"] == "service_started"
    assert payload["message"] == "服务已启动"
    assert "timestamp" in payload


def test_configure_logging_installs_json_formatter() -> None:
    """日志初始化应为 root logger 安装 JSON Lines formatter。"""
    logger = configure_logging(Settings())

    assert logger.handlers
    assert isinstance(logger.handlers[0].formatter, JsonLineFormatter)
