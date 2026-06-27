from typing import Any

from app.models.schemas import SkillContext


class ReportWritingSkill:
    """报告撰写 skill 占位实现。

    Returns:
        复用技术特征、权利要求草稿和校验报告的报告 skill。
    """

    required_inputs = ["technical_features", "claims_draft", "validation_report"]

    def run(self, context: SkillContext) -> dict[str, Any]:
        """生成报告结构化摘要。

        Args:
            context: Skill 调用上下文,从 state_snapshot 读取报告所需输入。

        Returns:
            包含技术特征、权利要求草稿和校验报告的摘要载荷。

        Raises:
            ValueError: 当缺少关键输入时抛出。
        """
        missing_inputs = [
            field_name
            for field_name in self.required_inputs
            if not context.state_snapshot.get(field_name)
        ]
        if missing_inputs:
            raise ValueError(f"missing_report_input:{','.join(missing_inputs)}")
        return {
            "technical_features": context.state_snapshot["technical_features"],
            "claims_draft": context.state_snapshot["claims_draft"],
            "validation_report": context.state_snapshot["validation_report"],
        }
