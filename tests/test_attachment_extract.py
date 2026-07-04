from pathlib import Path

import pytest

from app.core.config import Settings
from app.tools import file_extract
from app.tools.file_extract import AttachmentExtractionError, extract_document


def test_extract_text_file_normalizes_and_returns_metadata(tmp_path) -> None:
    """txt 附件应直读、归一化并返回文本元数据。"""
    path = tmp_path / "交底书.txt"
    path.write_text("第一行\r\n\x00\x01第二行\n\n\n第三行", encoding="utf-8")

    result = extract_document(path, settings=Settings(attachment_max_chars=100))

    assert result.text == "第一行\n第二行\n\n第三行"
    assert result.format == "text"
    assert result.chars == len(result.text)
    assert result.truncated is False
    assert result.media == []


def test_extract_markdown_file_keeps_markdown_format(tmp_path) -> None:
    """md 附件应按 Markdown 格式返回。"""
    path = tmp_path / "说明书.md"
    path.write_text("# 标题\n\n- 要点", encoding="utf-8")

    result = extract_document(path, settings=Settings(attachment_max_chars=100))

    assert result.format == "markdown"
    assert result.text == "# 标题\n\n- 要点"


def test_extract_document_truncates_text(tmp_path) -> None:
    """抽取文本超过上限时应截断并标记。"""
    path = tmp_path / "长文.txt"
    path.write_text("abcdef", encoding="utf-8")

    result = extract_document(path, settings=Settings(attachment_max_chars=3))

    assert result.text == "abc"
    assert result.chars == 3
    assert result.truncated is True


def test_extract_document_rejects_legacy_office_formats(tmp_path) -> None:
    """doc / ppt 旧格式应明确拒绝,不尝试 shell 转换。"""
    path = tmp_path / "旧格式.doc"
    path.write_bytes(b"legacy")

    with pytest.raises(AttachmentExtractionError, match="不支持"):
        extract_document(path, settings=Settings())


def test_extract_docx_delegates_to_office_converter(monkeypatch, tmp_path) -> None:
    """docx 附件应委托 Office 转换函数生成 Markdown。"""
    path = tmp_path / "交底书.docx"
    path.write_bytes(b"docx")

    def fake_convert_docx_to_markdown(file_path: Path, media_dir: Path | None = None):
        """返回测试用 docx 转换结果。"""
        return "# 技术交底书", [{"path": "media/image1.png", "content_type": "image/png"}]

    monkeypatch.setattr(file_extract, "convert_docx_to_markdown", fake_convert_docx_to_markdown)

    result = extract_document(path, settings=Settings())

    assert result.format == "markdown"
    assert result.text == "# 技术交底书"
    assert result.media == [{"path": "media/image1.png", "content_type": "image/png"}]


def test_extract_pptx_delegates_to_office_converter(monkeypatch, tmp_path) -> None:
    """pptx 附件应委托 Office 转换函数生成 Markdown。"""
    path = tmp_path / "答复方案.pptx"
    path.write_bytes(b"pptx")

    def fake_convert_pptx_to_markdown(file_path: Path, media_dir: Path | None = None):
        """返回测试用 pptx 转换结果。"""
        return "## 第 1 页\n方案", []

    monkeypatch.setattr(file_extract, "convert_pptx_to_markdown", fake_convert_pptx_to_markdown)

    result = extract_document(path, settings=Settings())

    assert result.format == "markdown"
    assert result.text == "## 第 1 页\n方案"


def test_extract_document_rejects_empty_content(tmp_path) -> None:
    """空内容附件应返回结构化抽取错误。"""
    path = tmp_path / "空.md"
    path.write_text("   ", encoding="utf-8")

    with pytest.raises(AttachmentExtractionError, match="空"):
        extract_document(path, settings=Settings())
