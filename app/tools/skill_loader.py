from pathlib import Path

from app.core.config import Settings, get_settings
from app.orchestrator.react_loop import ToolObservation


ALLOWED_SKILL_DOCS = {
    "patent_guide": {"filename": "patent_guide.md", "description": "专利申请文件撰写指南"},
    "mermaid_flowchart": {"filename": "mermaid_flowchart.md", "description": "Mermaid flowchart 语法指南"},
    "mermaid_sequence_diagram": {"filename": "mermaid_sequence_diagram.md", "description": "Mermaid sequence diagram 语法指南"},
}


class SkillLoaderTool:
    """按白名单列出和读取本地 Markdown skill 文档的工具。"""

    def __init__(self, settings: Settings | None = None, skills_dir: Path | str | None = None) -> None:
        """初始化 skill loader。

        Args:
            settings: 应用配置,未传入时读取全局配置。
            skills_dir: 可选技能文档目录,测试可注入;优先级高于 settings.skill_dir。

        Returns:
            无返回值。
        """
        self.settings = settings or get_settings()
        configured_dir = skills_dir if skills_dir is not None else self.settings.skill_dir
        self.skills_dir = Path(configured_dir).resolve()

    def run(self, tool_input: dict) -> ToolObservation:
        """列出或读取白名单 Markdown skill 文档。

        Args:
            tool_input: 包含 action=list 或 action=load/name 的输入。

        Returns:
            list 返回 name/description 列表;load 返回指定 skill 文档正文。
        """
        action = str(tool_input.get("action") or "").strip()
        if action == "list":
            return self._list_skills()
        if action == "load":
            return self._load_skill(str(tool_input.get("name") or "").strip())
        return ToolObservation(tool_name="skill_loader", error="invalid_action")

    def _list_skills(self) -> ToolObservation:
        """列出可加载 skill 的名称和描述。"""
        skills = [{"name": name, "description": str(spec["description"])} for name, spec in ALLOWED_SKILL_DOCS.items()]
        return ToolObservation(tool_name="skill_loader", evidence=[{"skills": skills}], sufficient=True)

    def _load_skill(self, name: str) -> ToolObservation:
        """按精确名称读取 skill 正文。"""
        spec = ALLOWED_SKILL_DOCS.get(name)
        if spec is None:
            return ToolObservation(tool_name="skill_loader", error="skill_unavailable")
        path = (self.skills_dir / str(spec["filename"])).resolve()
        if self.skills_dir not in path.parents or path.suffix != ".md" or not path.exists():
            return ToolObservation(tool_name="skill_loader", error="skill_unavailable")
        content = path.read_text(encoding="utf-8")
        return ToolObservation(
            tool_name="skill_loader",
            evidence=[{"name": name, "content": content, "chars": len(content), "path": str(path)}],
            sufficient=bool(content),
        )
