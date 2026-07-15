# Pagent create_agent Middleware Trace 规格

## 1. Objective

### 1.1 背景

当前项目已经完成 `WorkflowTraceEvent` schema、`WorkflowTraceEmitter`、logger sink、progress projection，以及 `DraftingParseInputNode` 到 `WorkflowState.trace` 的汇总链路。现有试点能把 `LangChainInputParserAgent` 的 agent / tool 活动写入 workflow trace，但实现方式是在 `LangChainInputParserAgent` 的工具 wrapper 中手写 `_emit_agent_event()` / `_emit_tool_event()`。

这类手写 wrapper trace 适合验证 schema 和汇总链路，但不适合继续推广：

- 每个 create_agent runner 都要重复写 started / completed / failed 打点。
- 每个工具函数混入 trace 采集逻辑，业务工具和可观测性耦合。
- 每个 node 单独注入、收集 tool trace，推广到多个 agent node 后会产生大量模板代码。
- 手写 wrapper 只能覆盖我们显式包裹的 tool call，不能系统性表达 create_agent 内部的 model call、agent step / reasoning step 等活动。

本阶段目标是：**用 LangChain 官方 create_agent middleware / callback / stream events 能力完全替代当前 `LangChainInputParserAgent` 中的手写 wrapper trace 事件**，并继续输出项目统一的 `WorkflowTraceEvent`，由现有 `NodeResult.trace_events` / `WorkflowState.trace` 管理。

### 1.2 目标

- create_agent 内部 trace 采集来源改为 LangChain 官方 middleware / callback / stream events。
- 移除或停止使用 `LangChainInputParserAgent` 中手写的 `_emit_agent_event()` / `_emit_tool_event()` wrapper 事件。
- middleware 捕获 create_agent 内部调用事件，并通过 adapter 转换为 `WorkflowTraceEvent`。
- 覆盖不止 tool call，还要覆盖：
  - agent started / completed / failed；
  - model call started / completed / failed；
  - tool call started / completed / failed；
  - agent step / reasoning step。
- 工具函数继续只负责业务安全边界，例如 artifact key 白名单、附件路径限制、受控读写；middleware 只负责捕获调用事件。
- trace 内容必须经过脱敏 / 摘要转换，禁止把 LangChain 原始输入输出直接写入 workflow trace。
- 默认测试不触网、不调用真实外部 LLM。

完成标准：

- `LangChainInputParserAgent` 不再在每个工具 wrapper 内手写 `tool_call_started` / `tool_call_completed` / `tool_call_failed`。
- `LangChainInputParserAgent` 不再依赖手写 `_emit_agent_event()` 表达 create_agent 生命周期。
- create_agent 执行路径能从官方 middleware / callback / stream events 采集 agent、model、tool、step 事件。
- 采集事件统一转换为 `WorkflowTraceEvent`，并进入 `NodeResult.trace_events` / `WorkflowState.trace`。
- `DraftingParseInputNode` 仍能看到 input parsed 前后的 workflow trace，且不泄露交底书正文、prompt 全文、完整工具参数、完整工具返回、附件本地路径、API key、token、secret、password。
- 旧 `tool_registry` 注入路径继续可用，不因 create_agent middleware trace 改造失败。

### 1.3 目标用户

- 后端维护者：通过 workflow trace / 日志看到 create_agent 内部 agent、model、tool、step 活动。
- 后续前端：未来可从同一 workflow trace 投影用户可理解的进度。
- agent node 开发者：新增 create_agent node 时复用统一 middleware trace，不再逐个工具手写 trace wrapper。

### 1.4 非目标

- 不另起独立于 workflow trace 的 agent trace 事实流。
- 不把 LangChain 原始 callback payload 直接暴露给前端或写入 `WorkflowState.trace`。
- 不在本阶段实现 SSE、WebSocket、API 实时推送或 trace 持久化。
- 不迁移所有普通 node 到新 schema。
- 不迁移所有 agent node；本阶段仍以 `LangChainInputParserAgent` / `DraftingParseInputNode` 为试点。
- 不保留手写 wrapper trace 作为同一事件的并行来源；如果官方能力无法覆盖目标事件，本阶段应阻塞并重新确认，而不是偷偷回退为 wrapper 方案。

---

## 2. Commands

所有 Python / pytest / 编译命令必须使用 conda 环境 `autoGLM`：

```bash
# create_agent middleware trace 试点测试
conda run -n autoGLM pytest tests/test_input_parser_agent.py

# DraftingParseInputNode trace 汇总测试
conda run -n autoGLM pytest tests/test_drafting_research_nodes.py

# WorkflowTraceEvent schema / sink / projection 回归
conda run -n autoGLM pytest tests/test_workflow_trace_events.py

# Orchestrator schema trace 保留回归
conda run -n autoGLM pytest tests/test_orchestrator_engine.py

# drafting 端到端回归
conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py

# 安全合规回归
conda run -n autoGLM pytest tests/test_security_compliance.py

# 全量回归
conda run -n autoGLM pytest

# 编译检查
conda run -n autoGLM python -m compileall app tests
```

约束：

- 默认测试不得触网，不得调用真实外部 LLM。
- 如果需要依赖 LangChain 已安装能力，必须先基于当前环境 API 验证；不得凭印象假设 API 名称。
- 如新增依赖，必须同步更新 `requirements.txt`；优先不新增依赖。
- 不执行 `git push`、`git reset --hard`、强制推送等危险操作，除非用户明确确认。
- 每完成一个可独立验证阶段，按项目规范单独提交。

---

## 3. Project Structure

优先复用现有 trace 结构，不新增与 workflow trace 并行的事实流。

```text
pagent/
  app/
    tracing/
      workflow_trace.py              # WorkflowTraceEvent schema、事件枚举、脱敏摘要
      sinks.py                       # WorkflowTraceEmitter、memory/logger/noop sink
      langchain_trace.py             # LangChain middleware/callback/stream event -> WorkflowTraceEvent adapter
    tools/
      subagents/
        input_parser_agent.py        # create_agent 试点 runner，接入 LangChain trace adapter
    nodes/
      drafting_research.py           # DraftingParseInputNode 汇总 NodeResult.trace_events
  tests/
    test_workflow_trace_events.py
    test_input_parser_agent.py
    test_drafting_research_nodes.py
    test_orchestrator_engine.py
```

如实现时发现 LangChain 当前版本的官方入口更适合放在其他模块，允许调整文件名，但职责必须保持：

- `workflow_trace.py`：项目统一 schema 和脱敏摘要。
- `sinks.py`：项目内部事件发送/收集/日志 sink。
- `langchain_trace.py`：LangChain 官方事件到 `WorkflowTraceEvent` 的 adapter。
- `input_parser_agent.py`：只装配 create_agent、工具、安全业务逻辑和 trace adapter，不再在每个 tool 里手写 trace 事件。

### 3.1 LangChain Trace Adapter

新增 LangChain trace adapter，负责把官方 middleware / callback / stream events 转换成项目 schema。

建议职责：

```text
LangChain official event
  -> normalize event type
  -> sanitize input/output/error payload
  -> map to WorkflowTraceEvent
  -> safe_emit_workflow_trace(emitter, event)
```

adapter 必须输出项目统一 `WorkflowTraceEvent`，不得把 LangChain 原始 payload 直接塞进 `metadata`。

### 3.2 事件覆盖

本阶段至少覆盖以下事件族：

| WorkflowTraceEvent.event | 来源 | 要求 |
| --- | --- | --- |
| `agent_started` | create_agent invoke 开始或等价官方事件 | 包含 node_name、stage、agent_name |
| `agent_completed` | create_agent 正常结束或等价官方事件 | 包含 duration / output_summary |
| `agent_failed` | create_agent 异常或等价官方事件 | 包含 error_type / error_message 摘要 |
| `model_call_started` | LLM/model 调用开始 | 不记录完整 prompt/messages |
| `model_call_completed` | LLM/model 调用成功 | 可记录 token/模型名/耗时等短字段，如官方事件提供 |
| `model_call_failed` | LLM/model 调用失败 | 只记录错误类型和短错误摘要 |
| `tool_call_started` | 工具调用开始 | 只记录工具名、调用 id、参数摘要 |
| `tool_call_completed` | 工具调用成功 | 只记录工具名、调用 id、结果摘要 |
| `tool_call_failed` | 工具调用失败 | 只记录错误类型和短错误摘要 |
| `agent_step_started` / `agent_step_completed` / `agent_step_failed` | agent step / reasoning step | 只记录 step 序号、阶段、短摘要 |

如现有 `WorkflowTraceEventName` 枚举缺少 model / step 事件，应扩展枚举和测试。

### 3.3 工具函数边界

工具函数仍负责业务安全，不负责 trace 采集：

- `read_source_artifact`：只允许读取 `01_input/raw_document.md`。
- `write_parsed_info`：只允许写入 `01_input/parsed_info.json`，且内容必须是 JSON object。
- `file_extract`：只允许处理受控附件，不接受任意本地路径。
- `office_to_md`：只允许处理受控 Office 附件，不接受任意本地路径。

工具函数内不应再出现用于 trace 的重复代码，例如：

```python
self._emit_tool_event("tool_call_started", ...)
self._emit_tool_event("tool_call_completed", ...)
self._emit_tool_event("tool_call_failed", ...)
```

但工具函数可以继续返回安全的业务 observation；trace adapter 负责对官方事件中的参数和返回做二次脱敏摘要。

### 3.4 脱敏 / 摘要规则

LangChain 官方事件中的输入输出必须先转换为摘要：

- prompt / messages：只记录类型、数量、角色数量、字符数，不记录全文。
- tool args：只记录允许字段的类型、长度、数量；敏感字段替换为 `[REDACTED]`。
- tool result：只记录 artifact key、done、chars、format、media_count、truncated、错误码等短字段。
- 文件路径：不得记录任意本地绝对路径；附件只允许记录受控 attachment id / format / chars。
- 错误：记录 `error_type` 和短 `error_message`，不得包含长正文或密钥。
- 敏感 key：`api_key`、`token`、`secret`、`password` 等必须脱敏。

现有 `summarize_trace_value()` / `sanitize_trace_mapping()` 应优先复用；如能力不足，只扩展通用 helper，不在 LangChain adapter 内写一次性脱敏逻辑。

### 3.5 Workflow Trace 汇总关系

目标链路：

```text
LangChain create_agent official middleware/callback/stream events
  -> LangChain trace adapter
  -> WorkflowTraceEmitter
  -> MemoryWorkflowTraceEmitter.trace_events
  -> DraftingParseInputNode NodeResult.trace_events
  -> Orchestrator._record_trace_events()
  -> WorkflowState.trace
```

`WorkflowState.trace` 仍是统一事实承载。logger sink 和 progress projection 继续从 `WorkflowTraceEvent` 派生。

---

## 4. Code Style

- 保持最小化、局部化改动。
- 复用现有 `WorkflowTraceEvent`、`WorkflowTraceEmitter`、`safe_emit_workflow_trace()`、`summarize_trace_value()`，不要新建第二套 trace schema。
- 日志 / 注释 / docstring 沿用中文风格。
- 新增公开类、公开函数、公开方法必须有中文 Google 风格 docstring。
- 私有简单 helper 可用一行中文概述。
- 不为单个 node 新增专用配置项；如需配置，应保持通用作用域。
- 不把 LangChain 具体 payload 结构扩散到 node 层；node 只消费 `WorkflowTraceEvent` dict。
- 不把 trace 采集逻辑写进每个工具函数；工具函数只保留业务安全逻辑。
- 不为了兼容旧 wrapper trace 保留无意义壳；如果确认废弃，应删除对应私有方法和测试。

---

## 5. Testing Strategy

### 5.1 单元测试

`tests/test_input_parser_agent.py` 应覆盖：

- create_agent 执行成功时，通过官方 middleware / callback / stream event adapter 产生：
  - `agent_started`
  - `model_call_started`
  - `model_call_completed`
  - `tool_call_started`
  - `tool_call_completed`
  - `agent_step_started` / `agent_step_completed`
  - `agent_completed`
- create_agent 异常时产生 `agent_failed`，并保持 fallback 行为。
- model 调用失败时产生 `model_call_failed`。
- tool 调用失败时产生 `tool_call_failed`。
- trace 中不包含 prompt 全文、交底书正文、工具完整 JSON content、附件正文、本地绝对路径、API key / token / secret / password。
- `LangChainInputParserAgent` 工具函数内不再依赖手写 `_emit_tool_event()`。

`tests/test_workflow_trace_events.py` 应覆盖：

- 新增 model / step 事件枚举。
- LangChain event payload 摘要和敏感字段脱敏。
- 非 drafting 样例仍可使用同一 schema。

`tests/test_drafting_research_nodes.py` 应覆盖：

- `DraftingParseInputNode` 仍汇总 middleware trace 到 `NodeResult.trace_events`。
- `NodeResult.output` 仍只包含短 artifact key。
- 旧 `tool_registry` 注入路径继续可用。

### 5.2 回归测试

必须运行：

```bash
conda run -n autoGLM pytest tests/test_input_parser_agent.py tests/test_drafting_research_nodes.py tests/test_workflow_trace_events.py tests/test_orchestrator_engine.py
conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py
conda run -n autoGLM pytest tests/test_security_compliance.py
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests
```

### 5.3 测试替身要求

- 默认测试使用 fake model / fake agent / fake LangChain event source，不触网。
- 如 LangChain 官方 middleware/callback/stream events API 需要构造特定对象，应在测试中最小化模拟该对象，不引入真实 LLM 调用。
- 测试应证明事件来源是 middleware/callback/stream adapter，而不是工具 wrapper 内部手写 emit。

---

## 6. Boundaries

### 6.1 Always

- 始终保持 `WorkflowState.trace` 是统一事实承载。
- 始终把 LangChain 官方事件转换为 `WorkflowTraceEvent` 后再进入项目 trace。
- 始终进行脱敏 / 摘要，不直接记录原始 prompt、messages、tool args、tool result。
- 始终保持默认测试离线可运行。
- 始终保持旧 `tool_registry` 路径可用。
- 始终优先复用现有 helper 和 sink。

### 6.2 Ask First

- 如果当前 LangChain 版本无法通过官方 middleware/callback/stream events 覆盖 agent、model、tool、step 四类事件，需要先停下来确认，不允许用手写 wrapper 悄悄替代。
- 如果需要升级 LangChain 或新增依赖，需要先确认。
- 如果要把 trace 持久化到数据库 / workspace artifact，需要先确认。
- 如果要实现 API 实时推送、SSE、WebSocket 或前端 UI，需要先确认。
- 如果要迁移除 `LangChainInputParserAgent` 以外的其他 agent node，需要先确认。

### 6.3 Never

- 不维护独立于 workflow trace 的第二套 agent trace 事实流。
- 不把 LangChain 原始事件对象直接写入 `WorkflowState.trace`。
- 不记录完整交底书正文、附件正文、prompt 全文、完整工具输入输出。
- 不记录 API key、token、secret、password 或本地敏感路径。
- 不在每个工具函数里继续新增 trace wrapper 代码。
- 不为了通过测试而 mock 掉核心 trace adapter 行为。
