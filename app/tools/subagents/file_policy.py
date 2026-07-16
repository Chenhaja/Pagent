from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import PurePosixPath


_DEFAULT_DENY_GLOBS = ["**/.env", ".env", "**/secrets/**", "secrets/**", "**/*.pem", "**/*.key"]


@dataclass(frozen=True)
class FileToolPolicy:
    """约束通用文件工具可访问的 artifact 路径。

    Args:
        readRoots: 允许读取的路径前缀。
        writeRoots: 允许写入的路径前缀。
        allowGlobs: 更细粒度的允许 glob 规则。
        denyGlobs: 拒绝 glob 规则,优先级高于允许规则。

    Returns:
        可用于 read/write 工具执行前校验的不可变策略对象。
    """

    readRoots: list[str] = field(default_factory=list)
    writeRoots: list[str] = field(default_factory=list)
    allowGlobs: list[str] = field(default_factory=list)
    denyGlobs: list[str] = field(default_factory=lambda: list(_DEFAULT_DENY_GLOBS))

    def check(self, operation: str, path: str) -> str | None:
        """校验指定操作是否允许访问路径。

        Args:
            operation: 操作类型,支持 read 或 write。
            path: 待访问 artifact 相对路径。

        Returns:
            允许时返回规范化路径,拒绝时返回 None。
        """
        normalized = self.normalize(path)
        if normalized is None:
            return None
        if self._matches_any(normalized, self.denyGlobs):
            return None
        roots = self.readRoots if operation == "read" else self.writeRoots if operation == "write" else []
        if not roots:
            return None
        if not self._under_any_root(normalized, roots):
            return None
        if self.allowGlobs and not self._matches_any(normalized, self.allowGlobs):
            return None
        return normalized

    def can_read(self, path: str) -> bool:
        """判断是否允许读取路径。"""
        return self.check("read", path) is not None

    def can_write(self, path: str) -> bool:
        """判断是否允许写入路径。"""
        return self.check("write", path) is not None

    def normalize(self, path: str) -> str | None:
        """规范化 artifact 路径,拒绝绝对路径和逃逸片段。"""
        raw = str(path or "").replace("\\", "/").strip()
        if not raw or raw.startswith("/") or "//" in raw:
            return None
        pure = PurePosixPath(raw)
        if any(part in {"", ".", ".."} for part in pure.parts):
            return None
        return pure.as_posix().strip("/")

    def _under_any_root(self, path: str, roots: list[str]) -> bool:
        """判断路径是否位于任一允许前缀下。"""
        for root in roots:
            normalized_root = self.normalize(root)
            if normalized_root is None:
                continue
            if path == normalized_root or path.startswith(f"{normalized_root.rstrip('/')}/"):
                return True
        return False

    def _matches_any(self, path: str, patterns: list[str]) -> bool:
        """判断路径是否命中任一 glob 规则。"""
        return any(fnmatch(path, pattern) for pattern in patterns)
