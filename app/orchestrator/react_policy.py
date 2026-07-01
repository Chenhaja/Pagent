from dataclasses import dataclass, field
from typing import Any, Protocol

from app.prompts.react_policy import REACT_DECISION_SCHEMA, build_react_policy_messages
from app.tools.llm import LLMClient


@dataclass
class ReActDecision:
    """ReAct 单步策略决策。

    Args:
        thought: 决策短摘要,仅用于内部 trace 摘要。
        action: 选中的工具名;None 表示停止。
        tool_input: 传给工具的结构化输入。
        stop: 是否停止主循环。
        sufficient: 是否认为证据已充分。

    Returns:
        可被主循环校验和执行的结构化决策。
    """

    thought: str
    action: str | None
    tool_input: dict[str, Any] = field(default_factory=dict)
    stop: bool = False
    sufficient: bool = False


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
    ) -> ReActDecision:
        """生成下一步 ReAct 决策。

        Args:
            task_input: 原始任务或问题。
            allowed_tools: 当前白名单工具卡片。
            scratchpad: 历史步骤摘要。
            step_index: 当前步数。

        Returns:
            结构化 ReAct 决策。
        """
        ...


class HeuristicReActPolicy:
    """确定性降级策略,保留旧版按顺序选工具行为。"""

    driver = "heuristic"

    def decide(
        self,
        task_input: str,
        allowed_tools: list[ToolCard],
        scratchpad: list[dict[str, Any]],
        step_index: int,
    ) -> ReActDecision:
        """按工具顺序生成确定性决策。

        Args:
            task_input: 原始任务或问题。
            allowed_tools: 当前白名单工具卡片。
            scratchpad: 历史步骤摘要。
            step_index: 当前步数。

        Returns:
            旧逻辑等价的 ReAct 决策。
        """
        if not allowed_tools:
            return ReActDecision(thought="无可用工具", action=None, tool_input={}, stop=True, sufficient=False)
        tool = allowed_tools[min(step_index, len(allowed_tools) - 1)]
        return ReActDecision(
            thought="使用确定性降级策略选择工具",
            action=tool.name,
            tool_input={"query": task_input, "step_index": step_index},
            stop=False,
            sufficient=False,
        )


class LLMReActPolicy:
    """基于 LLMClient 的 ReAct 决策策略。"""

    driver = "llm"

    def __init__(
        self,
        llm_client: LLMClient,
        node_name: str,
        model: str | None = None,
        temperature: float = 0.0,
        timeout: float | None = None,
    ) -> None:
        """初始化 LLM ReAct policy。

        Args:
            llm_client: 可注入的 LLM 客户端。
            node_name: 调用节点名称,用于 trace。
            model: 决策模型名称。
            temperature: 决策温度。
            timeout: 单次决策超时。
        """
        self.llm_client = llm_client
        self.node_name = node_name
        self.model = model
        self.temperature = temperature
        self.timeout = timeout

    def decide(
        self,
        task_input: str,
        allowed_tools: list[ToolCard],
        scratchpad: list[dict[str, Any]],
        step_index: int,
    ) -> ReActDecision:
        """调用 LLM 生成下一步 ReAct 决策。

        Args:
            task_input: 原始任务或问题。
            allowed_tools: 当前白名单工具卡片。
            scratchpad: 历史步骤摘要。
            step_index: 当前步数。

        Returns:
            结构化 ReAct 决策。

        Raises:
            ReActPolicyError: LLM 调用失败或输出结构不合规。
        """
        response = self.llm_client.generate(
            messages=build_react_policy_messages(task_input, allowed_tools, scratchpad, step_index),
            output_schema=REACT_DECISION_SCHEMA,
            model=self.model,
            temperature=self.temperature,
            timeout=self.timeout,
            trace_context={"node_name": self.node_name, "task_type": "react_policy"},
        )
        if response.errors:
            raise ReActPolicyError("llm_error")
        return _parse_decision(response.content)


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
    sufficient = payload.get("sufficient", False)
    if not isinstance(thought, str):
        raise ReActPolicyError("invalid_thought")
    if action is not None and not isinstance(action, str):
        raise ReActPolicyError("invalid_action")
    if not isinstance(tool_input, dict):
        raise ReActPolicyError("invalid_tool_input")
    if not isinstance(stop, bool) or not isinstance(sufficient, bool):
        raise ReActPolicyError("invalid_flags")
    return ReActDecision(thought=thought, action=action, tool_input=tool_input, stop=stop, sufficient=sufficient)
