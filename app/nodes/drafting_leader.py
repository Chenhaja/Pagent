from typing import Any

from app.core.config import Settings, get_settings
from app.models.schemas import NodeResult, WorkflowState
from app.orchestrator.node_base import Node
from app.orchestrator.tool_registry import ToolRegistry, build_default_tool_registry
from app.prompts.patent_drafting_leader import PATENT_DRAFTING_LEADER_PROMPT
from app.tools.draft_workspace import DraftWorkspaceTool


DRAFTING_SOURCE_ARTIFACT_KEY = "01_input/raw_document.md"
DRAFTING_ALLOWED_TOOLS = [
    "input_parser",
    "patent_searcher",
    "outline_generator",
    "abstract_writer",
    "claims_writer",
    "description_writer_part1",
    "description_writer_part2",
    "diagram_generator",
    "markdown_merger",
]
DRAFTING_STAGE_OUTPUTS: dict[str, list[str]] = {
    "input_parser": ["01_input/parsed_info.json"],
    "patent_searcher": ["02_research/prior_art_analysis.md"],
    "outline_generator": ["03_outline/patent_outline.md"],
    "abstract_writer": ["04_content/abstract.md"],
    "claims_writer": ["04_content/claims.md"],
    "description_writer_part1": ["04_content/description.md"],
    "description_writer_part2": ["04_content/description.md"],
    "diagram_generator": ["04_content/figures.md"],
    "markdown_merger": ["05_final/complete_patent.md"],
}
DRAFTING_STAGE_SOURCES: dict[str, str] = {
    "input_parser": DRAFTING_SOURCE_ARTIFACT_KEY,
    "patent_searcher": "01_input/parsed_info.json",
    "outline_generator": "01_input/parsed_info.json",
    "abstract_writer": "03_outline/patent_outline.md",
    "claims_writer": "04_content/abstract.md",
    "description_writer_part1": "04_content/claims.md",
    "description_writer_part2": "04_content/description.md",
    "diagram_generator": "04_content/description.md",
    "markdown_merger": "03_outline/patent_outline.md",
}
DRAFTING_ARTIFACT_FIELDS: dict[str, str] = {
    "01_input/parsed_info.json": "input_points_md",
    "02_research/prior_art_analysis.md": "prior_art_md",
    "03_outline/patent_outline.md": "outline_md",
    "04_content/abstract.md": "abstract_md",
    "04_content/claims.md": "claims_md",
    "04_content/description.md": "description_md",
    "04_content/figures.md": "figures_md",
    "05_final/complete_patent.md": "complete_patent_md",
}
_MAX_REDELEGATIONS = 5


class DraftingLeaderNode(Node):
    """专利文书生成 R12 编排节点。

    Args:
        settings: 应用配置,未传入时读取全局配置。
        workspace: 可注入的草稿 artifact 工作区工具。
        tool_registry: 可注入工具注册表,测试中用于记录子代理调用。

    Returns:
        按 R12 9 环节生成专利文书 artifact 的节点。
    """

    name = "drafting_leader"

    def __init__(
        self,
        settings: Settings | None = None,
        workspace: DraftWorkspaceTool | None = None,
        tool_registry: ToolRegistry | Any | None = None,
        **_: Any,
    ) -> None:
        """初始化 drafting leader 节点。"""
        super().__init__(name=self.name)
        self.settings = settings or get_settings()
        self.workspace = workspace or DraftWorkspaceTool(self.settings)
        self.tool_registry = tool_registry or build_default_tool_registry(self.settings)

    def run(self, state: WorkflowState) -> NodeResult:
        """执行 R12 专利文书 9 环节编排并回填 state。"""
        trace_events: list[dict[str, Any]] = []
        written = self.workspace.run(
            {"action": "write", "artifact_key": DRAFTING_SOURCE_ARTIFACT_KEY, "content": self._build_source_content(state)}
        )
        if written.error:
            state.drafting_incomplete = True
            return NodeResult.failed(errors=[written.error])
        trace_events.append(self._trace_event("drafting_source_written", artifact_key=DRAFTING_SOURCE_ARTIFACT_KEY, chars=self._chars(written)))

        incomplete = False
        for index, tool_name in enumerate(DRAFTING_ALLOWED_TOOLS):
            self._write_todo(index)
            stage_ok = self._run_stage_with_review(tool_name, trace_events)
            if not stage_ok:
                incomplete = True
                break

        artifacts = self._read_artifacts(state)
        if len(artifacts) != len(DRAFTING_ARTIFACT_FIELDS):
            incomplete = True
        state.drafting_incomplete = incomplete
        output = {field_name: getattr(state, field_name) for field_name in DRAFTING_ARTIFACT_FIELDS.values()}
        output["drafting_incomplete"] = incomplete
        trace_events.append(
            self._trace_event(
                "drafting_leader_completed",
                reason="incomplete" if incomplete else "sufficient",
                artifact_keys=list(artifacts),
                complete_patent_chars=len(state.complete_patent_md),
                drafting_incomplete=incomplete,
            )
        )
        return NodeResult.success(output=output, trace_events=trace_events)

    def _run_stage_with_review(self, tool_name: str, trace_events: list[dict[str, Any]]) -> bool:
        """执行单个子代理并用 workspace list 审查目标产物。"""
        for attempt in range(_MAX_REDELEGATIONS + 1):
            observation = self.tool_registry.run(tool_name, {"source_artifact_key": DRAFTING_STAGE_SOURCES[tool_name]})
            artifact_key = self._artifact_key_from_observation(observation) or DRAFTING_STAGE_OUTPUTS[tool_name][0]
            trace_events.append(
                self._trace_event(
                    "drafting_subagent_completed",
                    tool_name=tool_name,
                    artifact_key=artifact_key,
                    status="error" if observation.error else "ok",
                    error=observation.error,
                    attempt=attempt + 1,
                )
            )
            if observation.error:
                return False
            if self._outputs_exist(tool_name, trace_events):
                return True
        trace_events.append(self._trace_event("drafting_subagent_missing_output", tool_name=tool_name, status="failed"))
        return False

    def _outputs_exist(self, tool_name: str, trace_events: list[dict[str, Any]]) -> bool:
        """通过 list 审查当前阶段输出文件是否存在。"""
        expected = DRAFTING_STAGE_OUTPUTS[tool_name]
        prefix = expected[0].rsplit("/", 1)[0]
        listed = self.workspace.run({"action": "list", "prefix": prefix})
        artifacts = [] if listed.error or not listed.evidence else list(listed.evidence[0].get("artifacts") or [])
        trace_events.append(
            self._trace_event(
                "drafting_stage_reviewed",
                tool_name=tool_name,
                artifact_key=expected[0],
                status="ok" if all(key in artifacts for key in expected) else "missing",
            )
        )
        return all(key in artifacts for key in expected)

    def _write_todo(self, active_index: int) -> None:
        """将 Leader 当前 9 环节进度写入 todo 工具。"""
        if self.tool_registry.get("todo") is None:
            return
        todos = []
        for index, tool_name in enumerate(DRAFTING_ALLOWED_TOOLS):
            status = "done" if index < active_index else "in_progress" if index == active_index else "pending"
            todos.append({"content": tool_name, "status": status})
        self.tool_registry.run("todo", {"owner": "leader", "todos": todos})

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

    def _build_source_content(self, state: WorkflowState) -> str:
        """拼接用户输入和附件正文作为 source artifact 数据。"""
        parts = [state.normalized_input or state.raw_input]
        for document in state.documents:
            text = str(document.get("text") or "").strip()
            if text:
                parts.append(text)
        return "\n\n".join(part for part in parts if part.strip())

    def _trace_event(self, event: str, **data: Any) -> dict[str, Any]:
        """构造脱敏 trace 事件。"""
        safe = {key: value for key, value in data.items() if value is not None}
        return {"event": event, "data": safe}

    def _artifact_key_from_observation(self, observation: Any) -> str | None:
        """从工具 observation 中提取 artifact key。"""
        if not getattr(observation, "evidence", None):
            return None
        return str(observation.evidence[0].get("artifact_key") or "") or None

    def _chars(self, observation: Any) -> int:
        """从工具 observation 中提取字符数。"""
        if not getattr(observation, "evidence", None):
            return 0
        return int(observation.evidence[0].get("chars") or 0)
