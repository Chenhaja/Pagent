from app.models.schemas import NodeResult


def test_node_result_success_shape() -> None:
    """成功结果应包含输出和 trace 事件。"""
    result = NodeResult.success(
        output={"normalized_input": "一种节能控制方法"},
        next_node="intent_router",
        trace_events=[{"event": "normalize_input_completed"}],
    )

    assert result.status == "success"
    assert result.output == {"normalized_input": "一种节能控制方法"}
    assert result.errors == []
    assert result.next_node == "intent_router"
    assert result.requires_user_input is False
    assert result.trace_events == [{"event": "normalize_input_completed"}]


def test_node_result_failed_shape() -> None:
    """失败结果应包含错误列表且不要求用户输入。"""
    result = NodeResult.failed(errors=["字段缺失"])

    assert result.status == "failed"
    assert result.output == {}
    assert result.errors == ["字段缺失"]
    assert result.next_node is None
    assert result.requires_user_input is False
    assert result.trace_events == []


def test_node_result_requires_user_input_shape() -> None:
    """需要用户补充信息时应显式标记 requires_user_input。"""
    result = NodeResult.need_user_input(
        output={"question": "请补充技术效果"},
        errors=["技术效果缺失"],
    )

    assert result.status == "requires_user_input"
    assert result.output == {"question": "请补充技术效果"}
    assert result.errors == ["技术效果缺失"]
    assert result.next_node is None
    assert result.requires_user_input is True
    assert result.trace_events == []


def test_node_result_uses_independent_default_collections() -> None:
    """默认集合字段不应在不同结果实例之间共享。"""
    first_result = NodeResult.success()
    second_result = NodeResult.success()

    first_result.errors.append("first_error")
    first_result.trace_events.append({"event": "first_event"})

    assert second_result.errors == []
    assert second_result.trace_events == []
