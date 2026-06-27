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
    get_settings.cache_clear()


def test_settings_do_not_expose_secret_values() -> None:
    """配置序列化结果不应暴露密钥字段。"""
    settings = Settings(llm_api_key="secret-value")

    public_values = settings.to_public_dict()

    assert "llm_api_key" not in public_values
    assert "secret-value" not in str(public_values)


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
