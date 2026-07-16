import json
import re
import uuid
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings

_CASE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


class CaseService:
    """管理案件级 workspace 生命周期和元数据。"""

    def __init__(self, settings: Settings | None = None) -> None:
        """初始化案件服务。

        Args:
            settings: 应用配置,未传入时读取全局配置。

        Returns:
            无返回值。
        """
        self.settings = settings or get_settings()
        self.root_dir = Path(self.settings.draft_workspace_dir or ".draft_workspace")
        self.cases_dir = self.root_dir / "cases"

    def create_case(self) -> dict[str, Any]:
        """创建案件并绑定独立 workspace。

        Returns:
            包含 case_id、workspace_id 和相对 workspace_path 的案件元数据。
        """
        case_id = uuid.uuid4().hex
        workspace_id = uuid.uuid4().hex
        workspace_name = f"tmp_{workspace_id}"
        metadata = {
            "case_id": case_id,
            "workspace_id": workspace_id,
            "workspace_path": f".draft_workspace/{workspace_name}",
        }
        self.cases_dir.mkdir(parents=True, exist_ok=True)
        (self.root_dir / workspace_name).mkdir(parents=True, exist_ok=True)
        self._metadata_path(case_id).write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return metadata

    def get_case(self, case_id: str) -> dict[str, Any] | None:
        """读取案件元数据。

        Args:
            case_id: 已创建的案件 ID。

        Returns:
            存在时返回案件元数据,否则返回 None。
        """
        if not self._is_safe_case_id(case_id):
            return None
        path = self._metadata_path(case_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return data

    def get_workspace(self, case_id: str) -> dict[str, str] | None:
        """读取案件 workspace 标识信息。

        Args:
            case_id: 已创建的案件 ID。

        Returns:
            包含 workspace_id、workspace_name 和 workspace_path 的字典;案件不存在时返回 None。
        """
        metadata = self.get_case(case_id)
        if metadata is None:
            return None
        workspace_id = str(metadata.get("workspace_id") or "")
        return {
            "workspace_id": workspace_id,
            "workspace_name": f"tmp_{workspace_id}",
            "workspace_path": str(metadata.get("workspace_path") or ""),
        }

    def _metadata_path(self, case_id: str) -> Path:
        """返回案件元数据文件路径。"""
        return self.cases_dir / f"{case_id}.json"

    def _is_safe_case_id(self, case_id: str) -> bool:
        """校验案件 ID 是否可安全映射到元数据文件名。"""
        return bool(case_id and _CASE_ID_RE.fullmatch(case_id))
