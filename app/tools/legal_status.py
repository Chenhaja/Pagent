from datetime import date
from typing import Any

from app.orchestrator.react_loop import ToolObservation


class LegalStatusTool:
    """默认不触网的法律状态 stub 工具。"""

    def run(self, tool_input: dict[str, Any]) -> ToolObservation:
        """返回带核对提示的法律状态 stub observation。

        Args:
            tool_input: 包含 query 的工具输入。

        Returns:
            法律状态工具 observation;输入无效时返回可恢复错误。
        """
        query = str(tool_input.get("query") or "").strip()
        if not query:
            return ToolObservation(tool_name="legal_status", error="invalid_input", external=True)
        evidence = [
            {
                "content": f"legal status stub: {query}",
                "provenance": {
                    "source": "stub://legal_status",
                    "source_type": "legal_status",
                    "retrieved_at": date.today().isoformat(),
                    "legal_status": "unknown_stub",
                    "requires_official_check": True,
                },
                "confidence": 0.0,
            }
        ]
        return ToolObservation(tool_name="legal_status", evidence=evidence, sufficient=True, external=True)
