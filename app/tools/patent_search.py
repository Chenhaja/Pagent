from app.core.config import Settings, get_settings
from app.orchestrator.react_loop import ToolObservation


class PatentSearchTool:
    """专利检索占位工具。"""

    def __init__(self, settings: Settings | None = None) -> None:
        """初始化专利检索工具。

        Args:
            settings: 应用配置,未传入时读取全局配置。

        Returns:
            无返回值。
        """
        self.settings = settings or get_settings()

    def run(self, tool_input: dict) -> ToolObservation:
        """执行受门控的专利检索。

        Args:
            tool_input: 包含 query 的输入。

        Returns:
            默认离线或 fake evidence 的 observation。
        """
        query = str(tool_input.get("query") or "").strip()
        if not query:
            return ToolObservation(tool_name="patent_search", error="invalid_input", external=True)
        if not self.settings.allow_network:
            return ToolObservation(tool_name="patent_search", error="network_disabled", external=True)
        return ToolObservation(
            tool_name="patent_search",
            evidence=[
                {
                    "content": f"patent_search skipped: {query}",
                    "provenance": {"source": "patent_search://fake", "requires_official_check": True},
                }
            ],
            sufficient=False,
            external=True,
        )
