import json
import secrets
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.services.case_service import CaseService
from app.tools.draft_workspace import DraftWorkspaceTool
from app.tools.file_extract import AttachmentExtractionError, extract_document

ALLOWED_DOC_TYPES = {"invention_disclosure", "specification", "claims", "office_action", "prior_art", "other"}


class AttachmentServiceError(Exception):
    """附件服务可读错误。"""

    def __init__(self, code: str, message: str) -> None:
        """初始化附件服务错误。

        Args:
            code: 稳定错误码。
            message: 面向用户的错误说明。

        Returns:
            无返回值。
        """
        super().__init__(message)
        self.code = code
        self.message = message


class AttachmentService:
    """附件保存、解析与读取服务。

    Args:
        settings: 可选运行配置;未传入时读取全局配置。

    Returns:
        可被 API 和 dispatch 复用的附件服务实例。
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.storage_dir = Path(self.settings.attachment_storage_dir)

    def validate_count(self, count: int) -> None:
        """校验单次附件数量。

        Args:
            count: 本次请求附件数量。

        Returns:
            无返回值。

        Raises:
            AttachmentServiceError: 当数量超过配置上限时抛出。
        """
        if count > self.settings.attachment_max_count:
            raise AttachmentServiceError("attachment_count_exceeded", "附件数量超过上限。")

    def save_upload(self, filename: str, content_type: str | None, content: bytes, doc_type: str = "other", case_id: str | None = None) -> dict[str, Any]:
        """保存并解析上传附件。

        Args:
            filename: 用户上传文件名,仅作为元数据保留。
            content_type: 上传内容类型。
            content: 文件二进制内容。
            doc_type: 文档类型枚举。
            case_id: 已创建案件 ID,用于绑定附件归属。

        Returns:
            附件元数据字典。

        Raises:
            AttachmentServiceError: 当校验或抽取失败时抛出。
        """
        case = CaseService(settings=self.settings).get_case(case_id or "")
        if case is None:
            raise AttachmentServiceError("case_not_found", "请先创建案件并携带有效 case_id。")
        self._validate_doc_type(doc_type)
        suffix = Path(filename).suffix.lower()
        self._validate_suffix(suffix)
        if len(content) > self.settings.attachment_max_bytes:
            raise AttachmentServiceError("attachment_too_large", "附件大小超过上限。")

        attachment_id = secrets.token_urlsafe(16)
        attachment_dir = self._safe_attachment_dir(attachment_id)
        media_dir = attachment_dir / "media"
        attachment_dir.mkdir(parents=True, exist_ok=False)
        media_dir.mkdir(exist_ok=True)

        original_path = attachment_dir / f"original{suffix}"
        original_path.write_bytes(content)
        try:
            extracted = extract_document(original_path, settings=self.settings, media_dir=media_dir)
        except AttachmentExtractionError as exc:
            raise AttachmentServiceError("attachment_extract_failed", str(exc)) from exc

        extracted_name = "extracted.md" if extracted.format == "markdown" else "extracted.txt"
        (attachment_dir / extracted_name).write_text(extracted.text, encoding="utf-8")
        workspace_artifact_key = f"01_input/attachments/{attachment_id}/{extracted_name}"
        workspace = DraftWorkspaceTool(settings=self.settings, workspace_name=f"tmp_{case['workspace_id']}")
        observation = workspace.run({"action": "write", "artifact_key": workspace_artifact_key, "content": extracted.text})
        if observation.error:
            raise AttachmentServiceError("attachment_workspace_write_failed", "附件正文写入案件 workspace 失败。")
        metadata = {
            "attachment_id": attachment_id,
            "filename": filename,
            "content_type": content_type,
            "bytes": len(content),
            "chars": extracted.chars,
            "truncated": extracted.truncated,
            "doc_type": doc_type,
            "format": extracted.format,
            "media": extracted.media,
            "case_id": case["case_id"],
            "workspace_artifact_key": workspace_artifact_key,
        }
        (attachment_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return metadata

    def load_document(self, attachment_id: str, case_id: str | None = None) -> dict[str, Any]:
        """读取已上传附件并组织为 workflow document。

        Args:
            attachment_id: 附件 ID。
            case_id: 当前请求案件 ID,用于校验附件归属。

        Returns:
            包含正文与元数据的 workflow document。

        Raises:
            AttachmentServiceError: 当附件不存在、不可读取或不属于当前案件时抛出。
        """
        attachment_dir = self._safe_attachment_dir(attachment_id)
        metadata_path = attachment_dir / "metadata.json"
        if not metadata_path.exists():
            raise AttachmentServiceError("attachment_not_found", "附件不存在或已不可读取。")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("case_id") != case_id:
            raise AttachmentServiceError("attachment_not_found", "附件不存在或已不可读取。")
        extracted_name = "extracted.md" if metadata.get("format") == "markdown" else "extracted.txt"
        text_path = attachment_dir / extracted_name
        if not text_path.exists():
            raise AttachmentServiceError("attachment_not_found", "附件正文不存在或已不可读取。")
        return {
            "attachment_id": metadata["attachment_id"],
            "filename": metadata["filename"],
            "doc_type": metadata["doc_type"],
            "format": metadata["format"],
            "text": text_path.read_text(encoding="utf-8"),
            "media": metadata.get("media", []),
            "truncated": metadata["truncated"],
            "case_id": metadata["case_id"],
            "workspace_artifact_key": metadata.get("workspace_artifact_key"),
        }

    def _validate_doc_type(self, doc_type: str) -> None:
        """校验附件文档类型。"""
        if doc_type not in ALLOWED_DOC_TYPES:
            raise AttachmentServiceError("invalid_doc_type", "附件 doc_type 不受支持。")

    def _validate_suffix(self, suffix: str) -> None:
        """校验附件扩展名白名单。"""
        allowed = {item.lower() for item in self.settings.attachment_allowed_types}
        if suffix in {".doc", ".ppt"}:
            raise AttachmentServiceError("attachment_type_not_supported", "不支持旧版 Office 格式,请转换为 docx 或 pptx。")
        if suffix not in allowed:
            raise AttachmentServiceError("attachment_type_not_allowed", "附件类型不在允许列表中。")

    def _safe_attachment_dir(self, attachment_id: str) -> Path:
        """构造并校验附件目录位于存储根目录内。"""
        root = self.storage_dir.resolve()
        target = (root / attachment_id).resolve()
        if root != target and root not in target.parents:
            raise AttachmentServiceError("attachment_path_invalid", "附件路径非法。")
        return target
