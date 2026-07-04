from dataclasses import dataclass
from typing import Any

from app.core.config import Settings, get_settings
from app.orchestrator.react_loop import ReActTool, ToolObservation
from app.orchestrator.react_policy import ToolCard
from app.tools.draft_workspace import DraftWorkspaceTool
from app.tools.legal_status import LegalStatusTool
from app.tools.official_fee import OfficialFeeTool
from app.tools.patent_search import PatentSearchTool
from app.tools.retrieval import Retriever, RetrievalResult, build_retriever
from app.tools.skill_loader import ALLOWED_SKILL_DOCS, SkillLoaderTool
from app.tools.websearch import WebSearchTool


QUERY_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "top_k": {"type": "integer"},
        "as_of": {"type": ["string", "null"]},
        "fetch_k": {"type": ["integer", "null"]},
        "step_index": {"type": "integer"},
    },
    "required": ["query"],
    "additionalProperties": True,
}

PATENT_SEARCH_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "top_k": {"type": "integer"},
        "country": {"type": "string"},
        "status": {"type": "string"},
        "step_index": {"type": "integer"},
    },
    "required": ["query"],
    "additionalProperties": True,
}


@dataclass
class ToolSpec:
    """Agentic 工具注册元数据。

    Args:
        name: 工具名称。
        runner: 工具执行器。
        description: 工具用途描述,供 policy 决策使用。
        input_schema: 工具输入 JSON schema。
        external: 是否为外部工具。
        enabled: 当前配置下是否启用。
    """

    name: str
    runner: ReActTool
    description: str = ""
    input_schema: dict[str, Any] | None = None
    external: bool = False
    enabled: bool = True


class ToolRegistry:
    """Agentic 工具白名单注册表。"""

    def __init__(self, settings: Settings | None = None) -> None:
        """初始化工具注册表。

        Args:
            settings: 应用配置,未传入时读取全局配置。
        """
        self.settings = settings or get_settings()
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        """注册一个可被主循环调用的工具。

        Args:
            spec: 工具注册元数据。
        """
        self._tools[spec.name] = spec

    def get(self, name: str) -> ReActTool | None:
        """按工具名返回可用工具。

        Args:
            name: 工具名称。

        Returns:
            工具对象;未知或禁用时返回 None。
        """
        spec = self._tools.get(name)
        if spec is None or not spec.enabled:
            return None
        return spec.runner

    def available_tools(self) -> dict[str, ReActTool]:
        """返回当前启用工具映射。

        Returns:
            工具名到工具对象的映射。
        """
        return {name: spec.runner for name, spec in self._tools.items() if spec.enabled}

    def tool_cards(self, allowed_tools: list[str] | None = None) -> list[ToolCard]:
        """返回可供 policy 决策的工具卡片。

        Args:
            allowed_tools: 当前场景允许的工具名;未传入时返回全部启用工具。

        Returns:
            已启用且被允许的工具卡片列表。
        """
        allowed = set(allowed_tools) if allowed_tools is not None else None
        cards = []
        for name, spec in self._tools.items():
            if not spec.enabled or (allowed is not None and name not in allowed):
                continue
            cards.append(ToolCard(name=name, description=spec.description, input_schema=spec.input_schema or {}))
        return cards

    def tool_specs(self) -> dict[str, ToolSpec]:
        """返回工具元数据映射。"""
        return dict(self._tools)

    def run(self, name: str, tool_input: dict[str, Any]) -> ToolObservation:
        """执行已注册工具,未知或禁用时安全失败。

        Args:
            name: 工具名称。
            tool_input: 工具输入。

        Returns:
            工具 observation。
        """
        spec = self._tools.get(name)
        if spec is None:
            return ToolObservation(tool_name=name, error="tool_unavailable")
        if not spec.enabled:
            return ToolObservation(tool_name=name, error="tool_unavailable", external=spec.external)
        try:
            return spec.runner.run(tool_input)
        except Exception:
            return ToolObservation(tool_name=name, error="tool_unavailable", external=spec.external)


class KBRetrievalTool:
    """知识库检索 ReAct 工具。"""

    def __init__(self, retriever: Retriever, settings: Settings) -> None:
        """初始化 KB 检索工具。

        Args:
            retriever: 底层检索器。
            settings: 应用配置。
        """
        self.retriever = retriever
        self.settings = settings

    def run(self, tool_input: dict[str, Any]) -> ToolObservation:
        """执行 KB 检索。

        Args:
            tool_input: 包含 query、top_k、as_of、fetch_k 的结构化输入。

        Returns:
            归一化后的检索 observation。
        """
        query = str(tool_input.get("query") or "").strip()
        if not query:
            return ToolObservation(tool_name="kb_retrieval", error="invalid_input")
        top_k = int(tool_input.get("top_k") or self.settings.retrieval_top_k)
        as_of = tool_input.get("as_of")
        fetch_k = tool_input.get("fetch_k")
        try:
            results = self.retriever.search(query, top_k=top_k, as_of=as_of, fetch_k=fetch_k)
        except Exception:
            return ToolObservation(tool_name="kb_retrieval", error="tool_unavailable")
        evidence = [self._result_to_evidence(result) for result in results[:top_k]]
        top_score = max((self._result_score(result) for result in results), default=0.0)
        return ToolObservation(
            tool_name="kb_retrieval",
            evidence=evidence,
            sufficient=bool(evidence),
            top_score=top_score,
        )

    def _result_to_evidence(self, result: RetrievalResult) -> dict[str, Any]:
        """将检索结果转换为通用 evidence。"""
        provenance: dict[str, Any] = {
            "source": result.provenance.get("source", "local://unknown"),
            "document_id": result.provenance.get("document_id", "unknown"),
        }
        for key in ("locator", "doc_type"):
            if result.provenance.get(key):
                provenance[key] = result.provenance[key]
        for key in ("law_name", "version", "effective_date", "expiry_date", "status", "source_url", "retrieved_at"):
            value = getattr(result, key)
            if value:
                provenance[key] = value
        return {
            "content": result.content,
            "provenance": provenance,
            "score": result.score,
            "similarity": result.similarity,
        }

    def _result_score(self, result: RetrievalResult) -> float:
        """读取检索分数,优先 similarity。"""
        if result.similarity:
            return float(result.similarity)
        if result.score:
            return float(result.score)
        return 0.0


def build_default_tool_registry(settings: Settings | None = None, retriever: Retriever | None = None) -> ToolRegistry:
    """构建默认 agentic 工具注册表。

    Args:
        settings: 应用配置。
        retriever: 可注入 KB 检索器,测试中用于避免真实外部依赖。

    Returns:
        默认工具注册表。
    """
    current_settings = settings or get_settings()
    registry = ToolRegistry(settings=current_settings)
    registry.register(
        ToolSpec(
            name="kb_retrieval",
            runner=KBRetrievalTool(retriever or build_retriever(current_settings), current_settings),
            description="检索本地专利知识库、法规和既有材料,用于获取可引用 evidence。",
            input_schema=QUERY_INPUT_SCHEMA,
            external=False,
            enabled=True,
        )
    )
    registry.register(
        ToolSpec(
            name="draft_workspace",
            runner=DraftWorkspaceTool(current_settings),
            description="维护专利文书项目工作区 artifact,支持 read/write/list/merge,长正文只通过 workspace key 流转。",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["write", "read", "list", "merge"]},
                    "artifact_key": {"type": "string"},
                    "content": {"type": "string"},
                    "prefix": {"type": "string"},
                    "source_artifact_keys": {"type": "array", "items": {"type": "string"}},
                    "output_artifact_key": {"type": "string"},
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            external=False,
            enabled=True,
        )
    )
    registry.register(
        ToolSpec(
            name="skill_loader",
            runner=SkillLoaderTool(current_settings),
            description="按白名单读取本地 Markdown 专利技能文档,不允许任意路径或 Python 源码。",
            input_schema={
                "type": "object",
                "properties": {"skill_name": {"type": "string", "enum": list(ALLOWED_SKILL_DOCS)}},
                "required": ["skill_name"],
                "additionalProperties": False,
            },
            external=False,
            enabled=True,
        )
    )
    registry.register(
        ToolSpec(
            name="patent_search",
            runner=PatentSearchTool(current_settings),
            description="受联网配置和 SerpAPI Key 门控的专利检索工具,支持 query/top_k/country/status 并默认安全降级。",
            input_schema=PATENT_SEARCH_INPUT_SCHEMA,
            external=True,
            enabled=True,
        )
    )
    from app.tools.subagents import build_patent_drafting_subagent_specs

    for subagent_spec in build_patent_drafting_subagent_specs(current_settings):
        registry.register(subagent_spec)
    external_enabled = getattr(current_settings, "agentic_external_tools_enabled", False)
    registry.register(
        ToolSpec(
            name="websearch",
            runner=WebSearchTool(),
            description="查询公开网络信息或最新资料,返回带来源和 retrieved_at 的外部 evidence。",
            input_schema=QUERY_INPUT_SCHEMA,
            external=True,
            enabled=external_enabled and getattr(current_settings, "websearch_enabled", False),
        )
    )
    registry.register(
        ToolSpec(
            name="legal_status",
            runner=LegalStatusTool(),
            description="查询专利法律状态,返回需官方核对的状态 evidence。",
            input_schema=QUERY_INPUT_SCHEMA,
            external=True,
            enabled=external_enabled and getattr(current_settings, "legal_status_enabled", False),
        )
    )
    registry.register(
        ToolSpec(
            name="official_fee",
            runner=OfficialFeeTool(),
            description="查询专利官费或费用规则,返回带适用范围和核对提示的 evidence。",
            input_schema=QUERY_INPUT_SCHEMA,
            external=True,
            enabled=external_enabled and getattr(current_settings, "official_fee_enabled", False),
        )
    )
    return registry
