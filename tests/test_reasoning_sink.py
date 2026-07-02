import json

from app.core.reasoning_sink import JsonlReasoningSink, NoopReasoningSink, ReasoningRecord


def test_noop_reasoning_sink_does_not_write_file(tmp_path) -> None:
    """Noop sink 不应产生文件或异常。"""
    path = tmp_path / "reasoning.jsonl"
    sink = NoopReasoningSink()

    sink.write(
        ReasoningRecord(
            request_id="req-1",
            node_name="qa",
            task_type="react_policy",
            step_index=0,
            source="thought",
            text="敏感推理",
            outcome={"sufficient": False},
        )
    )

    assert not path.exists()


def test_jsonl_reasoning_sink_writes_redacted_and_truncated_record(tmp_path) -> None:
    """JSONL sink 应写入脱敏、截断后的推理记录。"""
    path = tmp_path / "reasoning.jsonl"
    sink = JsonlReasoningSink(path=path, max_chars=30)

    sink.write(
        ReasoningRecord(
            request_id="req-1",
            node_name="qa",
            task_type="react_policy",
            step_index=1,
            source="native_cot",
            text="Bearer secret-token password=pass123 " + "推理" * 40,
            outcome={"sufficient": True, "top_score": 0.8},
        )
    )

    payload = json.loads(path.read_text(encoding="utf-8").strip())
    assert payload["request_id"] == "req-1"
    assert payload["node_name"] == "qa"
    assert payload["task_type"] == "react_policy"
    assert payload["step_index"] == 1
    assert payload["source"] == "native_cot"
    assert payload["outcome"] == {"sufficient": True, "top_score": 0.8}
    assert "secret-token" not in payload["text"]
    assert "pass123" not in payload["text"]
    assert "[REDACTED]" in payload["text"]
    assert payload["text"].endswith("...[TRUNCATED]")


def test_jsonl_reasoning_sink_swallows_write_errors(tmp_path) -> None:
    """JSONL sink 写入失败时不应影响主流程。"""
    sink = JsonlReasoningSink(path=tmp_path, max_chars=20)

    sink.write(
        ReasoningRecord(
            request_id=None,
            node_name=None,
            task_type="react_reflect",
            step_index=0,
            source="reason",
            text="推理正文",
            outcome={},
        )
    )
