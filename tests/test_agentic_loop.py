import time

from app.orchestrator.react_loop import BoundedReActLoop, ReActBudget, ToolObservation


class FakeTool:
    """测试用工具,按顺序返回 observation。"""

    def __init__(self, observations: list[ToolObservation], should_raise: bool = False) -> None:
        self.observations = observations
        self.should_raise = should_raise
        self.calls = []

    def run(self, tool_input: dict) -> ToolObservation:
        """记录输入并返回下一条 observation。"""
        self.calls.append(tool_input)
        if self.should_raise:
            raise RuntimeError("tool failed")
        index = len(self.calls) - 1
        if index >= len(self.observations):
            return ToolObservation(tool_name="fake", evidence=[], sufficient=False)
        return self.observations[index]


def make_loop(tool: FakeTool, budget: ReActBudget | None = None) -> BoundedReActLoop:
    """构造只注册 fake 工具的测试 loop。"""
    return BoundedReActLoop(
        tools={"fake": tool},
        budget=budget or ReActBudget(max_steps=2, token_budget=100, timeout_seconds=5),
        node_name="qa",
    )


def test_agentic_loop_converges_when_first_observation_is_sufficient() -> None:
    """首轮 observation 充分时应立即收敛。"""
    tool = FakeTool([ToolObservation(tool_name="fake", evidence=[{"content": "证据", "provenance": {"source": "local://doc"}}], sufficient=True)])
    loop = make_loop(tool)

    outcome = loop.run("问题", allowed_tools=["fake"])

    assert len(tool.calls) == 1
    assert outcome.reason == "sufficient"
    assert outcome.steps_used == 1
    assert outcome.tool_calls == 1
    assert outcome.evidence == [{"content": "证据", "provenance": {"source": "local://doc"}}]
    assert [event["event"] for event in outcome.trace_events] == ["react_main_step", "react_main_converged"]


def test_agentic_loop_continues_until_max_steps_when_insufficient() -> None:
    """证据不足时应继续到 max_steps 后收敛。"""
    tool = FakeTool([
        ToolObservation(tool_name="fake", evidence=[], sufficient=False),
        ToolObservation(tool_name="fake", evidence=[], sufficient=False),
    ])
    loop = make_loop(tool, ReActBudget(max_steps=2, token_budget=100, timeout_seconds=5))

    outcome = loop.run("问题", allowed_tools=["fake"])

    assert len(tool.calls) == 2
    assert outcome.reason == "max_steps"
    assert outcome.steps_used == 2
    assert len([event for event in outcome.trace_events if event["event"] == "react_main_step"]) == 2


def test_agentic_loop_skips_tools_when_budget_blocks() -> None:
    """预算 guard 命中时不应调用工具。"""
    for budget, reason in [
        (ReActBudget(max_steps=0, token_budget=100, timeout_seconds=5), "max_steps"),
        (ReActBudget(max_steps=1, token_budget=0, timeout_seconds=5), "token_budget"),
        (ReActBudget(max_steps=1, token_budget=100, timeout_seconds=0), "timeout"),
    ]:
        tool = FakeTool([ToolObservation(tool_name="fake", evidence=[], sufficient=True)])
        loop = make_loop(tool, budget)

        outcome = loop.run("问题", allowed_tools=["fake"])

        assert tool.calls == []
        assert outcome.reason == reason
        assert outcome.steps_used == 0
        assert outcome.trace_events[-1]["event"] == "react_main_converged"


def test_agentic_loop_stops_when_token_budget_is_exhausted() -> None:
    """evidence 预算耗尽时应停止后续工具调用。"""
    tool = FakeTool([ToolObservation(tool_name="fake", evidence=[{"content": "x" * 40, "provenance": {"source": "local://doc"}}], sufficient=False)])
    loop = make_loop(tool, ReActBudget(max_steps=2, token_budget=5, timeout_seconds=5))

    outcome = loop.run("问题", allowed_tools=["fake"])

    assert len(tool.calls) == 1
    assert outcome.reason == "token_budget"


def test_agentic_loop_handles_unavailable_and_failing_tools() -> None:
    """未知工具或工具异常应安全收敛。"""
    missing = make_loop(FakeTool([])).run("问题", allowed_tools=["missing"])
    assert missing.reason == "tool_unavailable"

    failing_tool = FakeTool([], should_raise=True)
    failing = make_loop(failing_tool).run("问题", allowed_tools=["fake"])
    assert failing.reason == "tool_unavailable"
    assert len(failing_tool.calls) == 1


def test_agentic_loop_timeout_stops_gracefully(monkeypatch) -> None:
    """超时时应优雅收敛。"""
    times = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(times))
    tool = FakeTool([ToolObservation(tool_name="fake", evidence=[], sufficient=False)])
    loop = make_loop(tool, ReActBudget(max_steps=2, token_budget=100, timeout_seconds=1))

    outcome = loop.run("问题", allowed_tools=["fake"])

    assert outcome.reason == "timeout"
    assert len(tool.calls) == 1


def test_agentic_loop_trace_does_not_expose_full_input_or_content() -> None:
    """trace 只能记录摘要,不能包含完整 query 或 evidence 正文。"""
    tool = FakeTool([ToolObservation(tool_name="fake", evidence=[{"content": "敏感证据全文", "provenance": {"source": "local://doc"}}], sufficient=True)])
    loop = make_loop(tool)

    outcome = loop.run("完整敏感问题", allowed_tools=["fake"])

    trace_text = str(outcome.trace_events)
    assert "完整敏感问题" not in trace_text
    assert "敏感证据全文" not in trace_text
    step = outcome.trace_events[0]["data"]
    assert step["node_name"] == "qa"
    assert step["tool_name"] == "fake"
    assert step["input_len"] == len("完整敏感问题")
    assert step["observation_count"] == 1
    assert step["external"] is False
