# 日志与可观测性实施计划

## 背景

当前项目已有 `app/core/logging.py::JsonLineFormatter`，默认输出 JSON Lines 基础字段；`app/core/security.py::redact_sensitive_text()` 只覆盖 `sk-` 样式密钥；`app/tools/llm.py` 已有 `LLMTraceSink` 协议和不含完整输入输出的 trace；`app/tools/retrieval.py::MultiQueryRetriever._expand_queries()` 已记录 `query_rewrite_failed` / `query_rewrite_empty` 事件名但字段较少；API 入口、编排器、ReAct 主循环尚未统一注入 `request_id / node_name` 等上下文。

本阶段目标是按 `SPEC.md` 建立统一结构化事件日志：同一套埋点支持 `json` 与 `pretty` 两种渲染，通过 `contextvars` 关联请求、节点和 LLM 调用；补齐配置、脱敏、LLM trace sink、请求/Node/ReAct/检索降级事件。实现阶段不改变检索、ReAct、QA 或编排业务语义。

本计划只拆解实现路径与验收任务；实现阶段再修改业务代码。

## 当前代码基线

- `app/core/logging.py`
  - 已有 `MAX_LOG_MESSAGE_LENGTH=205`、`sanitize_log_message()`、`JsonLineFormatter`、`configure_logging(settings)`。
  - `JsonLineFormatter` 当前只输出 `timestamp / level / service / environment / logger / event / message / exception`。
  - 尚未平铺 `extra={"fields": ...}`，未注入上下文字段，未支持 pretty/auto。
- `app/core/config.py`
  - `Settings` 已有 `service_name / environment / log_level`。
  - 缺 `log_format / log_include_context / log_max_field_length / log_sample_llm_call`。
  - `get_settings()` 已有 `_get_bool_env()`，可复用读取布尔配置。
  - `to_public_dict()` 已排除 key 类敏感字段，需要加入日志非敏感配置。
- `app/core/security.py`
  - `redact_sensitive_text()` 只覆盖 `sk-` 并按长度截断。
  - 可作为日志 message 与 fields 清洗的底层能力。
- `app/tools/llm.py`
  - 已有 `LLMTraceSink`、`InMemoryLLMTraceSink`、`FakeLLMClient(trace_sink=...)`。
  - `FakeLLMClient` 和 `OpenAICompatibleClient` 已构造 `provider/model/input_chars/output_chars/fallback_used/...` trace，并调用 sink。
  - 缺 `LoggingLLMTraceSink`。
- `app/api/routes.py`
  - API handler 是请求生命周期事件和 `request_id/session_id` 绑定的合适入口。
  - `/agent` 请求包含 `session_id`；其他接口可仅绑定 `request_id`。
- `app/orchestrator/engine.py`
  - `Orchestrator.run()` 按 node 执行，是 `node_start/node_end/node_error` 的集中埋点点。
  - `NodeResult` 已包含状态、错误、trace_events，可用于输出 outcome 和统计。
- `app/orchestrator/react_loop.py`
  - `BoundedReActLoop.run()` 已维护 `step_index/tool_name/reason/steps_used/tool_calls/fallback_used` 等信息。
  - 可在不改变决策语义的前提下补 `react_step`、`react_converged` 日志。
- `app/tools/retrieval.py`
  - `MultiQueryRetriever._expand_queries()` 已使用 `logger.warning/info(..., extra={"event": ...})` 记录查询改写降级。
  - 需要按统一 `fields` schema 补 `degrade_reason` 等字段，且不记录完整 query。
- `tests/`
  - `tests/test_core_config_logging.py` 已覆盖配置、JSON formatter、敏感配置不公开。
  - `tests/test_security_compliance.py` 已覆盖 `sk-` 脱敏和长文本截断。
  - 缺 `tests/test_log_context.py`。

## 依赖图

```text
SPEC.md
  -> Config contract
      -> app/core/config.py                    # Settings 字段、env 读取、to_public_dict
      -> tests/test_core_config_logging.py
      -> app/core/logging.py                   # formatter 选择依赖 log_format/log_include_context/log_max_field_length

  -> Redaction contract
      -> app/core/security.py                  # 扩展敏感模式与截断
      -> app/core/logging.py                   # 清洗 message 和 fields
      -> tests/test_security_compliance.py

  -> Context contract
      -> app/core/log_context.py               # contextvars、ContextFilter、bind/reset/current
      -> app/core/logging.py                   # configure_logging 挂 filter
      -> app/api/routes.py                     # request_id/session_id 绑定
      -> app/orchestrator/engine.py            # node_name/task_type 绑定
      -> tests/test_log_context.py

  -> Structured formatter contract
      -> app/core/logging.py                   # JsonLineFormatter 扩展、PrettyFormatter、log_event
      -> tests/test_core_config_logging.py
      -> tests/test_log_context.py

  -> LLM trace logging contract
      -> app/tools/llm.py                      # LoggingLLMTraceSink
      -> app/core/logging.py                   # llm_call 字段平铺和脱敏
      -> tests/test_log_context.py 或 tests/test_llm_tool.py

  -> Runtime event instrumentation
      -> app/api/routes.py                     # request_start/request_end
      -> app/orchestrator/engine.py            # node_start/node_end/node_error
      -> app/orchestrator/react_loop.py        # react_step/react_converged/tool_error
      -> app/tools/retrieval.py                # query_rewrite_failed/query_rewrite_empty fields
      -> existing service/node/react/retrieval tests

  -> final verification
      -> tests/test_core_config_logging.py
      -> tests/test_log_context.py
      -> tests/test_security_compliance.py
      -> pytest / compileall
```

## 垂直切片原则

每个阶段交付一条可验证路径，而不是只改一层：

1. 先补配置与脱敏，使后续 formatter/context/LLM sink 共用稳定开关和清洗能力。
2. 再实现上下文与双模式 formatter，形成“写一条事件 → 自动上下文 → json/pretty 输出”的基础闭环。
3. 再接 LLM trace sink，证明现有 LLM trace 可进入统一日志管道且不改变 LLMResponse 契约。
4. 再接请求、Node、ReAct、检索降级埋点，逐步覆盖关键链路。
5. 最后运行目标测试、全量测试、编译检查，并按项目规范分阶段提交。

---

## Phase 0 — 口径确认与基线锁定

### 目标

确认本需求只做日志与可观测性增强，不改变业务语义、不引入外部依赖、不新增日志存储或上报。

### 实施要点

- 默认仍使用标准库 `logging` 和 `contextvars`。
- `log_format=auto` 在 `environment=local` 时走 pretty，其他环境走 json。
- `log_sample_llm_call` 本轮只作为公开配置占位，不实际采样丢弃。
- 不记录完整 query、prompt、检索正文、原始 LLM 输入输出、密钥或隐私数据。
- 默认测试不触网、不调用真实模型。

### 验收标准

- plan / todo 明确上述边界。
- 后续任务不包含 OTel/Prometheus/外部日志系统、业务逻辑重写或真实 LLM 调用。

### Checkpoint 0

确认计划后进入测试优先实现。

---

## Phase 1 — 配置与脱敏基础闭环

### 目标

建立日志开关和字段清洗能力，为 formatter、context filter、LLM trace sink 共用。

### 任务

1. 扩展 `Settings` 日志配置。
   - 新增 `log_format: str = "auto"`。
   - 新增 `log_include_context: bool = True`。
   - 新增 `log_max_field_length: int = 205`。
   - 新增 `log_sample_llm_call: bool = False`。
   - 更新 `Settings` docstring、`get_settings()` 环境变量读取、`to_public_dict()`。
2. 补配置测试。
   - 默认值测试。
   - `PAGENT_LOG_FORMAT`、`PAGENT_LOG_INCLUDE_CONTEXT`、`PAGENT_LOG_MAX_FIELD_LENGTH`、`PAGENT_LOG_SAMPLE_LLM_CALL` 环境变量读取。
   - public dict 包含新增非敏感日志配置，不包含 key/token/secret/password。
3. 扩展脱敏能力。
   - 在 `redact_sensitive_text()` 或共用清洗函数中覆盖 `sk-...`、`Bearer ...`、`password=...`、`token=...`、`api_key=...`。
   - 保持可传入 `max_length` 并追加稳定截断标记。
4. 补脱敏测试。
   - 覆盖 Bearer、password、token、api_key。
   - 覆盖超长字段截断。

### 验收标准

- 日志配置可通过环境变量覆盖，并安全进入 `to_public_dict()`。
- 脱敏函数不输出密钥类原文。
- 不新增依赖，不触网。

### 验证步骤

```bash
conda run -n autoGLM pytest tests/test_core_config_logging.py tests/test_security_compliance.py
```

### Checkpoint 1

配置和脱敏通过后，再实现上下文与 formatter，避免重复清洗逻辑。

---

## Phase 2 — 上下文与双模式 formatter 闭环

### 目标

实现“绑定上下文 → 记录结构化事件 → json/pretty 两种渲染”的基础日志管道。

### 任务

1. 新增 `app/core/log_context.py`。
   - 定义 `request_id_var / session_id_var / trace_id_var / node_name_var / task_type_var`。
   - 实现 `new_request_id()`。
   - 实现 `bind_context(**fields)` 和 `reset_context(token)`，支持回滚多个字段。
   - 实现 `current_context()`。
   - 实现 `ContextFilter(logging.Filter)`，将上下文字段注入 record。
2. 扩展 `app/core/logging.py`。
   - 复用统一脱敏/截断清洗 message。
   - 支持 `extra={"event": ..., "fields": {...}}`，将 fields 清洗后平铺到输出 payload。
   - 扩展 `JsonLineFormatter` 输出上下文字段和 fields。
   - 新增 `PrettyFormatter`，使用同一字段来源输出人类可读单行。
   - 新增 `log_event(logger, level, event, message, **fields)` 或等价 helper，降低埋点重复。
   - `configure_logging(settings)` 根据 `log_format` 选择 formatter，并按 `log_include_context` 挂载 `ContextFilter`。
3. 补 `tests/test_log_context.py`。
   - bind/reset/current_context。
   - 兄弟 Node 上下文不串。
   - ContextFilter 注入 record。
   - 未绑定字段安全为 `None` 或按配置省略。
   - json 输出可 `json.loads`。
   - pretty 输出包含 `event`、`node_name`、`request_id` 前缀和关键字段。
   - auto + local -> pretty；auto + prod -> json。

### 验收标准

- json 与 pretty 字段来源一致。
- formatter/filter 异常不影响主流程。
- `log_include_context=false` 时日志仍可正常输出。
- 结构化字段经过脱敏和截断。

### 验证步骤

```bash
conda run -n autoGLM pytest tests/test_core_config_logging.py tests/test_log_context.py tests/test_security_compliance.py
```

### Checkpoint 2

基础日志管道通过后，再接 LLM trace sink。

---

## Phase 3 — LLM trace 日志闭环

### 目标

将现有 `LLMTraceSink` 接入统一日志管道，形成 `llm_call` 事件，不修改 `LLMResponse.trace` 字段契约。

### 任务

1. 在 `app/tools/llm.py` 新增 `LoggingLLMTraceSink`。
   - 实现 `write(trace)`。
   - 输出 `event="llm_call"`。
   - `fallback_used=True` 时使用 WARNING，否则 INFO。
   - 将 trace 作为 `fields` 输出，不添加完整 prompt/response/raw_input/api_key。
   - sink 内部异常吞掉，不影响 LLM 调用返回。
2. 补 LLM trace sink 测试。
   - `FakeLLMClient(trace_sink=LoggingLLMTraceSink(...))` 或直接调用 sink 产生 `llm_call`。
   - 断言 `provider/model/input_chars/output_chars/fallback_used/duration_ms` 等字段输出。
   - 断言 fallback 升级 WARNING。
   - 断言 sink 写日志异常不抛出。
   - 断言日志不含 `api_key/raw_input` 或完整正文。
3. 根据需要调整 `build_llm_client()`。
   - 若 SPEC 要求默认接入日志 sink，则在真实 client 构造时传入或保持显式注入路径。
   - 不改变默认缺配置时返回 Fake 的安全行为。

### 验收标准

- LLM trace 可进入统一结构化日志。
- 不改变 `LLMClient.generate(...)` 返回结构和 trace 字段契约。
- sink 失败不影响调用方。

### 验证步骤

```bash
conda run -n autoGLM pytest tests/test_log_context.py tests/test_llm_tool.py
```

### Checkpoint 3

LLM trace 日志闭环通过后，再接请求、Node、ReAct 和检索降级埋点。

---

## Phase 4 — 运行链路事件埋点闭环

### 目标

在关键执行路径补稳定事件，覆盖请求生命周期、Node 生命周期、ReAct 步骤与检索降级，同时不改变业务结果。

### 任务

1. API 请求生命周期埋点。
   - 在 `app/api/routes.py` 或 FastAPI middleware 中为请求绑定 `request_id`。
   - `/agent` 额外绑定 `session_id=request.session_id`。
   - 输出 `request_start` / `request_end`，包含 `duration_ms`、`outcome`，不含完整请求正文。
   - 异常路径保留现有 HTTPException 行为并输出失败 outcome。
2. Node 生命周期埋点。
   - 在 `app/orchestrator/engine.py::Orchestrator.run()` 执行每个 node 前绑定 `node_name`。
   - 输出 `node_start` / `node_end` / `node_error`。
   - 字段包含 `duration_ms`、`outcome`、`error_count`、`trace_event_count` 等统计。
   - 确保 reset_context 在成功、失败、异常路径都会执行。
3. ReAct 主循环埋点。
   - 在 `app/orchestrator/react_loop.py::BoundedReActLoop.run()` 每步输出 `react_step`。
   - 收敛时输出 `react_converged`，包含 `reason`、`steps`、`tool_calls`、`fallback_used`。
   - 工具异常路径输出 `tool_error`，不记录 task_input 原文。
4. 检索查询改写降级事件收编。
   - 调整 `MultiQueryRetriever._expand_queries()` 的 `extra` 为 `{"event": ..., "fields": {"degrade_reason": ...}}`。
   - 不记录完整 query 或扩展 query。
5. 补/调整测试。
   - API 请求日志可通过 caplog 或测试 client 捕获事件。
   - Orchestrator 成功/失败节点事件。
   - ReAct 成功、工具异常、收敛事件。
   - Query rewrite failed/empty 事件字段。

### 验收标准

- 一次请求的日志可用同一 `request_id` 聚合。
- Node 上下文退出后不污染后续节点。
- ReAct 日志只含步骤、工具名、数量、耗时、原因，不含完整输入正文。
- 检索降级行为保持不变，只增强日志字段。

### 验证步骤

```bash
conda run -n autoGLM pytest tests/test_log_context.py tests/test_agent_api.py tests/test_orchestrator_engine.py tests/test_agentic_loop.py tests/test_retrieval_tool.py
```

### Checkpoint 4

关键链路事件通过后，进入总体验收。

---

## Phase 5 — 总体验收与提交准备

### 目标

跑完目标测试、全量测试和编译检查，确认本阶段可以独立提交。

### 任务

1. 运行目标测试。
2. 运行相关回归测试。
3. 运行全量测试。
4. 运行 compileall。
5. 检查 git diff，确认只包含本需求相关文件。
6. 如实现阶段形成可独立验证改动，按项目规范分阶段 commit。

### 验收标准

- 目标测试通过。
- 全量测试通过。
- 编译检查通过。
- 默认测试无真实 LLM / 网络调用。
- `environment=local` + `log_format=auto` 默认 pretty。
- 非 local + `log_format=auto` 默认 JSON Lines。
- 日志不输出密钥、完整 query、prompt、检索正文或原始 LLM 输入输出。

### 验证步骤

```bash
conda run -n autoGLM pytest tests/test_core_config_logging.py tests/test_log_context.py tests/test_security_compliance.py
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests scripts
```

### Checkpoint 5

提交前请用户确认是否需要：

- 接入外部日志系统或 OTel。
- 将日志写入文件。
- 对 `llm_call` 真正开启采样丢弃。
- 运行真实 LLM / API smoke test。

---

## 风险与控制

- **日志泄露敏感信息**：只记录规模、耗时、数量、原因、错误码；message 和 fields 双重脱敏截断。
- **上下文串线**：`bind_context()` 必须配套 `reset_context()`，Node 和请求入口使用 try/finally。
- **formatter 破坏业务**：formatter/filter/sink 内部捕获异常并降级，不向外抛。
- **测试输出格式脆弱**：json 测试断言字段，pretty 测试只断言关键片段和字段，不依赖完整字符串。
- **过度改造风险**：不引入外部依赖、不新增日志后端、不改变业务算法。
- **日志量增长**：本轮不做采样丢弃，只保留配置占位；如需采样另行确认。

## 文件改动清单

计划中的实现阶段会涉及：

- `app/core/config.py`：新增日志配置、环境变量读取、public dict。
- `app/core/security.py`：扩展脱敏模式和截断能力。
- `app/core/log_context.py`：新增上下文管理与 logging filter。
- `app/core/logging.py`：扩展 JSON formatter、新增 pretty formatter、结构化字段清洗和平铺。
- `app/tools/llm.py`：新增 `LoggingLLMTraceSink`。
- `app/api/routes.py`：请求生命周期上下文和事件。
- `app/orchestrator/engine.py`：Node 生命周期上下文和事件。
- `app/orchestrator/react_loop.py`：ReAct step/converged/tool_error 事件。
- `app/tools/retrieval.py`：查询改写降级事件字段规范化。
- `tests/test_core_config_logging.py`：日志配置和 formatter 测试。
- `tests/test_log_context.py`：新增上下文、双模式、LLM sink 测试。
- `tests/test_security_compliance.py`：脱敏和截断测试。
- 相关现有 API / orchestrator / react / retrieval 测试：补事件断言或更新格式断言。

不计划修改：

- `requirements.txt`。
- `LLMResponse.trace` 字段契约。
- 检索、ReAct、QA、编排的业务语义。
- embedding / Qdrant / rerank 主逻辑。
- 日志存储、队列、远程上报配置。
