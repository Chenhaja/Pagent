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


def test_local_memory_store_blocks_unconfirmed_model_output() -> None:
    """未经校验与用户确认的模型输出不能写入长期记忆。"""
    store = LocalMemoryStore()

    record = store.write(
        memory_type="case",
        content={"summary": "模型推断的技术方案"},
        provenance={"source": "model_output", "validated": "false", "user_confirmed": "false"},
    )

    assert record is None
    assert store.read("case") == []


def test_local_memory_store_allows_confirmed_model_output() -> None:
    """已校验且用户确认的模型输出可以写入长期记忆。"""
    store = LocalMemoryStore()

    record = store.write(
        memory_type="case",
        content={"summary": "确认后的技术方案"},
        provenance={"source": "model_output", "validated": "true", "user_confirmed": "true"},
    )

    assert record is not None
    assert store.read("case") == [record]


def test_local_memory_store_filters_by_memory_type() -> None:
    """本地 memory store 应按记忆类型过滤记录。"""
    store = LocalMemoryStore()
    store.write(memory_type="session", content={"turn": 1}, provenance={"source": "runtime"})
    store.write(memory_type="user_profile", content={"role": "inventor"}, provenance={"source": "user_confirmed"})

    assert [record.memory_type for record in store.read("session")] == ["session"]
    assert [record.memory_type for record in store.read()] == ["session", "user_profile"]
