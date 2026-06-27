import json
import logging

from app.core.logging import JsonLineFormatter
from app.services.workflow_service import WorkflowService


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


def test_failed_workflow_does_not_write_persistent_memory() -> None:
    """失败 workflow 不应写入长期记忆相关输出。"""
    result = WorkflowService().generate_claims("   ")

    assert result["status"] == "requires_user_input"
    assert "memory" not in result
    assert "case_store" not in result
