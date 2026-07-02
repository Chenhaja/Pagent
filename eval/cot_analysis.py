import json
from pathlib import Path
from typing import Any


def load_reasoning_records(path: str | Path) -> list[dict[str, Any]]:
    """读取 reasoning JSONL 记录。

    Args:
        path: reasoning JSON Lines 文件路径。

    Returns:
        解析后的记录列表;非法空行会被跳过。
    """
    records: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            records.append(payload)
    return records


def analyze_reasoning_records(
    records: list[dict[str, Any]],
    next_query_hint: str | None = None,
    budget_instruction: str | None = None,
    allowed_tools: list[str] | None = None,
    selected_tools: list[str] | None = None,
) -> dict[str, Any]:
    """分析推理记录中的 prompt 信号消费和 outcome 关联。

    Args:
        records: reasoning sink 记录列表。
        next_query_hint: 当步注入的下一步查询建议。
        budget_instruction: 当步注入的预算指令文本。
        allowed_tools: 当步允许的工具名。
        selected_tools: 当步实际选中的工具名。

    Returns:
        可 JSON 序列化的结构化分析报告。
    """
    report = {
        "total_records": len(records),
        "signal_hits": {
            "next_query_hint": {"count": 0, "rate": 0.0},
            "budget_instruction": {"count": 0, "rate": 0.0},
            "unselected_tool": {"count": 0, "rate": 0.0},
        },
        "by_source": {},
        "converged_reasons": {},
    }
    total = len(records) or 1
    unselected_tools = sorted(set(allowed_tools or []) - set(selected_tools or []))
    for record in records:
        source = str(record.get("source") or "unknown")
        text = str(record.get("text") or "")
        outcome = record.get("outcome") if isinstance(record.get("outcome"), dict) else {}
        source_stats = report["by_source"].setdefault(source, {"count": 0, "sufficient_true": 0, "steps_used_total": 0})
        source_stats["count"] += 1
        if outcome.get("sufficient") is True:
            source_stats["sufficient_true"] += 1
        source_stats["steps_used_total"] += int(outcome.get("steps_used") or 0)
        converged_reason = outcome.get("converged_reason")
        if converged_reason:
            report["converged_reasons"][str(converged_reason)] = report["converged_reasons"].get(str(converged_reason), 0) + 1
        if next_query_hint and next_query_hint in text:
            report["signal_hits"]["next_query_hint"]["count"] += 1
        if budget_instruction and budget_instruction in text:
            report["signal_hits"]["budget_instruction"]["count"] += 1
        if any(tool in text for tool in unselected_tools):
            report["signal_hits"]["unselected_tool"]["count"] += 1
    for stats in report["signal_hits"].values():
        stats["rate"] = stats["count"] / total
    return report
