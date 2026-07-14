import json
from typing import Any

from app.core.config import Settings, get_settings
from app.models.schemas import NodeResult, WorkflowState
from app.orchestrator.node_base import Node
from app.tools.draft_workspace import DraftWorkspaceTool


DRAFTING_OUTLINE_ARTIFACT_KEY = "03_outline/patent_outline.md"
DRAFTING_ABSTRACT_ARTIFACT_KEY = "04_content/abstract.md"
DRAFTING_CLAIMS_ARTIFACT_KEY = "04_content/claims.md"
DRAFTING_DESCRIPTION_ARTIFACT_KEY = "04_content/description.md"
DRAFTING_FIGURES_ARTIFACT_KEY = "04_content/figures.md"
DRAFTING_COMPLETE_PATENT_ARTIFACT_KEY = "05_final/complete_patent.md"
DRAFTING_REVIEW_REPORT_ARTIFACT_KEY = "05_final/review_report.json"
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


class DraftingGenerateOutlineNode(DraftingContentNodeBase):
    """专利文书大纲生成节点。

    Args:
        settings: 应用配置,未传入时读取全局配置。
        workspace: 可注入的草稿 artifact 工作区工具。

    Returns:
        读取前置研究 artifact 并写入大纲 artifact 的节点。
    """

    name = "drafting_generate_outline"

    def __init__(self, settings: Settings | None = None, workspace: DraftWorkspaceTool | None = None) -> None:
        """初始化大纲生成节点。"""
        super().__init__(name=self.name, settings=settings, workspace=workspace)

    def run(self, state: WorkflowState) -> NodeResult:
        """生成专利文书大纲 artifact。

        Args:
            state: 当前 workflow 状态,需包含 parsed、prior art、drawing 与 writing guide artifact key。

        Returns:
            成功时返回 outline artifact key。
        """
        parsed = self._read_json(str(state.drafting_context.get("parsed_info_key") or "01_input/parsed_info.json"))
        prior_art = self._read_json(str(state.drafting_context.get("prior_art_analysis_key") or "02_research/prior_art_analysis.json"))
        drawing = self._read_json(str(state.drafting_context.get("drawing_analysis_key") or "02_research/drawing_analysis.json"))
        guide = self._read_json(str(state.drafting_context.get("writing_style_guide_key") or "02_research/writing_style_guide.json"))
        if parsed is None:
            return NodeResult.failed(errors=["parsed_info_missing"])
        if prior_art is None:
            return NodeResult.failed(errors=["prior_art_analysis_missing"])
        if drawing is None:
            return NodeResult.failed(errors=["drawing_analysis_missing"])
        if guide is None:
            return NodeResult.failed(errors=["writing_style_guide_missing"])
        topic = str(parsed.get("technical_topic") or "技术方案")
        focus_features = list(prior_art.get("distinguishing_features") or guide.get("claim_style", {}).get("focus_features") or [])
        figures = list(drawing.get("figures") or [])
        content = self._outline_content(topic, focus_features, figures)
        error = self._write(DRAFTING_OUTLINE_ARTIFACT_KEY, content)
        if error:
            return NodeResult.failed(errors=[error])
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

    def __init__(self, settings: Settings | None = None, workspace: DraftWorkspaceTool | None = None) -> None:
        """初始化终稿合并节点。"""
        super().__init__(name=self.name, settings=settings, workspace=workspace)

    def run(self, state: WorkflowState) -> NodeResult:
        """合并摘要、权利要求、说明书和附图说明 artifact。

        Args:
            state: 当前 workflow 状态。

        Returns:
            成功时返回完整文书 artifact key。
        """
        parts: list[str] = []
        for artifact_key in DRAFTING_SECTION_KEYS:
            content = self._read_text(artifact_key)
            if content is None:
                return NodeResult.failed(errors=[f"artifact_missing:{artifact_key}"])
            parts.append(content)
        content = "# 完整专利文书\n\n" + "\n\n".join(parts)
        error = self._write(DRAFTING_COMPLETE_PATENT_ARTIFACT_KEY, content)
        if error:
            return NodeResult.failed(errors=[error])
        state.drafting_context["complete_patent_key"] = DRAFTING_COMPLETE_PATENT_ARTIFACT_KEY
        return NodeResult.success(
            output={"complete_patent_key": DRAFTING_COMPLETE_PATENT_ARTIFACT_KEY},
            trace_events=[{"event": "drafting_document_merged", "data": {"artifact_key": DRAFTING_COMPLETE_PATENT_ARTIFACT_KEY, "chars": len(content)}}],
        )


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
        guide_key = str(state.drafting_context.get("writing_style_guide_key") or "02_research/writing_style_guide.json")
        complete = self._read_text(complete_key)
        guide = self._read_json(guide_key)
        if complete is None:
            return NodeResult.failed(errors=["complete_patent_missing"])
        if guide is None:
            return NodeResult.failed(errors=["writing_style_guide_missing"])
        required_sections = ["# 摘要", "# 权利要求书", "# 说明书"]
        missing_sections = [section for section in required_sections if section not in complete]
        payload = {
            "passed": not missing_sections,
            "checked_artifacts": [complete_key, guide_key],
            "issues": [f"缺少章节: {section}" for section in missing_sections],
            "uncertain_points": list(guide.get("uncertain_points") or []),
            "confidence": "medium" if not missing_sections else "low",
        }
        error = self._write(DRAFTING_REVIEW_REPORT_ARTIFACT_KEY, json.dumps(payload, ensure_ascii=False))
        if error:
            return NodeResult.failed(errors=[error])
        state.drafting_context["review_report_key"] = DRAFTING_REVIEW_REPORT_ARTIFACT_KEY
        return NodeResult.success(
            output={"review_report_key": DRAFTING_REVIEW_REPORT_ARTIFACT_KEY},
            trace_events=[{"event": "drafting_document_reviewed", "data": {"artifact_key": DRAFTING_REVIEW_REPORT_ARTIFACT_KEY, "passed": payload["passed"]}}],
        )
