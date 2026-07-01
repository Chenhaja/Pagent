# 日志与可观测性规格说明

## 1. Objective

### 目标

在不改变现有业务逻辑的前提下，将当前零散的日志体系升级为统一的结构化事件日志，支持同一套埋点在本地开发和生产排障两个场景中使用不同渲染方式。

完成标准：

- 扩展 `app/core/logging.py`，在现有 JSON Lines 输出基础上新增 `PrettyFormatter`。
- 新增 `app/core/log_context.py`，通过 `contextvars` 维护 `request_id / session_id / trace_id / node_name / task_type` 等上下文字段。
- 通过 logging filter 自动向日志记录注入上下文，缺失字段时不报错。
- 通过 `log_format` 配置支持 `auto / pretty / json` 三种模式。
- 统一结构化事件名和字段 schema，覆盖请求生命周期、Node 生命周期、ReAct 步骤、LLM 调用和检索降级。
- 将 `app/tools/llm.py` 已有 `LLMTraceSink` / trace 字典接入统一日志管道，形成 `llm_call` 事件。
- 强化日志脱敏和字段截断，不记录完整 query、prompt、检索正文、密钥或过长正文。
- 新增非敏感日志配置进入 `Settings`、环境变量读取和 `to_public_dict()`。
- 默认测试不触网、不依赖真实模型。

### 目标用户

- 本地开发者：运行流程时快速看清当前 Node、输入输出规模、耗时、降级原因。
- 线上排障 / 运维：通过 `request_id` 串起一次请求跨改写、编排、ReAct、检索、LLM 的所有日志。
- 测试人员：通过稳定事件名和字段断言降级、错误、上下文传播是否发生。

### 非目标

- 不引入 OpenTelemetry、Jaeger、Prometheus、structlog 等外部依赖或 SDK。
- 不新增日志存储后端、日志上报服务、异步队列或采样丢弃机制。
- 不改变 `MultiQueryRetriever`、ReAct 主循环、`QANode`、编排层的业务行为。
- 不修改 `LLMResponse.trace` 既有字段契约，只新增日志 sink 接入。
- 不记录完整 query、prompt、检索正文、密钥、隐私数据或过长原文。

---

## 2. Commands

项目使用 conda 环境 `autoGLM`。所有 Python、pytest、脚本命令必须通过 `conda run -n autoGLM` 执行，不能依赖 `conda activate` 的跨命令状态。

```bash
# 日志配置、formatter、上下文与脱敏目标测试
conda run -n autoGLM pytest tests/test_core_config_logging.py tests/test_log_context.py tests/test_security_compliance.py

# 全量测试
conda run -n autoGLM pytest

# 编译检查
conda run -n autoGLM python -m compileall app tests scripts
```

约束：

- 默认测试不触网、不调用真实 LLM。
- 不新增第三方依赖；如确需新增，必须先确认并同步 `requirements.txt`。
- 不执行破坏性 git / 文件命令。
- 不执行 `git push`、`git reset --hard`、强制推送等危险操作，除非用户明确确认。

---

## 3. Project Structure

目标结构：

```text
pagent/
  app/
    core/
      logging.py       # 扩展 PrettyFormatter、log_event、formatter 选择和 ContextFilter 挂载
      log_context.py   # 新增 contextvars 上下文、ContextFilter、request_id 生成与绑定/回滚
      config.py        # 新增 log_format / log_include_context / log_max_field_length / log_sample_llm_call
      security.py      # 扩展脱敏模式和截断能力
    tools/
      llm.py           # 新增 LoggingLLMTraceSink，复用现有 LLMTraceSink / trace 字段
  tests/
    test_core_config_logging.py  # 日志配置默认值、环境变量、public dict、formatter 选择
    test_log_context.py          # 上下文绑定、回滚、注入、双模式渲染、LLM trace 日志
    test_security_compliance.py  # 密钥/令牌/密码脱敏和字段截断
  SPEC.md
```

### 3.1 双模式渲染契约

`configure_logging(settings)` 根据 `settings.log_format` 选择 formatter：

| `log_format` | 行为 | 典型场景 |
| --- | --- | --- |
| `auto` | `environment == "local"` 时使用 pretty，否则使用 json | 默认模式 |
| `pretty` | 人类可读单行，展示时间、级别、request_id 前缀、event、node_name、message 和关键字段 | 本地开发调试 |
| `json` | 一行一个 JSON，保留现有 JSON Lines 思路 | 生产聚合检索 |

要求：

- pretty 与 json 使用同一份日志 record 和字段来源，只改变渲染方式。
- 不允许字段只在某一种渲染模式中存在。
- `pretty` 优先展示 `duration_ms`、`input_chars`、`output_chars`、`result_count`、`degraded`、`degrade_reason` 等排障字段。
- 保留 `configure_logging` 清空 handlers、设置 level、添加 `StreamHandler` 的既有行为。
- formatter / filter 内部异常不得影响业务流程，必要时降级为最简输出。

### 3.2 上下文关联契约

新增 `app/core/log_context.py`：

```python
request_id_var: ContextVar[str | None]
session_id_var: ContextVar[str | None]
trace_id_var: ContextVar[str | None]
node_name_var: ContextVar[str | None]
task_type_var: ContextVar[str | None]

def new_request_id() -> str: ...
def bind_context(**fields) -> object: ...
def reset_context(token: object) -> None: ...
def current_context() -> dict[str, str | None]: ...
class ContextFilter(logging.Filter): ...
```

要求：

- `new_request_id()` 生成短 UUID 或等价稳定随机 ID，用于一次请求/会话关联。
- `bind_context(...)` 绑定传入字段，并返回可用于回滚的 token。
- `reset_context(token)` 回滚上下文，避免兄弟 Node 串上下文。
- `current_context()` 返回当前上下文字段字典。
- `ContextFilter` 将上下文字段注入 logging record。
- 未绑定上下文时字段值为 `None`，不得抛异常。
- `log_include_context=false` 时不注入上下文字段，日志系统仍正常工作。

### 3.3 结构化事件契约

基础字段由 formatter、settings、logging record 和 ContextFilter 保证：

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `timestamp` | formatter | UTC ISO8601 时间 |
| `level` | logging | 日志级别 |
| `service` | settings | 服务名 |
| `environment` | settings | 环境名 |
| `logger` | logging | logger 名称 |
| `event` | 埋点 | 稳定英文事件名 |
| `message` | 埋点 | 脱敏、截断后的人类可读中文说明 |
| `request_id` / `session_id` / `trace_id` | contextvars | 链路关联字段 |
| `node_name` / `task_type` | contextvars | 当前业务阶段 |
| `exception` | formatter | 有 `exc_info` 时输出堆栈 |

核心事件名：

| event | level | 关键附加字段 | 触发点 |
| --- | --- | --- | --- |
| `request_start` / `request_end` | INFO | `duration_ms`, `outcome` | 一次请求或会话处理进出 |
| `node_start` / `node_end` | INFO | `duration_ms`, `input_chars`, `output_chars`, `result_count`, `degraded`, `degrade_reason` | 每个 Node 进出 |
| `react_step` | INFO | `step`, `action`, `tool`, `duration_ms` | ReAct 主循环每步 |
| `react_converged` | INFO | `reason`, `steps`, `token_used` | ReAct 收敛或兜底 |
| `llm_call` | INFO/WARNING | `provider`, `model`, `input_chars`, `output_chars`, `fallback_used`, `duration_ms`, `token_usage` | 每次 LLM 调用 |
| `query_rewrite_failed` | WARNING | `degrade_reason`，不得含正文 | 查询改写失败并降级 |
| `query_rewrite_empty` | INFO | `degrade_reason`，不得含正文 | 查询改写为空并降级 |
| `tool_error` / `node_error` | ERROR | `error_code`, `retryable`, `exception` | 工具或节点异常 |

要求：

- 结构化字段通过 `extra={"event": ..., "fields": {...}}` 传入，由 formatter 平铺进输出。
- 附加字段不得包含完整 query、prompt、检索正文、密钥或隐私数据。
- 允许记录规模、数量、耗时、枚举原因、错误码、是否降级等信息。
- 事件名必须稳定英文，`message` 使用中文。

### 3.4 LLM trace 接入契约

在 `app/tools/llm.py` 中新增 `LoggingLLMTraceSink`，实现现有 `LLMTraceSink` 协议：

```python
class LoggingLLMTraceSink:
    """将 LLM trace 写入统一结构化日志。"""

    def write(self, trace: dict[str, object]) -> None: ...
```

要求：

- 复用现有 `LLMResponse.trace` 字段，不修改 trace 字段契约。
- `write(trace)` 输出 `event="llm_call"` 的结构化日志。
- `fallback_used=True` 时日志级别为 `WARNING`，否则为 `INFO`。
- trace 写日志失败不得影响 LLM 调用返回。
- trace 中不得新增 `api_key`、`raw_input`、完整 prompt、完整 response 等正文字段。
- `node_name` / `task_type` 优先使用 trace 中显式字段；缺失时由上下文补齐。

### 3.5 脱敏与截断契约

扩展现有 `app/core/security.py` 或日志清洗逻辑，复用已有 `sanitize_log_message` / `redact_sensitive_text` 思路。

要求：

- `sk-...`、`Bearer ...`、`password=...`、`token=...`、`api_key=...` 等敏感模式必须被替换为 `[REDACTED]` 或等价占位符。
- 字符串字段超过 `log_max_field_length` 时截断，并追加 `...[TRUNCATED]` 或等价稳定标记。
- 脱敏和截断应用于 `message` 与结构化 `fields`。
- 不把完整 query、prompt、检索正文作为字段传入日志；脱敏是兜底，不是记录正文的许可。

### 3.6 配置契约

`app/core/config.py` 新增日志配置：

| 配置项 | 默认值 | 环境变量 | 说明 |
| --- | --- | --- | --- |
| `log_format` | `auto` | `PAGENT_LOG_FORMAT` | `auto / pretty / json` |
| `log_include_context` | `true` | `PAGENT_LOG_INCLUDE_CONTEXT` | 是否注入上下文字段 |
| `log_max_field_length` | `205` | `PAGENT_LOG_MAX_FIELD_LENGTH` | 字符串字段最大长度 |
| `log_sample_llm_call` | `false` | `PAGENT_LOG_SAMPLE_LLM_CALL` | 本轮仅占位，默认不采样丢弃 |

要求：

- 新增非敏感配置全部进入 `to_public_dict()`。
- API key、token、secret、password 等敏感配置不得进入 `to_public_dict()`、日志或 trace。
- 配置项保持全局通用作用域，不新增单 Node 临时配置。
- 构造参数覆盖全局配置时使用 `settings.xxx if arg is None else arg`，避免吞掉 `0` / `False`。
- `log_sample_llm_call` 本轮只作为公开配置占位，不实际丢弃日志；如要实现采样丢弃需另行确认。

---

## 4. Code Style

### 基本原则

- 最小化、局部化改动，优先集中在 `app/core/logging.py`、`app/core/log_context.py`、`app/core/config.py`、`app/core/security.py`、`app/tools/llm.py` 与对应测试。
- 复用现有 logging、security、LLM trace 能力，不重复造脱敏轮子。
- 不新增外部依赖，不引入日志存储、队列或上报服务。
- 公共函数、公共方法、公共类必须添加中文 Google 风格 docstring，包含 Args / Returns / Raises（如有）。
- 简单私有 helper 可使用一行中文概述。
- 注释和 `message` 沿用中文风格；结构化 `event` 使用稳定英文。
- 日志字段必须参数化输出，禁止通过字符串拼接复杂对象塞进 message。
- 不记录完整 query、prompt、检索正文、原始 LLM 输入输出、密钥或隐私数据。

### 错误处理与兜底

- 日志系统自身永不抛异常影响主流程。
- formatter、filter、trace sink 内部异常必须吞掉或降级处理。
- contextvars 未绑定或字段缺失时输出 `None` 或省略字段，不得报错。
- LLM trace 写日志失败不得影响 LLM 调用结果。
- 不为日志写入失败引入重试、队列、熔断或后台线程。

---

## 5. Testing Strategy

### 上下文测试

`tests/test_log_context.py` 必须覆盖：

- `bind_context` / `reset_context` 正确设置与回滚上下文字段。
- 兄弟 Node 的 `node_name` / `task_type` 不串上下文。
- `current_context()` 返回当前上下文快照。
- `ContextFilter` 将 `request_id`、`session_id`、`trace_id`、`node_name`、`task_type` 注入 record。
- 未绑定上下文时日志不报错，字段为 `None` 或按配置省略。
- 同一 `request_id` 能贯穿请求、Node、LLM 多条日志。

### 双模式渲染测试

必须覆盖：

- `log_format=json` 输出可被 `json.loads` 解析。
- JSON 输出包含基础字段、`event` 和 `message`。
- `log_format=pretty` 输出为人类可读单行，包含 `event`、`node_name`、`request_id` 前缀和关键字段。
- `log_format=auto` 且 `environment=local` 时使用 pretty。
- `log_format=auto` 且非 local 环境时使用 json。
- pretty 与 json 的字段来源一致，不出现模式私有字段。

### LLM 接入测试

必须覆盖：

- `LoggingLLMTraceSink.write(trace)` 产生 `event=llm_call` 日志。
- 日志包含 `provider`、`model`、`input_chars`、`output_chars`、`fallback_used`、`duration_ms`。
- `fallback_used=False` 时 level 为 `INFO`。
- `fallback_used=True` 时 level 为 `WARNING`。
- trace 不含 `api_key`、`raw_input`、完整 prompt、完整 response。
- sink 写日志异常不向外抛出。

### 脱敏测试

`tests/test_security_compliance.py` 必须覆盖：

- `sk-...` 被脱敏。
- `Bearer ...` 被脱敏。
- `password=...` / `token=...` / `api_key=...` 被脱敏。
- 超长字符串字段按 `log_max_field_length` 截断并带稳定截断标记。
- `message` 与结构化 `fields` 均应用脱敏和截断。
- 结构化字段中不出现完整 query / prompt / 检索正文。

### 配置测试

`tests/test_core_config_logging.py` 必须覆盖：

- `Settings` 默认 `log_format="auto"`。
- `Settings` 默认 `log_include_context=True`。
- `Settings` 默认 `log_max_field_length=205`。
- `Settings` 默认 `log_sample_llm_call=False`。
- `PAGENT_LOG_FORMAT=pretty` 能正确读取。
- `PAGENT_LOG_INCLUDE_CONTEXT=false` 能正确读取为布尔值。
- `PAGENT_LOG_MAX_FIELD_LENGTH` 能正确读取为整数。
- `PAGENT_LOG_SAMPLE_LLM_CALL=true` 能正确读取为布尔值。
- `to_public_dict()` 包含新增非敏感日志配置。
- `to_public_dict()` 不包含 API key、token、secret、password。

### 验收口径

- `conda run -n autoGLM pytest tests/test_core_config_logging.py tests/test_log_context.py tests/test_security_compliance.py` 通过。
- `conda run -n autoGLM pytest` 通过。
- `conda run -n autoGLM python -m compileall app tests scripts` 通过。
- 本地 `environment=local` 且 `log_format=auto` 默认得到 pretty 日志。
- 生产环境且 `log_format=auto` 默认得到 JSON Lines 日志。
- 一次请求的日志可通过同一 `request_id` 聚合。
- 关闭 `log_include_context` 时行为接近现状且不崩溃。
- 默认测试不触网、不调用真实模型。

---

## 6. Boundaries

### Always do

- 始终保持同一套埋点、两种渲染，pretty/json 字段来源一致。
- 始终使用稳定英文 `event` 和中文 `message`。
- 始终通过 contextvars 注入并回滚 `request_id`、`node_name` 等上下文。
- 始终复用现有 `sanitize_log_message`、`redact_sensitive_text`、`LLMResponse.trace` 能力。
- 始终只记录规模、耗时、数量、原因、错误码、是否降级等排障信息。
- 始终保证 formatter、filter、sink 异常不影响主流程。
- 始终使用 `conda run -n autoGLM` 执行 Python、pytest 和脚本命令。

### Ask first

- 是否引入任何第三方观测依赖或 SDK。
- 是否接入 OpenTelemetry、Prometheus、Jaeger、日志上报服务或外部存储。
- 是否修改 `LLMResponse.trace` 现有字段契约。
- 是否把日志写入文件、队列或远程服务。
- 是否真正实现 `llm_call` 采样丢弃。
- 是否记录完整 query、prompt、检索正文或 LLM 输入输出用于排障。
- 是否改动检索、ReAct、QA、编排的业务行为。

### Never do

- 不记录完整 query、prompt、检索正文、原始 LLM 输入输出、密钥或隐私数据。
- 不让日志系统异常打断业务流程。
- 不修改检索、ReAct、QA、编排的业务语义。
- 不新增日志存储后端、异步队列、上报服务或复杂重试机制。
- 不为 pretty/json 任一模式添加独有字段。
- 不在默认测试中触网、调用真实 LLM 或下载模型。
- 不将 API key、token、secret、password 输出到日志、trace 或 `to_public_dict()`。

---

## 7. Functional Acceptance Checklist

- [ ] 新增 `app/core/log_context.py`。
- [ ] 实现 `new_request_id()`、`bind_context()`、`reset_context()`、`current_context()`。
- [ ] 实现 `ContextFilter` 并支持缺失上下文安全注入。
- [ ] 扩展 `Settings`：`log_format`、`log_include_context`、`log_max_field_length`、`log_sample_llm_call`。
- [ ] 新增对应 `PAGENT_` 环境变量读取。
- [ ] 新增日志配置进入 `to_public_dict()`，且不暴露敏感配置。
- [ ] 扩展 `app/core/logging.py`，支持 `PrettyFormatter`。
- [ ] `configure_logging` 按 `log_format=auto/pretty/json` 选择 formatter。
- [ ] JSON 与 pretty 输出字段来源一致。
- [ ] 支持 `extra={"event": ..., "fields": {...}}` 并平铺结构化字段。
- [ ] 扩展脱敏模式，覆盖 `sk-`、`Bearer`、`password`、`token`、`api_key`。
- [ ] 支持按 `log_max_field_length` 截断 `message` 与结构化字段。
- [ ] 新增 `LoggingLLMTraceSink`。
- [ ] `LoggingLLMTraceSink` 输出 `llm_call` 事件。
- [ ] `fallback_used=True` 时 `llm_call` 使用 WARNING。
- [ ] 收编现有 `query_rewrite_failed` / `query_rewrite_empty` 日志到结构化事件规范。
- [ ] 在请求入口和 Node 生命周期补充 `request_start/end`、`node_start/end` 埋点。
- [ ] ReAct 主循环补充 `react_step`、`react_converged` 埋点。
- [ ] `tests/test_log_context.py` 覆盖上下文绑定、回滚、注入和双模式渲染。
- [ ] `tests/test_core_config_logging.py` 覆盖新增日志配置。
- [ ] `tests/test_security_compliance.py` 覆盖脱敏与截断。
- [ ] 目标测试通过。
- [ ] 全量 pytest 通过。
- [ ] compileall 通过。

---

## 8. Implementation Order

1. 盘点现有 `app/core/logging.py`、`app/core/security.py`、`app/core/config.py`、`app/tools/llm.py` 的日志、trace 与脱敏能力。
2. 新增 `app/core/log_context.py`，实现 contextvars、`ContextFilter`、绑定与回滚能力，并补上下文测试。
3. 扩展 `app/core/config.py`，新增日志配置、环境变量读取和 `to_public_dict()`，并补配置测试。
4. 扩展 `app/core/logging.py`，新增 `PrettyFormatter`、结构化字段平铺、formatter 选择和 ContextFilter 挂载。
5. 扩展 `app/core/security.py` 或日志清洗逻辑，补敏感字段脱敏和截断能力。
6. 新增 `LoggingLLMTraceSink`，将 LLM trace 接入 `llm_call` 事件。
7. 在请求入口、Node 生命周期、ReAct 主循环和查询改写降级路径补充结构化事件埋点。
8. 运行目标测试、全量 pytest 和 compileall。
9. 每完成一个可独立验证阶段，按项目提交规范单独 commit；不执行 `git push`，等待用户确认。
