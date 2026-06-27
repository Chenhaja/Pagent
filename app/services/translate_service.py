from typing import Any

from app.models.schemas import WorkflowState
from app.nodes.normalize_input import NormalizeInputNode
from app.nodes.translate import TranslateNode
from app.orchestrator.engine import Orchestrator
from app.orchestrator.workflow_defs import WorkflowRegistry
from app.tools.translation_agent import FakeTranslationAgent, TranslationResult


class TranslateService:
    """专利翻译 workflow 服务。

    Args:
        agent: 外部翻译 agent adapter。

    Returns:
        封装翻译 node 链路的服务。
    """

    def __init__(self, agent: FakeTranslationAgent | None = None) -> None:
        default_agent = FakeTranslationAgent(result=TranslationResult(translated_text="A control method."))
        self.orchestrator = Orchestrator(
            nodes={
                "normalize_input": NormalizeInputNode(),
                "translate": TranslateNode(agent=agent or default_agent),
            }
        )
        self.workflow_def = WorkflowRegistry().get_workflow("translation")

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
            message = "请补充待翻译文本。" if "empty_raw_input" in result.errors else "翻译服务暂时不可用,请稍后重试。"
            return {
                "status": result.status,
                "errors": result.errors,
                "message": message,
            }
        return {"status": "success", **result.output, "workflow_trace": state.trace}
