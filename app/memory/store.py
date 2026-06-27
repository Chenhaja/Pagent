from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

MemoryType = Literal["session", "case", "user_profile", "experience"]


class MemoryRecord(BaseModel):
    """本地记忆记录。

    Args:
        memory_id: 记忆记录唯一标识。
        memory_type: 记忆类型,如 session、case、user_profile、experience。
        content: 结构化记忆内容。
        provenance: 记忆来源和确认信息。

    Returns:
        带 provenance 的本地记忆记录。
    """

    memory_id: str
    memory_type: MemoryType
    content: dict[str, Any]
    provenance: dict[str, str] = Field(default_factory=dict)


class LocalMemoryStore:
    """本地内存版 memory store。

    Returns:
        支持按类型读写的本地记忆存储实现。
    """

    def __init__(self) -> None:
        self.records: list[MemoryRecord] = []

    def write(self, memory_type: MemoryType, content: dict[str, Any], provenance: dict[str, str]) -> MemoryRecord | None:
        """写入一条本地记忆。

        Args:
            memory_type: 记忆类型。
            content: 结构化记忆内容。
            provenance: 记忆来源和确认信息。

        Returns:
            通过 gating 时返回已写入记录;否则返回 None。
        """
        if not self._can_write(provenance):
            return None
        record = MemoryRecord(
            memory_id=str(uuid4()),
            memory_type=memory_type,
            content=content,
            provenance=provenance,
        )
        self.records.append(record)
        return record

    def read(self, memory_type: MemoryType | None = None) -> list[MemoryRecord]:
        """读取本地记忆记录。

        Args:
            memory_type: 可选的记忆类型过滤条件。

        Returns:
            符合条件的记忆记录列表。
        """
        if memory_type is None:
            return list(self.records)
        return [record for record in self.records if record.memory_type == memory_type]

    def _can_write(self, provenance: dict[str, str]) -> bool:
        """判断记忆写入是否通过安全 gating。"""
        if provenance.get("source") != "model_output":
            return True
        return provenance.get("validated") == "true" and provenance.get("user_confirmed") == "true"
