import sqlite3

from app.core.config import Settings
from app.memory.session_store import NullSessionStore, SqliteSessionStore, build_session_store


def test_sqlite_store_initializes_tables(tmp_path) -> None:
    """SQLite store 初始化后应自动建表。"""
    db_path = tmp_path / "memory.sqlite3"

    SqliteSessionStore(str(db_path), history_window=6, token_budget=1500)

    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"sessions", "turns", "summaries"}.issubset(tables)


def test_append_and_load_history_in_turn_order(tmp_path) -> None:
    """append_turn 后 load_history 应按 turn_index 升序返回最近历史。"""
    store = SqliteSessionStore(str(tmp_path / "memory.sqlite3"), history_window=6, token_budget=1500)

    store.append_turn("s1", "user", "第一问")
    store.append_turn("s1", "assistant", "第一答")
    store.append_turn("s1", "user", "第二问")

    assert store.load_history("s1", max_turns=2) == [
        {"role": "assistant", "content": "第一答"},
        {"role": "user", "content": "第二问"},
    ]


def test_sqlite_store_persists_across_instances(tmp_path) -> None:
    """新建 store 实例应能读取旧实例写入的会话历史。"""
    db_path = tmp_path / "memory.sqlite3"
    first_store = SqliteSessionStore(str(db_path), history_window=6, token_budget=1500)
    first_store.append_turn("s1", "user", "跨请求问题")

    second_store = SqliteSessionStore(str(db_path), history_window=6, token_budget=1500)

    assert second_store.load_history("s1", max_turns=6) == [{"role": "user", "content": "跨请求问题"}]


def test_summary_crud_updates_summary(tmp_path) -> None:
    """upsert_summary 应能新增并更新会话摘要。"""
    store = SqliteSessionStore(str(tmp_path / "memory.sqlite3"), history_window=6, token_budget=1500)

    store.upsert_summary("s1", "旧摘要", covered_turn_index=1)
    assert store.load_summary("s1") == "旧摘要"
    store.upsert_summary("s1", "新摘要", covered_turn_index=3)

    assert store.load_summary("s1") == "新摘要"


def test_build_session_store_returns_null_when_disabled(tmp_path) -> None:
    """memory disabled 时工厂应返回空实现。"""
    settings = Settings(memory_enabled=False, memory_db_path=str(tmp_path / "memory.sqlite3"))

    store = build_session_store(settings)

    assert isinstance(store, NullSessionStore)
    assert store.load_history("s1", max_turns=6) == []


def test_build_session_store_falls_back_when_db_unavailable(tmp_path) -> None:
    """DB 路径不可用时工厂应降级为空实现而不是抛出。"""
    invalid_db_path = tmp_path / "missing" / "memory.sqlite3"
    settings = Settings(memory_enabled=True, memory_db_path=str(invalid_db_path))

    store = build_session_store(settings)

    assert isinstance(store, NullSessionStore)


def test_append_turn_redacts_sensitive_content(tmp_path) -> None:
    """会话 turn 入库前应脱敏明显 API Key。"""
    store = SqliteSessionStore(str(tmp_path / "memory.sqlite3"), history_window=6, token_budget=1500)

    store.append_turn("s1", "user", "密钥是 sk-secret123")

    history = store.load_history("s1", max_turns=6)
    assert "sk-secret123" not in history[0]["content"]
    assert "[REDACTED]" in history[0]["content"]
