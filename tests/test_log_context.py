import json
import logging

from app.core.config import Settings
from app.core.log_context import ContextFilter, bind_context, current_context, new_request_id, reset_context
from app.core.logging import JsonLineFormatter, PrettyFormatter, configure_logging, log_event


class ListHandler(logging.Handler):
    """测试用日志 handler。"""

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        """记录格式化后的日志文本。"""
        self.messages.append(self.format(record))


def test_bind_context_and_reset_context_rolls_back_values() -> None:
    """上下文绑定后应能按 token 回滚。"""
    token = bind_context(request_id="req-1", node_name="qa")

    assert current_context()["request_id"] == "req-1"
    assert current_context()["node_name"] == "qa"

    reset_context(token)

    assert current_context()["request_id"] is None
    assert current_context()["node_name"] is None


def test_nested_context_does_not_leak_to_sibling_node() -> None:
    """嵌套节点上下文应回滚到父级。"""
    parent = bind_context(request_id="req-1")
    first = bind_context(node_name="first")
    reset_context(first)
    second = bind_context(node_name="second")

    assert current_context()["request_id"] == "req-1"
    assert current_context()["node_name"] == "second"

    reset_context(second)
    reset_context(parent)


def test_context_filter_injects_bound_fields() -> None:
    """ContextFilter 应把上下文字段注入 LogRecord。"""
    token = bind_context(request_id="req-1", session_id="sess-1", trace_id="trace-1", node_name="qa", task_type="answer")
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "ok", (), None)

    ContextFilter().filter(record)

    reset_context(token)
    assert record.request_id == "req-1"
    assert record.session_id == "sess-1"
    assert record.trace_id == "trace-1"
    assert record.node_name == "qa"
    assert record.task_type == "answer"


def test_new_request_id_returns_distinct_values() -> None:
    """请求 ID 生成器应返回非空且不同的值。"""
    first = new_request_id()
    second = new_request_id()

    assert first
    assert second
    assert first != second


def test_json_formatter_flattens_fields_and_context() -> None:
    """JSON formatter 应平铺结构化字段和上下文。"""
    formatter = JsonLineFormatter(service="patent-agent", environment="prod", max_field_length=20)
    token = bind_context(request_id="req-123456", node_name="qa")
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "调用 sk-secret 成功", (), None)
    record.event = "node_end"
    record.fields = {"duration_ms": 12, "api_key": "sk-secret", "long": "技术内容" * 20}
    ContextFilter().filter(record)

    payload = json.loads(formatter.format(record))

    reset_context(token)
    assert payload["event"] == "node_end"
    assert payload["request_id"] == "req-123456"
    assert payload["node_name"] == "qa"
    assert payload["duration_ms"] == 12
    assert "api_key" not in payload
    assert payload["message"] == "调用 [REDACTED] 成功"
    assert payload["long"].endswith("...[TRUNCATED]")


def test_pretty_formatter_outputs_human_readable_line() -> None:
    """Pretty formatter 应输出包含关键字段的人类可读单行。"""
    formatter = PrettyFormatter(service="patent-agent", environment="local")
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "节点完成", (), None)
    record.event = "node_end"
    record.request_id = "request-abcdef"
    record.node_name = "qa"
    record.fields = {"duration_ms": 12, "result_count": 3}

    line = formatter.format(record)

    assert "INFO" in line
    assert "node_end" in line
    assert "qa" in line
    assert "request-" in line
    assert "duration_ms=12" in line
    assert "result_count=3" in line


def test_configure_logging_selects_formatter_by_log_format() -> None:
    """configure_logging 应按 log_format 选择 formatter。"""
    json_logger = configure_logging(Settings(log_format="json"))
    assert isinstance(json_logger.handlers[0].formatter, JsonLineFormatter)

    pretty_logger = configure_logging(Settings(log_format="pretty"))
    assert isinstance(pretty_logger.handlers[0].formatter, PrettyFormatter)

    auto_local_logger = configure_logging(Settings(log_format="auto", environment="local"))
    assert isinstance(auto_local_logger.handlers[0].formatter, PrettyFormatter)

    auto_prod_logger = configure_logging(Settings(log_format="auto", environment="prod"))
    assert isinstance(auto_prod_logger.handlers[0].formatter, JsonLineFormatter)


def test_log_event_writes_structured_fields() -> None:
    """log_event 应通过 fields 写入结构化字段。"""
    logger = logging.getLogger("test.log_event")
    logger.handlers.clear()
    logger.propagate = False
    handler = ListHandler()
    handler.setFormatter(JsonLineFormatter(service="patent-agent", environment="prod"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    log_event(logger, logging.INFO, "node_end", "节点完成", duration_ms=10)

    payload = json.loads(handler.messages[0])
    assert payload["event"] == "node_end"
    assert payload["duration_ms"] == 10


def test_configure_logging_can_disable_context_filter() -> None:
    """关闭上下文注入时 handler 不应挂 ContextFilter。"""
    logger = configure_logging(Settings(log_include_context=False))

    assert not any(isinstance(filter_item, ContextFilter) for filter_item in logger.handlers[0].filters)
