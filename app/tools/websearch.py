from datetime import date
from typing import Any

from app.orchestrator.react_loop import ToolObservation


class WebSearchTool:
    """默认不触网的 websearch stub 工具。"""

    def run(self, tool_input: dict[str, Any]) -> ToolObservation:
        """返回带来源元数据的 websearch stub observation。

        Args:
            tool_input: 包含 query 的工具输入。

        Returns:
            websearch 工具 observation;输入无效时返回可恢复错误。
        """
        query = str(tool_input.get("query") or "").strip()
        if not query:
            return ToolObservation(tool_name="websearch", error="invalid_input", external=True)
        evidence = [
            {
                "content": f"websearch stub: {query}",
                "provenance": {
                    "source": "stub://websearch",
                    "source_type": "web",
                    "title": "websearch stub",
                    "source_url": "stub://websearch",
                    "retrieved_at": date.today().isoformat(),
                    "requires_official_check": True,
                },
                "confidence": 0.0,
            }
        ]
        return ToolObservation(tool_name="websearch", evidence=evidence, sufficient=True, external=True)
