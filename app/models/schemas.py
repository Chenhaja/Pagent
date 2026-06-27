from typing import Any

from pydantic import BaseModel, Field


class WorkflowState(BaseModel):
    """工作流全局状态。

    Args:
        raw_input: 用户原始输入,必须保留用于审计和回退。
        normalized_input: 轻量归一化后的输入。
        intent: 意图识别结果。
        dialog_context: 会话上下文快照。
        invention_disclosure: 结构化技术交底。
        technical_features: 技术特征列表。
        claim_plan: 权利要求布局规划。
        claims_draft: 当前权利要求草稿。
        claim_versions: 权利要求版本链。
        claim_patches: 权利要求修改 patch 列表。
        validation_report: 校验报告。
        user_feedback: 用户反馈或修改意见。
        trace: workflow 和 node 执行轨迹。

    Returns:
        可在各 node 间传递和更新的工作流状态对象。
    """

    raw_input: str
    normalized_input: str | None = None
    intent: str | None = None
    dialog_context: dict[str, Any] = Field(default_factory=dict)
    invention_disclosure: dict[str, Any] = Field(default_factory=dict)
    technical_features: list[dict[str, Any]] = Field(default_factory=list)
    claim_plan: dict[str, Any] = Field(default_factory=dict)
    claims_draft: list[dict[str, Any]] = Field(default_factory=list)
    claim_versions: list[dict[str, Any]] = Field(default_factory=list)
    claim_patches: list[dict[str, Any]] = Field(default_factory=list)
    validation_report: dict[str, Any] | None = None
    user_feedback: str | None = None
    trace: list[dict[str, Any]] = Field(default_factory=list)

    def add_trace_event(self, event: str, data: dict[str, Any] | None = None) -> None:
        """追加一条工作流审计事件。

        Args:
            event: 稳定英文事件名,便于检索和聚合。
            data: 事件附加数据,不应包含密钥、隐私或过长原文。

        Returns:
            无返回值,会原地更新 trace。
        """
        self.trace.append({"event": event, "data": data or {}})
