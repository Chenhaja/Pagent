import json
import logging

from app.core.config import Settings
from app.core.logging import JsonLineFormatter
from app.core.security import redact_sensitive_text, should_send_full_content


def test_json_line_formatter_redacts_api_key_like_values() -> None:
    """日志格式化器不应输出 API key 样式敏感值。"""
    formatter = JsonLineFormatter(service="patent-agent", environment="local")
    record = logging.LogRecord(
        name="app.security",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="调用失败 sk-test-secret-token",
        args=(),
        exc_info=None,
    )

    payload = json.loads(formatter.format(record))

    assert "sk-test-secret-token" not in payload["message"]
    assert "[REDACTED]" in payload["message"]


def test_json_line_formatter_truncates_long_messages() -> None:
    """日志格式化器应截断过长文本。"""
    formatter = JsonLineFormatter(service="patent-agent", environment="local")
    record = logging.LogRecord(
        name="app.security",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="原文:" + "技术内容" * 200,
        args=(),
        exc_info=None,
    )

    payload = json.loads(formatter.format(record))

    assert len(payload["message"]) <= 220
    assert payload["message"].endswith("...[TRUNCATED]")



def test_security_defaults_do_not_send_full_sensitive_content() -> None:
    """默认安全策略不允许向云模型发送完整敏感材料。"""
    settings = Settings()

    assert should_send_full_content(settings, user_explicitly_allowed=False) is False
    assert should_send_full_content(settings, user_explicitly_allowed=True) is False
    assert should_send_full_content(Settings(allow_cloud_sensitive_content=True), user_explicitly_allowed=True) is True


def test_redact_sensitive_text_masks_api_keys_and_truncates_long_text() -> None:
    """脱敏工具应隐藏密钥并截断长文本。"""
    text = "API Key: sk-test-secret " + "技术交底" * 200

    redacted = redact_sensitive_text(text, max_length=80)

    assert "sk-test-secret" not in redacted
    assert "[REDACTED]" in redacted
    assert redacted.endswith("...[TRUNCATED]")
    assert len(redacted) <= 95


def test_redact_sensitive_text_masks_common_secret_patterns() -> None:
    """脱敏工具应隐藏常见令牌、密码和 API Key 模式。"""
    text = "Bearer token-secret password=pass123 token=tok123 api_key=key123 sk-test-secret"

    redacted = redact_sensitive_text(text)

    assert "token-secret" not in redacted
    assert "pass123" not in redacted
    assert "tok123" not in redacted
    assert "key123" not in redacted
    assert "sk-test-secret" not in redacted
    assert redacted.count("[REDACTED]") >= 5
