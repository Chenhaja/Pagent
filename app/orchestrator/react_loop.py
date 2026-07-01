import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.orchestrator.react_policy import HeuristicReActPolicy, ReActDecision, ReActPolicy, ReActPolicyError, ReflectResult, ToolCard


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
    driver: str = "heuristic"
    fallback_used: bool = False


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

    def __init__(
        self,
        tools: dict[str, ReActTool],
        budget: ReActBudget,
        node_name: str = "agentic",
        policy: ReActPolicy | None = None,
        heuristic_policy: ReActPolicy | None = None,
        tool_cards: list[ToolCard] | None = None,
        use_llm_judge: bool = True,
        sufficient_score_threshold: float = 0.5,
        observation_digest_chars: int = 600,
    ) -> None:
        """初始化主循环。

        Args:
            tools: 已由代码注册的工具白名单映射。
            budget: 步数、token 和超时预算。
            node_name: 调用方节点名称,写入 trace 便于定位。
            policy: 可选 LLM 或脚本化决策策略。
            heuristic_policy: policy 失败时使用的确定性降级策略。
            tool_cards: 可供 policy 决策的工具卡片。
            use_llm_judge: 是否使用 policy 的 reflect 判断。
            sufficient_score_threshold: 确定性阈值兜底的 top_score 门槛。
            observation_digest_chars: observation 摘要字符上限。
        """
        self.tools = tools
        self.budget = budget
        self.node_name = node_name
        self.policy = policy or HeuristicReActPolicy(sufficient_score_threshold=sufficient_score_threshold)
        self.heuristic_policy = heuristic_policy or HeuristicReActPolicy(sufficient_score_threshold=sufficient_score_threshold)
        self.tool_cards = tool_cards or [ToolCard(name=name, description="", input_schema={}) for name in tools]
        self.use_llm_judge = use_llm_judge
        self.sufficient_score_threshold = sufficient_score_threshold
        self.observation_digest_chars = observation_digest_chars
        self.emit_policy_trace = policy is not None

    def run(self, task_input: str, allowed_tools: list[str]) -> ReActOutcome:
        """执行 bounded ReAct 工具循环。

        Args:
            task_input: 用户任务或检索 query。
            allowed_tools: 当前场景允许使用的工具名列表。

        Returns:
            主循环 outcome,包含 evidence、收敛原因和 trace。
        """
        if self.budget.max_steps <= 0:
            return self._converge([], "max_steps", 0, 0, [], driver=self._policy_driver(), fallback_used=False)
        if self.budget.token_budget <= 0:
            return self._converge([], "token_budget", 0, 0, [], driver=self._policy_driver(), fallback_used=False)
        if self.budget.timeout_seconds <= 0:
            return self._converge([], "timeout", 0, 0, [], driver=self._policy_driver(), fallback_used=False)
        if not allowed_tools:
            return self._converge([], "tool_unavailable", 0, 0, [], driver=self._policy_driver(), fallback_used=False)

        started_at = time.monotonic()
        deadline = started_at + self.budget.timeout_seconds
        evidence: list[dict[str, Any]] = []
        trace_events: list[dict[str, Any]] = []
        scratchpad: list[dict[str, Any]] = []
        external_tools_used: list[str] = []
        reason = "max_steps"
        steps_used = 0
        tool_calls = 0
        driver = self._policy_driver()
        fallback_used = False

        for step_index in range(self.budget.max_steps):
            if time.monotonic() >= deadline:
                reason = "timeout"
                break

            cards = self._allowed_tool_cards(allowed_tools)
            if not cards:
                reason = "tool_unavailable"
                break
            decision, step_driver, step_fallback = self._decide(task_input, cards, scratchpad, step_index)
            driver = step_driver
            fallback_used = fallback_used or step_fallback
            if self.emit_policy_trace:
                trace_events.append(self._build_policy_trace(step_index, decision, step_driver))

            if decision.stop or decision.action is None:
                reason = "policy_stop"
                break

            tool_name = decision.action
            tool = self.tools.get(tool_name)
            if tool is None or tool_name not in allowed_tools:
                decision, step_driver, _ = self._fallback_decision(task_input, cards, scratchpad, step_index)
                driver = step_driver
                fallback_used = True
                tool_name = decision.action
                tool = self.tools.get(tool_name) if tool_name else None
            elif not self._valid_tool_input(tool_name, decision.tool_input, cards):
                decision, step_driver, _ = self._fallback_decision(task_input, cards, scratchpad, step_index)
                driver = step_driver
                fallback_used = True
                tool_name = decision.action
                tool = self.tools.get(tool_name) if tool_name else None

            if tool is None or tool_name is None:
                reason = "tool_unavailable"
                break

            try:
                observation = tool.run(decision.tool_input)
            except Exception:
                steps_used += 1
                tool_calls += 1
                reason = "tool_unavailable"
                observation = ToolObservation(tool_name=tool_name, error="tool_unavailable")
                observation_digest = self._build_observation_digest(observation)
                trace_events.append(self._build_step_trace(step_index, tool_name, task_input, 0, 0.0, False))
                scratchpad.append(self._build_scratchpad_item(step_index, decision, observation, observation_digest))
                break

            steps_used += 1
            tool_calls += 1
            evidence = self._accumulate_evidence(evidence, observation.evidence)
            if observation.external and tool_name not in external_tools_used:
                external_tools_used.append(tool_name)
            observation_digest = self._build_observation_digest(observation)
            reflection, reflect_driver, reflect_fallback = self._reflect(task_input, observation_digest, scratchpad, step_index, not step_fallback)
            fallback_used = fallback_used or reflect_fallback
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
            trace_events.append(self._build_reflect_trace(step_index, reflection, reflect_driver))
            scratchpad.append(self._build_scratchpad_item(step_index, decision, observation, observation_digest))
            if observation.error:
                reason = "tool_unavailable"
                break
            if reflection.sufficient:
                reason = "sufficient"
                break
            if self._estimate_evidence_tokens(evidence) >= self.budget.token_budget:
                reason = "token_budget"
                break
            if time.monotonic() >= deadline:
                reason = "timeout"
                break
            reason = "max_steps"

        return self._converge(evidence, reason, steps_used, tool_calls, trace_events, external_tools_used, driver, fallback_used)

    def _decide(
        self,
        task_input: str,
        cards: list[ToolCard],
        scratchpad: list[dict[str, Any]],
        step_index: int,
    ) -> tuple[ReActDecision, str, bool]:
        """调用主 policy,失败时返回 heuristic 决策。"""
        try:
            decision = self.policy.decide(task_input, cards, scratchpad, step_index)
            return decision, self._policy_driver(), False
        except Exception:
            return self._fallback_decision(task_input, cards, scratchpad, step_index)

    def _fallback_decision(
        self,
        task_input: str,
        cards: list[ToolCard],
        scratchpad: list[dict[str, Any]],
        step_index: int,
    ) -> tuple[ReActDecision, str, bool]:
        """生成 heuristic 降级决策。"""
        try:
            return self.heuristic_policy.decide(task_input, cards, scratchpad, step_index), "heuristic", True
        except ReActPolicyError:
            return ReActDecision(thought="降级策略失败", action=None, tool_input={}, stop=True, sufficient=False), "heuristic", True

    def _reflect(
        self,
        task_input: str,
        observation_digest: dict[str, Any],
        scratchpad: list[dict[str, Any]],
        step_index: int,
        can_use_policy: bool = True,
    ) -> tuple[ReflectResult, str, bool]:
        """执行 observation 反思,失败时用阈值策略降级。"""
        if not self.use_llm_judge or not can_use_policy:
            return self.heuristic_policy.reflect(task_input, observation_digest, scratchpad, step_index), "heuristic", False
        try:
            return self.policy.reflect(task_input, observation_digest, scratchpad, step_index), self._policy_driver(), False
        except Exception:
            return self.heuristic_policy.reflect(task_input, observation_digest, scratchpad, step_index), "fallback", True

    def _converge(
        self,
        evidence: list[dict[str, Any]],
        reason: str,
        steps_used: int,
        tool_calls: int,
        trace_events: list[dict[str, Any]],
        external_tools_used: list[str] | None = None,
        driver: str = "heuristic",
        fallback_used: bool = False,
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
                    "driver": driver,
                    "fallback_used": fallback_used,
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
            driver=driver,
            fallback_used=fallback_used,
        )

    def _build_policy_trace(self, step_index: int, decision: ReActDecision, driver: str) -> dict[str, Any]:
        """构造 policy 决策 trace,不记录 thought 原文。"""
        return {
            "event": "react_policy_step",
            "data": {
                "node_name": self.node_name,
                "step_index": step_index,
                "tool_name": decision.action,
                "thought_len": len(decision.thought),
                "stop": decision.stop,
                "sufficient": decision.sufficient,
                "driver": driver,
            },
        }

    def _build_reflect_trace(self, step_index: int, reflection: ReflectResult, driver: str) -> dict[str, Any]:
        """构造 reflect trace,不记录 reason 原文。"""
        return {
            "event": "react_reflect_step",
            "data": {
                "node_name": self.node_name,
                "step_index": step_index,
                "sufficient": reflection.sufficient,
                "reason_len": len(reflection.reason),
                "next_query_hint_present": bool(reflection.next_query_hint),
                "driver": driver,
            },
        }

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
                "external": external,
            },
        }

    def _build_observation_digest(self, observation: ToolObservation) -> dict[str, Any]:
        """构造本步 observation 的截断摘要。"""
        items = []
        used_chars = 0
        for item in observation.evidence:
            if used_chars >= self.observation_digest_chars:
                break
            content = str(item.get("content") or "")
            remaining = max(0, self.observation_digest_chars - used_chars)
            clipped_content = content[:remaining]
            used_chars += len(clipped_content)
            provenance = item.get("provenance") or {}
            items.append(
                {
                    "content": clipped_content,
                    "provenance": {
                        "source": provenance.get("source"),
                        "document_id": provenance.get("document_id"),
                        "locator": provenance.get("locator"),
                    },
                    "score": item.get("score", item.get("similarity", item.get("confidence"))),
                }
            )
        return {
            "evidence_count": len(observation.evidence),
            "top_score": observation.top_score,
            "error": observation.error,
            "external": observation.external,
            "items": items,
        }

    def _build_scratchpad_item(
        self,
        step_index: int,
        decision: ReActDecision,
        observation: ToolObservation,
        observation_digest: dict[str, Any],
    ) -> dict[str, Any]:
        """构造历史步骤摘要,避免保存完整正文。"""
        return {
            "step_index": step_index,
            "tool_name": decision.action,
            "thought_len": len(decision.thought),
            "observation_count": len(observation.evidence),
            "top_score": observation.top_score,
            "error": observation.error,
            "external": observation.external,
            "observation_digest": observation_digest,
        }

    def _allowed_tool_cards(self, allowed_tools: list[str]) -> list[ToolCard]:
        """筛选当前场景允许的工具卡片。"""
        allowed = set(allowed_tools)
        cards = [card for card in self.tool_cards if card.name in allowed and card.name in self.tools]
        if cards:
            return cards
        return [ToolCard(name=name, description="", input_schema={}) for name in allowed_tools if name in self.tools]

    def _valid_tool_input(self, tool_name: str, tool_input: dict[str, Any], cards: list[ToolCard]) -> bool:
        """按工具 schema 做最小输入校验。"""
        if not isinstance(tool_input, dict):
            return False
        card = next((item for item in cards if item.name == tool_name), None)
        if card is None:
            return False
        schema = card.input_schema or {}
        required = schema.get("required") or []
        for field_name in required:
            if field_name not in tool_input:
                return False
        properties = schema.get("properties") or {}
        for field_name, field_schema in properties.items():
            if field_name not in tool_input:
                continue
            if not self._matches_schema_type(tool_input[field_name], field_schema.get("type")):
                return False
        return True

    def _matches_schema_type(self, value: Any, expected_type: Any) -> bool:
        """校验 JSON schema 基础类型。"""
        if expected_type is None:
            return True
        expected_types = expected_type if isinstance(expected_type, list) else [expected_type]
        for item in expected_types:
            if item == "null" and value is None:
                return True
            if item == "string" and isinstance(value, str):
                return True
            if item == "integer" and isinstance(value, int) and not isinstance(value, bool):
                return True
            if item == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
                return True
            if item == "boolean" and isinstance(value, bool):
                return True
            if item == "object" and isinstance(value, dict):
                return True
            if item == "array" and isinstance(value, list):
                return True
        return False

    def _policy_driver(self) -> str:
        """读取当前主 policy driver 名称。"""
        return str(getattr(self.policy, "driver", "heuristic"))

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
