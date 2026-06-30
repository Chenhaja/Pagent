from datetime import date
from typing import Any

from app.orchestrator.react_loop import ToolObservation


class OfficialFeeTool:
    """默认不触网的官费 stub 工具。"""

    def run(self, tool_input: dict[str, Any]) -> ToolObservation:
        """返回带适用范围提示的官费 stub observation。

        Args:
            tool_input: 包含 query 的工具输入。

        Returns:
            官费工具 observation;输入无效时返回可恢复错误。
        """
        query = str(tool_input.get("query") or "").strip()
        if not query:
            return ToolObservation(tool_name="official_fee", error="invalid_input", external=True)
        evidence = [
            {
                "content": f"official fee stub: {query}",
                "provenance": {
                    "source": "stub://official_fee",
                    "source_type": "official_fee",
                    "retrieved_at": date.today().isoformat(),
                    "applicable_scope": "unknown_stub",
                    "requires_official_check": True,
                },
                "confidence": 0.0,
            }
        ]
        return ToolObservation(tool_name="official_fee", evidence=evidence, sufficient=True, external=True)
