<aside>
 🧭

本 PRD 基于 GitHub 仓库 `Chenhaja/Pagent` 当前代码现状编写，沿用项目已有的 PRD / [SPEC.md](http://SPEC.md) 结构与 `PAGENT_` 配置规范，并把「本地开发调试」与「生产问题排查」两种诉求统一为一个 `log_format` 开关落地。

</aside>

## 1. Objective

### 目标

在**不改变现有业务逻辑**的前提下，把当前「零散 `logging.getLogger(__name__)` + 单一 JSON Lines」的日志体系，升级为**统一的结构化事件日志**，同时满足两类场景：

- **本地开发调试**：人类可读渲染（pretty），快速看清「跑到哪个 Node、输入输出规模、为什么降级」。
- **生产问题排查**：机器可检索的 JSON Lines，带 `request_id / session_id / trace_id` 全链路关联、结构化字段、错误堆栈，便于线上聚合检索。

两者是**同一套埋点、两种渲染**，靠配置切换，业务代码只写一次。

完成标准：

- 扩展 `app/core/logging.py`，在现有 `JsonLineFormatter` 基础上新增 `PrettyFormatter`，由 `log_format` 决定使用哪种。
- 新增 `app/core/log_context.py`，用 `contextvars` 维护 `request_id / session_id / trace_id / node_name / task_type`，并通过 logging filter 自动注入每条日志。
- 统一结构化事件名与字段 schema（见 §3.4），覆盖请求生命周期、Node 生命周期、ReAct 步、LLM 调用、检索降级。
- 把 `app/tools/llm.py` 已有的 `LLMTraceSink` / trace 字典接入统一日志管道，形成 `llm_call` 事件。
- 强化脱敏：在现有 `sanitize_log_message`（仅 `sk-` 截断）基础上扩展密钥/敏感模式，并延续「不记录完整 query / prompt / 正文」的既有约束。
- 新增非敏感配置进入 `Settings`、环境变量读取和 `to_public_dict()`。
- 默认测试不触网、不依赖真实模型。

### 目标用户

- **本地开发者**：跑 `conda run -n autoGLM ...` 时希望一眼看清阶段流转、降级原因，而不是刷一屏 JSON。
- **线上排障 / 运维**：需要用 `request_id` 串起一次请求跨 改写 Node → 编排 → ReAct → 检索 → LLM 的所有日志，并按 `event`、`level`、`node_name` 聚合。
- **测试人员**：通过日志事件断言「降级发生了、发生在哪、原因是什么」。

### 非目标

- 不引入 OpenTelemetry、Jaeger、Prometheus 等外部依赖或 SDK（本轮只做标准库 logging + contextvars）。
- 不改 `MultiQueryRetriever`、ReAct 主循环、`QANode`、编排层的**业务行为**，只加/规范埋点。
- 不新增日志存储后端、日志上报服务、异步队列。
- 不记录完整 query / prompt / 检索正文 / 密钥（延续现有 style 约束）。
- 不改 `LLMResponse.trace` 的已有字段契约，只做「接入日志管道」。

------

## 2. Commands

沿用项目 conda 环境 `autoGLM`，所有命令通过 `conda run -n autoGLM` 执行。

```bash
# 本需求目标测试
conda run -n autoGLM pytest tests/test_core_config_logging.py tests/test_log_context.py tests/test_security_compliance.py

# 全量测试
conda run -n autoGLM pytest

# 编译检查
conda run -n autoGLM python -m compileall app tests scripts
```

约束：

- 默认测试不触网、不调用真实 LLM。
- 不新增第三方依赖；如确需新增，先确认并同步 `requirements.txt`。
- 不执行破坏性 git / 文件命令。

------

## 3. Project Structure

目标结构（新增/改动）：

```
pagent/
  app/
    core/
      logging.py       # 扩展：PrettyFormatter、事件辅助函数 log_event()、配置驱动 formatter 选择
      log_context.py   # 新增：contextvars 上下文 + ContextFilter + 生成/绑定 request_id 的辅助
      config.py        # 新增 log_format / log_include_context / log_max_field_length 等配置
      security.py      # 扩展脱敏模式（复用现有 redact_sensitive_text）
  tests/
    test_core_config_logging.py  # 补新增配置默认值 / 环境变量 / public dict 断言
    test_log_context.py          # 新增：上下文注入、request_id 传播、双模式渲染
    test_security_compliance.py  # 补扩展脱敏断言
```

### 3.1 双模式渲染契约（本地 vs 生产）

`configure_logging(settings)` 根据 `settings.log_format` 选择 formatter：

| log_format     | 行为                                                         | 典型场景     |
| -------------- | ------------------------------------------------------------ | ------------ |
| `auto`（默认） | `environment == "local"` → pretty，否则 → json               | 无需手动切换 |
| `pretty`       | 人类可读单行：`时间 级别 [request_id前8位] event node_name msg key=val ...` | 本地开发调试 |
| `json`         | 现有 `JsonLineFormatter`，一行一个 JSON                      | 生产聚合检索 |

- `pretty` 与 `json` **字段来源完全一致**，只是渲染不同；不允许某些字段只在一种模式出现。
- `pretty` 模式对 `duration_ms`、`input_chars`、`output_chars`、`degraded` 等关键字段优先展示，便于开发时定位阶段与规模。
- 保留现有 `configure_logging` 签名与「清空 handlers、设置 level、加 StreamHandler」的行为，只替换 formatter 选择逻辑。

### 3.2 上下文关联契约（`app/core/log_context.py`）

```python
request_id_var: ContextVar[str | None]
session_id_var: ContextVar[str | None]
trace_id_var: ContextVar[str | None]
node_name_var: ContextVar[str | None]
task_type_var: ContextVar[str | None]

def new_request_id() -> str: ...                 # 生成短 uuid
def bind_context(**fields) -> Token: ...         # 绑定并返回可回滚 token
def reset_context(token) -> None: ...
class ContextFilter(logging.Filter): ...         # 把 contextvars 注入 record
def current_context() -> dict[str, str | None]: ...
```

要求：

- 请求入口（`app/main.py` / API handler / 一次会话处理入口）在最外层 `bind_context(request_id=new_request_id(), session_id=...)`，请求结束 `reset_context`。
- Node 执行前后 `bind_context(node_name=..., task_type=...)`，退出时回滚，保证不污染兄弟 Node。
- `ContextFilter` 注入的字段合并进每条日志；缺失时字段值为 `None`，不报错。
- 与 `llm.py` 现有 `trace_context={"node_name": ..., "task_type": ...}` 对齐：优先复用 contextvars，未显式传入时从上下文补齐。

### 3.3 LLM trace 接入契约

- 复用 `app/tools/llm.py` 现有 `LLMTraceSink` 协议与 `LLMResponse.trace`（`provider / model / input_chars / output_chars / fallback_used / duration_ms / token_usage / node_name / task_type`）。
- 新增 `LoggingLLMTraceSink`（实现 `write(trace)`）：把 trace 作为 `event="llm_call"` 的结构化日志输出，`level=INFO`；`fallback_used=True` 时升级为 `WARNING`。
- 不改 `OpenAICompatibleClient` / `FakeLLMClient` 现有 trace 构造逻辑，只提供一个把 trace 写进 logger 的 sink。
- trace 中已排除 `api_key` / `raw_input`，本 PRD 不得新增会带正文的字段。

### 3.4 结构化事件与字段 Schema

**基础字段（每条日志都有，由 formatter + ContextFilter 保证）：**

| 字段                                     | 来源        | 说明                        |
| ---------------------------------------- | ----------- | --------------------------- |
| `timestamp`                              | formatter   | UTC ISO8601                 |
| `level`                                  | logging     | 日志级别                    |
| `service` / `environment`                | settings    | 现有字段                    |
| `logger`                                 | logging     | logger 名                   |
| `event`                                  | 埋点        | 稳定英文事件名（下表）      |
| `message`                                | 埋点        | 脱敏 + 截断后的人类可读说明 |
| `request_id` / `session_id` / `trace_id` | contextvars | 全链路关联                  |
| `node_name` / `task_type`                | contextvars | 当前阶段                    |
| `exception`                              | formatter   | 有 `exc_info` 时的堆栈      |

**核心事件名（稳定英文，禁止随意改名）：**

| event                           | level     | 关键附加字段                                                 | 触发点                |
| ------------------------------- | --------- | ------------------------------------------------------------ | --------------------- |
| `request_start` / `request_end` | INFO      | `duration_ms`, `outcome`                                     | 一次请求/会话处理进出 |
| `node_start` / `node_end`       | INFO      | `node_name`, `duration_ms`, `input_chars`, `output_chars`/`result_count`, `degraded`, `degrade_reason` | 每个 Node 进出        |
| `react_step`                    | INFO      | `step`, `action`, `tool`, `duration_ms`                      | ReAct 主循环每步      |
| `react_converged`               | INFO      | `reason`, `steps`, `token_used`                              | 收敛/兜底             |
| `llm_call`                      | INFO/WARN | 见 §3.3 trace 字段                                           | 每次 LLM 调用         |
| `query_rewrite_failed`          | WARN      | 无正文                                                       | 已有，纳入规范        |
| `query_rewrite_empty`           | INFO      | 无正文                                                       | 已有，纳入规范        |
| `tool_error` / `node_error`     | ERROR     | `error_code`, `retryable`, `exception`                       | 工具/节点异常         |

- 结构化字段通过 `logger.info(msg, extra={"event": ..., "fields": {...}})` 传入，由 formatter 平铺进输出。
- **附加字段一律不含完整 query / prompt / 检索正文 / 密钥**；只允许规模（`*_chars` / `*_count`）、耗时、枚举原因、错误码。

### 3.5 配置契约（`app/core/config.py`）

新增字段：

| 配置项                 | 默认值  | 说明                                                     |
| ---------------------- | ------- | -------------------------------------------------------- |
| `log_format`           | `auto`  | `auto` / `pretty` / `json`，见 §3.1                      |
| `log_include_context`  | `true`  | 是否注入 request_id 等上下文字段                         |
| `log_max_field_length` | `205`   | 结构化字段截断长度，复用现有 205 常量口径                |
| `log_sample_llm_call`  | `false` | 预留：是否对高频 `llm_call` 采样（本轮仅占位，默认全量） |

要求：

- 环境变量一一对应，前缀 `PAGENT_`：`PAGENT_LOG_FORMAT`、`PAGENT_LOG_INCLUDE_CONTEXT`、`PAGENT_LOG_MAX_FIELD_LENGTH`、`PAGENT_LOG_SAMPLE_LLM_CALL`。
- 新增非敏感配置全部进入 `to_public_dict()`。
- 覆盖全局配置时用 `settings.xxx if arg is None else arg`，不得用 `or` 吞掉 `0` / `False`。
- 不新增单 Node 临时配置。

------

## 4. Code Style

- 最小化改动，集中在 `app/core/logging.py`、`app/core/log_context.py`、`app/core/config.py`、`app/core/security.py` 与对应测试。
- 复用现有 `sanitize_log_message` / `redact_sensitive_text`，不重复造脱敏轮子。
- 公共函数/类加中文 Google 风格 docstring（Args / Returns / Raises）。
- 事件名使用**稳定英文**；`message`、注释、docstring 使用中文（延续现有风格）。
- **禁止**记录完整 query、完整 prompt、检索正文、密钥；只记录规模、耗时、原因、错误码。
- 埋点用 `extra={"event": ..., "fields": {...}}`，不用字符串拼接把数据塞进 message。

### 错误处理

- 日志系统自身**永不**抛异常影响主流程：formatter / filter 内部异常需吞掉并降级为最简输出。
- contextvars 缺失、未绑定时字段为 `None`，不得报错。
- LLM trace sink 写日志失败不得影响 LLM 调用返回。

------

## 5. Testing Strategy

### 上下文测试（`test_log_context.py`）

- `bind_context` / `reset_context` 正确设置与回滚，兄弟 Node 不串。
- `ContextFilter` 把 `request_id / node_name` 注入 record。
- 未绑定时字段为 `None`，日志不报错。
- 同一 `request_id` 贯穿「请求→Node→LLM」多条日志。

### 双模式渲染测试

- `log_format=json` 输出可被 `json.loads` 解析，含基础字段 + `event`。
- `log_format=pretty` 输出为人类可读单行，含 `event`、`node_name`、`request_id` 前缀。
- `log_format=auto` 且 `environment=local` → pretty；其他环境 → json。

### LLM 接入测试

- `LoggingLLMTraceSink.write(trace)` 产生 `event=llm_call` 日志，含 `model / input_chars / output_chars / fallback_used`。
- `fallback_used=True` 时 level 为 `WARNING`。
- trace 不含 `api_key` / `raw_input`。

### 脱敏测试（`test_security_compliance.py`）

- `sk-xxx`、`Bearer xxx`、`password=xxx` 等被替换为 `[REDACTED]`。
- 超长字段按 `log_max_field_length` 截断并带 `...[TRUNCATED]`。
- 结构化字段中不出现完整 query / prompt。

### 配置测试（`test_core_config_logging.py`）

- `Settings` 默认 `log_format="auto"`、`log_include_context=True`、`log_max_field_length=205`。
- `PAGENT_LOG_FORMAT=pretty` / `PAGENT_LOG_INCLUDE_CONTEXT=false` / `PAGENT_LOG_MAX_FIELD_LENGTH` 可正确读取。
- `to_public_dict()` 包含新增日志配置，且不含任何 `api_key`。

### 验收口径

- 上述三份目标测试 + 全量 pytest + compileall 全绿。
- 本地 `environment=local` 默认得到 pretty 日志；生产 `environment=prod` 默认得到 JSON。
- 一次请求的所有日志可用 `request_id` 聚合。
- 关闭 `log_include_context` 时行为退回接近现状（无上下文字段），不崩溃。

------

## 6. Boundaries

### Always do

- 始终「同一埋点、双模式渲染」，pretty/json 字段一致。
- 始终注入 `request_id` 等上下文并保证回滚。
- 始终复用现有 `sanitize_log_message` / `redact_sensitive_text` / `LLMResponse.trace`。
- 始终只记录规模 / 耗时 / 原因 / 错误码，不记录正文与密钥。
- 始终保证日志系统异常不影响主流程。
- 始终用 `conda run -n autoGLM` 执行命令。

### Ask first

- 是否引入任何第三方观测依赖（OTel / structlog 等）。
- 是否改动 `LLMResponse.trace` 现有字段契约。
- 是否把日志写入文件 / 上报外部服务（本轮只 stdout）。
- 是否对 `llm_call` 真正开启采样丢弃。

### Never do

- 不记录完整 query / prompt / 检索正文 / 密钥。
- 不让 formatter / filter / sink 抛出异常打断业务。
- 不改检索、ReAct、QA、编排的业务行为。
- 不新增存储后端、队列、异步上报。
- 不给某一种渲染模式偷偷加独有字段。

------

## 7. Functional Acceptance Checklist

- [ ]  新增 `app/core/log_context.py`（contextvars + `ContextFilter` + `bind/reset/new_request_id`）。
- [ ]  `configure_logging` 按 `log_format`（auto/pretty/json）选择 formatter。
- [ ]  新增 `PrettyFormatter`，与 JSON 字段一致。
- [ ]  每条日志含 `event` + `request_id/session_id/trace_id/node_name/task_type`。
- [ ]  标准事件名落地：`request_start/end`、`node_start/end`、`react_step/converged`、`llm_call`、`*_error`，并收编现有 `query_rewrite_failed/empty`。
- [ ]  新增 `LoggingLLMTraceSink`，`llm_call` 事件接入统一管道，降级升 WARN。
- [ ]  扩展脱敏模式（Bearer / password / token），按 `log_max_field_length` 截断。
- [ ]  新增 `log_format` / `log_include_context` / `log_max_field_length` / `log_sample_llm_call` 配置 + 环境变量 + `to_public_dict()`。
- [ ]  `test_log_context.py` / 双模式 / LLM 接入 / 脱敏 / 配置测试通过。
- [ ]  `conda run -n autoGLM pytest` 通过。
- [ ]  `conda run -n autoGLM python -m compileall app tests scripts` 通过。

------

## 8. Implementation Order

1. 盘点现有 `logging.py`、`security.py`、`config.py`、`llm.py` 的 trace 与脱敏能力（已完成）。
2. 新增 `app/core/log_context.py`：contextvars、`ContextFilter`、`bind/reset/new_request_id`，配套测试。
3. 扩展 `config.py`：新增 4 个日志配置 + 环境变量 + `to_public_dict()`，补配置测试。
4. 扩展 `logging.py`：加 `PrettyFormatter`、`log_event()` 辅助、按 `log_format` 选择 formatter，并挂 `ContextFilter`。
5. 扩展 `security.py` 脱敏模式，补 `test_security_compliance.py`。
6. 新增 `LoggingLLMTraceSink`，把 LLM trace 接入 `llm_call` 事件（不改 client 逻辑）。
7. 在请求入口与各 Node 埋 `request_start/end`、`node_start/end`（结构化字段，无正文）。
8. 跑目标测试、全量 pytest、compileall。
9. 按项目提交规范，分可独立验证的小步 commit（不 `git push`，等你确认）。