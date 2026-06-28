import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

from app.core.config import Settings
from app.core.security import redact_sensitive_text

SessionRole = Literal["user", "assistant"]


class SessionMemoryStore(Protocol):
    """会话记忆存储协议。

    Args:
        session_id: 会话标识。
        max_turns: 最多读取的 turn 数。
        role: 会话 turn 角色,仅允许 user 或 assistant。
        content: turn 原文内容。
        summary: 会话滚动摘要。
        covered_turn_index: 摘要覆盖到的最大 turn index。

    Returns:
        按会话读取或写入后的结果。
    """

    def load_history(self, session_id: str, max_turns: int) -> list[dict[str, str]]:
        """读取最近会话历史。

        Args:
            session_id: 会话标识。
            max_turns: 最多返回的 turn 数。

        Returns:
            按时间升序排列的历史 turn 列表。
        """
        ...

    def append_turn(self, session_id: str, role: SessionRole, content: str) -> None:
        """追加一条会话 turn。

        Args:
            session_id: 会话标识。
            role: turn 角色。
            content: turn 内容。

        Returns:
            无返回值。
        """
        ...

    def load_summary(self, session_id: str) -> str | None:
        """读取会话摘要。

        Args:
            session_id: 会话标识。

        Returns:
            摘要文本;不存在时返回 None。
        """
        ...

    def upsert_summary(self, session_id: str, summary: str, covered_turn_index: int) -> None:
        """写入或更新会话摘要。

        Args:
            session_id: 会话标识。
            summary: 摘要文本。
            covered_turn_index: 摘要覆盖到的最大 turn index。

        Returns:
            无返回值。
        """
        ...

    def build_context(self, session_id: str) -> dict[str, Any]:
        """构造 query_rewrite 可消费的会话上下文。

        Args:
            session_id: 会话标识。

        Returns:
            包含 history 与 session_summary 的上下文字典。
        """
        ...


class NullSessionStore:
    """会话记忆空实现,用于配置关闭或存储不可用时降级。

    Returns:
        不持久化任何内容的会话存储。
    """

    def load_history(self, session_id: str, max_turns: int) -> list[dict[str, str]]:
        """返回空会话历史。"""
        return []

    def append_turn(self, session_id: str, role: SessionRole, content: str) -> None:
        """忽略会话 turn 写入。"""
        return None

    def load_summary(self, session_id: str) -> str | None:
        """返回空摘要。"""
        return None

    def upsert_summary(self, session_id: str, summary: str, covered_turn_index: int) -> None:
        """忽略摘要写入。"""
        return None

    def build_context(self, session_id: str) -> dict[str, Any]:
        """返回空会话上下文。"""
        return {"history": [], "session_summary": None}


class SqliteSessionStore:
    """基于 SQLite 的会话记忆存储。

    Args:
        db_path: SQLite 数据库文件路径。
        history_window: 最近原文 turn 窗口大小。
        token_budget: 摘要触发字符预算。
        redaction_enabled: 是否在入库前脱敏。

    Returns:
        可跨请求持久化会话 turn 和摘要的存储实例。
    """

    def __init__(
        self,
        db_path: str,
        history_window: int,
        token_budget: int,
        redaction_enabled: bool = True,
    ) -> None:
        self.db_path = db_path
        self.history_window = history_window
        self.token_budget = token_budget
        self.redaction_enabled = redaction_enabled
        self._initialize_schema()

    def load_history(self, session_id: str, max_turns: int) -> list[dict[str, str]]:
        """读取最近会话历史。

        Args:
            session_id: 会话标识。
            max_turns: 最多返回的 turn 数。

        Returns:
            按 turn_index 升序排列的历史列表。
        """
        if max_turns <= 0:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT role, content
                FROM (
                    SELECT role, content, turn_index
                    FROM turns
                    WHERE session_id = ?
                    ORDER BY turn_index DESC
                    LIMIT ?
                )
                ORDER BY turn_index ASC
                """,
                (session_id, max_turns),
            ).fetchall()
        return [{"role": row[0], "content": row[1]} for row in rows]

    def append_turn(self, session_id: str, role: SessionRole, content: str) -> None:
        """追加一条会话 turn。

        Args:
            session_id: 会话标识。
            role: turn 角色。
            content: turn 内容。

        Returns:
            无返回值。

        Raises:
            ValueError: role 不是 user 或 assistant 时抛出。
        """
        if role not in {"user", "assistant"}:
            raise ValueError("role must be user or assistant")
        now = _utc_now()
        stored_content = redact_sensitive_text(content) if self.redaction_enabled else content
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions(session_id, created_at, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (session_id, now, now),
            )
            next_index = conn.execute(
                "SELECT COALESCE(MAX(turn_index), 0) + 1 FROM turns WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
            conn.execute(
                """
                INSERT INTO turns(session_id, turn_index, role, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, next_index, role, stored_content, now),
            )

    def load_summary(self, session_id: str) -> str | None:
        """读取会话摘要。

        Args:
            session_id: 会话标识。

        Returns:
            摘要文本;不存在时返回 None。
        """
        with self._connect() as conn:
            row = conn.execute("SELECT summary FROM summaries WHERE session_id = ?", (session_id,)).fetchone()
        return row[0] if row else None

    def upsert_summary(self, session_id: str, summary: str, covered_turn_index: int) -> None:
        """写入或更新会话摘要。

        Args:
            session_id: 会话标识。
            summary: 摘要文本。
            covered_turn_index: 摘要覆盖到的最大 turn index。

        Returns:
            无返回值。
        """
        now = _utc_now()
        stored_summary = redact_sensitive_text(summary) if self.redaction_enabled else summary
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions(session_id, created_at, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (session_id, now, now),
            )
            conn.execute(
                """
                INSERT INTO summaries(session_id, summary, covered_turn_index, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    summary = excluded.summary,
                    covered_turn_index = excluded.covered_turn_index,
                    updated_at = excluded.updated_at
                """,
                (session_id, stored_summary, covered_turn_index, now),
            )

    def build_context(self, session_id: str) -> dict[str, Any]:
        """构造会话上下文。

        Args:
            session_id: 会话标识。

        Returns:
            包含 history 与 session_summary 的上下文字典。
        """
        return {"history": self.load_history(session_id, self.history_window), "session_summary": self.load_summary(session_id)}

    def _initialize_schema(self) -> None:
        """初始化 SQLite 表结构。"""
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    turn_index INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_turns_session_turn_index
                    ON turns(session_id, turn_index);
                CREATE TABLE IF NOT EXISTS summaries (
                    session_id TEXT PRIMARY KEY,
                    summary TEXT NOT NULL,
                    covered_turn_index INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        """创建 SQLite 连接。"""
        return sqlite3.connect(self.db_path)


def build_session_store(settings: Settings) -> SessionMemoryStore:
    """按配置构造会话记忆存储。

    Args:
        settings: 应用配置。

    Returns:
        SQLite 会话存储;配置关闭或数据库不可用时返回空实现。
    """
    if not settings.memory_enabled:
        return NullSessionStore()
    db_path = Path(settings.memory_db_path)
    if db_path.parent and not db_path.parent.exists():
        return NullSessionStore()
    try:
        return SqliteSessionStore(
            settings.memory_db_path,
            history_window=settings.memory_history_window,
            token_budget=settings.memory_token_budget,
            redaction_enabled=settings.redaction_enabled,
        )
    except sqlite3.Error:
        return NullSessionStore()


def _utc_now() -> str:
    """返回 UTC ISO 时间字符串。"""
    return datetime.now(timezone.utc).isoformat()
