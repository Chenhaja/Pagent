import re
from pathlib import Path

from app.core.config import Settings, get_settings
from app.orchestrator.react_loop import ToolObservation


_SAFE_KEY_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


class DraftWorkspaceTool:
    """专利文书草稿 artifact 工作区工具。"""

    def __init__(self, settings: Settings | None = None) -> None:
        """初始化草稿工作区工具。

        Args:
            settings: 应用配置,未传入时读取全局配置。

        Returns:
            无返回值。
        """
        self.settings = settings or get_settings()
        self.workspace_dir = Path(self.settings.draft_workspace_dir).resolve()

    def run(self, tool_input: dict) -> ToolObservation:
        """执行 artifact 读写。

        Args:
            tool_input: 包含 action、artifact_key 和可选 content 的输入。

        Returns:
            工具 observation,仅在读取时返回正文。
        """
        action = str(tool_input.get("action") or "").strip()
        artifact_key = str(tool_input.get("artifact_key") or "").strip()
        if not self._is_safe_key(artifact_key):
            return ToolObservation(tool_name="draft_workspace", error="invalid_artifact_key")
        if action == "write":
            return self._write(artifact_key, str(tool_input.get("content") or ""))
        if action == "read":
            return self._read(artifact_key)
        return ToolObservation(tool_name="draft_workspace", error="invalid_action")

    def _write(self, artifact_key: str, content: str) -> ToolObservation:
        """写入 artifact 并返回元数据。"""
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        max_chars = self.settings.draft_artifact_max_chars
        truncated = len(content) > max_chars
        safe_content = content[:max_chars]
        path = self._path_for(artifact_key)
        path.write_text(safe_content, encoding="utf-8")
        return ToolObservation(
            tool_name="draft_workspace",
            evidence=[{"artifact_key": artifact_key, "chars": len(safe_content), "truncated": truncated}],
            sufficient=True,
        )

    def _read(self, artifact_key: str) -> ToolObservation:
        """读取 artifact 正文。"""
        path = self._path_for(artifact_key)
        if not path.exists():
            return ToolObservation(tool_name="draft_workspace", error="artifact_not_found")
        content = path.read_text(encoding="utf-8")
        return ToolObservation(
            tool_name="draft_workspace",
            evidence=[{"artifact_key": artifact_key, "content": content, "chars": len(content)}],
            sufficient=bool(content),
        )

    def _path_for(self, artifact_key: str) -> Path:
        """生成位于 workspace 内的 artifact 路径。"""
        path = (self.workspace_dir / f"{artifact_key}.md").resolve()
        if self.workspace_dir not in path.parents and path != self.workspace_dir:
            raise ValueError("artifact path escaped workspace")
        return path

    def _is_safe_key(self, artifact_key: str) -> bool:
        """校验 artifact key 仅包含安全字符。"""
        return bool(artifact_key and _SAFE_KEY_RE.fullmatch(artifact_key))
