class WorkflowRegistry:
    """预定义 workflow 模板注册表。

    Returns:
        按 intent 查询 concrete workflow_def 的轻量注册表。
    """

    def __init__(self) -> None:
        self.workflow_defs = {
            "claim_generation": ["normalize_input", "feature_extract", "claim_plan", "claim_generate", "claim_check"],
            "translation": ["normalize_input", "translate"],
            "claim_revision": ["claim_revise", "claim_check"],
        }

    def get_workflow(self, intent: str) -> list[str]:
        """按 intent 返回预定义 workflow。

        Args:
            intent: 已识别或显式 API 提供的 known intent。

        Returns:
            节点名称序列;未知 intent 返回空列表。
        """
        return list(self.workflow_defs.get(intent, []))
