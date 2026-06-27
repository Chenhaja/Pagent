from app.models.schemas import NodeResult, WorkflowState
from app.orchestrator.node_base import Node
from app.tools.translation_agent import FakeTranslationAgent


class TranslateNode(Node):
    """专利文本翻译节点。

    Args:
        agent: 外部翻译 agent adapter。

    Returns:
        调用外部翻译 adapter 的节点。
    """

    name = "translate"

    def __init__(self, agent: FakeTranslationAgent | None = None) -> None:
        super().__init__(name=self.name)
        self.agent = agent or FakeTranslationAgent()

    def run(self, state: WorkflowState) -> NodeResult:
        """调用外部翻译 adapter。

        Args:
            state: 当前工作流状态。

        Returns:
            翻译成功结果或 adapter 失败结果。
        """
        try:
            translation = self.agent.translate(
                text=state.normalized_input or state.raw_input,
                source_language="zh",
                target_language="en",
            )
        except RuntimeError as error:
            return NodeResult.failed(errors=[f"translation_failed:{error}"])

        if not translation.translated_text:
            return NodeResult.failed(errors=["translation_empty_response"])

        output = translation.model_dump()
        return NodeResult.success(
            output=output,
            trace_events=[{"event": "translate_completed", "data": {"trace": translation.trace}}],
        )
