import re
from pathlib import Path, PurePosixPath

from app.core.config import Settings, get_settings
from app.orchestrator.react_loop import ToolObservation


_SAFE_KEY_RE = re.compile(r"^[a-zA-Z0-9_./-]+$")
_WORKSPACE_DIRS = ["01_input", "02_research", "03_outline", "04_content", "05_final"]
_DEFAULT_PROJECT_ID = "default"


class DraftWorkspaceTool:
    """专利文书草稿 artifact 工作区工具。"""

    _memory_stores: dict[str, dict[str, str]] = {}

    def __init__(self, settings: Settings | None = None, project_id: str | None = None) -> None:
        """初始化草稿工作区工具。

        Args:
            settings: 应用配置,未传入时读取全局配置。
            project_id: 项目 ID,用于隔离同一进程内不同专利项目的 artifact。

        Returns:
            无返回值。
        """
        self.settings = settings or get_settings()
        self.project_id = self._safe_project_id(project_id or _DEFAULT_PROJECT_ID)
        self.storage_mode = "disk" if self.settings.draft_workspace_dir else "memory"
        self.workspace_dir = self._build_workspace_dir()
        self._store = self._memory_stores.setdefault(self.project_id, {})

    def run(self, tool_input: dict) -> ToolObservation:
        """执行 artifact 工作区操作。

        Args:
            tool_input: 包含 action 与对应 artifact key 的输入。

        Returns:
            工具 observation,正文只在读取时返回。
        """
        action = str(tool_input.get("action") or "").strip()
        if action == "write":
            artifact_key = str(tool_input.get("artifact_key") or "").strip()
            if not self._is_safe_key(artifact_key):
                return ToolObservation(tool_name="draft_workspace", error="invalid_artifact_key")
            return self._write(artifact_key, str(tool_input.get("content") or ""))
        if action == "read":
            artifact_key = str(tool_input.get("artifact_key") or "").strip()
            if not self._is_safe_key(artifact_key):
                return ToolObservation(tool_name="draft_workspace", error="invalid_artifact_key")
            return self._read(artifact_key)
        if action == "list":
            prefix = str(tool_input.get("prefix") or "").strip()
            if prefix and not self._is_safe_prefix(prefix):
                return ToolObservation(tool_name="draft_workspace", error="invalid_artifact_key")
            return self._list(prefix)
        if action == "merge":
            source_keys = tool_input.get("source_artifact_keys") or []
            output_key = str(tool_input.get("output_artifact_key") or "").strip()
            if not isinstance(source_keys, list) or not source_keys:
                return ToolObservation(tool_name="draft_workspace", error="invalid_input")
            if not self._is_safe_key(output_key) or any(not self._is_safe_key(str(key)) for key in source_keys):
                return ToolObservation(tool_name="draft_workspace", error="invalid_artifact_key")
            return self._merge([str(key) for key in source_keys], output_key)
        return ToolObservation(tool_name="draft_workspace", error="invalid_action")

    def _write(self, artifact_key: str, content: str) -> ToolObservation:
        """写入 artifact 并返回元数据。"""
        normalized_key = self._normalize_key(artifact_key)
        max_chars = self.settings.draft_artifact_max_chars
        truncated = len(content) > max_chars
        safe_content = content[:max_chars]
        if self.storage_mode == "memory":
            self._store[normalized_key] = safe_content
        else:
            path = self._path_for(normalized_key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(safe_content, encoding="utf-8")
        return ToolObservation(
            tool_name="draft_workspace",
            evidence=[
                {
                    "artifact_key": normalized_key,
                    "chars": len(safe_content),
                    "truncated": truncated,
                    "storage_mode": self.storage_mode,
                }
            ],
            sufficient=True,
        )

    def _read(self, artifact_key: str) -> ToolObservation:
        """读取 artifact 正文。"""
        normalized_key = self._normalize_key(artifact_key)
        if self.storage_mode == "memory":
            if normalized_key not in self._store:
                return ToolObservation(tool_name="draft_workspace", error="artifact_not_found")
            content = self._store[normalized_key]
        else:
            path = self._path_for(normalized_key)
            if not path.exists():
                return ToolObservation(tool_name="draft_workspace", error="artifact_not_found")
            content = path.read_text(encoding="utf-8")
        return ToolObservation(
            tool_name="draft_workspace",
            evidence=[{"artifact_key": normalized_key, "content": content, "chars": len(content)}],
            sufficient=bool(content),
        )

    def _list(self, prefix: str = "") -> ToolObservation:
        """枚举工作区 artifact。"""
        normalized_prefix = self._normalize_prefix(prefix)
        if self.storage_mode == "memory":
            artifacts = sorted(key for key in self._store if not normalized_prefix or key.startswith(normalized_prefix))
        else:
            self._ensure_project_dirs()
            artifacts = sorted(
                path.relative_to(self.workspace_dir).as_posix()
                for path in self.workspace_dir.rglob("*")
                if path.is_file()
                and (not normalized_prefix or path.relative_to(self.workspace_dir).as_posix().startswith(normalized_prefix))
            )
        return ToolObservation(
            tool_name="draft_workspace",
            evidence=[{"prefix": normalized_prefix, "artifacts": artifacts, "directories": list(_WORKSPACE_DIRS), "count": len(artifacts)}],
            sufficient=True,
        )

    def _merge(self, source_keys: list[str], output_key: str) -> ToolObservation:
        """按顺序合并多个 artifact。"""
        contents = []
        for source_key in source_keys:
            observation = self._read(source_key)
            if observation.error or not observation.evidence:
                return ToolObservation(tool_name="draft_workspace", error=observation.error or "artifact_not_found")
            contents.append(str(observation.evidence[0].get("content") or ""))
        merged_content = "\n\n".join(contents)
        written = self._write(output_key, merged_content)
        if written.error:
            return written
        evidence = dict(written.evidence[0]) if written.evidence else {}
        evidence["source_artifact_keys"] = [self._normalize_key(key) for key in source_keys]
        return ToolObservation(tool_name="draft_workspace", evidence=[evidence], sufficient=True)

    def _build_workspace_dir(self) -> Path:
        """生成磁盘项目工作区目录。"""
        base_dir = Path(self.settings.draft_workspace_dir).resolve() if self.settings.draft_workspace_dir else Path()
        return (base_dir / f"temp_{self.project_id}").resolve() if self.settings.draft_workspace_dir else base_dir

    def _ensure_project_dirs(self) -> None:
        """确保磁盘项目工作区目录结构存在。"""
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        for directory in _WORKSPACE_DIRS:
            (self.workspace_dir / directory).mkdir(parents=True, exist_ok=True)

    def _path_for(self, artifact_key: str) -> Path:
        """生成位于 workspace 内的 artifact 路径。"""
        self._ensure_project_dirs()
        path = (self.workspace_dir / artifact_key).resolve()
        if self.workspace_dir not in path.parents and path != self.workspace_dir:
            raise ValueError("artifact path escaped workspace")
        return path

    def _normalize_key(self, artifact_key: str) -> str:
        """规范化 artifact key,兼容旧 simple key。"""
        key = PurePosixPath(artifact_key.replace("\\", "/")).as_posix().strip("/")
        if "/" not in key and "." not in PurePosixPath(key).name:
            key = f"{key}.md"
        return key

    def _normalize_prefix(self, prefix: str) -> str:
        """规范化 list prefix。"""
        return PurePosixPath(prefix.replace("\\", "/")).as_posix().strip("/") if prefix else ""

    def _is_safe_key(self, artifact_key: str) -> bool:
        """校验 artifact key 是安全相对路径。"""
        key = artifact_key.replace("\\", "/").strip()
        if not key or key.startswith("/") or "//" in key or not _SAFE_KEY_RE.fullmatch(key):
            return False
        path = PurePosixPath(key)
        return all(part not in {"", ".", ".."} for part in path.parts)

    def _is_safe_prefix(self, prefix: str) -> bool:
        """校验 list prefix 是安全相对路径前缀。"""
        return self._is_safe_key(prefix) or bool(prefix in _WORKSPACE_DIRS)

    def _safe_project_id(self, project_id: str) -> str:
        """校验并规范化项目 ID。"""
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", project_id.strip())
        return safe or _DEFAULT_PROJECT_ID
