import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from app.core.security import redact_sensitive_text


@dataclass(frozen=True)
class ReasoningRecord:
    """推理轨迹记录。

    Args:
        request_id: 当前请求 ID,未绑定时为 None。
        node_name: 当前节点名称,未绑定时为 None。
        task_type: 推理任务类型,如 react_policy 或 react_reflect。
        step_index: ReAct 当前步序号。
        source: 推理信号来源,如 native_cot、thought 或 reason。
        text: 推理正文,写入 sink 前会脱敏并截断。
        outcome: 当前步骤结果快照,不得包含正文。

    Returns:
        可写入 reasoning sink 的结构化记录。
    """

    request_id: str | None
    node_name: str | None
    task_type: str
    step_index: int
    source: str
    text: str
    outcome: dict[str, Any]


class ReasoningTraceSink(Protocol):
    """写入推理轨迹记录的协议。"""

    def write(self, record: ReasoningRecord) -> None:
        """写入一条推理轨迹记录。

        Args:
            record: 推理轨迹记录。

        Returns:
            无返回值。
        """
        ...


class NoopReasoningSink:
    """不写入任何推理记录的默认 sink。"""

    def write(self, record: ReasoningRecord) -> None:
        """忽略推理轨迹记录。

        Args:
            record: 推理轨迹记录。

        Returns:
            无返回值。
        """
        return None


class JsonlReasoningSink:
    """将推理轨迹记录写入独立 JSON Lines 文件。"""

    def __init__(self, path: str | Path, max_chars: int) -> None:
        """初始化 JSONL 推理轨迹 sink。

        Args:
            path: JSON Lines 文件路径。
            max_chars: 单条推理正文最大保留字符数。
        """
        self.path = Path(path)
        self.max_chars = max_chars

    def write(self, record: ReasoningRecord) -> None:
        """写入脱敏、截断后的推理轨迹记录。

        Args:
            record: 推理轨迹记录。

        Returns:
            无返回值。
        """
        try:
            payload = asdict(record)
            payload["text"] = redact_sensitive_text(record.text, max_length=self.max_chars)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            return
