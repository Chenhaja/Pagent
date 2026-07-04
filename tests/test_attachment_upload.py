import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.services.attachment_service import AttachmentService, AttachmentServiceError


def test_attachment_service_saves_text_attachment(monkeypatch, tmp_path) -> None:
    """附件服务应保存原文件、抽取文本和元数据。"""
    settings = Settings(attachment_storage_dir=str(tmp_path), attachment_max_bytes=1024, attachment_max_chars=100)
    service = AttachmentService(settings=settings)

    metadata = service.save_upload(filename="交底书.txt", content_type="text/plain", content=b"hello", doc_type="invention_disclosure")

    attachment_dir = tmp_path / metadata["attachment_id"]
    assert metadata["filename"] == "交底书.txt"
    assert metadata["bytes"] == 5
    assert metadata["chars"] == 5
    assert metadata["doc_type"] == "invention_disclosure"
    assert metadata["format"] == "text"
    assert (attachment_dir / "original.txt").exists()
    assert (attachment_dir / "extracted.txt").read_text(encoding="utf-8") == "hello"
    assert json.loads((attachment_dir / "metadata.json").read_text(encoding="utf-8"))["attachment_id"] == metadata["attachment_id"]


def test_attachment_service_rejects_invalid_type(tmp_path) -> None:
    """附件服务应拒绝非白名单扩展名。"""
    service = AttachmentService(settings=Settings(attachment_storage_dir=str(tmp_path)))

    try:
        service.save_upload(filename="evil.exe", content_type="application/octet-stream", content=b"x", doc_type="other")
    except AttachmentServiceError as exc:
        assert exc.code == "attachment_type_not_allowed"
    else:
        raise AssertionError("非白名单类型应被拒绝")


def test_attachment_service_rejects_oversized_file(tmp_path) -> None:
    """附件服务应拒绝超过大小限制的文件。"""
    service = AttachmentService(settings=Settings(attachment_storage_dir=str(tmp_path), attachment_max_bytes=1))

    try:
        service.save_upload(filename="a.txt", content_type="text/plain", content=b"ab", doc_type="other")
    except AttachmentServiceError as exc:
        assert exc.code == "attachment_too_large"
    else:
        raise AssertionError("超大附件应被拒绝")


def test_attachment_service_rejects_invalid_doc_type(tmp_path) -> None:
    """附件服务应拒绝非法 doc_type。"""
    service = AttachmentService(settings=Settings(attachment_storage_dir=str(tmp_path)))

    try:
        service.save_upload(filename="a.txt", content_type="text/plain", content=b"a", doc_type="unknown")
    except AttachmentServiceError as exc:
        assert exc.code == "invalid_doc_type"
    else:
        raise AssertionError("非法 doc_type 应被拒绝")


def test_attachment_upload_api_returns_batch_response(monkeypatch, tmp_path) -> None:
    """上传端点应返回 attachments 批量包装。"""
    monkeypatch.setattr(
        "app.services.attachment_service.get_settings",
        lambda: Settings(attachment_storage_dir=str(tmp_path), attachment_max_bytes=1024, attachment_max_count=2),
    )
    client = TestClient(app)

    response = client.post(
        "/agent/attachments",
        data={"doc_type": "invention_disclosure"},
        files={"files": ("交底书.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["attachments"]) == 1
    assert payload["attachments"][0]["filename"] == "交底书.txt"
    assert payload["attachments"][0]["chars"] == 5
    assert payload["attachments"][0]["truncated"] is False


def test_attachment_upload_api_rejects_too_many_files(monkeypatch, tmp_path) -> None:
    """上传端点应拒绝超过数量限制的文件。"""
    monkeypatch.setattr(
        "app.services.attachment_service.get_settings",
        lambda: Settings(attachment_storage_dir=str(tmp_path), attachment_max_count=1),
    )
    client = TestClient(app)

    response = client.post(
        "/agent/attachments",
        files=[("files", ("a.txt", b"a", "text/plain")), ("files", ("b.txt", b"b", "text/plain"))],
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["errors"] == ["attachment_count_exceeded"]
