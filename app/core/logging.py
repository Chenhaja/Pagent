import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings
from app.core.log_context import ContextFilter, current_context
from app.core.security import DEFAULT_REDACTION_MAX_LENGTH, redact_sensitive_text


MAX_LOG_MESSAGE_LENGTH = DEFAULT_REDACTION_MAX_LENGTH
_CONTEXT_FIELD_NAMES = ("request_id", "session_id", "trace_id", "node_name", "task_type")
_PRIORITY_PRETTY_FIELDS = ("duration_ms", "input_chars", "output_chars", "result_count", "degraded", "degrade_reason")
_DROPPED_FIELD_NAMES = {"api_key", "raw_input", "prompt", "raw_output", "response"}


def sanitize_log_message(message: str, max_length: int = MAX_LOG_MESSAGE_LENGTH) -> str:
    """脱敏并截断日志消息。

    Args:
        message: 原始日志消息。
        max_length: 日志消息最大保留长度。

    Returns:
        隐去敏感值并限制长度后的消息。
    """
    return redact_sensitive_text(str(message), max_length=max_length)


def _sanitize_log_value(value: Any, max_length: int) -> Any:
    """清洗单个结构化日志字段。"""
    if isinstance(value, str):
        return redact_sensitive_text(value, max_length=max_length)
    if isinstance(value, dict):
        return {str(key): _sanitize_log_value(item, max_length) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_log_value(item, max_length) for item in value]
    return value


def _record_event(record: logging.LogRecord) -> str:
    """读取日志事件名。"""
    return str(getattr(record, "event", "log_event"))


def _record_fields(record: logging.LogRecord, max_length: int) -> dict[str, Any]:
    """读取并清洗 LogRecord 上的结构化字段。"""
    fields = getattr(record, "fields", {})
    if not isinstance(fields, dict):
        return {}
    return {str(key): _sanitize_log_value(value, max_length) for key, value in fields.items() if str(key) not in _DROPPED_FIELD_NAMES}


def _record_context(record: logging.LogRecord) -> dict[str, str | None]:
    """读取 LogRecord 上的上下文字段。"""
    return {name: getattr(record, name, None) for name in _CONTEXT_FIELD_NAMES}


class JsonLineFormatter(logging.Formatter):
    """将日志记录格式化为 JSON Lines。

    Args:
        service: 服务名称。
        environment: 运行环境名称。
        max_field_length: 消息和字符串字段最大保留长度。
        include_context: 是否输出上下文字段。

    Returns:
        JSON Lines 日志 formatter。
    """

    def __init__(self, service: str, environment: str, max_field_length: int = MAX_LOG_MESSAGE_LENGTH, include_context: bool = True) -> None:
        super().__init__()
        self.service = service
        self.environment = environment
        self.max_field_length = max_field_length
        self.include_context = include_context

    def format(self, record: logging.LogRecord) -> str:
        """格式化单条日志记录。

        Args:
            record: Python logging 日志记录。

        Returns:
            JSON 字符串,包含稳定基础字段。
        """
        try:
            payload: dict[str, Any] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "service": self.service,
                "environment": self.environment,
                "logger": record.name,
                "event": _record_event(record),
                "message": sanitize_log_message(record.getMessage(), max_length=self.max_field_length),
            }
            if self.include_context:
                payload.update(_record_context(record))
            payload.update(_record_fields(record, self.max_field_length))
            if record.exc_info:
                payload["exception"] = self.formatException(record.exc_info)
            return json.dumps(payload, ensure_ascii=False)
        except Exception:
            return json.dumps(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "level": record.levelname,
                    "service": self.service,
                    "environment": self.environment,
                    "logger": record.name,
                    "event": "log_format_failed",
                    "message": sanitize_log_message(record.getMessage(), max_length=self.max_field_length),
                },
                ensure_ascii=False,
            )


class PrettyFormatter(logging.Formatter):
    """将日志记录格式化为本地可读单行文本。

    Args:
        service: 服务名称。
        environment: 运行环境名称。
        max_field_length: 消息和字符串字段最大保留长度。
        include_context: 是否输出上下文字段。

    Returns:
        人类可读日志 formatter。
    """

    def __init__(self, service: str, environment: str, max_field_length: int = MAX_LOG_MESSAGE_LENGTH, include_context: bool = True) -> None:
        super().__init__()
        self.service = service
        self.environment = environment
        self.max_field_length = max_field_length
        self.include_context = include_context

    def format(self, record: logging.LogRecord) -> str:
        """格式化单条本地可读日志。

        Args:
            record: Python logging 日志记录。

        Returns:
            单行 pretty 日志文本。
        """
        try:
            timestamp = datetime.now(timezone.utc).isoformat()
            event = _record_event(record)
            message = sanitize_log_message(record.getMessage(), max_length=self.max_field_length)
            fields = _record_fields(record, self.max_field_length)
            context = _record_context(record) if self.include_context else {}
            request_id = context.get("request_id")
            request_label = f"[{request_id[:8]}]" if request_id else "[-]"
            parts = [timestamp, record.levelname, request_label, event]
            node_name = context.get("node_name")
            if node_name:
                parts.append(str(node_name))
            parts.append(message)
            for key in _ordered_pretty_keys(fields):
                parts.append(f"{key}={fields[key]}")
            if record.exc_info:
                parts.append(f"exception={self.formatException(record.exc_info)}")
            return " ".join(parts)
        except Exception:
            return f"{datetime.now(timezone.utc).isoformat()} {record.levelname} [-] log_format_failed {sanitize_log_message(record.getMessage(), max_length=self.max_field_length)}"


def _ordered_pretty_keys(fields: dict[str, Any]) -> list[str]:
    """按调试优先级排序 pretty 日志字段。"""
    priority = [key for key in _PRIORITY_PRETTY_FIELDS if key in fields]
    rest = [key for key in fields if key not in priority]
    return priority + rest


def log_event(logger: logging.Logger, level: int, event: str, message: str, **fields: Any) -> None:
    """输出结构化事件日志。

    Args:
        logger: 目标 logger。
        level: logging 级别。
        event: 稳定英文事件名。
        message: 中文可读日志消息。
        **fields: 附加结构化字段。

    Returns:
        无返回值。
    """
    context = {key: value for key, value in current_context().items() if value is not None}
    logger.log(level, message, extra={"event": event, "fields": fields, **context})


def configure_logging(settings: Settings) -> logging.Logger:
    """初始化应用日志。

    Args:
        settings: 应用配置,提供服务名、环境和日志级别。

    Returns:
        已配置的 root logger。
    """
    logger = logging.getLogger()
    logger.handlers.clear()
    logger.setLevel(settings.log_level)

    handler = logging.StreamHandler()
    formatter = _build_formatter(settings)
    handler.setFormatter(formatter)
    if settings.log_include_context:
        handler.addFilter(ContextFilter())
    logger.addHandler(handler)
    return logger


def _build_formatter(settings: Settings) -> logging.Formatter:
    """按配置构造日志 formatter。"""
    log_format = (settings.log_format or "auto").strip().lower()
    if log_format == "auto":
        log_format = "pretty" if settings.environment == "local" else "json"
    formatter_kwargs = {
        "service": settings.service_name,
        "environment": settings.environment,
        "max_field_length": settings.log_max_field_length,
        "include_context": settings.log_include_context,
    }
    if log_format == "pretty":
        return PrettyFormatter(**formatter_kwargs)
    return JsonLineFormatter(**formatter_kwargs)
