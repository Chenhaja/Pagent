from pathlib import Path

from app.core.config import Settings, get_settings
from app.orchestrator.react_loop import ToolObservation


ALLOWED_SKILL_DOCS = {
    "patent_drafting": "patent_drafting.md",
    "mermaid": "mermaid.md",
}


class SkillLoaderTool:
    """按白名单读取本地 Markdown skill 文档的工具。"""

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
        """读取白名单 Markdown skill 文档。

        Args:
            tool_input: 包含 skill_name 的输入。

        Returns:
            包含 skill 文档内容的 observation;未知 skill 返回安全错误。
        """
        skill_name = str(tool_input.get("skill_name") or "").strip()
        filename = ALLOWED_SKILL_DOCS.get(skill_name)
        if filename is None:
            return ToolObservation(tool_name="skill_loader", error="skill_unavailable")
        path = (self.skills_dir / filename).resolve()
        if self.skills_dir not in path.parents or path.suffix != ".md" or not path.exists():
            return ToolObservation(tool_name="skill_loader", error="skill_unavailable")
        content = path.read_text(encoding="utf-8")
        return ToolObservation(
            tool_name="skill_loader",
            evidence=[{"skill_name": skill_name, "content": content, "chars": len(content), "path": str(path)}],
            sufficient=bool(content),
        )
