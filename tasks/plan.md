# Pagent Agent Trace Event 可观测性实施计划

## 目标与范围

本计划基于根目录 `SPEC.md`，用于为 `DraftingParseInputNode` 中的 `create_agent` 试点建立统一 TraceEvent 可观测性。

本轮只规划，不实现业务代码。计划输出：

- `tasks/plan.md`：实施计划、依赖图、垂直切片、检查点。
- `tasks/todo.md`：可执行任务清单、验收标准、验证命令。

核心范围：

- 使用一套统一 TraceEvent 事实流。
- 后端技术日志 sink 与前端进度视图都从同一 TraceEvent 派生。
- 先在 `DraftingParseInputNode` / `LangChainInputParserAgent` 试点。
- 先实现后端日志 sink，前端只保留 progress 映射函数和字段，不做 SSE / WebSocket / UI。
- 默认测试不触网、不调用真实外部 LLM。

非范围：

- 不迁移所有节点到 `create_agent`。
- 不实现前端 UI 或推送接口。
- 不持久化 trace event 到数据库或 workspace artifact。
- 不引入第三方 observability 依赖。

## 只读探索结论

- `DraftingParseInputNode` 位于 `app/nodes/drafting_research.py:18`。
- 节点当前通过 `LangChainInputParserAgent` 执行输入解析 runner，默认路径位于 `app/tools/subagents/input_parser_agent.py:17`。
- `LangChainInputParserAgent.run()` 当前在 `app/tools/subagents/input_parser_agent.py:47` 创建 `create_agent`，并在 `app/tools/subagents/input_parser_agent.py:58` 调用 `agent.invoke(...)`。
- 现有 runner 内部工具定义在 `app/tools/subagents/input_parser_agent.py:83`，包括 `read_source_artifact`、`write_parsed_info`、`file_extract`、`office_to_md`。
- 现有结构化日志入口是 `app/core/logging.py:182` 的 `log_event()`，formatter 已支持 `event` 和 `fields`。
- `Orchestrator` 已在 `app/orchestrator/engine.py:51` 绑定 `node_name` 上下文，并在 `app/orchestrator/engine.py:59` 把 `NodeResult.trace_events` 写回 `WorkflowState`。
- 现有 `NodeResult.trace_events` 是 `list[dict[str, Any]]`，定义在 `app/models/schemas.py:165`。
- 现有 drafting 节点 trace 仍是轻量 `{"event": ..., "data": ...}` 形态，见 `app/nodes/drafting_research.py:121`。
- 测试入口已有 `tests/test_input_parser_agent.py`，适合扩展 fake agent / fake tool / fake emitter 测试。

## 依赖图

```text
P0 事件契约与现有 trace 接入点确认
  └─> P1 TraceEvent schema + 脱敏摘要 + progress 映射
        ├─> P2 TraceEmitter + logger sink
        │     └─> P3 input_parser agent runner 接入 emitter
        │           └─> P4 DraftingParseInputNode 试点贯通
        │                 └─> P5 回归、文档检查与推广边界确认
        └─> P5 回归、文档检查与推广边界确认
```

说明：

- P0 先锁定事件与现有 `NodeResult.trace_events` / logger 的关系，避免重复造两套 trace。
- P1 是 schema 和安全边界基础，阻塞后续 emitter 和节点接入。
- P2 提供可替换 sink，第一阶段只落 logger sink 和 no-op / memory fake。
- P3 是关键试点：在 `LangChainInputParserAgent` 内捕获 agent / tool 事件。
- P4 把 runner 的事件带到 `DraftingParseInputNode` 和 workflow trace 中，形成端到端可观测路径。
- P5 做回归和边界收敛，不扩展到其他节点。

## 垂直切片计划

### P0 — 事件契约与现有 trace 接入点确认

#### 目标

确认统一 TraceEvent 如何兼容现有 `NodeResult.trace_events`、`WorkflowState.trace` 和结构化日志，避免引入平行事件体系。

#### 覆盖范围

- `app/models/schemas.py`
- `app/orchestrator/engine.py`
- `app/core/logging.py`
- `app/nodes/drafting_research.py`
- `app/tools/subagents/input_parser_agent.py`
- `tests/test_input_parser_agent.py`

#### 实施要点

- 明确 TraceEvent 是统一事实流。
- `NodeResult.trace_events` 继续作为 workflow 内审计输出的承载方式。
- logger sink 使用 `app.core.logging.log_event()` 输出结构化日志。
- 不修改 `Orchestrator` 的调度语义。
- 不新增单节点专用配置项。

#### 验收标准

- 计划中明确事件生产者、sink、workflow trace 的关系。
- 明确第一阶段不做 API 推送、不做持久化、不做全节点迁移。
- 明确 `DraftingParseInputNode` 是唯一试点节点。

#### 检查点

- 如果实现时发现 `NodeResult.trace_events` 字段不足，优先在事件转换层适配，不优先修改通用 `NodeResult` schema。

---

### P1 — TraceEvent schema、脱敏摘要与 progress 映射

#### 目标

建立统一事件对象、受控枚举、摘要脱敏规则和前端 progress 映射，形成后续所有 sink 的共同输入。

#### 覆盖范围

- 优先新增 `app/tracing/events.py`
- 优先新增 `app/tracing/progress.py`
- 新增 `tests/test_trace_events.py`

如项目实现时已有更合适 trace 模块，应复用现有位置，但职责保持一致。

#### 实施要点

- 定义 `TraceEvent` 数据结构，包含：`trace_id`、`span_id`、`parent_span_id`、`workflow_id`、`workspace_id`、`node_name`、`agent_name`、`agent_run_id`、`event`、`status`、`tool_name`、`tool_call_id`、`input_summary`、`output_summary`、`progress_label`、`progress_message`、`duration_ms`、`error_type`、`error_message`、`metadata`、`timestamp`。
- 定义事件枚举：`agent_started`、`agent_completed`、`agent_failed`、`agent_tool_call_started`、`agent_tool_call_completed`、`agent_tool_call_failed`、`node_progress`。
- 定义状态枚举：`started`、`completed`、`failed`、`skipped`。
- 提供 `summarize_value()` 或等价 helper，只输出类型、长度、数量、短摘要。
- 敏感字段名如 `api_key`、`token`、`secret`、`password` 必须被过滤。
- 提供 `to_node_trace_event()`，把 TraceEvent 转成现有 `{"event": ..., "data": ...}` 形态。
- 提供 progress 映射函数，输出受控 `progress_label` / `progress_message`。

#### 验收标准

- TraceEvent 必填字段完整，事件和状态枚举受控。
- 摘要函数不输出长正文。
- 敏感字段不会进入公开事件 dict。
- progress 映射来自同一 TraceEvent，而不是第二套事实事件。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_trace_events.py
conda run -n autoGLM python -m compileall app tests
```

#### 检查点

- 确认是否使用 pydantic model；若会扩大改动，可先使用 dataclass / TypedDict + helper。

---

### P2 — TraceEmitter 与 logger sink

#### 目标

提供可注入 emitter 边界，并用现有 `log_event()` 实现第一阶段后端日志 sink。

#### 覆盖范围

- 优先新增 `app/tracing/emitter.py`
- `app/core/logging.py` 仅在必要时小改
- `tests/test_trace_events.py`

#### 实施要点

- 定义 `TraceEmitter.emit(event: TraceEvent) -> None`。
- 提供 `NoopTraceEmitter`，未注入时安全无副作用。
- 提供 `LoggerTraceEmitter`，调用 `log_event()` 输出结构化日志。
- 提供测试用 `MemoryTraceEmitter` 或在测试内定义 fake emitter。
- emitter 自身异常不得破坏主业务流程；实现时可提供 `safe_emit()` 或在调用方包裹。
- logger fields 只输出脱敏后的短字段。

#### 验收标准

- logger sink 输出稳定英文 `event`。
- 输出字段包含 `trace_id`、`node_name`、`agent_name`、`tool_name`、`status`、`duration_ms` 等可检索字段。
- emitter 抛错不会导致业务失败。
- 不记录 prompt 全文、交底书正文、工具完整输入输出或密钥。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_trace_events.py
conda run -n autoGLM pytest tests/test_core_config_logging.py
conda run -n autoGLM python -m compileall app tests
```

#### 检查点

- 如现有 formatter 已能满足字段输出，不修改 `app/core/logging.py`。

---

### P3 — `LangChainInputParserAgent` 接入 emitter

#### 目标

在 `create_agent` 试点 runner 内捕获 agent start / completed / failed 和工具 call / result / error 事件。

#### 覆盖范围

- `app/tools/subagents/input_parser_agent.py`
- `tests/test_input_parser_agent.py`

#### 实施要点

- `LangChainInputParserAgent.__init__()` 增加可选 `trace_emitter` 参数。
- `run()` 开始真实 agent 路径前发送 `agent_started`。
- `agent.invoke(...)` 成功后发送 `agent_completed`。
- `agent.invoke(...)` 或初始化异常时发送 `agent_failed`，同时保持现有 fallback 行为。
- 在 `_build_tools()` 内包装四个受控工具：调用前发送 `agent_tool_call_started`，成功后发送 `agent_tool_call_completed`，异常或返回 error 时发送 `agent_tool_call_failed`。
- 工具 input / output 只记录摘要，不记录正文：例如 artifact key、attachment id、chars、media_count、error code。
- 优先保持现有 fallback 行为，不因 trace 改变业务结果。
- 如果当前 LangChain 版本缺少合适 callback / stream event，先用 wrapper 捕获工具边界；接口保留未来替换官方事件源的空间。

#### 验收标准

- fake agent 成功时能看到 `agent_started`、工具事件、`agent_completed`。
- fake agent 失败时能看到 `agent_failed`，并仍写入 fallback parsed info。
- 工具返回 error 时能看到 `agent_tool_call_failed`。
- 事件中不包含 `read_source_artifact` 返回的完整 content，也不包含 `write_parsed_info` 的完整 JSON content。
- 未传 emitter 时原有测试继续通过。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_input_parser_agent.py
conda run -n autoGLM pytest tests/test_trace_events.py
conda run -n autoGLM python -m compileall app tests
```

#### 检查点

- 如果 fake LangChain tool 调用难以稳定模拟，优先测试 `_build_tools()` 返回工具的直接 invoke 行为，避免真实 LLM。

---

### P4 — `DraftingParseInputNode` 试点贯通

#### 目标

让 `DraftingParseInputNode` 能注入并汇总 TraceEvent，使一次 workflow 节点执行可同时进入后端日志和 `NodeResult.trace_events`。

#### 覆盖范围

- `app/nodes/drafting_research.py`
- `tests/test_drafting_research_nodes.py`
- 可能新增 `tests/test_drafting_parse_input_node.py`，但优先复用现有 drafting research 测试文件。

#### 实施要点

- `DraftingParseInputNode.__init__()` 增加可选 `trace_emitter` 参数。
- 默认构造 `LangChainInputParserAgent` 时传入同一个 emitter。
- 节点本身继续记录 `drafting_source_written`、`drafting_input_parsed` 等业务 trace。
- runner 产生的 agent TraceEvent 需要能进入测试 fake emitter；如需进入 `NodeResult.trace_events`，通过 memory collector 或 adapter 汇总为现有 trace dict。
- 保持 `run()` 输出契约不变：只返回 `input_key` / `parsed_info_key` 等短字段。
- 失败路径保持现有错误语义。

#### 验收标准

- `DraftingParseInputNode` 成功执行时，事件包含 source 写入、agent started、工具调用、agent completed、input parsed。
- agent 失败并 fallback 时，事件包含 `agent_failed`，节点仍按现有 fallback 成功或失败语义返回。
- 未传 emitter 时节点仍可正常运行。
- `NodeResult.output` 不包含长正文。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_drafting_research_nodes.py
conda run -n autoGLM pytest tests/test_input_parser_agent.py
conda run -n autoGLM python -m compileall app tests
```

#### 检查点

- 确认是否新增独立 `tests/test_drafting_parse_input_node.py`。若现有 `tests/test_drafting_research_nodes.py` 已覆盖该节点，优先扩展现有文件。

---

### P5 — 回归、文档检查与推广边界确认

#### 目标

确认试点不会破坏现有 drafting workflow，并明确后续推广到其他节点前的边界。

#### 覆盖范围

- `tests/test_patent_drafting_workflow.py`
- `tests/test_security_compliance.py`
- `SPEC.md`
- `tasks/plan.md`
- `tasks/todo.md`

#### 实施要点

- 跑 drafting 端到端回归，确认 parse 节点事件不影响完整 workflow。
- 跑安全相关测试，确认日志 / trace 不泄露敏感信息。
- 跑全量测试和 compileall。
- 不在本阶段接入其他 drafting 节点。
- 如果实现中发现需要修改 SPEC，先回到规格确认，不直接扩大范围。

#### 验收标准

- trace event 试点满足 SPEC 验收。
- 所有新增和相关回归测试通过。
- 没有新增第三方依赖；如不得不新增，先确认并更新 `requirements.txt`。
- 后续推广到其他节点的接口边界清晰：节点只依赖 `TraceEmitter`，不依赖具体 logger sink。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_trace_events.py tests/test_input_parser_agent.py tests/test_drafting_research_nodes.py
conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py
conda run -n autoGLM pytest tests/test_security_compliance.py
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests
```

#### 检查点

- 人工确认是否进入下一阶段：SSE / WebSocket / API 推送、trace 持久化、或扩展到其他 agent 节点。

## 分阶段提交建议

按项目规范，每个可独立验证阶段单独提交：

1. `feat(trace): 增加 agent 事件模型与进度映射`
2. `feat(trace): 增加 agent 事件日志 sink`
3. `feat(drafting): 观测输入解析 agent 工具调用`
4. `test(drafting): 增加输入解析 agent trace 回归`

如 P1 + P2 改动很小，可合并为一个提交；P3 + P4 涉及业务试点，建议单独提交。
