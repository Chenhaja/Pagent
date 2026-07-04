from dataclasses import dataclass

from app.core.config import Settings, get_settings
from app.orchestrator.react_loop import ToolObservation
from app.orchestrator.tool_registry import ToolSpec
from app.tools.draft_workspace import DraftWorkspaceTool


@dataclass(frozen=True)
class SubagentDefinition:
    """专利文书子代理定义。"""

    name: str
    title: str
    output_artifact_key: str


SUBAGENT_DEFINITIONS = [
    SubagentDefinition("subagent_input_points", "输入要点", "input_points"),
    SubagentDefinition("subagent_prior_art", "现有技术", "prior_art"),
    SubagentDefinition("subagent_outline", "文书提纲", "outline"),
    SubagentDefinition("subagent_abstract", "摘要", "abstract"),
    SubagentDefinition("subagent_claims", "权利要求", "claims"),
    SubagentDefinition("subagent_description", "说明书", "description"),
    SubagentDefinition("subagent_figures", "附图说明", "figures"),
    SubagentDefinition("subagent_complete_patent", "完整专利文书", "complete_patent"),
]


class PatentDraftingSubagentTool:
    """专利文书子代理工具。"""

    def __init__(self, definition: SubagentDefinition, settings: Settings | None = None) -> None:
        """初始化子代理工具。

        Args:
            definition: 子代理定义。
            settings: 应用配置,未传入时读取全局配置。

        Returns:
            无返回值。
        """
        self.definition = definition
        self.settings = settings or get_settings()
        self.workspace = DraftWorkspaceTool(self.settings)

    def run(self, tool_input: dict) -> ToolObservation:
        """执行子代理生成。

        Args:
            tool_input: 必须包含 source_artifact_key,不得包含长正文 content。

        Returns:
            写入 Markdown artifact 的 observation。
        """
        if "content" in tool_input:
            return ToolObservation(tool_name=self.definition.name, error="inline_content_not_allowed")
        source_key = str(tool_input.get("source_artifact_key") or "").strip()
        if not source_key:
            return ToolObservation(tool_name=self.definition.name, error="invalid_input")
        source = self.workspace.run({"action": "read", "artifact_key": source_key})
        if source.error:
            return ToolObservation(tool_name=self.definition.name, error=source.error)
        source_content = str(source.evidence[0].get("content") or "") if source.evidence else ""
        markdown = f"# {self.definition.title}\n\n{source_content}".strip()
        written = self.workspace.run(
            {"action": "write", "artifact_key": self.definition.output_artifact_key, "content": markdown}
        )
        if written.error:
            return ToolObservation(tool_name=self.definition.name, error=written.error)
        return ToolObservation(
            tool_name=self.definition.name,
            evidence=[{"artifact_key": self.definition.output_artifact_key, "markdown": markdown, "done": True}],
            sufficient=True,
        )


def build_patent_drafting_subagent_specs(settings: Settings | None = None) -> list[ToolSpec]:
    """构建专利文书子代理 ToolSpec 列表。

    Args:
        settings: 应用配置,未传入时读取全局配置。

    Returns:
        8 个专利文书子代理工具注册元数据。
    """
    current_settings = settings or get_settings()
    return [
        ToolSpec(
            name=definition.name,
            runner=PatentDraftingSubagentTool(definition, current_settings),
            description=f"生成{definition.title} Markdown artifact,只通过 workspace key 读取正文。",
            input_schema={
                "type": "object",
                "properties": {"source_artifact_key": {"type": "string"}},
                "required": ["source_artifact_key"],
                "additionalProperties": False,
            },
            external=False,
            enabled=True,
        )
        for definition in SUBAGENT_DEFINITIONS
    ]
