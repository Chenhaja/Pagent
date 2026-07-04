from typing import Any

from app.core.config import Settings, get_settings
from app.models.schemas import NodeResult, WorkflowState
from app.orchestrator.node_base import Node
from app.orchestrator.react_loop import BoundedReActLoop, ReActBudget, ReActOutcome
from app.orchestrator.react_policy import HeuristicReActPolicy
from app.orchestrator.tool_registry import build_default_tool_registry
from app.prompts.patent_drafting_sop import PATENT_DRAFTING_SOP_PROMPT
from app.tools.draft_workspace import DraftWorkspaceTool


DRAFTING_SOURCE_ARTIFACT_KEY = "drafting_source"
DRAFTING_ARTIFACT_FIELDS: dict[str, str] = {
    "input_points": "input_points_md",
    "prior_art": "prior_art_md",
    "outline": "outline_md",
    "abstract": "abstract_md",
    "claims": "claims_md",
    "description": "description_md",
    "figures": "figures_md",
    "complete_patent": "complete_patent_md",
}
DRAFTING_ALLOWED_TOOLS = [
    "subagent_input_points",
    "subagent_prior_art",
    "subagent_outline",
    "subagent_abstract",
    "subagent_claims",
    "subagent_description",
    "subagent_figures",
    "subagent_complete_patent",
]


class DraftingLeaderPolicy(HeuristicReActPolicy):
    """按专利文书 SOP 顺序选择子代理工具。"""

    def decide(self, task_input: str, allowed_tools: list, scratchpad: list[dict], step_index: int, max_steps: int):
        """按 step_index 生成 source_artifact_key 决策。"""
        decision = super().decide(task_input, allowed_tools, scratchpad, step_index, max_steps)
        if decision.action:
            decision.tool_input = {"source_artifact_key": DRAFTING_SOURCE_ARTIFACT_KEY}
        return decision


class DraftingLeaderNode(Node):
    """专利文书生成编排节点。

    Args:
        settings: 应用配置,未传入时读取全局配置。
        react_loop: 可注入的 bounded ReAct loop。
        workspace: 可注入的草稿 artifact 工作区工具。
        max_steps: 子代理最大调用步数。
        token_budget: ReAct evidence token 预算。
        timeout_seconds: ReAct 主循环超时时间。

    Returns:
        按 SOP 生成专利文书 Markdown 产物的节点。
    """

    name = "drafting_leader"

    def __init__(
        self,
        settings: Settings | None = None,
        react_loop: BoundedReActLoop | None = None,
        workspace: DraftWorkspaceTool | None = None,
        max_steps: int | None = None,
        token_budget: int | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        """初始化 drafting leader 节点。"""
        super().__init__(name=self.name)
        self.settings = settings or get_settings()
        self.max_steps = self.settings.react_max_steps if max_steps is None else max_steps
        self.token_budget = self.settings.react_token_budget if token_budget is None else token_budget
        self.timeout_seconds = self.settings.react_timeout_seconds if timeout_seconds is None else timeout_seconds
        self.workspace = workspace or DraftWorkspaceTool(self.settings)
        self.react_loop = react_loop or self._build_react_loop()

    def run(self, state: WorkflowState) -> NodeResult:
        """执行专利文书 SOP 编排并回填 state。"""
        source_content = self._build_source_content(state)
        written = self.workspace.run(
            {"action": "write", "artifact_key": DRAFTING_SOURCE_ARTIFACT_KEY, "content": source_content}
        )
        if written.error:
            state.drafting_incomplete = True
            return NodeResult.failed(errors=[written.error])

        outcome = self.react_loop.run(self._build_task_input(state), allowed_tools=DRAFTING_ALLOWED_TOOLS)
        artifacts = self._read_artifacts(state)
        incomplete = outcome.reason != "sufficient" or len(artifacts) != len(DRAFTING_ARTIFACT_FIELDS)
        state.drafting_incomplete = incomplete
        output = {field_name: getattr(state, field_name) for field_name in DRAFTING_ARTIFACT_FIELDS.values()}
        output["drafting_incomplete"] = incomplete
        return NodeResult.success(
            output=output,
            trace_events=[
                *outcome.trace_events,
                {
                    "event": "drafting_leader_completed",
                    "data": {
                        "reason": outcome.reason,
                        "steps_used": outcome.steps_used,
                        "tool_calls": outcome.tool_calls,
                        "artifact_keys": list(artifacts),
                        "complete_patent_chars": len(state.complete_patent_md),
                        "drafting_incomplete": incomplete,
                    },
                },
            ],
        )

    def _build_react_loop(self) -> BoundedReActLoop:
        """构建 drafting leader 默认 bounded ReAct loop。"""
        registry = build_default_tool_registry(self.settings)
        return BoundedReActLoop(
            tools=registry.available_tools(),
            budget=ReActBudget(
                max_steps=self.max_steps,
                token_budget=self.token_budget,
                timeout_seconds=self.timeout_seconds,
            ),
            node_name=self.name,
            policy=DraftingLeaderPolicy(),
            tool_cards=registry.tool_cards(DRAFTING_ALLOWED_TOOLS),
            use_llm_judge=False,
            observation_digest_chars=0,
            settings=self.settings,
        )

    def _build_source_content(self, state: WorkflowState) -> str:
        """拼接用户输入和附件正文作为 source artifact 数据。"""
        parts = [state.normalized_input or state.raw_input]
        for document in state.documents:
            text = str(document.get("text") or "").strip()
            if text:
                parts.append(text)
        return "\n\n".join(part for part in parts if part.strip())

    def _build_task_input(self, state: WorkflowState) -> str:
        """构造不含正文的 ReAct 任务说明。"""
        return (
            f"{PATENT_DRAFTING_SOP_PROMPT}\n"
            f"source_artifact_key={DRAFTING_SOURCE_ARTIFACT_KEY}; "
            f"document_count={len(state.documents)}; input_chars={len(state.normalized_input or state.raw_input)}"
        )

    def _read_artifacts(self, state: WorkflowState) -> dict[str, int]:
        """读取各阶段 artifact 并写入 WorkflowState。"""
        artifacts: dict[str, int] = {}
        for artifact_key, field_name in DRAFTING_ARTIFACT_FIELDS.items():
            observation = self.workspace.run({"action": "read", "artifact_key": artifact_key})
            if observation.error or not observation.evidence:
                continue
            content = str(observation.evidence[0].get("content") or "")
            setattr(state, field_name, content)
            artifacts[artifact_key] = len(content)
        return artifacts
