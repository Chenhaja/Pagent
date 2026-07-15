# Pagent WorkflowTraceEvent schema 化与试点 Todo

## P0 — 统一口径确认：Workflow trace 是唯一事实承载

- [ ] 确认 `WorkflowTraceEvent` 是当前 workflow trace 的 schema 化结果。
  - 验收：不新增独立 agent trace 事实流；新事件直接进入 `NodeResult.trace_events`。
  - 验证：代码审查 `app/models/schemas.py`、`app/orchestrator/engine.py`。
- [ ] 确认 `WorkflowState.trace` 是统一管理 / 存储 / 审计入口。
  - 验收：后端日志和前端 progress 都从 workflow trace 派生。
  - 验证：代码审查 `app/orchestrator/engine.py`。
- [ ] 确认 schema 面向全 workflow node。
  - 验收：字段和事件枚举覆盖 QA、translate、query_rewrite、drafting 等普通节点和 agent 节点。
  - 验证：`tests/test_workflow_trace_events.py` 包含非 drafting 样例。
- [ ] 确认第一阶段唯一实现试点为 `DraftingParseInputNode`。
  - 验收：不迁移所有节点、不迁移所有 create_agent、不做前端推送。
  - 验证：代码 diff 范围检查。

## P1 — WorkflowTraceEvent schema、脱敏摘要与 ProgressEvent projection

- [x] 新增 `WorkflowTraceEvent` 数据结构。
  - 验收：包含 `schema_version`、`node_name`、`node_type`、`event`、`status`、`stage`、agent/tool 字段、summary 字段、progress 字段、metadata、timestamp。
  - 验证：`conda run -n autoGLM pytest tests/test_workflow_trace_events.py`
- [x] 新增通用事件 / 状态 / node_type 枚举。
  - 验收：覆盖 workflow、node、agent、tool、progress 事件；覆盖 `normal`、`agent`、`tool`、`gate`。
  - 验证：`tests/test_workflow_trace_events.py`。
- [x] 新增脱敏摘要 helper。
  - 验收：输入长文本、dict、list、工具参数时，只输出类型、长度、数量、短摘要；过滤 `api_key`、`token`、`secret`、`password`。
  - 验证：`tests/test_workflow_trace_events.py` 覆盖长正文和敏感字段。
- [x] 新增可进入 `NodeResult.trace_events` 的 dict 输出 helper。
  - 验收：输出就是新 schema dict，不再转换成另一套事实格式；旧 `{"event": ..., "data": ...}` 可兼容共存。
  - 验证：`tests/test_workflow_trace_events.py`。
- [x] 新增 `ProgressEvent` projection。
  - 验收：只投影 `progress.visible=true`；输出 `stage`、`status`、`label`、`message`、`visible`、`order`、`timestamp` 等稳定字段。
  - 验证：`tests/test_workflow_trace_events.py`。
- [x] 增加非 drafting schema 样例。
  - 验收：至少包含 `qa.retrieval`、`translate.translation` 或 `query_rewrite.rewrite` 示例，证明 schema 不绑定 drafting。
  - 验证：`tests/test_workflow_trace_events.py`。
- [x] 运行 P1 验证。
  - 验收：workflow trace event 测试与编译通过。
  - 验证：`conda run -n autoGLM pytest tests/test_workflow_trace_events.py && conda run -n autoGLM python -m compileall app tests`

## P2 — WorkflowTraceEmitter / sink 适配当前 trace 与 logger

- [ ] 新增 `WorkflowTraceEmitter` 接口。
  - 验收：提供 `emit(event)`；节点和 runner 只依赖接口。
  - 验证：`tests/test_workflow_trace_events.py`。
- [ ] 新增 `NoopWorkflowTraceEmitter`。
  - 验收：未注入 emitter 时无副作用且不报错。
  - 验证：`tests/test_workflow_trace_events.py`。
- [ ] 新增测试用 `MemoryWorkflowTraceEmitter`。
  - 验收：收集到的事件可直接作为 `NodeResult.trace_events`。
  - 验证：`tests/test_workflow_trace_events.py`。
- [ ] 新增 logger sink。
  - 验收：复用 `log_event()` 输出稳定英文事件和结构化字段，不重复实现 formatter。
  - 验证：`tests/test_workflow_trace_events.py` 或 `caplog` 断言。
- [ ] 确保 emitter / sink 异常不破坏主业务流程。
  - 验收：fake sink 抛错时，调用方可安全降级；最多输出 warning。
  - 验证：`tests/test_workflow_trace_events.py`。
- [ ] 运行 P2 验证。
  - 验收：workflow trace、logging 相关测试与编译通过。
  - 验证：`conda run -n autoGLM pytest tests/test_workflow_trace_events.py tests/test_core_config_logging.py && conda run -n autoGLM python -m compileall app tests`

## P3 — `LangChainInputParserAgent` 发送 agent / tool WorkflowTraceEvent

- [ ] 为 `LangChainInputParserAgent.__init__()` 增加可选 `workflow_trace_emitter`。
  - 验收：默认不传时现有行为不变。
  - 验证：`conda run -n autoGLM pytest tests/test_input_parser_agent.py`
- [ ] 在真实 agent 路径发送 agent 生命周期事件。
  - 验收：成功路径发送 `agent_started`、`agent_completed`；异常路径发送 `agent_failed` 并保持 fallback 行为。
  - 验证：`tests/test_input_parser_agent.py` fake agent 成功 / 失败用例。
- [ ] 包装 `read_source_artifact` 工具事件。
  - 验收：发送 `tool_call_started` / `tool_call_completed` / `tool_call_failed`；不包含完整 content。
  - 验证：`tests/test_input_parser_agent.py`。
- [ ] 包装 `write_parsed_info` 工具事件。
  - 验收：发送 tool 事件；不记录完整 JSON content。
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
  - 验收：input parser agent 与 workflow trace event 测试通过。
  - 验证：`conda run -n autoGLM pytest tests/test_input_parser_agent.py tests/test_workflow_trace_events.py && conda run -n autoGLM python -m compileall app tests`

## P4 — `DraftingParseInputNode` 汇总到 workflow trace

- [ ] 为 `DraftingParseInputNode.__init__()` 增加可选 `workflow_trace_emitter`。
  - 验收：默认不传时节点现有行为不变。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_research_nodes.py`
- [ ] 默认构造 `LangChainInputParserAgent` 时传入同一个 emitter / collector。
  - 验收：parse node 与 input parser runner 使用同一 workflow trace 出口。
  - 验证：fake emitter 断言事件顺序。
- [ ] 将 agent / tool `WorkflowTraceEvent` 汇总进 `NodeResult.trace_events`。
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

## P5 — 回归、非 drafting 兼容样例与推广边界确认

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
  - 验收：明确下一阶段是 API 推送、trace 持久化、全局节点迁移，还是继续扩展其他 agent node。
  - 验证：用户确认。

## Checkpoints

- [ ] Checkpoint A：P1 完成后确认 `WorkflowTraceEvent` 字段是否足够覆盖 QA / translate / query_rewrite / drafting。
- [ ] Checkpoint B：P2 完成后确认 logger sink 输出是否满足后端排查。
- [ ] Checkpoint C：P3 完成后确认 wrapper 捕获的工具事件粒度是否足够；若不足，再评估 LangChain 官方 callback / stream events。
- [ ] Checkpoint D：P4 完成后确认是否立即把 `drafting_source_written` 等旧业务 trace 迁移到新 schema，还是保留到后续全局迁移。
- [ ] Checkpoint E：P5 完成后再决定是否推广到其他节点，禁止默认扩范围。
