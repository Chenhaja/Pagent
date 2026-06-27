from app.models.schemas import SkillContext


def test_skill_context_contains_required_fields() -> None:
    """SkillContext 应表达 skill 调用所需上下文。"""
    context = SkillContext(
        task_type="claim_generate",
        state_snapshot={"technical_features": [{"name": "节能控制"}]},
        domain_rules={"jurisdiction": "CN"},
        output_schema={"type": "ClaimSet"},
        examples=[{"input": "技术方案", "output": "权利要求"}],
    )

    assert context.task_type == "claim_generate"
    assert context.state_snapshot == {"technical_features": [{"name": "节能控制"}]}
    assert context.domain_rules == {"jurisdiction": "CN"}
    assert context.output_schema == {"type": "ClaimSet"}
    assert context.examples == [{"input": "技术方案", "output": "权利要求"}]


def test_skill_context_serializes_for_skill_call() -> None:
    """SkillContext 应可序列化为字典供 skill 调用。"""
    context = SkillContext(
        task_type="claim_revise",
        state_snapshot={"target_claim_id": "2"},
        output_schema={"type": "ClaimPatch"},
    )

    payload = context.to_payload()

    assert payload == {
        "task_type": "claim_revise",
        "state_snapshot": {"target_claim_id": "2"},
        "domain_rules": {},
        "output_schema": {"type": "ClaimPatch"},
        "examples": [],
    }


def test_skill_context_uses_independent_default_collections() -> None:
    """默认集合字段不应在不同上下文实例之间共享。"""
    first_context = SkillContext(task_type="claim_generate")
    second_context = SkillContext(task_type="claim_generate")

    first_context.examples.append({"input": "a", "output": "b"})
    first_context.domain_rules["rule"] = "value"

    assert second_context.examples == []
    assert second_context.domain_rules == {}
