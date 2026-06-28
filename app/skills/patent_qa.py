import json

from app.models.schemas import PatentQAResult, SkillContext
from app.prompts.patent_qa import (
    PATENT_QA_FEW_SHOT_EXAMPLES,
    PATENT_QA_OUTPUT_SCHEMA,
    PATENT_QA_SYSTEM_PROMPT,
    PATENT_QA_TASK_PROMPT,
    build_patent_qa_user_prompt,
)
from app.tools.llm import LLMClient, LLMMessage, build_llm_client


class PatentQASkill:
    """专利问答 skill。

    Args:
        llm_client: 可注入的 LLM 抽象客户端,默认使用安全 LLM factory。

    Returns:
        构造分层 prompt 并输出结构化专利问答结果的 skill。
    """

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or build_llm_client()
        self.last_prompt_layers: dict[str, str] = {}
        self.last_safety_policy: dict[str, bool] = {}

    def run(self, context: SkillContext) -> PatentQAResult:
        """生成结构化专利问答结果。

        Args:
            context: Skill 调用上下文,包含用户问题和可用案件状态。

        Returns:
            符合 PatentQAResult schema 的问答结果。

        Raises:
            ValueError: 当 LLM 返回结构化错误时抛出。
            pydantic.ValidationError: 当输出不符合 PatentQAResult schema 时抛出。
        """
        prompt_layers = self._build_prompt_layers(context)
        safety_policy = {"separate_instruction_and_data": True}
        self.last_prompt_layers = prompt_layers
        self.last_safety_policy = safety_policy
        context.prompt_layers.update(prompt_layers)
        context.safety_policy.update(safety_policy)
        context.examples.extend(PATENT_QA_FEW_SHOT_EXAMPLES)
        context.output_schema.update(PATENT_QA_OUTPUT_SCHEMA)

        response = self.llm_client.generate(
            messages=[
                LLMMessage(role="system", content=prompt_layers["system"]),
                LLMMessage(role="user", content=prompt_layers["task"]),
                LLMMessage(role="user", content=prompt_layers["user_data"]),
            ],
            output_schema=PATENT_QA_OUTPUT_SCHEMA,
            trace_context={"task_type": context.task_type, "node_name": "qa"},
        )
        if response.errors:
            raise ValueError(response.errors[0]["code"])
        return PatentQAResult.model_validate(response.content)

    def _build_prompt_layers(self, context: SkillContext) -> dict[str, str]:
        """构造 QA 分层 prompt。

        Args:
            context: Skill 调用上下文。

        Returns:
            包含 system、task、user_data、output_contract 的 prompt 层。
        """
        question = str(context.state_snapshot.get("question") or "")
        retrieval_results = context.state_snapshot.get("retrieval_results") or []
        claims_draft = context.state_snapshot.get("claims_draft") or []
        return {
            "system": PATENT_QA_SYSTEM_PROMPT,
            "task": PATENT_QA_TASK_PROMPT,
            "user_data": build_patent_qa_user_prompt(question, retrieval_results, claims_draft),
            "output_contract": json.dumps(PATENT_QA_OUTPUT_SCHEMA, ensure_ascii=False),
        }
