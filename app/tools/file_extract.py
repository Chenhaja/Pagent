import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.core.config import Settings, get_settings
from app.tools.office_to_md import OfficeConversionError, convert_docx_to_markdown, convert_pptx_to_markdown


class AttachmentExtractionError(Exception):
    """附件文本抽取失败。"""


@dataclass(frozen=True)
class ExtractedDocument:
    """附件抽取结果。

    Args:
        text: 抽取并归一化后的正文。
        format: 正文格式,text 或 markdown。
        chars: 正文字符数。
        truncated: 是否因字符上限被截断。
        media: 媒体元数据列表。

    Returns:
        可由附件服务保存和注入 workflow 的抽取结果。
    """

    text: str
    format: Literal["markdown", "text"]
    chars: int
    truncated: bool
    media: list[dict[str, Any]] = field(default_factory=list)


def extract_document(file_path: Path, settings: Settings | None = None, media_dir: Path | None = None) -> ExtractedDocument:
    """按文件扩展名抽取附件正文。

    Args:
        file_path: 待抽取的本地文件路径。
        settings: 可选配置;未传入时读取全局配置。
        media_dir: 可选媒体输出目录。

    Returns:
        结构化抽取结果。

    Raises:
        AttachmentExtractionError: 当文件类型不支持、内容为空或解析失败时抛出。
    """
    active_settings = settings or get_settings()
    suffix = file_path.suffix.lower()
    try:
        if suffix == ".txt":
            text = _read_text_file(file_path)
            return _build_result(text, "text", active_settings, [])
        if suffix == ".md":
            text = _read_text_file(file_path)
            return _build_result(text, "markdown", active_settings, [])
        if suffix == ".docx":
            text, media = convert_docx_to_markdown(file_path, media_dir=media_dir)
            return _build_result(text, "markdown", active_settings, media)
        if suffix == ".pptx":
            text, media = convert_pptx_to_markdown(file_path, media_dir=media_dir)
            return _build_result(text, "markdown", active_settings, media)
        if suffix in {".doc", ".ppt"}:
            raise AttachmentExtractionError(f"不支持 {suffix} 旧版 Office 格式,请转换为 docx 或 pptx 后上传。")
        raise AttachmentExtractionError(f"不支持的附件类型: {suffix or 'unknown'}")
    except OfficeConversionError as exc:
        raise AttachmentExtractionError(str(exc)) from exc


def _read_text_file(file_path: Path) -> str:
    """读取文本文件,UTF-8 失败时使用容错解码。"""
    data = file_path.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="ignore")


def _build_result(text: str, format_name: Literal["markdown", "text"], settings: Settings, media: list[dict[str, Any]]) -> ExtractedDocument:
    """归一化并按配置截断抽取文本。"""
    normalized = _normalize_text(text)
    if not normalized.strip():
        raise AttachmentExtractionError("附件抽取内容为空。")
    truncated = len(normalized) > settings.attachment_max_chars
    if truncated:
        normalized = normalized[: settings.attachment_max_chars]
    return ExtractedDocument(text=normalized, format=format_name, chars=len(normalized), truncated=truncated, media=media)


def _normalize_text(text: str) -> str:
    """执行轻量文本归一化。"""
    normalized = text.replace("\r\r\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
    normalized = "".join(char for char in normalized if char == "\n" or char == "\t" or ord(char) >= 32)
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()
