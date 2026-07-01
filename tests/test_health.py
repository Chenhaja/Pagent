import logging

from fastapi.testclient import TestClient

from app.core.logging import PrettyFormatter
from app.main import app


def test_health_check_returns_ok_status() -> None:
    """健康检查接口应返回固定可用状态。"""
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_app_startup_configures_logging() -> None:
    """应用入口应初始化日志配置,保证调试启动时可见日志。"""
    root_logger = logging.getLogger()

    assert root_logger.handlers
    assert isinstance(root_logger.handlers[0].formatter, PrettyFormatter)
