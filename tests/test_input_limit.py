from app.core.config import Settings, get_settings
from app.models.schemas import NodeResult, WorkflowState
from app.services.agent_dispatch_service import AgentDispatchService


class FailingNormalizeNode:
    """测试用 normalize 节点,用于证明超限时不会进入下游。"""

    def run(self, state: WorkflowState) -> NodeResult:
        """如果被调用则让测试失败。"""
        raise AssertionError("raw_input 超限时不应调用 normalize")


def test_input_limit_allows_exact_limit(monkeypatch) -> None:
    """raw_input 去除首尾空白后等于上限时应放行。"""
    monkeypatch.setattr("app.services.agent_dispatch_service.get_settings", lambda: Settings(input_max_chars=4))
    service = AgentDispatchService()

    result = service.dispatch("  翻译文本  ")

    assert result["status"] == "success"
    assert result["intent"] == "translation"


def test_input_limit_rejects_before_downstream_nodes(monkeypatch) -> None:
    """raw_input 超限时应在 normalize / rewrite / router 前拒绝。"""
    monkeypatch.setattr("app.services.agent_dispatch_service.get_settings", lambda: Settings(input_max_chars=3))
    service = AgentDispatchService()
    service.normalize_node = FailingNormalizeNode()

    result = service.dispatch("生成权利")

    assert result["status"] == "requires_user_input"
    assert result["errors"] == ["raw_input_too_long"]
    assert "文件上传" in result["message"]
    assert result["trace"] == [{"event": "input_length_rejected", "data": {"input_len": 4, "limit": 3}}]
    assert "生成权利" not in str(result["trace"])


def test_input_limit_reads_environment(monkeypatch) -> None:
    """raw_input 字符上限应支持通过环境变量覆盖。"""
    monkeypatch.setenv("PAGENT_INPUT_MAX_CHARS", "123")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.input_max_chars == 123
    get_settings.cache_clear()
