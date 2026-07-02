import json

from eval.cot_analysis import analyze_reasoning_records, load_reasoning_records


def test_load_reasoning_records_handles_jsonl(tmp_path) -> None:
    """分析模块应能读取 reasoning JSONL。"""
    path = tmp_path / "reasoning.jsonl"
    path.write_text(json.dumps({"source": "thought", "text": "使用 hint A", "outcome": {"sufficient": True}}, ensure_ascii=False) + "\n", encoding="utf-8")

    records = load_reasoning_records(path)

    assert records == [{"source": "thought", "text": "使用 hint A", "outcome": {"sufficient": True}}]


def test_analyze_reasoning_records_detects_prompt_signal_usage() -> None:
    """分析模块应检测 hint、预算和未选工具引用。"""
    records = [
        {
            "source": "native_cot",
            "text": "我会参考 缩小后的问题，并注意 最后一个可用步骤，同时不选 websearch。",
            "outcome": {"sufficient": False, "steps_used": 1, "converged_reason": "max_steps"},
        },
        {
            "source": "reason",
            "text": "证据充分，可以停止。",
            "outcome": {"sufficient": True, "steps_used": 2, "converged_reason": "sufficient"},
        },
    ]

    report = analyze_reasoning_records(
        records,
        next_query_hint="缩小后的问题",
        budget_instruction="最后一个可用步骤",
        allowed_tools=["kb_retrieval", "websearch"],
        selected_tools=["kb_retrieval"],
    )

    assert report["total_records"] == 2
    assert report["signal_hits"]["next_query_hint"]["count"] == 1
    assert report["signal_hits"]["budget_instruction"]["count"] == 1
    assert report["signal_hits"]["unselected_tool"]["count"] == 1
    assert report["by_source"]["native_cot"]["count"] == 1
    assert report["by_source"]["reason"]["sufficient_true"] == 1
    assert report["converged_reasons"]["sufficient"] == 1


def test_analyze_reasoning_records_tolerates_missing_fields() -> None:
    """分析模块遇到空文本和缺失字段不应崩溃。"""
    report = analyze_reasoning_records([{"source": "unknown"}, {}])

    assert report["total_records"] == 2
    assert report["by_source"]["unknown"]["count"] == 2
    assert report["by_source"]["unknown"]["sufficient_true"] == 0
