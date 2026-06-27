from typing import Any

from app.models.schemas import WorkflowState
from app.nodes.intent_router import IntentRouterNode
from app.nodes.normalize_input import NormalizeInputNode
from app.nodes.translate import TranslateNode
from app.orchestrator.engine import Orchestrator
from app.tools.translation_agent import FakeTranslationAgent


class TranslateService:
    """专利翻译 workflow 服务。

    Args:
        agent: 外部翻译 agent adapter。

    Returns:
        封装翻译 node 链路的服务。
    """

    def __init__(self, agent: FakeTranslationAgent | None = None) -> None:
        self.orchestrator = Orchestrator(
            nodes={
                "normalize_input": NormalizeInputNode(),
                "intent_router": IntentRouterNode(),
                "translate": TranslateNode(agent=agent),
            }
        )
        self.workflow_def = ["normalize_input", "intent_router", "translate"]

    def translate(self, raw_input: str) -> dict[str, Any]:
        """执行专利文本翻译。

        Args:
            raw_input: 用户输入的待翻译文本。

        Returns:
            成功时返回译文、术语表和 trace;失败时返回结构化错误。
        """
        state = WorkflowState(raw_input=raw_input)
        result = self.orchestrator.run(state, self.workflow_def)
        if result.status != "success":
            return {
                "status": result.status,
                "errors": result.errors,
                "message": "翻译服务暂时不可用,请稍后重试。",
            }
        return {"status": "success", **result.output, "workflow_trace": state.trace}
