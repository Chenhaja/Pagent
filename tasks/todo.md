# 日志与可观测性 Todo

## Phase 0 — 口径确认与基线锁定

- [x] 确认本需求只做日志与可观测性增强。
  - 验收：计划不包含检索、ReAct、QA、编排业务语义重写。
  - 验证：review `tasks/plan.md`。
- [x] 确认不引入第三方观测依赖。
  - 验收：实现阶段仅使用标准库 `logging` / `contextvars` 和现有项目能力。
  - 验证：review diff / `requirements.txt` 不变。
- [x] 确认不新增日志存储、队列或远程上报。
  - 验收：日志仍输出到现有 stream handler。
  - 验证：review `app/core/logging.py`。
- [x] 确认 `log_sample_llm_call` 本轮只占位。
  - 验收：配置存在但不丢弃日志。
  - 验证：配置测试 / review。
- [x] 确认默认测试不触网、不调用真实 LLM。
  - 验收：新增测试使用 fake/stub/caplog。
  - 验证：review 测试实现。

## Phase 1 — 配置与脱敏基础闭环

- [x] 新增 `Settings.log_format`。
  - 验收：默认 `auto`；`PAGENT_LOG_FORMAT` 可覆盖为 `pretty` / `json`。
  - 验证：`conda run -n autoGLM pytest tests/test_core_config_logging.py`
- [x] 新增 `Settings.log_include_context`。
  - 验收：默认 `True`；`PAGENT_LOG_INCLUDE_CONTEXT=false` 可读取为 `False`。
  - 验证：配置测试。
- [x] 新增 `Settings.log_max_field_length`。
  - 验收：默认 `205`；`PAGENT_LOG_MAX_FIELD_LENGTH` 可读取为整数。
  - 验证：配置测试。
- [x] 新增 `Settings.log_sample_llm_call`。
  - 验收：默认 `False`；`PAGENT_LOG_SAMPLE_LLM_CALL=true` 可读取为 `True`。
  - 验证：配置测试。
- [x] 更新 `Settings` docstring。
  - 验收：新增日志配置均说明用途。
  - 验证：review。
- [x] 更新 `get_settings()` 环境变量读取。
  - 验收：四个 `PAGENT_LOG_*` 环境变量生效。
  - 验证：配置测试。
- [x] 更新 `to_public_dict()`。
  - 验收：新增日志配置进入 public dict；不包含 key/token/secret/password。
  - 验证：配置测试。
- [x] 扩展 `redact_sensitive_text()` 脱敏模式。
  - 验收：`sk-...`、`Bearer ...`、`password=...`、`token=...`、`api_key=...` 均被脱敏。
  - 验证：`conda run -n autoGLM pytest tests/test_security_compliance.py`
- [x] 保持脱敏后截断能力。
  - 验收：超过 `max_length` 的文本追加稳定截断标记。
  - 验证：安全测试。

## Phase 2 — 上下文与双模式 formatter 闭环

- [x] 新增 `app/core/log_context.py`。
  - 验收：模块可 import；公共函数/类有中文 Google 风格 docstring。
  - 验证：`conda run -n autoGLM pytest tests/test_log_context.py`
- [x] 定义上下文变量。
  - 验收：包含 `request_id`、`session_id`、`trace_id`、`node_name`、`task_type`。
  - 验证：上下文测试。
- [x] 实现 `new_request_id()`。
  - 验收：返回非空短 ID，连续调用不相同。
  - 验证：单测。
- [x] 实现 `bind_context()` / `reset_context()`。
  - 验收：可绑定多个字段并按 token 回滚。
  - 验证：单测。
- [x] 实现 `current_context()`。
  - 验收：返回当前上下文字段快照；未绑定时字段为 `None`。
  - 验证：单测。
- [x] 实现 `ContextFilter`。
  - 验收：向 `LogRecord` 注入上下文字段；未绑定不抛异常。
  - 验证：单测。
- [x] 扩展 `JsonLineFormatter` 支持结构化 fields。
  - 验收：`extra={"event": ..., "fields": {...}}` 被平铺到 JSON payload。
  - 验证：formatter 测试。
- [x] 扩展 `JsonLineFormatter` 支持上下文字段。
  - 验收：JSON 包含 request/session/trace/node/task 字段或按配置省略。
  - 验证：上下文日志测试。
- [x] 新增 `PrettyFormatter`。
  - 验收：输出人类可读单行，包含 event、message、request_id 前缀、node_name 和关键 fields。
  - 验证：formatter 测试。
- [x] 实现 formatter 选择逻辑。
  - 验收：`json` 固定 JSON；`pretty` 固定 pretty；`auto + local` 为 pretty；`auto + 非 local` 为 JSON。
  - 验证：formatter 测试。
- [x] 在 `configure_logging()` 挂载 `ContextFilter`。
  - 验收：`log_include_context=True` 时挂载；为 false 时不注入但日志不崩溃。
  - 验证：上下文测试。
- [x] 新增或实现结构化事件 helper。
  - 验收：可统一输出 `event/message/fields`，不强制业务方字符串拼接复杂对象。
  - 验证：formatter/helper 测试。
- [x] 对 message 与 fields 应用脱敏截断。
  - 验收：结构化字段中敏感值被脱敏、长字段被截断。
  - 验证：安全与 formatter 测试。
- [x] 确认 formatter/filter 异常不影响业务。
  - 验收：异常场景降级输出或吞掉，不向业务抛出。
  - 验证：单测 / review。

## Phase 3 — LLM trace 日志闭环

- [x] 新增 `LoggingLLMTraceSink`。
  - 验收：实现 `LLMTraceSink.write(trace)` 协议；公共类有中文 docstring。
  - 验证：`conda run -n autoGLM pytest tests/test_log_context.py tests/test_llm_tool.py`
- [x] 输出 `llm_call` 事件。
  - 验收：trace 写入日志时 `event=llm_call`。
  - 验证：caplog / formatter 测试。
- [x] 实现 fallback 日志级别升级。
  - 验收：`fallback_used=False` 为 INFO；`fallback_used=True` 为 WARNING。
  - 验证：单测。
- [x] 保留 trace 字段契约。
  - 验收：不修改 `LLMResponse.trace` 现有字段结构。
  - 验证：既有 `test_llm_tool.py` 继续通过。
- [x] 确认 trace 不含敏感正文。
  - 验收：不输出 `api_key`、`raw_input`、完整 prompt、完整 response。
  - 验证：单测 / review。
- [x] 确认 sink 异常不影响 LLM 调用。
  - 验收：logger 抛错或格式化失败时 `write()` 不向外抛。
  - 验证：单测。
- [x] 明确默认接入策略。
  - 验收：如默认接入真实 client，仍不触网；如仅提供 sink，也在计划和测试中明确。
  - 验证：review / 测试。

## Phase 4 — 运行链路事件埋点闭环

- [x] API 请求入口绑定 `request_id`。
  - 验收：每个 API 请求有 request_id；请求结束后上下文回滚。
  - 验证：API 日志测试。
- [x] `/agent` 绑定 `session_id`。
  - 验收：有 `request.session_id` 时日志带 session_id；不记录 raw_input。
  - 验证：API 测试。
- [x] 输出 `request_start` / `request_end`。
  - 验收：包含 `duration_ms`、`outcome`；异常路径保留现有 HTTPException 行为。
  - 验证：API 测试。
- [x] `Orchestrator.run()` 绑定 `node_name`。
  - 验收：每个 node 执行期间日志带 node_name，退出后回滚。
  - 验证：orchestrator 测试。
- [x] 输出 `node_start` / `node_end`。
  - 验收：包含 `duration_ms`、`outcome`、`error_count`、`trace_event_count` 等统计。
  - 验证：orchestrator 测试。
- [x] 输出 `node_error`。
  - 验收：未知 node、非法 next_node、loop limit、节点非 success 或异常路径有错误事件。
  - 验证：orchestrator 测试。
- [x] ReAct 每步输出 `react_step`。
  - 验收：包含 `step`、`tool`、`duration_ms` 或可获得的步骤统计；不含 task_input 原文。
  - 验证：`conda run -n autoGLM pytest tests/test_agentic_loop.py`
- [x] ReAct 收敛输出 `react_converged`。
  - 验收：包含 `reason`、`steps`、`tool_calls`、`fallback_used`。
  - 验证：ReAct 测试。
- [x] 工具异常输出 `tool_error`。
  - 验收：异常路径含工具名、错误码/原因，不含输入正文。
  - 验证：ReAct 工具异常测试。
- [x] 收编 `query_rewrite_failed` 字段。
  - 验收：异常降级日志使用 `fields.degrade_reason`，不记录完整 query。
  - 验证：`conda run -n autoGLM pytest tests/test_retrieval_tool.py`
- [x] 收编 `query_rewrite_empty` 字段。
  - 验收：空结果降级日志使用 `fields.degrade_reason`，不记录完整 query。
  - 验证：检索测试。
- [x] 确认业务结果不变。
  - 验收：既有 API、orchestrator、ReAct、retrieval 测试继续通过。
  - 验证：相关测试 + 全量测试。

## Phase 5 — 总体验收与提交准备

- [x] 运行日志目标测试。
  - 命令：`conda run -n autoGLM pytest tests/test_core_config_logging.py tests/test_log_context.py tests/test_security_compliance.py`
  - 验收：全部通过。
- [x] 运行关键链路回归测试。
  - 命令：`conda run -n autoGLM pytest tests/test_agent_api.py tests/test_orchestrator_engine.py tests/test_agentic_loop.py tests/test_retrieval_tool.py tests/test_llm_tool.py`
  - 验收：全部通过。
- [x] 运行全量测试。
  - 命令：`conda run -n autoGLM pytest`
  - 验收：全部通过。
- [x] 运行编译检查。
  - 命令：`conda run -n autoGLM python -m compileall app tests scripts`
  - 验收：无语法错误。
- [x] 检查本地 pretty 默认行为。
  - 验收：`environment=local` 且 `log_format=auto` 输出 pretty。
  - 验证：formatter 测试。
- [x] 检查生产 JSON 默认行为。
  - 验收：非 local 且 `log_format=auto` 输出 JSON Lines。
  - 验证：formatter 测试。
- [x] 检查日志脱敏。
  - 验收：日志不含密钥、完整 query、prompt、检索正文、原始 LLM 输入输出。
  - 验证：安全测试 / review。
- [x] 检查 diff 范围。
  - 验收：只包含本需求相关文件；无密钥、临时文件、调试代码。
  - 验证：`git status` / `git diff`。
- [x] 阶段性提交。
  - 验收：目标测试和 compileall 通过后，按 `<type>(scope): <summary>` 中文提交规范提交。
  - 验证：`git status` clean。

## 需用户另行确认的可选项

- [x] 是否引入 OpenTelemetry / Prometheus / Jaeger / structlog。
  - 默认：不引入。
- [x] 是否把日志写入文件、队列或远程服务。
  - 默认：不写入，仅沿用 stream handler。
- [x] 是否真正实现 `llm_call` 采样丢弃。
  - 默认：不实现，只保留配置占位。
- [x] 是否记录完整 query / prompt / 检索正文 / LLM 输入输出用于排障。
  - 默认：不记录。
- [x] 是否运行真实 LLM 或真实 API smoke test。
  - 默认：不运行。
