import time
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ReActBudget:
    """ReAct 主循环预算。"""

    max_steps: int
    token_budget: int
    timeout_seconds: int


@dataclass
class ToolObservation:
    """工具单步执行结果。"""

    tool_name: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    sufficient: bool = False
    error: str | None = None
    external: bool = False
    top_score: float = 0.0


@dataclass
class ReActOutcome:
    """ReAct 主循环收敛结果。"""

    evidence: list[dict[str, Any]]
    reason: str
    steps_used: int
    tool_calls: int
    trace_events: list[dict[str, Any]]
    external_tools_used: list[str] = field(default_factory=list)


class ReActTool(Protocol):
    """可被 ReAct 主循环调用的工具协议。"""

    def run(self, tool_input: dict[str, Any]) -> ToolObservation:
        """执行工具调用。

        Args:
            tool_input: 工具输入,由主循环按结构化字段传入。

        Returns:
            工具 observation。
        """
        ...


class BoundedReActLoop:
    """受限 ReAct 主循环。"""

    def __init__(self, tools: dict[str, ReActTool], budget: ReActBudget, node_name: str = "agentic") -> None:
        """初始化主循环。

        Args:
            tools: 已由代码注册的工具白名单映射。
            budget: 步数、token 和超时预算。
            node_name: 调用方节点名称,写入 trace 便于定位。
        """
        self.tools = tools
        self.budget = budget
        self.node_name = node_name

    def run(self, task_input: str, allowed_tools: list[str]) -> ReActOutcome:
        """执行 bounded ReAct 工具循环。

        Args:
            task_input: 用户任务或检索 query。
            allowed_tools: 当前场景允许使用的工具名列表。

        Returns:
            主循环 outcome,包含 evidence、收敛原因和 trace。
        """
        if self.budget.max_steps <= 0:
            return self._converge([], "max_steps", 0, 0, [])
        if self.budget.token_budget <= 0:
            return self._converge([], "token_budget", 0, 0, [])
        if self.budget.timeout_seconds <= 0:
            return self._converge([], "timeout", 0, 0, [])
        if not allowed_tools:
            return self._converge([], "tool_unavailable", 0, 0, [])

        started_at = time.monotonic()
        deadline = started_at + self.budget.timeout_seconds
        evidence: list[dict[str, Any]] = []
        trace_events: list[dict[str, Any]] = []
        external_tools_used: list[str] = []
        reason = "max_steps"
        steps_used = 0
        tool_calls = 0

        for step_index in range(self.budget.max_steps):
            if time.monotonic() >= deadline:
                reason = "timeout"
                break
            tool_name = allowed_tools[min(step_index, len(allowed_tools) - 1)]
            tool = self.tools.get(tool_name)
            if tool is None:
                reason = "tool_unavailable"
                break
            try:
                observation = tool.run({"query": task_input, "step_index": step_index})
            except Exception:
                steps_used += 1
                tool_calls += 1
                reason = "tool_unavailable"
                trace_events.append(self._build_step_trace(step_index, tool_name, task_input, 0, 0.0, False))
                break

            steps_used += 1
            tool_calls += 1
            evidence = self._accumulate_evidence(evidence, observation.evidence)
            if observation.external and tool_name not in external_tools_used:
                external_tools_used.append(tool_name)
            trace_events.append(
                self._build_step_trace(
                    step_index,
                    tool_name,
                    task_input,
                    len(observation.evidence),
                    observation.top_score,
                    observation.external,
                )
            )
            if observation.error:
                reason = "tool_unavailable"
                break
            if observation.sufficient:
                reason = "sufficient"
                break
            if self._estimate_evidence_tokens(evidence) >= self.budget.token_budget:
                reason = "token_budget"
                break
            if time.monotonic() >= deadline:
                reason = "timeout"
                break
            reason = "max_steps"

        return self._converge(evidence, reason, steps_used, tool_calls, trace_events, external_tools_used)

    def _converge(
        self,
        evidence: list[dict[str, Any]],
        reason: str,
        steps_used: int,
        tool_calls: int,
        trace_events: list[dict[str, Any]],
        external_tools_used: list[str] | None = None,
    ) -> ReActOutcome:
        """构造收敛结果并追加收敛 trace。"""
        external_tools = external_tools_used or []
        trace_events.append(
            {
                "event": "react_main_converged",
                "data": {
                    "node_name": self.node_name,
                    "reason": reason,
                    "steps_used": steps_used,
                    "tool_calls": tool_calls,
                    "total_evidence": len(evidence),
                    "external_tools_used": external_tools,
                },
            }
        )
        return ReActOutcome(
            evidence=evidence,
            reason=reason,
            steps_used=steps_used,
            tool_calls=tool_calls,
            trace_events=trace_events,
            external_tools_used=external_tools,
        )

    def _build_step_trace(
        self,
        step_index: int,
        tool_name: str,
        task_input: str,
        observation_count: int,
        top_score: float,
        external: bool,
    ) -> dict[str, Any]:
        """构造单步 trace,只记录摘要字段。"""
        return {
            "event": "react_main_step",
            "data": {
                "node_name": self.node_name,
                "step_index": step_index,
                "tool_name": tool_name,
                "input_len": len(task_input),
                "observation_count": observation_count,
                "top_score": top_score,
                "decision": "continue_or_converge",
                "external": external,
            },
        }

    def _accumulate_evidence(self, existing: list[dict[str, Any]], new_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """累积 evidence,按来源 key 去重并保留较高分版本。"""
        merged: dict[tuple[Any, ...], dict[str, Any]] = {}
        for item in [*existing, *new_items]:
            key = self._evidence_key(item)
            current = merged.get(key)
            if current is None or self._evidence_score(item) > self._evidence_score(current):
                merged[key] = item
        return sorted(merged.values(), key=self._evidence_score, reverse=True)

    def _evidence_key(self, item: dict[str, Any]) -> tuple[Any, ...]:
        """构造 evidence 去重 key。"""
        provenance = item.get("provenance") or {}
        if provenance.get("document_id"):
            return ("document_id", provenance["document_id"])
        if provenance.get("source_url"):
            return ("source_url", provenance["source_url"])
        return ("fallback", provenance.get("source"), provenance.get("locator"), str(item.get("content", ""))[:128])

    def _evidence_score(self, item: dict[str, Any]) -> float:
        """读取 evidence 分数。"""
        value = item.get("similarity") or item.get("score") or item.get("confidence") or 0.0
        return float(value)

    def _estimate_evidence_tokens(self, evidence: list[dict[str, Any]]) -> int:
        """用字符长度确定性估算 evidence token 数。"""
        total = 0
        for item in evidence:
            content = str(item.get("content") or "")
            if content:
                total += max(1, len(content) // 4)
        return total
