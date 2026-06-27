from typing import Any

from app.models.schemas import ClaimSet, SkillContext


class ClaimWritingSkill:
    """权利要求撰写 skill 占位实现。

    Args:
        fake_outputs: 按任务类型组织的固定输出,用于测试生成和修改链路。

    Returns:
        可复用的权利要求生成 / 修改 skill。
    """

    def __init__(self, fake_outputs: dict[str, dict[str, Any]] | None = None) -> None:
        self.fake_outputs = fake_outputs or {}

    def run(self, context: SkillContext) -> ClaimSet:
        """根据任务类型返回符合权利要求 schema 的固定输出。

        Args:
            context: Skill 调用上下文,通过 task_type 区分生成或修改。

        Returns:
            解析后的权利要求集合。

        Raises:
            pydantic.ValidationError: 当固定输出不符合 ClaimSet schema 时抛出。
        """
        output = self.fake_outputs.get(context.task_type, {"version": "v1", "claims": []})
        return ClaimSet.model_validate(output)
