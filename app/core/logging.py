import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings


class JsonLineFormatter(logging.Formatter):
    """将日志记录格式化为 JSON Lines。

    Args:
        service: 服务名称。
        environment: 运行环境名称。

    Returns:
        JSON Lines 日志 formatter。
    """

    def __init__(self, service: str, environment: str) -> None:
        super().__init__()
        self.service = service
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        """格式化单条日志记录。

        Args:
            record: Python logging 日志记录。

        Returns:
            JSON 字符串,包含稳定基础字段。
        """
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": self.service,
            "environment": self.environment,
            "logger": record.name,
            "event": getattr(record, "event", "log_event"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


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
    handler.setFormatter(
        JsonLineFormatter(
            service=settings.service_name,
            environment=settings.environment,
        )
    )
    logger.addHandler(handler)
    return logger
