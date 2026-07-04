from pathlib import Path

from app.orchestrator.react_loop import ToolObservation


_ALLOWED_SKILLS = {
    "patent_qa": "patent_qa.py",
    "patent_translation": "patent_translation.py",
    "report_writing": "report_writing.py",
}


class SkillLoaderTool:
    """按白名单读取本地 skill 内容的工具。"""

    def __init__(self, skills_dir: Path | None = None) -> None:
        """初始化 skill loader。

        Args:
            skills_dir: 可选 skill 目录,测试可注入;默认使用 app/skills。

        Returns:
            无返回值。
        """
        self.skills_dir = (skills_dir or Path(__file__).resolve().parents[1] / "skills").resolve()

    def run(self, tool_input: dict) -> ToolObservation:
        """读取白名单 skill 文件。

        Args:
            tool_input: 包含 skill_name 的输入。

        Returns:
            包含 skill 内容的 observation;未知 skill 返回安全错误。
        """
        skill_name = str(tool_input.get("skill_name") or "").strip()
        filename = _ALLOWED_SKILLS.get(skill_name)
        if filename is None:
            return ToolObservation(tool_name="skill_loader", error="skill_unavailable")
        path = (self.skills_dir / filename).resolve()
        if self.skills_dir not in path.parents or not path.exists():
            return ToolObservation(tool_name="skill_loader", error="skill_unavailable")
        content = path.read_text(encoding="utf-8")
        return ToolObservation(
            tool_name="skill_loader",
            evidence=[{"skill_name": skill_name, "content": content, "chars": len(content)}],
            sufficient=bool(content),
        )
