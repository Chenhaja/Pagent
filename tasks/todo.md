# Pagent Agent Trace Event 可观测性 Todo

## P0 — 事件契约与现有 trace 接入点确认

- [ ] 确认 TraceEvent 与现有 `NodeResult.trace_events` 的适配关系。
  - 验收：不新增第二套 workflow trace 承载；TraceEvent 可转换为现有 `{"event": ..., "data": ...}` 形态。
  - 验证：代码审查 `app/models/schemas.py`、`app/orchestrator/engine.py`、`app/nodes/drafting_research.py`。
- [ ] 确认 logger sink 复用 `app.core.logging.log_event()`。
  - 验收：不重复实现日志 formatter；结构化字段进入现有 `fields`。
  - 验证：代码审查 `app/core/logging.py`。
- [ ] 确认第一阶段唯一试点节点为 `DraftingParseInputNode`。
  - 验收：不修改其他 drafting 节点的 agent 化逻辑。
  - 验证：代码 diff 只涉及 trace 基础设施、input parser runner、parse node 和测试。

## P1 — TraceEvent schema、脱敏摘要与 progress 映射

- [ ] 新增 TraceEvent 数据结构与事件 / 状态枚举。
  - 验收：覆盖 `agent_started`、`agent_completed`、`agent_failed`、`agent_tool_call_started`、`agent_tool_call_completed`、`agent_tool_call_failed`、`node_progress`。
  - 验证：`conda run -n autoGLM pytest tests/test_trace_events.py`
- [ ] 新增脱敏摘要 helper。
  - 验收：输入长文本、dict、list、工具参数时，只输出类型、长度、数量、短摘要；过滤 `api_key`、`token`、`secret`、`password`。
  - 验证：`tests/test_trace_events.py` 覆盖长正文和敏感字段。
- [ ] 新增 TraceEvent 到 `NodeResult.trace_events` dict 的转换 helper。
  - 验收：输出包含稳定 `event` 和脱敏 `data`，不包含完整 prompt / 正文 / 工具完整输入输出。
  - 验证：`tests/test_trace_events.py`。
- [ ] 新增 progress 映射函数。
  - 验收：同一 TraceEvent 可映射出受控 `progress_label` / `progress_message`；不直接暴露工具原始参数。
  - 验证：`tests/test_trace_events.py`。
- [ ] 运行 P1 验证。
  - 验收：trace event 测试与编译通过。
  - 验证：`conda run -n autoGLM pytest tests/test_trace_events.py && conda run -n autoGLM python -m compileall app tests`

## P2 — TraceEmitter 与 logger sink

- [ ] 新增 `TraceEmitter` 接口。
  - 验收：提供 `emit(event)`，后续节点只依赖接口，不依赖具体 logger。
  - 验证：`tests/test_trace_events.py`。
- [ ] 新增 `NoopTraceEmitter`。
  - 验收：未注入 emitter 时无副作用且不报错。
  - 验证：`tests/test_trace_events.py`。
- [ ] 新增 `LoggerTraceEmitter`。
  - 验收：通过 `log_event()` 输出稳定英文事件和结构化字段。
  - 验证：`tests/test_trace_events.py` 或 `caplog` 断言。
- [ ] 确保 emitter 异常不破坏主业务流程。
  - 验收：fake emitter 抛错时，调用方可安全降级；最多输出 warning。
  - 验证：`tests/test_trace_events.py`。
- [ ] 运行 P2 验证。
  - 验收：trace event、logging 相关测试与编译通过。
  - 验证：`conda run -n autoGLM pytest tests/test_trace_events.py tests/test_core_config_logging.py && conda run -n autoGLM python -m compileall app tests`

## P3 — `LangChainInputParserAgent` 接入 emitter

- [ ] 为 `LangChainInputParserAgent.__init__()` 增加可选 `trace_emitter`。
  - 验收：默认不传时现有行为不变。
  - 验证：`conda run -n autoGLM pytest tests/test_input_parser_agent.py`
- [ ] 在真实 agent 路径发送 agent 生命周期事件。
  - 验收：成功路径发送 `agent_started`、`agent_completed`；异常路径发送 `agent_failed` 并保持 fallback 行为。
  - 验证：`tests/test_input_parser_agent.py` fake agent 成功 / 失败用例。
- [ ] 包装 `read_source_artifact` 工具事件。
  - 验收：发送 tool started / completed / failed；输出只包含 artifact key、chars、error code 等摘要，不包含完整 content。
  - 验证：`tests/test_input_parser_agent.py`。
- [ ] 包装 `write_parsed_info` 工具事件。
  - 验收：发送 tool started / completed / failed；不记录完整 JSON content。
  - 验证：`tests/test_input_parser_agent.py`。
- [ ] 包装 `file_extract` 工具事件。
  - 验收：只记录 attachment id、format、chars、truncated、error code；不记录附件正文或任意路径。
  - 验证：`tests/test_input_parser_agent.py`。
- [ ] 包装 `office_to_md` 工具事件。
  - 验收：只记录 attachment id、format、chars、media_count、error code；不记录 markdown 正文。
  - 验证：`tests/test_input_parser_agent.py`。
- [ ] 保持 fallback 和安全约束不变。
  - 验收：LLM 配置不完整、非法 source key、非法 JSON、agent 写入非法 JSON 等现有测试继续通过。
  - 验证：`conda run -n autoGLM pytest tests/test_input_parser_agent.py`
- [ ] 运行 P3 验证。
  - 验收：input parser agent 与 trace event 测试通过。
  - 验证：`conda run -n autoGLM pytest tests/test_input_parser_agent.py tests/test_trace_events.py && conda run -n autoGLM python -m compileall app tests`

## P4 — `DraftingParseInputNode` 试点贯通

- [ ] 为 `DraftingParseInputNode.__init__()` 增加可选 `trace_emitter`。
  - 验收：默认不传时节点现有行为不变。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_research_nodes.py`
- [ ] 默认构造 `LangChainInputParserAgent` 时传入同一个 emitter。
  - 验收：parse node 与 input parser runner 使用同一 TraceEvent 出口。
  - 验证：fake emitter 断言事件顺序。
- [ ] 将 agent TraceEvent 汇总到节点可观测输出。
  - 验收：一次 parse node 执行可看到 source 写入、agent started、tool call、agent completed / failed、input parsed。
  - 验证：`tests/test_drafting_research_nodes.py` 或新增 `tests/test_drafting_parse_input_node.py`。
- [ ] 确认 `NodeResult.output` 与 `trace_events` 不泄露长正文。
  - 验收：output 只包含 `input_key` / `parsed_info_key`；trace 只包含短摘要。
  - 验证：节点测试断言。
- [ ] 保持旧 `tool_registry` 注入路径可用。
  - 验收：显式传入 `tool_registry` 时仍走旧 input_parser 工具路径，不因 trace 改造失败。
  - 验证：现有 drafting research 测试。
- [ ] 运行 P4 验证。
  - 验收：drafting parse、input parser agent 与编译通过。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_research_nodes.py tests/test_input_parser_agent.py && conda run -n autoGLM python -m compileall app tests`

## P5 — 回归、文档检查与推广边界确认

- [ ] 运行 drafting 端到端回归。
  - 验收：trace 改造不影响完整 patent drafting workflow。
  - 验证：`conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py`
- [ ] 运行安全合规回归。
  - 验收：日志 / trace 不包含敏感字段、prompt 全文、正文长文本或工具完整输入输出。
  - 验证：`conda run -n autoGLM pytest tests/test_security_compliance.py`
- [ ] 运行全量测试。
  - 验收：全量 pytest 通过。
  - 验证：`conda run -n autoGLM pytest`
- [ ] 运行编译检查。
  - 验收：app 和 tests 编译通过。
  - 验证：`conda run -n autoGLM python -m compileall app tests`
- [ ] 人工确认后续推广方向。
  - 验收：明确下一阶段是 SSE / WebSocket / API、trace 持久化、还是扩展到更多 agent 节点。
  - 验证：用户确认。

## Checkpoints

- [ ] Checkpoint A：P1 完成后确认 TraceEvent 字段是否足够支撑前端进度视图。
- [ ] Checkpoint B：P2 完成后确认 logger sink 输出是否满足后端排查。
- [ ] Checkpoint C：P3 完成后确认 wrapper 捕获的工具事件粒度是否足够；若不足，再评估 LangChain 官方 callback / stream events。
- [ ] Checkpoint D：P4 完成后确认是否需要把 TraceEvent 写入 `WorkflowState.trace`，还是仅 logger + fake emitter 已足够当前阶段。
- [ ] Checkpoint E：P5 完成后再决定是否推广到其他节点，禁止默认扩范围。
