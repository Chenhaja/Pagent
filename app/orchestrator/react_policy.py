from dataclasses import dataclass, field
from typing import Any, Protocol

from app.prompts.react_policy import REACT_DECISION_SCHEMA, REACT_REFLECT_SCHEMA, build_react_policy_messages, build_react_reflect_messages
from app.tools.llm import LLMClient


@dataclass
class ReActDecision:
    """ReAct 单步策略决策。

    Args:
        thought: 决策短摘要,仅用于内部 trace 摘要。
        action: 选中的工具名;None 表示停止。
        tool_input: 传给工具的结构化输入。
        stop: 是否停止主循环。。

    Returns:
        可被主循环校验和执行的结构化决策。
    """

    thought: str
    action: str | None
    tool_input: dict[str, Any] = field(default_factory=dict)
    stop: bool = False


@dataclass
class ReflectResult:
    """ReAct 观察后反思结果。

    Args:
        sufficient: 当前 observation 是否足以支撑任务。
        reason: 判断依据短摘要,仅用于 trace 摘要。
        next_query_hint: 证据不足时的下一步 query 建议。

    Returns:
        可被主循环消费的结构化反思结果。
    """

    sufficient: bool
    reason: str
    next_query_hint: str | None = None


@dataclass
class ToolCard:
    """供 policy 决策使用的工具卡片。

    Args:
        name: 工具名称。
        description: 工具用途描述。
        input_schema: 工具输入 JSON schema。

    Returns:
        可传给 LLM policy 的工具元数据。
    """

    name: str
    description: str
    input_schema: dict[str, Any]


class ReActPolicyError(Exception):
    """ReAct policy 决策失败,主循环可捕获后降级。"""


class ReActPolicy(Protocol):
    """ReAct 策略协议。"""

    def decide(
        self,
        task_input: str,
        allowed_tools: list[ToolCard],
        scratchpad: list[dict[str, Any]],
        step_index: int,
        max_steps: int,
    ) -> ReActDecision:
        """生成下一步 ReAct 决策。

        Args:
            task_input: 原始任务或问题。
            allowed_tools: 当前白名单工具卡片。
            scratchpad: 历史步骤摘要。
            step_index: 当前步数。
            max_steps: 当前主循环最大步数。

        Returns:
            结构化 ReAct 决策。
        """
        ...

    def reflect(
        self,
        task_input: str,
        observation_digest: dict[str, Any],
        scratchpad: list[dict[str, Any]],
        step_index: int,
    ) -> ReflectResult:
        """生成 observation 反思结果。

        Args:
            task_input: 当前任务或问题。
            observation_digest: 本步 observation 摘要。
            scratchpad: 历史步骤摘要。
            step_index: 当前步数。

        Returns:
            结构化反思结果。
        """
        ...


class HeuristicReActPolicy:
    """确定性降级策略,保留旧版按顺序选工具行为。"""

    driver = "heuristic"

    def __init__(self, sufficient_score_threshold: float = 0.5) -> None:
        """初始化确定性 ReAct policy。

        Args:
            sufficient_score_threshold: 阈值兜底的 top_score 门槛。
        """
        self.sufficient_score_threshold = sufficient_score_threshold

    def decide(
        self,
        task_input: str,
        allowed_tools: list[ToolCard],
        scratchpad: list[dict[str, Any]],
        step_index: int,
        max_steps: int,
    ) -> ReActDecision:
        """按工具顺序生成确定性决策。

        Args:
            task_input: 原始任务或问题。
            allowed_tools: 当前白名单工具卡片。
            scratchpad: 历史步骤摘要。
            step_index: 当前步数。
            max_steps: 当前主循环最大步数。

        Returns:
            旧逻辑等价的 ReAct 决策。
        """
        if not allowed_tools:
            return ReActDecision(thought="无可用工具", action=None, tool_input={}, stop=True)
        tool = allowed_tools[min(step_index, len(allowed_tools) - 1)]
        return ReActDecision(
            thought="使用确定性降级策略选择工具",
            action=tool.name,
            tool_input={"query": task_input, "step_index": step_index},
            stop=False,
        )

    def reflect(
        self,
        task_input: str,
        observation_digest: dict[str, Any],
        scratchpad: list[dict[str, Any]],
        step_index: int,
    ) -> ReflectResult:
        """按 evidence 数量和分数阈值生成确定性反思结果。

        Args:
            task_input: 当前任务或问题。
            observation_digest: 本步 observation 摘要。
            scratchpad: 历史步骤摘要。
            step_index: 当前步数。

        Returns:
            阈值兜底反思结果。
        """
        evidence_count = int(observation_digest.get("evidence_count") or 0)
        top_score = float(observation_digest.get("top_score") or 0.0)
        has_error = bool(observation_digest.get("error"))
        sufficient = evidence_count > 0 and top_score >= self.sufficient_score_threshold and not has_error
        reason = "证据达到阈值" if sufficient else "证据未达到阈值"
        return ReflectResult(sufficient=sufficient, reason=reason, next_query_hint=None)


class LLMReActPolicy:
    """基于 LLMClient 的 ReAct 决策策略。"""

    driver = "llm"

    def __init__(
        self,
        llm_client: LLMClient,
        node_name: str,
        model: str | None = None,
        reflect_model: str | None = None,
        temperature: float = 0.0,
        timeout: float | None = None,
    ) -> None:
        """初始化 LLM ReAct policy。

        Args:
            llm_client: 可注入的 LLM 客户端。
            node_name: 调用节点名称,用于 trace。
            model: 决策模型名称。
            reflect_model: 反思模型名称,为空时回退决策模型。
            temperature: 决策温度。
            timeout: 单次决策超时。
        """
        self.llm_client = llm_client
        self.node_name = node_name
        self.model = model
        self.reflect_model = reflect_model
        self.temperature = temperature
        self.timeout = timeout

    def decide(
        self,
        task_input: str,
        allowed_tools: list[ToolCard],
        scratchpad: list[dict[str, Any]],
        step_index: int,
        max_steps: int,
    ) -> ReActDecision:
        """调用 LLM 生成下一步 ReAct 决策。

        Args:
            task_input: 原始任务或问题。
            allowed_tools: 当前白名单工具卡片。
            scratchpad: 历史步骤摘要。
            step_index: 当前步数。
            max_steps: 当前主循环最大步数。

        Returns:
            结构化 ReAct 决策。

        Raises:
            ReActPolicyError: LLM 调用失败或输出结构不合规。
        """
        response = self.llm_client.generate(
            messages=build_react_policy_messages(task_input, allowed_tools, scratchpad, step_index, max_steps),
            output_schema=REACT_DECISION_SCHEMA,
            model=self.model,
            temperature=self.temperature,
            timeout=self.timeout,
            trace_context={"node_name": self.node_name, "task_type": "react_policy"},
        )
        if response.errors:
            raise ReActPolicyError("llm_error")
        return _parse_decision(response.content)

    def reflect(
        self,
        task_input: str,
        observation_digest: dict[str, Any],
        scratchpad: list[dict[str, Any]],
        step_index: int,
    ) -> ReflectResult:
        """调用 LLM 生成 observation 反思结果。

        Args:
            task_input: 当前任务或问题。
            observation_digest: 本步 observation 摘要。
            scratchpad: 历史步骤摘要。
            step_index: 当前步数。

        Returns:
            结构化反思结果。

        Raises:
            ReActPolicyError: LLM 调用失败或输出结构不合规。
        """
        response = self.llm_client.generate(
            messages=build_react_reflect_messages(task_input, observation_digest, scratchpad, step_index),
            output_schema=REACT_REFLECT_SCHEMA,
            model=self.reflect_model or self.model,
            temperature=0.0,
            timeout=self.timeout,
            trace_context={"node_name": self.node_name, "task_type": "react_reflect"},
        )
        if response.errors:
            raise ReActPolicyError("llm_error")
        return _parse_reflection(response.content)


def _parse_decision(payload: dict[str, Any]) -> ReActDecision:
    """解析并校验 LLM 决策。"""
    if not isinstance(payload, dict):
        raise ReActPolicyError("invalid_decision")
    for key in ("thought", "stop"):
        if key not in payload:
            raise ReActPolicyError("missing_required")
    thought = payload["thought"]
    action = payload.get("action")
    tool_input = payload["tool_input"] if "tool_input" in payload else {}
    stop = payload["stop"]
    if not isinstance(thought, str):
        raise ReActPolicyError("invalid_thought")
    if action is not None and not isinstance(action, str):
        raise ReActPolicyError("invalid_action")
    if not isinstance(tool_input, dict):
        raise ReActPolicyError("invalid_tool_input")
    if not isinstance(stop, bool):
        raise ReActPolicyError("invalid_flags")
    return ReActDecision(thought=thought, action=action, tool_input=tool_input, stop=stop)


def _parse_reflection(payload: dict[str, Any]) -> ReflectResult:
    """解析并校验 LLM 反思结果。"""
    if not isinstance(payload, dict):
        raise ReActPolicyError("invalid_reflection")
    for key in ("sufficient", "reason"):
        if key not in payload:
            raise ReActPolicyError("missing_required")
    sufficient = payload["sufficient"]
    reason = payload["reason"]
    next_query_hint = payload.get("next_query_hint")
    if not isinstance(sufficient, bool):
        raise ReActPolicyError("invalid_sufficient")
    if not isinstance(reason, str):
        raise ReActPolicyError("invalid_reason")
    if next_query_hint is not None and not isinstance(next_query_hint, str):
        raise ReActPolicyError("invalid_next_query_hint")
    return ReflectResult(sufficient=sufficient, reason=reason, next_query_hint=next_query_hint)
