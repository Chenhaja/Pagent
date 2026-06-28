import sqlite3

from app.core.config import Settings
from app.memory.session_store import NullSessionStore, SqliteSessionStore, build_session_store
from app.memory.summarizer import SessionSummarizer
from app.tools.llm import LLMResponse


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


def test_build_context_returns_window_history(tmp_path) -> None:
    """build_context 应只返回最近窗口内的原文历史。"""
    store = SqliteSessionStore(str(tmp_path / "memory.sqlite3"), history_window=2, token_budget=1500)
    store.append_turn("s1", "user", "第一问")
    store.append_turn("s1", "assistant", "第一答")
    store.append_turn("s1", "user", "第二问")

    context = store.build_context("s1")

    assert context == {
        "history": [
            {"role": "assistant", "content": "第一答"},
            {"role": "user", "content": "第二问"},
        ],
        "session_summary": None,
    }


def test_build_context_prepends_summary_header(tmp_path) -> None:
    """已有摘要时 build_context 应把摘要作为 assistant 合成消息放在头部。"""
    store = SqliteSessionStore(str(tmp_path / "memory.sqlite3"), history_window=2, token_budget=1500)
    store.append_turn("s1", "user", "第一问")
    store.append_turn("s1", "assistant", "第一答")
    store.append_turn("s1", "user", "第二问")
    store.upsert_summary("s1", "用户讨论了机械臂夹爪。", covered_turn_index=1)

    context = store.build_context("s1")

    assert context["session_summary"] == "用户讨论了机械臂夹爪。"
    assert context["history"] == [
        {"role": "assistant", "content": "[早期对话摘要] 用户讨论了机械臂夹爪。"},
        {"role": "assistant", "content": "第一答"},
        {"role": "user", "content": "第二问"},
    ]


def test_session_summarizer_returns_valid_summary() -> None:
    """SessionSummarizer 应解析合法 JSON 摘要响应。"""
    llm = RecordingLLMClient({"summary": "用户讨论夹爪方案。", "confidence": 0.9, "uncertain": False})
    summarizer = SessionSummarizer(llm_client=llm, model="summary-model")

    result = summarizer.summarize(
        session_id="s1",
        previous_summary=None,
        turns=[{"role": "user", "content": "夹爪能夹瓶子"}],
    )

    assert result.success is True
    assert result.summary == "用户讨论夹爪方案。"
    assert llm.calls[0]["model"] == "summary-model"
    assert "<data>" in llm.calls[0]["messages"][1].content


def test_session_summarizer_fails_safely_on_invalid_response() -> None:
    """摘要响应非法时 summarizer 应返回失败结果而不是抛出。"""
    summarizer = SessionSummarizer(llm_client=RecordingLLMClient({"summary": ""}))

    result = summarizer.summarize(
        session_id="s1",
        previous_summary=None,
        turns=[{"role": "user", "content": "夹爪能夹瓶子"}],
    )

    assert result.success is False
    assert result.summary is None
    assert result.reason == "invalid_summary_response"


def test_summarize_if_needed_compacts_old_turns(tmp_path) -> None:
    """超过窗口时应压缩窗口外 turn 并保留最近窗口原文。"""
    llm = RecordingLLMClient({"summary": "早期讨论了夹爪结构。", "confidence": 0.8, "uncertain": False})
    summarizer = SessionSummarizer(llm_client=llm)
    store = SqliteSessionStore(
        str(tmp_path / "memory.sqlite3"),
        history_window=2,
        token_budget=1500,
        summarizer=summarizer,
    )
    store.append_turn("s1", "user", "第一问")
    store.append_turn("s1", "assistant", "第一答")
    store.append_turn("s1", "user", "第二问")

    result = store.summarize_if_needed("s1")

    assert result.success is True
    assert store.load_summary("s1") == "早期讨论了夹爪结构。"
    context = store.build_context("s1")
    assert len(context["history"]) == 3
    assert context["history"][0]["content"] == "[早期对话摘要] 早期讨论了夹爪结构。"


def test_summarize_if_needed_keeps_window_when_llm_fails(tmp_path) -> None:
    """摘要失败时应保留窗口原文并返回失败结果。"""
    summarizer = SessionSummarizer(llm_client=RecordingLLMClient({}, should_raise=True))
    store = SqliteSessionStore(
        str(tmp_path / "memory.sqlite3"),
        history_window=2,
        token_budget=1500,
        summarizer=summarizer,
    )
    store.append_turn("s1", "user", "第一问")
    store.append_turn("s1", "assistant", "第一答")
    store.append_turn("s1", "user", "第二问")

    result = store.summarize_if_needed("s1")

    assert result.success is False
    assert store.load_summary("s1") is None
    assert store.build_context("s1")["history"] == [
        {"role": "assistant", "content": "第一答"},
        {"role": "user", "content": "第二问"},
    ]


class RecordingLLMClient:
    """测试用 LLM client,记录调用并返回固定响应。"""

    def __init__(self, content: dict, should_raise: bool = False) -> None:
        self.content = content
        self.should_raise = should_raise
        self.calls = []

    def generate(self, **kwargs):
        """记录调用并返回固定 LLM 响应。"""
        self.calls.append(kwargs)
        if self.should_raise:
            raise RuntimeError("llm failed")
        return LLMResponse(content=self.content)
