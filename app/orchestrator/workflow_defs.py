from pydantic import BaseModel, Field


class WorkflowDef(BaseModel):
    """预定义 workflow 元数据。

    Args:
        intent: workflow 对应的标准意图。
        nodes: 确定性节点顺序。
        start_node: 起始节点名称。
        max_loop_count: 最大局部回环次数。

    Returns:
        可供 orchestrator 执行的 workflow 定义。
    """

    intent: str
    nodes: list[str]
    start_node: str
    max_loop_count: int = Field(default=0, ge=0)


class WorkflowRegistry:
    """预定义 workflow 模板注册表。

    Returns:
        按 intent 查询 concrete workflow_def 的轻量注册表。
    """

    def __init__(self) -> None:
        self.workflow_defs = {
            "translation": WorkflowDef(
                intent="translation",
                nodes=["normalize_input", "translate"],
                start_node="normalize_input",
                max_loop_count=0,
            ),
            "qa": WorkflowDef(
                intent="qa",
                nodes=["normalize_input", "qa"],
                start_node="normalize_input",
                max_loop_count=1,
            ),
            "patent_drafting": WorkflowDef(
                intent="patent_drafting",
                nodes=[
                    "normalize_input",
                    "drafting_parse_input",
                    "drafting_patent_search",
                    "drafting_generate_outline",
                    "drafting_claims_writer",
                    "drafting_description_writer",
                    "drafting_diagram_generator",
                    "drafting_abstract_writer",
                    "drafting_merge_document",
                    "drafting_finalize",
                ],
                start_node="normalize_input",
                max_loop_count=0,
            ),
        }

    def get_workflow(self, intent: str) -> list[str]:
        """按 intent 返回预定义 workflow 节点序列。

        Args:
            intent: 已识别或显式 API 提供的 known intent。

        Returns:
            节点名称序列;未知 intent 返回空列表。
        """
        workflow_def = self.workflow_defs.get(intent)
        if workflow_def is None:
            return []
        return list(workflow_def.nodes)

    def get_workflow_def(self, intent: str) -> WorkflowDef:
        """按 intent 返回带元数据的 workflow 定义。

        Args:
            intent: 已识别或显式 API 提供的 known intent。

        Returns:
            workflow 元数据;未知 intent 返回空定义。
        """
        workflow_def = self.workflow_defs.get(intent)
        if workflow_def is None:
            return WorkflowDef(intent=intent, nodes=[], start_node="", max_loop_count=0)
        return workflow_def.model_copy(deep=True)
