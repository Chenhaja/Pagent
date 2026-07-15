import json
from typing import Any

from app.core.config import Settings, get_settings
from app.models.schemas import NodeResult, WorkflowState
from app.orchestrator.node_base import Node
from app.orchestrator.tool_registry import ToolRegistry, build_default_tool_registry
from app.tools.draft_workspace import DraftWorkspaceTool
from app.tools.subagents.input_parser_agent import LangChainInputParserAgent
from app.tracing.sinks import MemoryWorkflowTraceEmitter, WorkflowTraceEmitter


DRAFTING_SOURCE_ARTIFACT_KEY = "01_input/raw_document.md"
DRAFTING_PARSED_INFO_ARTIFACT_KEY = "01_input/parsed_info.json"
DRAFTING_PATENT_SEARCH_ARTIFACT_KEY = "02_research/patent_search_results.json"
DRAFTING_PRIOR_ART_ANALYSIS_ARTIFACT_KEY = "02_research/prior_art_analysis.json"


class DraftingParseInputNode(Node):
    """文书生成输入解析节点。

    Args:
        settings: 应用配置,未传入时读取全局配置。
        workspace: 可注入的草稿 artifact 工作区工具。
        tool_registry: 显式传入时沿用旧 input_parser 子代理调用路径。
        input_parser_runner: 可注入输入解析 runner,默认使用 LangChain create_agent 试点 runner。
        workflow_trace_emitter: 可选 workflow trace 事件发送端。

    Returns:
        写入 source 与 parsed_info artifact 的顶层 workflow 节点。
    """

    name = "drafting_parse_input"

    def __init__(
        self,
        settings: Settings | None = None,
        workspace: DraftWorkspaceTool | None = None,
        tool_registry: ToolRegistry | Any | None = None,
        input_parser_runner: Any | None = None,
        workflow_trace_emitter: WorkflowTraceEmitter | None = None,
    ) -> None:
        """初始化输入解析节点。"""
        super().__init__(name=self.name)
        self.settings = settings or get_settings()
        self.workspace = workspace or DraftWorkspaceTool(self.settings)
        self.tool_registry = tool_registry
        self.workflow_trace_emitter = workflow_trace_emitter or MemoryWorkflowTraceEmitter()
        self.input_parser_runner = input_parser_runner or (
            None
            if tool_registry is not None
            else LangChainInputParserAgent(settings=self.settings, workspace=self.workspace, workflow_trace_emitter=self.workflow_trace_emitter)
        )

    def run(self, state: WorkflowState) -> NodeResult:
        """写入原始输入 artifact 并委托 input_parser 生成 parsed_info。

        Args:
            state: 当前 workflow 状态,包含用户输入和附件解析文本。

        Returns:
            成功时返回 artifact key 短结果;失败时返回可解释错误。
        """
        trace_events: list[dict[str, Any]] = []
        source_content = self._build_source_content(state)
        written = self.workspace.run(
            {"action": "write", "artifact_key": DRAFTING_SOURCE_ARTIFACT_KEY, "content": source_content}
        )
        if written.error:
            return NodeResult.failed(errors=[written.error])
        source_chars = self._chars(written)
        state.drafting_context["input_key"] = DRAFTING_SOURCE_ARTIFACT_KEY
        trace_events.append(
            self._trace_event("drafting_source_written", artifact_key=DRAFTING_SOURCE_ARTIFACT_KEY, chars=source_chars)
        )

        parsed = self._run_input_parser({"source_artifact_key": DRAFTING_SOURCE_ARTIFACT_KEY})
        if parsed.error:
            return NodeResult.failed(errors=[parsed.error])
        parsed_key = self._artifact_key_from_observation(parsed) or DRAFTING_PARSED_INFO_ARTIFACT_KEY
        if not self._artifact_json_object_exists(parsed_key):
            return NodeResult.failed(errors=["parsed_info_missing"])
        state.drafting_context["parsed_info_key"] = parsed_key
        trace_events.extend(self._workflow_trace_events())
        trace_events.append(self._trace_event("drafting_input_parsed", artifact_key=parsed_key))
        return NodeResult.success(
            output={"input_key": DRAFTING_SOURCE_ARTIFACT_KEY, "parsed_info_key": parsed_key},
            trace_events=trace_events,
        )

    def _build_source_content(self, state: WorkflowState) -> str:
        """拼接用户输入和附件正文作为 source artifact 数据。"""
        parts = [state.normalized_input or state.raw_input]
        for document in state.documents:
            text = str(document.get("text") or "").strip()
            if text:
                parts.append(text)
        return "\n\n".join(part for part in parts if part.strip())

    def _run_input_parser(self, tool_input: dict[str, Any]) -> Any:
        """按注入优先级执行 input_parser runner 或旧 tool_registry。"""
        if self.input_parser_runner is not None:
            return self.input_parser_runner.run(tool_input)
        registry = self.tool_registry or build_default_tool_registry(self.settings)
        return registry.run("input_parser", tool_input)

    def _artifact_json_object_exists(self, artifact_key: str) -> bool:
        """检查 artifact 已写入且内容是 JSON object。"""
        observation = self.workspace.run({"action": "read", "artifact_key": artifact_key})
        if observation.error or not getattr(observation, "evidence", None):
            return False
        try:
            payload = json.loads(str(observation.evidence[0].get("content") or ""))
        except json.JSONDecodeError:
            return False
        return isinstance(payload, dict)

    def _artifact_key_from_observation(self, observation: Any) -> str | None:
        """从工具 observation 中提取 artifact key。"""
        if not getattr(observation, "evidence", None):
            return None
        return str(observation.evidence[0].get("artifact_key") or "") or None

    def _chars(self, observation: Any) -> int:
        """从工具 observation 中提取字符数。"""
        if not getattr(observation, "evidence", None):
            return 0
        return int(observation.evidence[0].get("chars") or 0)

    def _workflow_trace_events(self) -> list[dict[str, Any]]:
        """读取可进入 NodeResult 的 workflow trace 事件。"""
        return list(getattr(self.workflow_trace_emitter, "trace_events", []) or [])

    def _trace_event(self, event: str, **data: Any) -> dict[str, Any]:
        """构造不包含正文内容的 trace 事件。"""
        safe = {key: value for key, value in data.items() if value is not None}
        return {"event": event, "data": safe}


class DraftingPatentSearchNode(Node):
    """文书生成专利检索节点。

    Args:
        settings: 应用配置,未传入时读取全局配置。
        workspace: 可注入的草稿 artifact 工作区工具。
        tool_registry: 可注入工具注册表,用于调用 patent_search 工具。

    Returns:
        写入专利检索结果 artifact 的顶层 workflow 节点。
    """

    name = "drafting_patent_search"

    def __init__(
        self,
        settings: Settings | None = None,
        workspace: DraftWorkspaceTool | None = None,
        tool_registry: ToolRegistry | Any | None = None,
    ) -> None:
        """初始化专利检索节点。"""
        super().__init__(name=self.name)
        self.settings = settings or get_settings()
        self.workspace = workspace or DraftWorkspaceTool(self.settings)
        self.tool_registry = tool_registry or build_default_tool_registry(self.settings)

    def run(self, state: WorkflowState) -> NodeResult:
        """读取 parsed info 并写入专利检索结果 artifact。

        Args:
            state: 当前 workflow 状态,需包含 parsed info artifact key。

        Returns:
            成功时返回检索结果 artifact key;检索不可用时写入 skipped 结果并降级成功。
        """
        parsed_key = str(state.drafting_context.get("parsed_info_key") or DRAFTING_PARSED_INFO_ARTIFACT_KEY)
        parsed = self._read_json(parsed_key)
        if parsed is None:
            return NodeResult.failed(errors=["parsed_info_missing"])
        query = self._query_from_parsed(parsed)
        observation = self.tool_registry.run("patent_search", {"query": query})
        error = getattr(observation, "error", None)
        evidence = list(getattr(observation, "evidence", []) or []) if not error else []
        payload = {
            "queries": [query] if query else [],
            "results": evidence,
            "sufficient": bool(getattr(observation, "sufficient", bool(evidence))) and not error,
            "skipped": bool(error),
            "reason": str(error or ""),
        }
        written = self.workspace.run(
            {
                "action": "write",
                "artifact_key": DRAFTING_PATENT_SEARCH_ARTIFACT_KEY,
                "content": json.dumps(payload, ensure_ascii=False),
            }
        )
        if written.error:
            return NodeResult.failed(errors=[written.error])
        state.drafting_context["patent_search_key"] = DRAFTING_PATENT_SEARCH_ARTIFACT_KEY
        return NodeResult.success(
            output={"patent_search_key": DRAFTING_PATENT_SEARCH_ARTIFACT_KEY, "skipped": bool(error)},
            trace_events=[
                {
                    "event": "drafting_patent_search_completed",
                    "data": {"artifact_key": DRAFTING_PATENT_SEARCH_ARTIFACT_KEY, "result_count": len(evidence), "skipped": bool(error)},
                }
            ],
        )

    def _read_json(self, artifact_key: str) -> dict[str, Any] | None:
        """读取 JSON artifact,失败时返回 None。"""
        observation = self.workspace.run({"action": "read", "artifact_key": artifact_key})
        if observation.error or not getattr(observation, "evidence", None):
            return None
        return json.loads(str(observation.evidence[0].get("content") or "{}"))

    def _query_from_parsed(self, parsed: dict[str, Any]) -> str:
        """从 parsed info 中提取检索 query。"""
        return str(parsed.get("technical_topic") or parsed.get("title") or "").strip()


class DraftingPriorArtAnalysisNode(Node):
    """文书生成现有技术分析节点。

    Args:
        settings: 应用配置,未传入时读取全局配置。
        workspace: 可注入的草稿 artifact 工作区工具。

    Returns:
        写入结构化现有技术分析 artifact 的顶层 workflow 节点。
    """

    name = "drafting_prior_art_analysis"

    def __init__(self, settings: Settings | None = None, workspace: DraftWorkspaceTool | None = None) -> None:
        """初始化现有技术分析节点。"""
        super().__init__(name=self.name)
        self.settings = settings or get_settings()
        self.workspace = workspace or DraftWorkspaceTool(self.settings)

    def run(self, state: WorkflowState) -> NodeResult:
        """读取检索结果并写入结构化现有技术分析 artifact。

        Args:
            state: 当前 workflow 状态,需包含 parsed info 与 patent search artifact key。

        Returns:
            成功时返回现有技术分析 artifact key;检索不足时显式标注不确定点。
        """
        parsed_key = str(state.drafting_context.get("parsed_info_key") or DRAFTING_PARSED_INFO_ARTIFACT_KEY)
        search_key = str(state.drafting_context.get("patent_search_key") or DRAFTING_PATENT_SEARCH_ARTIFACT_KEY)
        parsed = self._read_json(parsed_key)
        search_results = self._read_json(search_key)
        if parsed is None:
            return NodeResult.failed(errors=["parsed_info_missing"])
        if search_results is None:
            return NodeResult.failed(errors=["patent_search_results_missing"])
        payload = self._build_analysis(parsed, search_results)
        written = self.workspace.run(
            {
                "action": "write",
                "artifact_key": DRAFTING_PRIOR_ART_ANALYSIS_ARTIFACT_KEY,
                "content": json.dumps(payload, ensure_ascii=False),
            }
        )
        if written.error:
            return NodeResult.failed(errors=[written.error])
        state.drafting_context["prior_art_analysis_key"] = DRAFTING_PRIOR_ART_ANALYSIS_ARTIFACT_KEY
        return NodeResult.success(
            output={"prior_art_analysis_key": DRAFTING_PRIOR_ART_ANALYSIS_ARTIFACT_KEY},
            trace_events=[
                {
                    "event": "drafting_prior_art_analysis_completed",
                    "data": {"artifact_key": DRAFTING_PRIOR_ART_ANALYSIS_ARTIFACT_KEY, "confidence": payload["confidence"]},
                }
            ],
        )

    def _read_json(self, artifact_key: str) -> dict[str, Any] | None:
        """读取 JSON artifact,失败时返回 None。"""
        observation = self.workspace.run({"action": "read", "artifact_key": artifact_key})
        if observation.error or not getattr(observation, "evidence", None):
            return None
        return json.loads(str(observation.evidence[0].get("content") or "{}"))

    def _build_analysis(self, parsed: dict[str, Any], search_results: dict[str, Any]) -> dict[str, Any]:
        """根据检索结果构造不臆造来源的现有技术分析。"""
        results = list(search_results.get("results") or [])
        sufficient = bool(search_results.get("sufficient")) and bool(results)
        if not sufficient:
            reason = str(search_results.get("reason") or "结果不足")
            return {
                "technical_topic": str(parsed.get("technical_topic") or ""),
                "closest_prior_art": [],
                "distinguishing_features": [],
                "technical_effects": [],
                "novelty_risks": [],
                "inventiveness_risks": [],
                "recommended_claim_focus": [],
                "uncertain_points": [f"专利检索未获得足够结果: {reason}"],
                "confidence": "low",
            }
        closest = [self._prior_art_item(item) for item in results]
        return {
            "technical_topic": str(parsed.get("technical_topic") or ""),
            "closest_prior_art": closest,
            "distinguishing_features": ["需结合交底书技术特征与检索结果逐项比对确认区别特征"],
            "technical_effects": ["需基于区别特征补充对应技术效果"],
            "novelty_risks": ["检索结果中存在相近主题,需重点核对独立权利要求的新颖性"],
            "inventiveness_risks": ["需避免将现有技术已有特征作为创造性贡献"],
            "recommended_claim_focus": ["围绕检索结果未直接公开的结构关系、控制步骤或协同效果撰写"],
            "uncertain_points": [],
            "confidence": "medium",
        }

    def _prior_art_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """提取检索结果中已有的现有技术字段。"""
        return {
            "title": str(item.get("title") or ""),
            "publication_number": str(item.get("publication_number") or ""),
            "abstract": str(item.get("abstract") or ""),
            "url": str(item.get("url") or ""),
            "country": str(item.get("country") or ""),
            "status": str(item.get("status") or ""),
            "provenance": item.get("provenance") or {},
        }
