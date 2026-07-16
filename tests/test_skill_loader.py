from app.core.config import Settings
from app.orchestrator.tool_registry import build_default_tool_registry
from app.tools.skill_loader import SkillLoaderTool


def test_skill_loader_lists_skill_names_and_descriptions(tmp_path) -> None:
    """skill_loader list 只应返回技能名称和描述。"""
    skill_dir = tmp_path / "skills_docs"
    skill_dir.mkdir()
    (skill_dir / "patent_guide.md").write_text("# 专利写作技能", encoding="utf-8")
    tool = SkillLoaderTool(Settings(skill_dir=str(skill_dir)))

    observation = tool.run({"action": "list"})

    assert observation.error is None
    assert observation.evidence[0]["skills"] == [
        {"name": "patent_guide", "description": "专利申请文件撰写指南"},
        {"name": "mermaid_flowchart", "description": "Mermaid flowchart 语法指南"},
        {"name": "mermaid_sequence_diagram", "description": "Mermaid sequence diagram 语法指南"},
    ]
    assert "content" not in observation.evidence[0]



def test_skill_loader_loads_exact_skill_body(tmp_path) -> None:
    """skill_loader load 应按精确名称读取正文。"""
    skill_dir = tmp_path / "skills_docs"
    skill_dir.mkdir()
    (skill_dir / "patent_guide.md").write_text("# 专利写作技能", encoding="utf-8")
    tool = SkillLoaderTool(Settings(skill_dir=str(skill_dir)))

    observation = tool.run({"action": "load", "name": "patent_guide"})

    assert observation.error is None
    assert observation.evidence[0]["name"] == "patent_guide"
    assert observation.evidence[0]["content"] == "# 专利写作技能"
    assert observation.evidence[0]["path"].endswith("patent_guide.md")


def test_skill_loader_rejects_unknown_and_path_traversal(tmp_path) -> None:
    """skill_loader 应拒绝未知技能和路径穿越。"""
    skill_dir = tmp_path / "skills_docs"
    skill_dir.mkdir()
    (skill_dir / "patent_guide.md").write_text("# 专利写作技能", encoding="utf-8")
    tool = SkillLoaderTool(Settings(skill_dir=str(skill_dir)))

    unknown = tool.run({"action": "load", "name": "patent_qa"})
    escaped = tool.run({"action": "load", "name": "../patent_guide"})
    legacy = tool.run({"action": "load", "name": "patent_drafting"})

    assert unknown.error == "skill_unavailable"
    assert escaped.error == "skill_unavailable"
    assert legacy.error == "skill_unavailable"


def test_skill_loader_does_not_return_python_source(tmp_path) -> None:
    """skill_loader 不应读取或返回 Python 可执行 skill 源码。"""
    skill_dir = tmp_path / "skills_docs"
    skill_dir.mkdir()
    (skill_dir / "patent_drafting.py").write_text("SECRET = 'python-source'", encoding="utf-8")
    tool = SkillLoaderTool(Settings(skill_dir=str(skill_dir)))

    observation = tool.run({"action": "load", "name": "patent_guide"})

    assert observation.error == "skill_unavailable"
    assert observation.evidence == []


def test_default_tool_registry_describes_markdown_skill_loader(tmp_path) -> None:
    """默认 ToolRegistry 应将 skill_loader 描述为 Markdown 技能文档加载器。"""
    registry = build_default_tool_registry(Settings(skill_dir=str(tmp_path)))
    spec = registry.tool_specs()["skill_loader"]

    assert "Markdown" in spec.description
    assert spec.input_schema["properties"]["action"]["enum"] == ["list", "load"]
    assert spec.input_schema["properties"]["name"]["enum"] == ["patent_guide", "mermaid_flowchart", "mermaid_sequence_diagram"]
