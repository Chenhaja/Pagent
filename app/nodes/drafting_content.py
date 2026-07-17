import json
from typing import Any

from app.core.config import Settings, get_settings
from app.models.schemas import NodeResult, WorkflowState
from app.orchestrator.node_base import Node
from app.prompts.subagents.abstract_writer_prompt import ABSTRACT_WRITER_PROMPT
from app.prompts.subagents.claims_writer_prompt import CLAIMS_WRITER_PROMPT
from app.prompts.subagents.description_writer_part1_prompt import DESCRIPTION_WRITER_PART1_PROMPT
from app.prompts.subagents.description_writer_part2_prompt import DESCRIPTION_WRITER_PART2_PROMPT
from app.prompts.subagents.diagram_generator_prompt import DIAGRAM_GENERATOR_PROMPT
from app.prompts.subagents.markdown_merger_prompt import MARKDOWN_MERGER_PROMPT
from app.prompts.subagents.outline_generator_prompt import OUTLINE_GENERATOR_PROMPT
from app.tools.draft_workspace import DraftWorkspaceTool
from app.tools.subagents.agent_runner import LangChainAgentRunner
from app.tools.subagents.file_policy import FileToolPolicy
from app.tracing.sinks import MemoryWorkflowTraceEmitter, WorkflowTraceEmitter


DRAFTING_OUTLINE_ARTIFACT_KEY = "03_outline/patent_outline.md"
DRAFTING_ABSTRACT_ARTIFACT_KEY = "04_content/abstract.md"
DRAFTING_CLAIMS_ARTIFACT_KEY = "04_content/claims.md"
DRAFTING_DESCRIPTION_ARTIFACT_KEY = "04_content/description.md"
DRAFTING_FIGURES_ARTIFACT_KEY = "04_content/figures.md"
DRAFTING_COMPLETE_PATENT_ARTIFACT_KEY = "05_final/complete_patent.md"
DRAFTING_REVIEW_REPORT_ARTIFACT_KEY = "05_final/review_report.md"
DRAFTING_SECTION_KEYS = [
    DRAFTING_ABSTRACT_ARTIFACT_KEY,
    DRAFTING_CLAIMS_ARTIFACT_KEY,
    DRAFTING_DESCRIPTION_ARTIFACT_KEY,
    DRAFTING_FIGURES_ARTIFACT_KEY,
]


class DraftingContentNodeBase(Node):
    """文书生成内容节点基类。

    Args:
        name: 当前内容节点名称。
        settings: 应用配置,未传入时读取全局配置。
        workspace: 可注入的草稿 artifact 工作区工具。

    Returns:
        提供 workspace 读写 helper 的内容节点基类。
    """

    def __init__(self, name: str, settings: Settings | None = None, workspace: DraftWorkspaceTool | None = None) -> None:
        """初始化内容节点基类。"""
        super().__init__(name=name)
        self.settings = settings or get_settings()
        self.workspace = workspace or DraftWorkspaceTool(self.settings)

    def _read_text(self, artifact_key: str) -> str | None:
        """读取文本 artifact,失败时返回 None。"""
        observation = self.workspace.run({"action": "read", "artifact_key": artifact_key})
        if observation.error or not getattr(observation, "evidence", None):
            return None
        return str(observation.evidence[0].get("content") or "")

    def _read_json(self, artifact_key: str) -> dict[str, Any] | None:
        """读取 JSON artifact,失败时返回 None。"""
        content = self._read_text(artifact_key)
        if content is None:
            return None
        return json.loads(content or "{}")

    def _write(self, artifact_key: str, content: str) -> str | None:
        """写入 artifact,成功返回 None,失败返回错误码。"""
        observation = self.workspace.run({"action": "write", "artifact_key": artifact_key, "content": content})
        return observation.error

    def _topic(self, state: WorkflowState) -> str:
        """从 parsed info 或大纲中读取技术主题。"""
        parsed = self._read_json(str(state.drafting_context.get("parsed_info_key") or "01_input/parsed_info.json")) or {}
        return str(parsed.get("technical_topic") or parsed.get("title") or "技术方案")

    def _run_text_agent(self, runner: Any, artifact_key: str, task: str) -> NodeResult | None:
        """执行文本生成 runner 并验证目标 artifact 存在。"""
        observation = runner.run({"task": task})
        if getattr(observation, "error", None):
            return NodeResult.failed(errors=[str(observation.error)])
        if self._read_text(artifact_key) is None:
            return NodeResult.failed(errors=[f"artifact_missing:{artifact_key}"])
        return None

    def _trace_events_from(self, emitter: WorkflowTraceEmitter | None) -> list[dict[str, Any]]:
        """读取 emitter 中可进入 NodeResult 的 trace 事件。"""
        return list(getattr(emitter, "trace_events", []) or [])


class DraftingGenerateOutlineNode(DraftingContentNodeBase):
    """专利文书大纲生成节点。

    Args:
        settings: 应用配置,未传入时读取全局配置。
        workspace: 可注入的草稿 artifact 工作区工具。

    Returns:
        读取前置研究 artifact 并写入大纲 artifact 的节点。
    """

    name = "drafting_generate_outline"

    def __init__(
        self,
        settings: Settings | None = None,
        workspace: DraftWorkspaceTool | None = None,
        outline_runner: Any | None = None,
        workflow_trace_emitter: WorkflowTraceEmitter | None = None,
    ) -> None:
        """初始化大纲生成节点。"""
        super().__init__(name=self.name, settings=settings, workspace=workspace)
        self.workflow_trace_emitter = workflow_trace_emitter or MemoryWorkflowTraceEmitter()
        outline_reads = ["01_input/parsed_info.json", "02_research/patent_search_results.json", "02_research/prior_art_analysis.md"]
        self.outline_runner = outline_runner or LangChainAgentRunner(
            node_name=self.name,
            stage="drafting.outline",
            agent_name="outline_generator_agent",
            prompt_name="OUTLINE_GENERATOR_PROMPT",
            system_prompt=OUTLINE_GENERATOR_PROMPT,
            allowed_tools=["read_file", "write_file", "mkdir", "list_directory", "list_skills", "load_skill"],
            file_policy=FileToolPolicy(
                readRoots=["01_input", "02_research"] + outline_reads,
                writeRoots=["03_outline", DRAFTING_OUTLINE_ARTIFACT_KEY],
            ),
            output_artifact_keys=[DRAFTING_OUTLINE_ARTIFACT_KEY],
            fallback_builder=self._build_outline_fallback,
            settings=self.settings,
            workspace=self.workspace,
            workflow_trace_emitter=self.workflow_trace_emitter,
        )

    def run(self, state: WorkflowState) -> NodeResult:
        """生成专利文书大纲 artifact。

        Args:
            state: 当前 workflow 状态,需包含 parsed、prior art、drawing 与 writing guide artifact key。

        Returns:
            成功时返回 outline artifact key。
        """
        parsed = self._read_json(str(state.drafting_context.get("parsed_info_key") or "01_input/parsed_info.json"))
        prior_art_key = str(state.drafting_context.get("prior_art_analysis_key") or "02_research/prior_art_analysis.md")
        prior_art = self._read_text(prior_art_key)
        if parsed is None:
            return NodeResult.failed(errors=["parsed_info_missing"])
        if prior_art is None:
            return NodeResult.failed(errors=["prior_art_analysis_missing"])
        failed = self._run_text_agent(self.outline_runner, DRAFTING_OUTLINE_ARTIFACT_KEY, "生成专利文书大纲")
        if failed is not None:
            return failed
        content = self._read_text(DRAFTING_OUTLINE_ARTIFACT_KEY) or ""
        state.drafting_context["outline_key"] = DRAFTING_OUTLINE_ARTIFACT_KEY
        return NodeResult.success(
            output={"outline_key": DRAFTING_OUTLINE_ARTIFACT_KEY},
            trace_events=[{"event": "drafting_outline_generated", "data": {"artifact_key": DRAFTING_OUTLINE_ARTIFACT_KEY, "chars": len(content)}}],
        )

    def _outline_content(self, topic: str, focus_features: list[Any], figures: list[Any]) -> str:
        """构造本地确定性大纲正文。"""
        feature_text = "、".join(str(item) for item in focus_features) or "待结合交底书确认"
        figure_text = "、".join(str(item.get("figure_no")) for item in figures if isinstance(item, dict) and item.get("figure_no")) or "无明确附图"
        return f"# 专利大纲\n\n## 技术主题\n\n{topic}\n\n## 权利要求重点\n\n{feature_text}\n\n## 说明书结构\n\n技术领域、背景技术、发明内容、附图说明、具体实施方式。\n\n## 附图\n\n{figure_text}"

    def _build_outline_fallback(self, reason: str, workspace: DraftWorkspaceTool) -> str:
        """生成大纲 fallback 正文。"""
        parsed = self._read_json("01_input/parsed_info.json") or {}
        topic = str(parsed.get("technical_topic") or "技术方案")
        return self._outline_content(topic, [], [])


class _SingleArtifactWriterNode(DraftingContentNodeBase):
    """单 artifact 文书内容生成节点基类。"""

    def __init__(self, name: str, stage: str, agent_name: str, prompt_name: str, system_prompt: str, allowed_read_artifact_keys: list[str], output_artifact_key: str, fallback_builder: Any, output_field: str, settings: Settings | None = None, workspace: DraftWorkspaceTool | None = None, runner: Any | None = None, workflow_trace_emitter: WorkflowTraceEmitter | None = None) -> None:
        """初始化单 artifact 文书内容生成节点。"""
        super().__init__(name=name, settings=settings, workspace=workspace)
        self.output_artifact_key = output_artifact_key
        self.output_field = output_field
        self.workflow_trace_emitter = workflow_trace_emitter or MemoryWorkflowTraceEmitter()
        self.runner = runner or LangChainAgentRunner(
            node_name=name,
            stage=stage,
            agent_name=agent_name,
            prompt_name=prompt_name,
            system_prompt=system_prompt,
            allowed_tools=["read_file", "write_file", "mkdir", "list_directory", "list_skills", "load_skill"],
            file_policy=FileToolPolicy(
                readRoots=["01_input", "02_research", "03_outline", "04_content"] + allowed_read_artifact_keys,
                writeRoots=["04_content", output_artifact_key],
            ),
            output_artifact_keys=[output_artifact_key],
            fallback_builder=fallback_builder,
            settings=self.settings,
            workspace=self.workspace,
            workflow_trace_emitter=self.workflow_trace_emitter,
        )

    def run(self, state: WorkflowState) -> NodeResult:
        """执行单 artifact 内容生成。"""
        failed = self._run_text_agent(self.runner, self.output_artifact_key, f"生成 {self.output_artifact_key}")
        if failed is not None:
            return failed
        state.drafting_context[self.output_field] = self.output_artifact_key
        return NodeResult.success(output={self.output_field: self.output_artifact_key}, trace_events=[*self._trace_events_from(self.workflow_trace_emitter), {"event": f"{self.name}_completed", "data": {"artifact_key": self.output_artifact_key}}])


class DraftingClaimsWriterNode(_SingleArtifactWriterNode):
    """专利权利要求书生成节点。"""

    name = "drafting_claims_writer"

    def __init__(self, settings: Settings | None = None, workspace: DraftWorkspaceTool | None = None, claims_runner: Any | None = None, workflow_trace_emitter: WorkflowTraceEmitter | None = None) -> None:
        """初始化权利要求书生成节点。"""
        super().__init__(self.name, "drafting.claims", "claims_writer_agent", "CLAIMS_WRITER_PROMPT", CLAIMS_WRITER_PROMPT, ["01_input/parsed_info.json", "02_research/patent_search_results.json", "02_research/prior_art_analysis.md", DRAFTING_OUTLINE_ARTIFACT_KEY], DRAFTING_CLAIMS_ARTIFACT_KEY, self._build_fallback, "claims_key", settings, workspace, claims_runner, workflow_trace_emitter)

    def _build_fallback(self, reason: str, workspace: DraftWorkspaceTool) -> str:
        """生成权利要求书 fallback 正文。"""
        topic = self._topic(WorkflowState(raw_input=""))
        return f"# 权利要求书\n\n1. 一种{topic},其特征在于,包括基于输入材料限定的核心技术特征。\n\n2. 根据权利要求1所述的{topic},其特征在于,所述核心技术特征用于实现柔性夹持。"


class DraftingDescriptionWriterNode(DraftingContentNodeBase):
    """专利说明书生成节点,内部串行生成 Part1 与 Part2。"""

    name = "drafting_description_writer"

    def __init__(self, settings: Settings | None = None, workspace: DraftWorkspaceTool | None = None, part1_runner: Any | None = None, part2_runner: Any | None = None, workflow_trace_emitter: WorkflowTraceEmitter | None = None) -> None:
        """初始化说明书生成节点。"""
        super().__init__(name=self.name, settings=settings, workspace=workspace)
        self.workflow_trace_emitter = workflow_trace_emitter or MemoryWorkflowTraceEmitter()
        common_reads = ["01_input/parsed_info.json", "02_research/patent_search_results.json", "02_research/prior_art_analysis.md", DRAFTING_OUTLINE_ARTIFACT_KEY, DRAFTING_CLAIMS_ARTIFACT_KEY]
        self.part1_runner = part1_runner or LangChainAgentRunner(
            node_name=self.name,
            stage="drafting.description.part1",
            agent_name="description_writer_part1_agent",
            prompt_name="DESCRIPTION_WRITER_PART1_PROMPT",
            system_prompt=DESCRIPTION_WRITER_PART1_PROMPT,
            allowed_tools=["read_file", "write_file", "mkdir", "list_directory", "list_skills", "load_skill"],
            file_policy=FileToolPolicy(
                readRoots=["01_input", "02_research", "03_outline", "04_content"] + common_reads,
                writeRoots=["04_content", "04_content/description_part1.md"],
            ),
            output_artifact_keys=["04_content/description_part1.md"],
            fallback_builder=self._build_part1_fallback,
            settings=self.settings,
            workspace=self.workspace,
            workflow_trace_emitter=self.workflow_trace_emitter,
        )
        self.part2_runner = part2_runner or LangChainAgentRunner(
            node_name=self.name,
            stage="drafting.description.part2",
            agent_name="description_writer_part2_agent",
            prompt_name="DESCRIPTION_WRITER_PART2_PROMPT",
            system_prompt=DESCRIPTION_WRITER_PART2_PROMPT,
            allowed_tools=["read_file", "write_file", "mkdir", "list_directory", "list_skills", "load_skill"],
            file_policy=FileToolPolicy(
                readRoots=["01_input", "02_research", "03_outline", "04_content"] + common_reads,
                writeRoots=["04_content", "04_content/description_part2.md"],
            ),
            output_artifact_keys=["04_content/description_part2.md"],
            fallback_builder=self._build_part2_fallback,
            settings=self.settings,
            workspace=self.workspace,
            workflow_trace_emitter=self.workflow_trace_emitter,
        )

    def run(self, state: WorkflowState) -> NodeResult:
        """生成说明书 Part1、Part2 并合并为完整说明书。"""
        failed = self._run_text_agent(self.part1_runner, "04_content/description_part1.md", "生成说明书第一部分")
        if failed is not None:
            return failed
        failed = self._run_text_agent(self.part2_runner, "04_content/description_part2.md", "生成说明书第二部分")
        if failed is not None:
            return failed
        part1 = self._read_text("04_content/description_part1.md") or ""
        part2 = self._read_text("04_content/description_part2.md") or ""
        error = self._write(DRAFTING_DESCRIPTION_ARTIFACT_KEY, f"{part1}\n\n{part2}".strip())
        if error:
            return NodeResult.failed(errors=[error])
        state.drafting_context["description_key"] = DRAFTING_DESCRIPTION_ARTIFACT_KEY
        return NodeResult.success(output={"description_key": DRAFTING_DESCRIPTION_ARTIFACT_KEY}, trace_events=[*self._trace_events_from(self.workflow_trace_emitter), {"event": "drafting_description_writer_completed", "data": {"artifact_key": DRAFTING_DESCRIPTION_ARTIFACT_KEY}}])

    def _build_part1_fallback(self, reason: str, workspace: DraftWorkspaceTool) -> str:
        """生成说明书第一部分 fallback 正文。"""
        topic = self._topic(WorkflowState(raw_input=""))
        return f"# 说明书\n\n## 技术领域\n\n本申请涉及{topic}。\n\n## 背景技术\n\n现有技术仍需改进。\n\n## 发明内容\n\n本申请提供一种{topic},以提升技术效果。\n\n## 附图说明\n\n图1为本申请实施例的流程示意图。"

    def _build_part2_fallback(self, reason: str, workspace: DraftWorkspaceTool) -> str:
        """生成说明书第二部分 fallback 正文。"""
        return "## 具体实施方式\n\n以下结合附图对本申请的技术方案进行说明。本实施例用于说明本申请,不构成限制。"


class DraftingDiagramGeneratorNode(_SingleArtifactWriterNode):
    """说明书附图生成节点。"""

    name = "drafting_diagram_generator"

    def __init__(self, settings: Settings | None = None, workspace: DraftWorkspaceTool | None = None, diagram_runner: Any | None = None, workflow_trace_emitter: WorkflowTraceEmitter | None = None) -> None:
        """初始化说明书附图生成节点。"""
        super().__init__(self.name, "drafting.diagram", "diagram_generator_agent", "DIAGRAM_GENERATOR_PROMPT", DIAGRAM_GENERATOR_PROMPT, ["01_input/parsed_info.json", DRAFTING_OUTLINE_ARTIFACT_KEY, DRAFTING_DESCRIPTION_ARTIFACT_KEY], DRAFTING_FIGURES_ARTIFACT_KEY, self._build_fallback, "figures_key", settings, workspace, diagram_runner, workflow_trace_emitter)

    def _build_fallback(self, reason: str, workspace: DraftWorkspaceTool) -> str:
        """生成附图 fallback 正文。"""
        return "# 附图说明\n\n```mermaid\nflowchart TB\n    A[101：获取输入] --> B[102：执行处理]\n```\n\n图1"


class DraftingAbstractWriterNode(_SingleArtifactWriterNode):
    """专利摘要生成节点。"""

    name = "drafting_abstract_writer"

    def __init__(self, settings: Settings | None = None, workspace: DraftWorkspaceTool | None = None, abstract_runner: Any | None = None, workflow_trace_emitter: WorkflowTraceEmitter | None = None) -> None:
        """初始化专利摘要生成节点。"""
        super().__init__(self.name, "drafting.abstract", "abstract_writer_agent", "ABSTRACT_WRITER_PROMPT", ABSTRACT_WRITER_PROMPT, [DRAFTING_CLAIMS_ARTIFACT_KEY, DRAFTING_DESCRIPTION_ARTIFACT_KEY], DRAFTING_ABSTRACT_ARTIFACT_KEY, self._build_fallback, "abstract_key", settings, workspace, abstract_runner, workflow_trace_emitter)

    def _build_fallback(self, reason: str, workspace: DraftWorkspaceTool) -> str:
        """生成摘要 fallback 正文。"""
        topic = self._topic(WorkflowState(raw_input=""))
        return f"# 摘要\n\n本申请公开了一种{topic},能够基于输入材料限定的技术特征解决相关技术问题。\n\n# 发明名称\n\n{topic}"


class DraftingGenerateSectionsNode(DraftingContentNodeBase):
    """专利文书正文分段生成节点。

    Args:
        settings: 应用配置,未传入时读取全局配置。
        workspace: 可注入的草稿 artifact 工作区工具。

    Returns:
        写入摘要、权利要求、说明书和附图说明 artifact 的节点。
    """

    name = "drafting_generate_sections"

    def __init__(self, settings: Settings | None = None, workspace: DraftWorkspaceTool | None = None) -> None:
        """初始化正文分段生成节点。"""
        super().__init__(name=self.name, settings=settings, workspace=workspace)

    def run(self, state: WorkflowState) -> NodeResult:
        """根据大纲和写作指南生成正文分段 artifact。

        Args:
            state: 当前 workflow 状态,需包含 outline 与 writing guide artifact key。

        Returns:
            成功时返回 section artifact key 列表,不返回长正文。
        """
        outline = self._read_text(str(state.drafting_context.get("outline_key") or DRAFTING_OUTLINE_ARTIFACT_KEY))
        guide = self._read_json(str(state.drafting_context.get("writing_style_guide_key") or "02_research/writing_style_guide.json"))
        if outline is None:
            return NodeResult.failed(errors=["outline_missing"])
        if guide is None:
            return NodeResult.failed(errors=["writing_style_guide_missing"])
        topic = self._topic_from_outline(outline)
        contents = {
            DRAFTING_ABSTRACT_ARTIFACT_KEY: f"# 摘要\n\n本申请公开了一种{topic},用于解决相关技术问题。",
            DRAFTING_CLAIMS_ARTIFACT_KEY: f"# 权利要求书\n\n1. 一种{topic},其特征在于,包括基于输入材料限定的核心技术特征。",
            DRAFTING_DESCRIPTION_ARTIFACT_KEY: f"# 说明书\n\n## 技术领域\n\n本申请涉及{topic}。\n\n## 背景技术\n\n现有技术仍需改进。\n\n## 发明内容\n\n本申请提供一种{topic}。\n\n## 具体实施方式\n\n以下结合实施例说明本申请技术方案。",
            DRAFTING_FIGURES_ARTIFACT_KEY: "# 附图说明\n\n附图内容以输入材料中明确记载的图号为准。",
        }
        for artifact_key, content in contents.items():
            error = self._write(artifact_key, content)
            if error:
                return NodeResult.failed(errors=[error])
        state.drafting_context["section_keys"] = list(DRAFTING_SECTION_KEYS)
        return NodeResult.success(
            output={"section_keys": list(DRAFTING_SECTION_KEYS)},
            trace_events=[{"event": "drafting_sections_generated", "data": {"artifact_keys": list(DRAFTING_SECTION_KEYS)}}],
        )

    def _topic_from_outline(self, outline: str) -> str:
        """从大纲正文中提取技术主题。"""
        lines = [line.strip() for line in outline.splitlines() if line.strip() and not line.startswith("#")]
        return lines[0].removeprefix("主题：") if lines else "技术方案"


class DraftingMergeDocumentNode(DraftingContentNodeBase):
    """专利文书终稿合并节点。

    Args:
        settings: 应用配置,未传入时读取全局配置。
        workspace: 可注入的草稿 artifact 工作区工具。

    Returns:
        按稳定顺序合并正文 artifact 的节点。
    """

    name = "drafting_merge_document"

    def __init__(
        self,
        settings: Settings | None = None,
        workspace: DraftWorkspaceTool | None = None,
        merge_runner: Any | None = None,
        workflow_trace_emitter: WorkflowTraceEmitter | None = None,
    ) -> None:
        """初始化终稿合并节点。"""
        super().__init__(name=self.name, settings=settings, workspace=workspace)
        self.workflow_trace_emitter = workflow_trace_emitter or MemoryWorkflowTraceEmitter()
        self.merge_runner = merge_runner or LangChainAgentRunner(
            node_name=self.name,
            stage="drafting.merge",
            agent_name="markdown_merger_agent",
            prompt_name="MARKDOWN_MERGER_PROMPT",
            system_prompt=MARKDOWN_MERGER_PROMPT,
            allowed_tools=["read_file", "write_file", "mkdir", "list_directory", "list_skills", "load_skill"],
            file_policy=FileToolPolicy(
                readRoots=list(DRAFTING_SECTION_KEYS),
                writeRoots=[DRAFTING_COMPLETE_PATENT_ARTIFACT_KEY, DRAFTING_REVIEW_REPORT_ARTIFACT_KEY],
            ),
            output_artifact_keys=[DRAFTING_COMPLETE_PATENT_ARTIFACT_KEY, DRAFTING_REVIEW_REPORT_ARTIFACT_KEY],
            fallback_builder=self._build_merge_fallback,
            settings=self.settings,
            workspace=self.workspace,
            workflow_trace_emitter=self.workflow_trace_emitter,
        )

    def run(self, state: WorkflowState) -> NodeResult:
        """合并摘要、权利要求、说明书和附图说明 artifact。

        Args:
            state: 当前 workflow 状态。

        Returns:
            成功时返回完整文书 artifact key。
        """
        for artifact_key in DRAFTING_SECTION_KEYS:
            if self._read_text(artifact_key) is None:
                return NodeResult.failed(errors=[f"artifact_missing:{artifact_key}"])
        failed = self._run_text_agent(
            self.merge_runner,
            DRAFTING_COMPLETE_PATENT_ARTIFACT_KEY,
            f"合并完整专利文书并生成终稿评审报告，分别写入 `{DRAFTING_COMPLETE_PATENT_ARTIFACT_KEY}` 和 `{DRAFTING_REVIEW_REPORT_ARTIFACT_KEY}`",
        )
        if failed is not None:
            return failed
        content = self._read_text(DRAFTING_COMPLETE_PATENT_ARTIFACT_KEY) or ""
        if self._read_text(DRAFTING_REVIEW_REPORT_ARTIFACT_KEY) is None:
            return NodeResult.failed(errors=[f"artifact_missing:{DRAFTING_REVIEW_REPORT_ARTIFACT_KEY}"])
        state.drafting_context["complete_patent_key"] = DRAFTING_COMPLETE_PATENT_ARTIFACT_KEY
        state.drafting_context["review_report_key"] = DRAFTING_REVIEW_REPORT_ARTIFACT_KEY
        return NodeResult.success(
            output={"complete_patent_key": DRAFTING_COMPLETE_PATENT_ARTIFACT_KEY},
            trace_events=[*self._trace_events_from(self.workflow_trace_emitter), {"event": "drafting_document_merged", "data": {"artifact_key": DRAFTING_COMPLETE_PATENT_ARTIFACT_KEY, "chars": len(content)}}],
        )

    def _build_merge_fallback(self, reason: str, workspace: DraftWorkspaceTool) -> str:
        """生成终稿合并 fallback 正文。"""
        parts = []
        for artifact_key in DRAFTING_SECTION_KEYS:
            content = self._read_text(artifact_key)
            if content is not None:
                parts.append(content)
        return "# 完整专利文书\n\n" + "\n\n".join(parts)


DRAFTING_FINALIZE_FIELDS = {
    "01_input/parsed_info.json": "input_points_md",
    "02_research/prior_art_analysis.md": "prior_art_md",
    DRAFTING_OUTLINE_ARTIFACT_KEY: "outline_md",
    DRAFTING_ABSTRACT_ARTIFACT_KEY: "abstract_md",
    DRAFTING_CLAIMS_ARTIFACT_KEY: "claims_md",
    DRAFTING_DESCRIPTION_ARTIFACT_KEY: "description_md",
    DRAFTING_FIGURES_ARTIFACT_KEY: "figures_md",
    DRAFTING_COMPLETE_PATENT_ARTIFACT_KEY: "complete_patent_md",
}


class DraftingReviewDocumentNode(DraftingContentNodeBase):
    """专利文书终稿评审节点。

    Args:
        settings: 应用配置,未传入时读取全局配置。
        workspace: 可注入的草稿 artifact 工作区工具。

    Returns:
        读取终稿和写作指南并写入结构化评审报告的节点。
    """

    name = "drafting_review_document"

    def __init__(self, settings: Settings | None = None, workspace: DraftWorkspaceTool | None = None) -> None:
        """初始化终稿评审节点。"""
        super().__init__(name=self.name, settings=settings, workspace=workspace)

    def run(self, state: WorkflowState) -> NodeResult:
        """生成结构化评审报告 artifact。

        Args:
            state: 当前 workflow 状态,需包含 complete patent 与 writing guide artifact key。

        Returns:
            成功时返回 review report artifact key。
        """
        complete_key = str(state.drafting_context.get("complete_patent_key") or DRAFTING_COMPLETE_PATENT_ARTIFACT_KEY)
        report_key = str(state.drafting_context.get("review_report_key") or DRAFTING_REVIEW_REPORT_ARTIFACT_KEY)
        if self._read_text(complete_key) is None:
            return NodeResult.failed(errors=["complete_patent_missing"])
        if self._read_text(report_key) is None:
            return NodeResult.failed(errors=["review_report_missing"])
        state.drafting_context["review_report_key"] = report_key
        return NodeResult.success(
            output={"review_report_key": report_key},
            trace_events=[{"event": "drafting_document_reviewed", "data": {"artifact_key": report_key}}],
        )


class DraftingFinalizeNode(DraftingContentNodeBase):
    """专利文书最终响应回填节点。

    Args:
        settings: 应用配置,未传入时读取全局配置。
        workspace: 可注入的草稿 artifact 工作区工具。

    Returns:
        读取最终 artifact 并回填现有 API 兼容字段的节点。
    """

    name = "drafting_finalize"

    def __init__(self, settings: Settings | None = None, workspace: DraftWorkspaceTool | None = None) -> None:
        """初始化最终响应回填节点。"""
        super().__init__(name=self.name, settings=settings, workspace=workspace)

    def run(self, state: WorkflowState) -> NodeResult:
        """读取文书生成 artifact 并回填 WorkflowState 与输出字段。

        Args:
            state: 当前 workflow 状态。

        Returns:
            成功时返回兼容旧 patent_drafting API 的字段集合。
        """
        output: dict[str, Any] = {}
        missing: list[str] = []
        for artifact_key, field_name in DRAFTING_FINALIZE_FIELDS.items():
            content = self._read_text(artifact_key)
            if content is None:
                missing.append(artifact_key)
                content = ""
            setattr(state, field_name, content)
            output[field_name] = content
        state.drafting_incomplete = bool(missing)
        output["drafting_incomplete"] = state.drafting_incomplete
        trace_data = {"missing_artifacts": missing, "drafting_incomplete": state.drafting_incomplete}
        return NodeResult.success(output=output, trace_events=[{"event": "drafting_finalized", "data": trace_data}])
