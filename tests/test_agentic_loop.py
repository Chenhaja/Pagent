import time

from app.orchestrator.react_loop import BoundedReActLoop, ReActBudget, ToolObservation
from app.orchestrator.react_policy import ReActDecision, ReActPolicyError, ReflectResult
from app.orchestrator.tool_registry import ToolCard


class ScriptedPolicy:
    """测试用 policy,按顺序返回决策。"""

    driver = "llm"

    def __init__(
        self,
        decisions: list[ReActDecision] | None = None,
        reflections: list[ReflectResult] | None = None,
        should_raise: bool = False,
        reflect_should_raise: bool = False,
    ) -> None:
        self.decisions = decisions or []
        self.reflections = reflections or []
        self.should_raise = should_raise
        self.reflect_should_raise = reflect_should_raise
        self.calls = []
        self.reflect_calls = []

    def decide(self, task_input: str, allowed_tools: list[ToolCard], scratchpad: list[dict], step_index: int) -> ReActDecision:
        """记录调用并返回下一条决策。"""
        self.calls.append({"task_input": task_input, "allowed_tools": allowed_tools, "scratchpad": scratchpad, "step_index": step_index})
        if self.should_raise:
            raise ReActPolicyError("policy_failed")
        index = len(self.calls) - 1
        if index >= len(self.decisions):
            return ReActDecision(thought="停止", action=None, tool_input={}, stop=True, sufficient=False)
        return self.decisions[index]

    def reflect(self, task_input: str, observation_digest: dict, scratchpad: list[dict], step_index: int) -> ReflectResult:
        """记录反思调用并返回下一条结果。"""
        self.reflect_calls.append(
            {"task_input": task_input, "observation_digest": observation_digest, "scratchpad": scratchpad, "step_index": step_index}
        )
        if self.reflect_should_raise:
            raise ReActPolicyError("reflect_failed")
        index = len(self.reflect_calls) - 1
        if index >= len(self.reflections):
            return ReflectResult(sufficient=False, reason="默认不足", next_query_hint=None)
        return self.reflections[index]


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
    tool = FakeTool([ToolObservation(tool_name="fake", evidence=[{"content": "证据", "provenance": {"source": "local://doc"}}], sufficient=True, top_score=0.8)])
    loop = make_loop(tool)

    outcome = loop.run("问题", allowed_tools=["fake"])

    assert len(tool.calls) == 1
    assert outcome.reason == "sufficient"
    assert outcome.steps_used == 1
    assert outcome.tool_calls == 1
    assert outcome.evidence == [{"content": "证据", "provenance": {"source": "local://doc"}}]
    assert [event["event"] for event in outcome.trace_events] == ["react_main_step", "react_reflect_step", "react_main_converged"]


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


def test_agentic_loop_policy_trace_does_not_expose_thought_or_query() -> None:
    """policy trace 只能记录 thought 长度,不能记录完整 thought 或 query。"""
    tool = FakeTool([ToolObservation(tool_name="fake", evidence=[], sufficient=False)])
    policy = ScriptedPolicy([
        ReActDecision(thought="敏感推理全文", action="fake", tool_input={"query": "敏感改写查询"}, stop=False, sufficient=False),
    ])
    loop = BoundedReActLoop(
        tools={"fake": tool},
        budget=ReActBudget(max_steps=1, token_budget=100, timeout_seconds=5),
        node_name="qa",
        policy=policy,
        tool_cards=[ToolCard("fake", "测试工具", {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]})],
    )

    outcome = loop.run("原始敏感问题", allowed_tools=["fake"])

    trace_text = str(outcome.trace_events)
    assert "敏感推理全文" not in trace_text
    assert "敏感改写查询" not in trace_text
    assert "原始敏感问题" not in trace_text
    policy_step = outcome.trace_events[0]["data"]
    assert policy_step["thought_len"] == len("敏感推理全文")
    assert "thought" not in policy_step


def test_agentic_loop_uses_policy_decision_and_rewritten_query() -> None:
    """LLM policy 路径应使用决策中的工具和改写 query。"""
    tool = FakeTool([
        ToolObservation(tool_name="fake", evidence=[], sufficient=False),
        ToolObservation(tool_name="fake", evidence=[{"content": "证据", "provenance": {"source": "local://doc"}}], sufficient=False),
    ])
    policy = ScriptedPolicy(
        decisions=[
            ReActDecision(thought="先查宽泛问题", action="fake", tool_input={"query": "宽泛问题"}, stop=False, sufficient=False),
            ReActDecision(thought="基于观察缩小问题", action="fake", tool_input={"query": "缩小后的问题"}, stop=False, sufficient=True),
        ],
        reflections=[
            ReflectResult(sufficient=False, reason="继续检索"),
            ReflectResult(sufficient=True, reason="证据充分"),
        ],
    )
    loop = BoundedReActLoop(
        tools={"fake": tool},
        budget=ReActBudget(max_steps=4, token_budget=100, timeout_seconds=5),
        node_name="qa",
        policy=policy,
        tool_cards=[ToolCard("fake", "测试工具", {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]})],
    )

    outcome = loop.run("原问题", allowed_tools=["fake"])

    assert tool.calls == [{"query": "宽泛问题"}, {"query": "缩小后的问题"}]
    assert outcome.reason == "sufficient"
    assert outcome.driver == "llm"
    assert outcome.fallback_used is False
    assert [event["event"] for event in outcome.trace_events[:6]] == [
        "react_policy_step",
        "react_main_step",
        "react_reflect_step",
        "react_policy_step",
        "react_main_step",
        "react_reflect_step",
    ]
    assert policy.calls[1]["scratchpad"][0]["observation_count"] == 0


def test_agentic_loop_reflect_controls_sufficient_after_observation() -> None:
    """tool.run 后的 reflect false 应阻止有 evidence 即停。"""
    tool = FakeTool([
        ToolObservation(tool_name="fake", evidence=[{"content": "低分证据", "provenance": {"source": "local://doc"}}], sufficient=True, top_score=0.4),
        ToolObservation(tool_name="fake", evidence=[{"content": "高分证据", "provenance": {"source": "local://doc2"}}], sufficient=False, top_score=0.9),
    ])
    policy = ScriptedPolicy(
        decisions=[
            ReActDecision(thought="第一步", action="fake", tool_input={"query": "q1"}, stop=False, sufficient=True),
            ReActDecision(thought="第二步", action="fake", tool_input={"query": "q2"}, stop=False, sufficient=False),
        ],
        reflections=[
            ReflectResult(sufficient=False, reason="证据不足", next_query_hint=None),
            ReflectResult(sufficient=True, reason="证据充分", next_query_hint=None),
        ],
    )
    loop = BoundedReActLoop(
        tools={"fake": tool},
        budget=ReActBudget(max_steps=3, token_budget=100, timeout_seconds=5),
        node_name="qa",
        policy=policy,
        tool_cards=[ToolCard("fake", "测试工具", {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]})],
    )

    outcome = loop.run("原问题", allowed_tools=["fake"])

    assert tool.calls == [{"query": "q1"}, {"query": "q2"}]
    assert outcome.reason == "sufficient"
    assert [event["event"] for event in outcome.trace_events[:6]] == [
        "react_policy_step",
        "react_main_step",
        "react_reflect_step",
        "react_policy_step",
        "react_main_step",
        "react_reflect_step",
    ]
    assert outcome.trace_events[2]["data"]["sufficient"] is False
    assert outcome.trace_events[5]["data"]["sufficient"] is True


def test_agentic_loop_threshold_fallback_when_llm_judge_disabled() -> None:
    """禁用 LLM judge 时应使用 top_score 阈值判断充分性。"""
    low_tool = FakeTool([ToolObservation(tool_name="fake", evidence=[{"content": "证据"}], sufficient=True, top_score=0.4)])
    low_loop = BoundedReActLoop(
        tools={"fake": low_tool},
        budget=ReActBudget(max_steps=1, token_budget=100, timeout_seconds=5),
        use_llm_judge=False,
        sufficient_score_threshold=0.5,
    )

    low = low_loop.run("问题", allowed_tools=["fake"])

    assert low.reason == "max_steps"
    assert low.trace_events[1]["data"]["driver"] == "heuristic"

    high_tool = FakeTool([ToolObservation(tool_name="fake", evidence=[{"content": "证据"}], sufficient=False, top_score=0.6)])
    high_loop = BoundedReActLoop(
        tools={"fake": high_tool},
        budget=ReActBudget(max_steps=1, token_budget=100, timeout_seconds=5),
        use_llm_judge=False,
        sufficient_score_threshold=0.5,
    )

    high = high_loop.run("问题", allowed_tools=["fake"])

    assert high.reason == "sufficient"


def test_agentic_loop_supports_policy_stop() -> None:
    """policy 主动停止时应以 policy_stop 收敛。"""
    tool = FakeTool([])
    policy = ScriptedPolicy([ReActDecision(thought="无需继续", action=None, tool_input={}, stop=True, sufficient=False)])
    loop = BoundedReActLoop(
        tools={"fake": tool},
        budget=ReActBudget(max_steps=2, token_budget=100, timeout_seconds=5),
        node_name="qa",
        policy=policy,
        tool_cards=[ToolCard("fake", "测试工具", {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]})],
    )

    outcome = loop.run("问题", allowed_tools=["fake"])

    assert tool.calls == []
    assert outcome.reason == "policy_stop"
    assert outcome.steps_used == 0
    assert outcome.trace_events[0]["event"] == "react_policy_step"


def test_agentic_loop_falls_back_when_policy_fails() -> None:
    """policy 失败时应当步降级 heuristic 并继续执行。"""
    tool = FakeTool([ToolObservation(tool_name="fake", evidence=[{"content": "证据", "provenance": {"source": "local://doc"}}], sufficient=True, top_score=0.8)])
    policy = ScriptedPolicy(should_raise=True)
    loop = BoundedReActLoop(
        tools={"fake": tool},
        budget=ReActBudget(max_steps=2, token_budget=100, timeout_seconds=5),
        node_name="qa",
        policy=policy,
        tool_cards=[ToolCard("fake", "测试工具", {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]})],
    )

    outcome = loop.run("原问题", allowed_tools=["fake"])

    assert tool.calls == [{"query": "原问题", "step_index": 0}]
    assert outcome.reason == "sufficient"
    assert outcome.driver == "heuristic"
    assert outcome.fallback_used is True
    assert outcome.trace_events[-1]["data"]["fallback_used"] is True


def test_agentic_loop_rejects_invalid_policy_action_and_schema() -> None:
    """非法 action 或 tool_input schema 不合规时应 fallback。"""
    for decision in [
        ReActDecision(thought="越权", action="missing", tool_input={"query": "x"}, stop=False, sufficient=False),
        ReActDecision(thought="缺字段", action="fake", tool_input={}, stop=False, sufficient=False),
    ]:
        tool = FakeTool([ToolObservation(tool_name="fake", evidence=[], sufficient=False)])
        policy = ScriptedPolicy([decision])
        loop = BoundedReActLoop(
            tools={"fake": tool},
            budget=ReActBudget(max_steps=1, token_budget=100, timeout_seconds=5),
            node_name="qa",
            policy=policy,
            tool_cards=[ToolCard("fake", "测试工具", {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]})],
        )

        outcome = loop.run("原问题", allowed_tools=["fake"])

        assert tool.calls == [{"query": "原问题", "step_index": 0}]
        assert outcome.fallback_used is True
        assert outcome.steps_used <= 1
