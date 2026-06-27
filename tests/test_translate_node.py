from app.models.schemas import WorkflowState
from app.nodes.translate import TranslateNode
from app.tools.translation_agent import FakeTranslationAgent, TranslationResult


def test_translate_node_writes_translation_result() -> None:
    """翻译 node 应调用外部翻译 adapter 并返回译文、术语表和 trace。"""
    agent = FakeTranslationAgent(
        result=TranslationResult(
            translated_text="A control method.",
            terms={"控制方法": "control method"},
            trace=[{"event": "external_translation_completed"}],
        )
    )
    state = WorkflowState(raw_input="", normalized_input="一种控制方法")
    node = TranslateNode(agent=agent)

    result = node.run(state)

    assert result.status == "success"
    assert result.output == {
        "translated_text": "A control method.",
        "terms": {"控制方法": "control method"},
        "trace": [{"event": "external_translation_completed"}],
    }


def test_translate_node_returns_failed_on_timeout() -> None:
    """翻译 node 应在 adapter 超时时返回失败。"""
    agent = FakeTranslationAgent(error="adapter_timeout")
    node = TranslateNode(agent=agent)

    result = node.run(WorkflowState(raw_input="", normalized_input="一种控制方法"))

    assert result.status == "failed"
    assert result.errors == ["translation_failed:adapter_timeout"]


def test_translate_node_returns_failed_on_empty_response() -> None:
    """翻译 node 应拒绝空译文响应。"""
    agent = FakeTranslationAgent(result=TranslationResult(translated_text=""))
    node = TranslateNode(agent=agent)

    result = node.run(WorkflowState(raw_input="", normalized_input="一种控制方法"))

    assert result.status == "failed"
    assert result.errors == ["translation_empty_response"]
