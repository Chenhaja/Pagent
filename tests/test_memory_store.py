from app.memory.store import LocalMemoryStore, MemoryRecord


def test_local_memory_store_writes_and_reads_records_with_provenance() -> None:
    """本地 memory store 应读写会话、案件、用户画像和经验记忆并保留 provenance。"""
    store = LocalMemoryStore()

    record = store.write(
        memory_type="case",
        content={"summary": "传感器控制方案"},
        provenance={"source": "user_confirmed", "request_id": "req-1"},
    )

    assert isinstance(record, MemoryRecord)
    assert record.memory_type == "case"
    assert record.content == {"summary": "传感器控制方案"}
    assert record.provenance == {"source": "user_confirmed", "request_id": "req-1"}
    assert store.read("case") == [record]


def test_local_memory_store_filters_by_memory_type() -> None:
    """本地 memory store 应按记忆类型过滤记录。"""
    store = LocalMemoryStore()
    store.write(memory_type="session", content={"turn": 1}, provenance={"source": "runtime"})
    store.write(memory_type="user_profile", content={"role": "inventor"}, provenance={"source": "user_confirmed"})

    assert [record.memory_type for record in store.read("session")] == ["session"]
    assert [record.memory_type for record in store.read()] == ["session", "user_profile"]
