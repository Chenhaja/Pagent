from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class Claim(BaseModel):
    """单条权利要求。

    Args:
        number: 权利要求编号,从 1 开始。
        claim_type: 权利要求类型,如 independent 或 dependent。
        text: 权利要求正文。
        references: 引用的权利要求编号列表。
        terms: 关键术语列表。
        source_trace: 生成或修改来源 trace。

    Returns:
        单条权利要求模型。
    """

    number: int = Field(gt=0)
    claim_type: Literal["independent", "dependent"]
    text: str
    references: list[int] = Field(default_factory=list)
    terms: list[str] = Field(default_factory=list)
    source_trace: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        """校验权利要求正文非空。

        Args:
            value: 权利要求正文。

        Returns:
            去除首尾空白后的正文。

        Raises:
            ValueError: 当正文为空时抛出。
        """
        stripped = value.strip()
        if not stripped:
            raise ValueError("claim text must not be empty")
        return stripped


class ClaimSet(BaseModel):
    """权利要求集合。

    Args:
        version: 权利要求版本号。
        claims: 权利要求列表。

    Returns:
        带版本号的权利要求集合。
    """

    version: str
    claims: list[Claim] = Field(default_factory=list)


class ClaimPatch(BaseModel):
    """权利要求修改 patch。

    Args:
        target_claim_number: 目标权利要求编号。
        operation: 修改操作类型。
        before_text: 修改前文本。
        after_text: 修改后文本。
        impact_scope: 受影响的权利要求编号列表。
        risk_notes: 修改风险说明。

    Returns:
        单次权利要求修改 patch。
    """

    target_claim_number: int = Field(gt=0)
    operation: str
    before_text: str
    after_text: str
    impact_scope: list[int] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)


class ValidationReport(BaseModel):
    """权利要求校验报告。

    Args:
        passed: 是否通过基础校验。
        reference_errors: 引用关系错误列表。
        terminology_errors: 术语一致性错误列表。
        missing_required_features: 缺失必要技术特征列表。
        clarity_warnings: 清楚性风险提示。
        risk_notes: 综合风险提示。

    Returns:
        权利要求基础校验报告。
    """

    passed: bool = True
    reference_errors: list[str] = Field(default_factory=list)
    terminology_errors: list[str] = Field(default_factory=list)
    missing_required_features: list[str] = Field(default_factory=list)
    clarity_warnings: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)


class NodeResult(BaseModel):
    """节点执行结果。

    Args:
        status: 节点执行状态。
        output: 节点结构化输出。
        errors: 错误列表。
        next_node: 可选的下一节点名称。
        requires_user_input: 是否需要用户补充输入。
        trace_events: 节点产生的审计事件。

    Returns:
        可供 orchestrator 消费的节点执行结果。
    """

    status: Literal["success", "failed", "requires_user_input"]
    output: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    next_node: str | None = None
    requires_user_input: bool = False
    trace_events: list[dict[str, Any]] = Field(default_factory=list)

    @classmethod
    def success(
        cls,
        output: dict[str, Any] | None = None,
        next_node: str | None = None,
        trace_events: list[dict[str, Any]] | None = None,
    ) -> "NodeResult":
        """创建成功节点结果。

        Args:
            output: 节点结构化输出。
            next_node: 可选的下一节点名称。
            trace_events: 节点产生的审计事件。

        Returns:
            状态为 success 的节点结果。
        """
        return cls(
            status="success",
            output=output or {},
            next_node=next_node,
            trace_events=trace_events or [],
        )

    @classmethod
    def failed(cls, errors: list[str]) -> "NodeResult":
        """创建失败节点结果。

        Args:
            errors: 错误列表。

        Returns:
            状态为 failed 的节点结果。
        """
        return cls(status="failed", errors=errors)

    @classmethod
    def need_user_input(
        cls,
        output: dict[str, Any] | None = None,
        errors: list[str] | None = None,
    ) -> "NodeResult":
        """创建需要用户补充输入的节点结果。

        Args:
            output: 面向用户的问题或补充信息说明。
            errors: 当前缺失或无法继续的原因。

        Returns:
            状态为 requires_user_input 的节点结果。
        """
        return cls(
            status="requires_user_input",
            output=output or {},
            errors=errors or [],
            requires_user_input=True,
        )


class SkillContext(BaseModel):
    """Skill 调用上下文。

    Args:
        task_type: skill 任务类型,如 claim_generate 或 claim_revise。
        state_snapshot: 调用 skill 所需的状态快照。
        domain_rules: 领域规则和约束。
        output_schema: 期望输出 schema 描述。
        examples: few-shot 示例列表。

    Returns:
        可传入 skill 的结构化上下文。
    """

    task_type: str
    state_snapshot: dict[str, Any] = Field(default_factory=dict)
    domain_rules: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    examples: list[dict[str, Any]] = Field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        """转换为 skill 调用载荷。

        Returns:
            包含任务类型、状态快照、领域规则、输出 schema 和示例的字典。
        """
        return {
            "task_type": self.task_type,
            "state_snapshot": self.state_snapshot,
            "domain_rules": self.domain_rules,
            "output_schema": self.output_schema,
            "examples": self.examples,
        }


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
