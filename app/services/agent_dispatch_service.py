from typing import Any

from app.core.config import get_settings
from app.memory.session_store import SessionMemoryStore, build_session_store
from app.models.schemas import WorkflowState
from app.nodes.intent_router import IntentRouterNode
from app.nodes.normalize_input import NormalizeInputNode
from app.nodes.qa import QANode
from app.nodes.query_rewrite import QueryRewriteNode
from app.services.attachment_service import AttachmentService, AttachmentServiceError
from app.orchestrator.engine import Orchestrator
from app.orchestrator.workflow_defs import WorkflowDef, WorkflowRegistry
from app.services.translate_service import TranslateService


class AgentDispatchService:
    """统一 Agent 入口 dispatch 服务。

    Returns:
        先执行 normalize 和 intent_router,再按预定义 workflow 分派到具体业务服务的入口服务。
    """

    def __init__(self, session_store: SessionMemoryStore | None = None) -> None:
        self.normalize_node = NormalizeInputNode()
        self.query_rewrite_node = QueryRewriteNode()
        self.intent_router_node = IntentRouterNode()
        self.workflow_registry = WorkflowRegistry()
        self.session_store = session_store or build_session_store(get_settings())

    def dispatch(
        self,
        raw_input: str,
        claims_draft: list[dict[str, Any]] | None = None,
        session_id: str | None = None,
        attachment_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """根据用户输入识别意图并分派到预定义 workflow。

        Args:
            raw_input: 用户原始输入。
            claims_draft: 修改权利要求时传入的当前权利要求草稿。
            session_id: 可选会话标识,用于读取和写入会话记忆。
            attachment_ids: 可选已上传附件 ID 列表。

        Returns:
            具体 workflow 的结构化结果,或需要用户补充输入的错误结果。
        """
        settings = get_settings()
        input_len = len(raw_input.strip())
        if input_len > settings.input_max_chars:
            state = WorkflowState(raw_input=raw_input, claims_draft=claims_draft or [])
            state.add_trace_event(event="input_length_rejected", data={"input_len": input_len, "limit": settings.input_max_chars})
            return {
                "status": "requires_user_input",
                "errors": ["raw_input_too_long"],
                "message": "输入内容过长,请将技术交底书等长文以文件上传,文字框仅填写简短指令。",
                "trace": state.trace,
            }
        state = WorkflowState(raw_input=raw_input, claims_draft=claims_draft or [])
        attachment_error = self._inject_attachments(state, attachment_ids or [], settings)
        if attachment_error is not None:
            return attachment_error
        self._inject_session_context(state, session_id)
        normalize_result = self.normalize_node.run(state)
        if normalize_result.status != "success":
            return self._finalize_result(
                state,
                session_id,
                {"status": normalize_result.status, "errors": normalize_result.errors, "message": "请补充要办理的专利任务类型。"},
            )
        for trace_event in normalize_result.trace_events:
            state.add_trace_event(event=str(trace_event.get("event", "node_event")), data=trace_event.get("data", {}))

        rewrite_result = self.query_rewrite_node.run(state)
        for trace_event in rewrite_result.trace_events:
            state.add_trace_event(event=str(trace_event.get("event", "node_event")), data=trace_event.get("data", {}))
        if rewrite_result.status != "success":
            return self._finalize_result(
                state,
                session_id,
                {"status": rewrite_result.status, "errors": rewrite_result.errors, "message": "请补充要办理的专利任务类型。"},
            )

        route_result = self.intent_router_node.run(state)
        for trace_event in route_result.trace_events:
            state.add_trace_event(event=str(trace_event.get("event", "node_event")), data=trace_event.get("data", {}))
        if route_result.status != "success":
            message = route_result.output.get("message") or "请补充要办理的专利任务类型。"
            return self._finalize_result(
                state,
                session_id,
                {"status": route_result.status, "errors": route_result.errors, "message": message, **route_result.output},
            )

        workflow_def = self.workflow_registry.get_workflow_def(state.intent or "")
        remaining_nodes = self._remaining_nodes_after(workflow_def, route_result.next_node)
        if state.intent == "translation":
            result = TranslateService().translate(
                state.normalized_input or state.raw_input,
                state=state,
                workflow_def=remaining_nodes,
            )
            return self._finalize_result(state, session_id, {"intent": state.intent, "workflow": "translation", **result})
        if state.intent == "qa":
            result = self._run_qa(state, remaining_nodes)
            return self._finalize_result(state, session_id, {"intent": state.intent, "workflow": "qa", **result})

        return self._finalize_result(
            state,
            session_id,
            {"status": "requires_user_input", "errors": ["unknown_intent"], "message": "请补充要办理的专利任务类型。"},
        )

    def _inject_attachments(self, state: WorkflowState, attachment_ids: list[str], settings: Any) -> dict[str, Any] | None:
        """加载附件并写入 workflow documents。

        Args:
            state: 当前 workflow 状态。
            attachment_ids: 用户请求中引用的附件 ID 列表。
            settings: 当前运行配置。

        Returns:
            成功时返回 None;失败时返回可直接响应的错误结果。
        """
        if not attachment_ids:
            return None
        service = AttachmentService(settings=settings)
        try:
            service.validate_count(len(attachment_ids))
            state.documents = [service.load_document(attachment_id) for attachment_id in attachment_ids]
        except AttachmentServiceError as exc:
            state.add_trace_event(event="attachment_rejected", data={"reason": exc.code, "count": len(attachment_ids)})
            return {"status": "requires_user_input", "errors": [exc.code], "message": exc.message, "trace": state.trace}
        total_chars = sum(len(str(document.get("text", ""))) for document in state.documents)
        state.add_trace_event(event="attachment_injected", data={"doc_count": len(state.documents), "total_chars": total_chars})
        return None

    def _inject_session_context(self, state: WorkflowState, session_id: str | None) -> None:
        """在 query_rewrite 前注入会话上下文。

        Args:
            state: 当前 workflow 状态。
            session_id: 可选会话标识。

        Returns:
            无返回值;失败时只写降级 trace。
        """
        if not session_id:
            state.add_trace_event(event="session_memory_skipped", data={"reason": "no_session"})
            return
        try:
            context = self.session_store.build_context(session_id)
        except Exception as exc:
            state.add_trace_event(event="session_memory_unavailable", data={"reason": exc.__class__.__name__})
            return
        history = context.get("history") or []
        state.dialog_context["history"] = history
        state.dialog_context["session_summary"] = context.get("session_summary")
        state.add_trace_event(
            event="session_memory_loaded",
            data={"history_count": len(history), "has_summary": bool(context.get("session_summary"))},
        )

    def _finalize_result(self, state: WorkflowState, session_id: str | None, result: dict[str, Any]) -> dict[str, Any]:
        """请求结束后写入会话 turn 并触发摘要。

        Args:
            state: 当前 workflow 状态。
            session_id: 可选会话标识。
            result: 即将返回给调用方的结果。

        Returns:
            带最新 trace 的服务结果。
        """
        if not session_id:
            return result
        turn_count = 0
        try:
            self.session_store.append_turn(session_id, "user", state.raw_input)
            turn_count += 1
            assistant_text = self._extract_assistant_text(result)
            if assistant_text:
                self.session_store.append_turn(session_id, "assistant", assistant_text)
                turn_count += 1
            state.add_trace_event(event="session_memory_appended", data={"turn_count": turn_count})
            if hasattr(self.session_store, "summarize_if_needed"):
                summary_result = self.session_store.summarize_if_needed(session_id)
                if summary_result.success:
                    state.add_trace_event(
                        event="memory_summary_completed",
                        data={
                            "covered_turn_index": summary_result.covered_turn_index,
                            "history_window": getattr(self.session_store, "history_window", None),
                        },
                    )
                elif summary_result.reason not in {"no_summary_needed", "summarizer_unavailable"}:
                    state.add_trace_event(event="memory_summary_failed_fallback", data={"reason": summary_result.reason})
        except Exception as exc:
            state.add_trace_event(event="session_memory_unavailable", data={"reason": exc.__class__.__name__})
        if "trace" in result:
            result["trace"] = state.trace
        return result

    def _extract_assistant_text(self, result: dict[str, Any]) -> str:
        """从服务结果中提取可落库的 assistant 文本。

        Args:
            result: 服务层结构化结果。

        Returns:
            可保存的简短 assistant 文本;无可用内容时返回空字符串。
        """
        if result.get("message"):
            return str(result["message"])
        if result.get("claims_draft"):
            return "\n".join(str(claim.get("text", "")) for claim in result["claims_draft"] if isinstance(claim, dict)).strip()
        if result.get("translated_text"):
            return str(result["translated_text"])
        if result.get("claim") and isinstance(result["claim"], dict):
            return str(result["claim"].get("text", ""))
        if result.get("answer"):
            return str(result["answer"])
        if result.get("qa_result"):
            qa_result = result.get("qa_result")
            if isinstance(qa_result, dict):
                return str(qa_result.get("answer", ""))
        return ""

    def _run_qa(self, state: WorkflowState, workflow_def: list[str]) -> dict[str, Any]:
        """执行 QA workflow 并转换为服务响应。

        Args:
            state: 已完成 normalize 和 intent_router 的 workflow 状态。
            workflow_def: 从 QA 节点开始的节点序列。

        Returns:
            QA 成功输出或结构化失败结果。
        """
        result = Orchestrator(nodes={"qa": QANode()}).run(state, workflow_def)
        if result.status != "success":
            return {"status": result.status, "errors": result.errors, "message": "问答服务暂时不可用,请稍后重试。"}
        return {"status": "success", **result.output, "trace": state.trace}

    def _remaining_nodes_after(self, workflow_def: WorkflowDef, next_node: str | None) -> list[str]:
        """根据 intent_router 的下一节点裁剪待执行节点序列。

        Args:
            workflow_def: 已识别 intent 对应的 workflow 定义。
            next_node: intent_router 返回的业务起始节点。

        Returns:
            从业务起始节点开始的节点序列;未命中时返回完整节点序列。
        """
        if next_node in workflow_def.nodes:
            return workflow_def.nodes[workflow_def.nodes.index(next_node) :]
        return list(workflow_def.nodes)
