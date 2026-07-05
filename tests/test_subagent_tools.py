from app.core.config import Settings
from app.orchestrator.tool_registry import build_default_tool_registry
from app.tools.draft_workspace import DraftWorkspaceTool
from app.tools.llm import LLMResponse
from app.tools.subagents import SUBAGENT_DEFINITIONS, build_patent_drafting_subagent_specs


SUBAGENT_NAMES = [
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


class RecordingLLM:
    """记录调用的 fake LLM。"""

    def __init__(self, content: dict | None = None) -> None:
        """初始化 fake LLM。"""
        self.content = content or {"content": "LLM 生成内容"}
        self.calls: list[dict] = []

    def generate(self, **kwargs) -> LLMResponse:
        """记录调用参数并返回固定内容。"""
        self.calls.append(kwargs)
        return LLMResponse(content=self.content)


def test_builds_nine_r12_patent_drafting_subagent_specs(tmp_path) -> None:
    """subagent-as-tool 应提供 R12 9 个专利文书子代理。"""
    settings = Settings(draft_workspace_dir=str(tmp_path))

    specs = build_patent_drafting_subagent_specs(settings)

    assert [spec.name for spec in specs] == SUBAGENT_NAMES
    assert [definition.name for definition in SUBAGENT_DEFINITIONS] == SUBAGENT_NAMES
    assert all(spec.enabled for spec in specs)
    assert all(spec.external is False for spec in specs)


def test_subagent_calls_llm_and_writes_r12_workspace_key(tmp_path) -> None:
    """子代理应调用 LLM 并写入 R12 workspace key,只返回短结果。"""
    settings = Settings(draft_workspace_dir=str(tmp_path))
    workspace = DraftWorkspaceTool(settings)
    workspace.run({"action": "write", "artifact_key": "01_input/raw_document.md", "content": "技术交底内容"})
    llm = RecordingLLM({"content": "{\"发明名称\":\"夹爪\"}"})
    tool = next(spec.runner for spec in build_patent_drafting_subagent_specs(settings, llm_client=llm) if spec.name == "input_parser")

    observation = tool.run({"source_artifact_key": "01_input/raw_document.md"})
    read = workspace.run({"action": "read", "artifact_key": "01_input/parsed_info.json"})

    assert observation.error is None
    assert observation.sufficient is True
    assert observation.evidence == [{"artifact_key": "01_input/parsed_info.json", "done": True}]
    assert read.evidence[0]["content"] == "{\"发明名称\":\"夹爪\"}"
    assert llm.calls
    assert "技术交底内容" in llm.calls[0]["prompt"]


def test_subagent_rejects_long_inline_content(tmp_path) -> None:
    """子代理不接收长正文参数,只能通过 workspace key 读取。"""
    settings = Settings(draft_workspace_dir=str(tmp_path))
    tool = build_patent_drafting_subagent_specs(settings, llm_client=RecordingLLM())[0].runner

    observation = tool.run({"content": "技术交底内容"})

    assert observation.error == "inline_content_not_allowed"


def test_subagent_tool_specs_expose_restricted_tools(tmp_path) -> None:
    """子代理 ToolSpec 应暴露角色受限工具集。"""
    specs = build_patent_drafting_subagent_specs(Settings(draft_workspace_dir=str(tmp_path)), llm_client=RecordingLLM())
    by_name = {spec.name: spec for spec in specs}

    assert "patent_search" in by_name["patent_searcher"].input_schema["x_allowed_tools"]
    assert "skill_loader" in by_name["abstract_writer"].input_schema["x_allowed_tools"]
    assert "patent_search" not in by_name["abstract_writer"].input_schema["x_allowed_tools"]


def test_description_writer_part2_merges_description(tmp_path) -> None:
    """description_writer_part2 应合并说明书第一部分与具体实施方式。"""
    settings = Settings(draft_workspace_dir=str(tmp_path))
    workspace = DraftWorkspaceTool(settings)
    workspace.run({"action": "write", "artifact_key": "04_content/description.md", "content": "# 专利说明书\n\n## 技术领域"})
    llm = RecordingLLM({"content": "## 具体实施方式\n具体内容"})
    tool = next(
        spec.runner
        for spec in build_patent_drafting_subagent_specs(settings, llm_client=llm)
        if spec.name == "description_writer_part2"
    )

    observation = tool.run({"source_artifact_key": "04_content/description.md"})
    read = workspace.run({"action": "read", "artifact_key": "04_content/description.md"})

    assert observation.evidence == [{"artifact_key": "04_content/description.md", "done": True}]
    assert "## 技术领域" in read.evidence[0]["content"]
    assert "## 具体实施方式" in read.evidence[0]["content"]


def test_markdown_merger_merges_final_patent_and_report(tmp_path) -> None:
    """markdown_merger 应按顺序合并终稿并写入评审报告。"""
    settings = Settings(draft_workspace_dir=str(tmp_path))
    workspace = DraftWorkspaceTool(settings)
    for key, content in [
        ("04_content/abstract.md", "摘要"),
        ("04_content/claims.md", "权利要求"),
        ("04_content/description.md", "说明书"),
        ("04_content/figures.md", "附图"),
        ("03_outline/patent_outline.md", "大纲"),
    ]:
        workspace.run({"action": "write", "artifact_key": key, "content": content})
    llm = RecordingLLM({"content": "评审报告"})
    tool = next(spec.runner for spec in build_patent_drafting_subagent_specs(settings, llm_client=llm) if spec.name == "markdown_merger")

    observation = tool.run({"source_artifact_key": "03_outline/patent_outline.md"})
    final_doc = workspace.run({"action": "read", "artifact_key": "05_final/complete_patent.md"})
    report = workspace.run({"action": "read", "artifact_key": "05_final/summary_report.md"})

    assert observation.evidence == [{"artifact_key": "05_final/complete_patent.md", "done": True}]
    assert final_doc.evidence[0]["content"] == "# 完整专利文书\n\n摘要\n\n权利要求\n\n说明书\n\n附图"
    assert report.evidence[0]["content"] == "评审报告"


def test_default_registry_registers_nine_subagent_tools(tmp_path) -> None:
    """默认 ToolRegistry 应注册 R12 9 个 subagent-as-tool。"""
    registry = build_default_tool_registry(Settings(draft_workspace_dir=str(tmp_path)))

    assert [name for name in SUBAGENT_NAMES if registry.get(name) is not None] == SUBAGENT_NAMES
