from fastapi.testclient import TestClient

from app.main import app


def test_health_check_returns_ok_status() -> None:
    """健康检查接口应返回固定可用状态。"""
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
