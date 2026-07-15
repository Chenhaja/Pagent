# Pagent WorkflowTraceEvent schema 化与试点实施计划

## 目标与范围

本计划基于根目录 `SPEC.md`，用于将当前 workflow trace schema 化为统一 `WorkflowTraceEvent`，并在 `DraftingParseInputNode` 中试点 `create_agent` 内部活动可观测。

核心范围：

- `NodeResult.trace_events` / `WorkflowState.trace` 是统一 workflow trace 管理入口。
- 不另起独立 agent trace 事实流。
- `WorkflowTraceEvent` schema 面向全部 workflow node：QA、translate、query_rewrite、normalize_input、intent_router、drafting 等。
- 第一阶段只在 `DraftingParseInputNode` / `LangChainInputParserAgent` 试点 agent / tool 细粒度事件。
- 后端 logger sink 与前端 `ProgressEvent` projection 都从 `WorkflowTraceEvent` 派生。
- 第一阶段不做 SSE / WebSocket / API 推送，不做 trace 持久化，不迁移全部节点。

## 只读探索结论

- 当前 workflow trace 承载字段是 `NodeResult.trace_events`，定义在 `app/models/schemas.py:165`。
- `Orchestrator._record_trace_events()` 在 `app/orchestrator/engine.py:96` 将节点 trace 写入 `WorkflowState.trace`。
- 当前 trace 多为自由 dict，例如 `app/nodes/drafting_research.py:121` 的 `{"event": ..., "data": ...}`。
- 结构化日志入口是 `app/core/logging.py:182` 的 `log_event()`，已支持稳定 `event` 和结构化 `fields`。
- `DraftingParseInputNode` 位于 `app/nodes/drafting_research.py:18`。
- `LangChainInputParserAgent` 位于 `app/tools/subagents/input_parser_agent.py:17`，在 `run()` 中创建并调用 `create_agent`。
- input parser agent 的受控工具在 `app/tools/subagents/input_parser_agent.py:83` 构造，包括 `read_source_artifact`、`write_parsed_info`、`file_extract`、`office_to_md`。
- QA / translate / query_rewrite 已有各自节点和 trace 事件，但本阶段不迁移实现，只用测试样例验证 schema 通用性。

## 依赖图

```text
P0 统一口径确认：Workflow trace 是唯一事实承载
  └─> P1 WorkflowTraceEvent schema + 脱敏摘要 + ProgressEvent projection
        ├─> P2 WorkflowTraceEmitter / sink 适配当前 NodeResult.trace_events 与 logger
        │     └─> P3 LangChainInputParserAgent 发送 agent / tool WorkflowTraceEvent
        │           └─> P4 DraftingParseInputNode 汇总到 workflow trace
        │                 └─> P5 回归、非 drafting 兼容样例、推广边界确认
        └─> P5 回归、非 drafting 兼容样例、推广边界确认
```

说明：

- P0 防止误解为新增独立 TraceEvent 体系。
- P1 是全局 schema，不绑定 drafting。
- P2 解决事件如何进入当前 workflow trace 和后端日志。
- P3 捕获 `create_agent` runner 内部活动。
- P4 将试点事件贯通到 `DraftingParseInputNode` 的 `NodeResult.trace_events` / `WorkflowState.trace`。
- P5 验证非 drafting 兼容性，但不迁移非 drafting 节点。

## 垂直切片计划

### P0 — 统一口径确认：Workflow trace 是唯一事实承载

#### 目标

把术语和边界统一为：`WorkflowTraceEvent` 是当前 workflow trace 的 schema 化结果，`NodeResult.trace_events` / `WorkflowState.trace` 是统一管理入口。

#### 覆盖范围

- `app/models/schemas.py`
- `app/orchestrator/engine.py`
- `app/core/logging.py`
- `app/nodes/drafting_research.py`
- `app/tools/subagents/input_parser_agent.py`

#### 实施要点

- 不引入与 workflow trace 平行的 agent trace 事实流。
- 新事件直接按 `WorkflowTraceEvent` schema 放入 `NodeResult.trace_events`。
- 第一阶段兼容旧 `{"event": ..., "data": ...}` 事件，不强制迁移全项目。
- logger sink 和 progress projection 都读取 `WorkflowTraceEvent`。
- schema 设计包含普通 node、agent、tool、gate 等 node_type。

#### 验收标准

- 文档、测试和命名均使用 `WorkflowTraceEvent`。
- 计划明确 QA / translate / query_rewrite 适用，但第一阶段不迁移。
- 计划明确 `WorkflowState.trace` 是统一管理入口。

#### 检查点

- 若实现时发现 `WorkflowState.trace` 当前结构不足，优先做兼容 adapter，不优先大改 orchestrator。

---

### P1 — WorkflowTraceEvent schema、脱敏摘要与 ProgressEvent projection

#### 目标

定义全 workflow 通用事件 schema、安全摘要规则和前端进度 projection。

#### 覆盖范围

- 优先新增 `app/tracing/workflow_trace.py`
- 优先新增 `app/tracing/progress.py`
- 新增 `tests/test_workflow_trace_events.py`

#### 实施要点

- 定义 `WorkflowTraceEvent`，字段至少包含：`schema_version`、`trace_id`、`span_id`、`parent_span_id`、`workflow_id`、`session_id`、`request_id`、`node_name`、`node_type`、`event`、`status`、`stage`、`agent_name`、`agent_run_id`、`tool_name`、`tool_call_id`、`input_summary`、`output_summary`、`duration_ms`、`error_type`、`error_message`、`progress`、`metadata`、`timestamp`。
- 定义通用事件枚举：`workflow_started`、`workflow_completed`、`workflow_failed`、`node_started`、`node_completed`、`node_failed`、`node_skipped`、`progress_updated`。
- 定义 agent / tool 事件枚举：`agent_started`、`agent_completed`、`agent_failed`、`tool_call_started`、`tool_call_completed`、`tool_call_failed`。
- 定义状态枚举：`started`、`running`、`completed`、`failed`、`skipped`、`waiting`。
- 定义 node_type 枚举：`normal`、`agent`、`tool`、`gate`。
- 提供脱敏摘要 helper，只输出类型、长度、数量、短摘要。
- 过滤敏感字段：`api_key`、`token`、`secret`、`password` 等。
- 提供 `to_trace_dict()`，输出可直接进入 `NodeResult.trace_events` 的 dict。
- 提供 `ProgressEvent` projection，仅投影 `progress.visible=true` 的事件。
- 测试中加入非 drafting 样例，例如 `qa.retrieval` 或 `translate.translation`。

#### 验收标准

- schema 不绑定 drafting。
- 旧 trace dict 仍可共存。
- ProgressEvent 字段稳定：`trace_id`、`workflow_id`、`node_name`、`stage`、`status`、`label`、`message`、`visible`、`order`、`timestamp`。
- 摘要和 projection 不泄露正文、prompt、完整工具输入输出或密钥。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_workflow_trace_events.py
conda run -n autoGLM python -m compileall app tests
```

#### 检查点

- 确认是否需要 pydantic。若会扩大变更，优先使用 dataclass / TypedDict + helper。

---

### P2 — WorkflowTraceEmitter / sink 适配当前 trace 与 logger

#### 目标

提供统一发送入口，让事件既可进入 `NodeResult.trace_events`，也可输出到后端结构化日志。

#### 覆盖范围

- 优先新增 `app/tracing/sinks.py`
- `app/core/logging.py` 仅在必要时小改
- `tests/test_workflow_trace_events.py`

#### 实施要点

- 定义 `WorkflowTraceEmitter.emit(event: WorkflowTraceEvent) -> None`。
- 提供 `NoopWorkflowTraceEmitter`。
- 提供测试用 `MemoryWorkflowTraceEmitter`，用于收集事件并注入到 `NodeResult.trace_events`。
- 提供 `LoggerWorkflowTraceSink` 或等价 logger sink，复用 `log_event()`。
- sink 输出字段必须脱敏。
- emitter / sink 异常不得破坏主业务流程。

#### 验收标准

- logger sink 输出稳定英文 `event`。
- 输出字段包含 `node_name`、`node_type`、`stage`、`agent_name`、`tool_name`、`status`、`duration_ms` 等。
- Memory emitter 收集的事件可直接作为 `NodeResult.trace_events`。
- emitter 抛错不会导致业务失败。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_workflow_trace_events.py tests/test_core_config_logging.py
conda run -n autoGLM python -m compileall app tests
```

#### 检查点

- 如果现有 formatter 已能满足字段输出，不修改 `app/core/logging.py`。

---

### P3 — `LangChainInputParserAgent` 发送 agent / tool WorkflowTraceEvent

#### 目标

在 `create_agent` 试点 runner 内捕获 agent 生命周期和受控工具调用事件。

#### 覆盖范围

- `app/tools/subagents/input_parser_agent.py`
- `tests/test_input_parser_agent.py`

#### 实施要点

- `LangChainInputParserAgent.__init__()` 增加可选 `workflow_trace_emitter`。
- 真实 agent 路径开始前发送 `agent_started`。
- `agent.invoke(...)` 成功后发送 `agent_completed`。
- `agent.invoke(...)` 或初始化异常时发送 `agent_failed`，保持现有 fallback 行为。
- 包装 `read_source_artifact`、`write_parsed_info`、`file_extract`、`office_to_md`：调用前发送 `tool_call_started`，成功后发送 `tool_call_completed`，失败或返回 error 时发送 `tool_call_failed`。
- 工具 input / output 只记录摘要：artifact key、attachment id、chars、media_count、error code 等。
- 不记录 `read_source_artifact` 返回的完整 content，也不记录 `write_parsed_info` 的完整 JSON content。
- 如果 LangChain 官方 callback / stream event 暂不可用，先用 wrapper 捕获工具边界，保留未来切换空间。

#### 验收标准

- fake agent 成功时有 `agent_started`、工具事件、`agent_completed`。
- fake agent 失败时有 `agent_failed`，并仍写入 fallback parsed info。
- 工具返回 error 时有 `tool_call_failed`。
- 未传 emitter 时原有测试继续通过。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_input_parser_agent.py tests/test_workflow_trace_events.py
conda run -n autoGLM python -m compileall app tests
```

#### 检查点

- 如果 fake LangChain tool 调用难以稳定模拟，优先测试 `_build_tools()` 返回工具的直接 invoke 行为，避免真实 LLM。

---

### P4 — `DraftingParseInputNode` 汇总到 workflow trace

#### 目标

让 `DraftingParseInputNode` 的一次执行把业务 trace 和 agent / tool trace 都汇总到 `NodeResult.trace_events`，由现有 orchestrator 写入 `WorkflowState.trace`。

#### 覆盖范围

- `app/nodes/drafting_research.py`
- `tests/test_drafting_research_nodes.py`
- 可选新增 `tests/test_drafting_parse_input_node.py`，但优先复用现有测试文件。

#### 实施要点

- `DraftingParseInputNode.__init__()` 增加可选 `workflow_trace_emitter`。
- 默认构造 `LangChainInputParserAgent` 时传入同一个 emitter / collector。
- 节点原有 `drafting_source_written`、`drafting_input_parsed` 业务 trace 可先保留旧格式，或新增为 `WorkflowTraceEvent`。
- agent / tool 新事件必须使用 `WorkflowTraceEvent` schema。
- runner 事件通过 collector 汇总进节点 `NodeResult.trace_events`。
- 保持 `run()` 输出契约不变，只返回 artifact key 等短字段。
- 显式传入旧 `tool_registry` 时保持原有路径可用。

#### 验收标准

- 成功执行时 trace 包含 source 写入、agent started、tool call、agent completed、input parsed。
- agent 失败并 fallback 时 trace 包含 `agent_failed`，节点仍按现有 fallback / 失败语义返回。
- `NodeResult.output` 不包含长正文。
- `NodeResult.trace_events` 不包含正文、prompt、完整工具参数或密钥。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_drafting_research_nodes.py tests/test_input_parser_agent.py
conda run -n autoGLM python -m compileall app tests
```

#### 检查点

- 确认是否需要立即将 `drafting_source_written` 等旧业务 trace 也迁移到新 schema。若非必要，留到后续全局迁移。

---

### P5 — 回归、非 drafting 兼容样例与推广边界确认

#### 目标

确认 schema 通用、试点不破坏现有 workflow，并明确后续迁移边界。

#### 覆盖范围

- `tests/test_workflow_trace_events.py`
- `tests/test_patent_drafting_workflow.py`
- `tests/test_security_compliance.py`
- `SPEC.md`
- `tasks/plan.md`
- `tasks/todo.md`

#### 实施要点

- 在 schema 测试里加入 QA / translate / query_rewrite 样例，不迁移其实现。
- 跑 drafting 端到端回归。
- 跑安全相关测试，确认日志 / trace 不泄露敏感信息。
- 跑全量测试和 compileall。
- 不在本阶段接入其他节点。
- 若实现中发现需要修改 SPEC，先回到规格确认，不直接扩大范围。

#### 验收标准

- `WorkflowTraceEvent` 支持非 drafting stage 样例。
- `DraftingParseInputNode` 试点满足 SPEC 验收。
- 所有新增和相关回归测试通过。
- 没有新增第三方依赖；如不得不新增，先确认并更新 `requirements.txt`。
- 后续推广到其他节点的接口边界清晰：节点只依赖 workflow trace emitter，不依赖具体 logger sink 或前端 projection。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_workflow_trace_events.py tests/test_input_parser_agent.py tests/test_drafting_research_nodes.py
conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py
conda run -n autoGLM pytest tests/test_security_compliance.py
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests
```

#### 检查点

- 人工确认后续方向：API 推送、trace 持久化、全局节点迁移，或继续扩展其他 agent node。

## 分阶段提交建议

1. `feat(trace): 规范 workflow trace 事件模型`
2. `feat(trace): 增加 workflow trace 日志与进度投影`
3. `feat(drafting): 观测输入解析 agent 工具调用`
4. `test(trace): 增加 workflow trace 回归样例`
