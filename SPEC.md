# Pagent Agent Trace Event 可观测性规格

## 1. Objective

### 1.1 背景

`DraftingParseInputNode` 已初步接入 `create_agent`，但当前无法观察 agent 内部活动，例如工具调用、工具返回、模型阶段输出与异常路径。这会导致节点行为在调试、回归和后续前端展示中都偏黑盒。

本规格目标是先为 agent 节点建立统一 trace event 事实流：底层只维护一套事件 schema，再由不同 sink / view 消费，分别满足后端技术日志排查与后续前端进度展示。

### 1.2 目标

- 定义统一 `trace event` schema，覆盖 node / agent / tool / error 等执行事实。
- 技术日志流和前端进度流复用同一事件事实源，不维护两套分叉事件。
- 先在 `DraftingParseInputNode` 试点，验证 `create_agent` 内部活动可观测。
- 先实现后端日志 sink，前端进度 sink 只保留映射字段 / 接口边界，不实现 SSE、WebSocket 或 UI。
- 事件必须可脱敏、可测试、可扩展到其他节点。

完成标准：

- `DraftingParseInputNode` 执行时能输出结构化 trace event。
- 可观察 agent start / completed / failed、tool call / tool result / tool error 等关键事件。
- 后端日志能按稳定英文 `event` 检索 agent 内部活动。
- trace event 不记录交底书正文、prompt 全文、工具完整输入输出、API key、token 或隐私数据。
- 前端进度视图可从同一 trace event 映射得到用户可理解的 `progress_label` / `progress_message`。
- 默认测试不触网、不调用真实外部 LLM。

### 1.3 目标用户

- 后端维护者：需要通过日志流排查 `create_agent` 在节点内做了什么。
- 后续前端：需要基于同一事件事实源展示用户可理解的办理进度。
- agent 节点开发者：需要复用统一 emitter / schema，而不是每个节点自造日志格式。

### 1.4 非目标

- 不在本阶段迁移所有节点到 `create_agent`。
- 不在本阶段实现完整前端 UI。
- 不在本阶段实现 SSE / WebSocket / API 推送。
- 不维护独立的“技术日志事件”和“前端进度事件”两套事实流。
- 不记录完整 prompt、完整原文、完整工具输入输出或敏感信息。

---

## 2. Commands

项目使用 conda 环境 `autoGLM`。所有 Python / pytest / 脚本命令必须通过 `conda run -n autoGLM` 执行。

```bash
# trace event schema / emitter 单元测试
conda run -n autoGLM pytest tests/test_trace_events.py

# DraftingParseInputNode trace 试点测试
conda run -n autoGLM pytest tests/test_drafting_parse_input_node.py

# 相关 drafting 回归测试
conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py

# 全量回归
conda run -n autoGLM pytest

# 编译检查
conda run -n autoGLM python -m compileall app tests
```

约束：

- 默认测试不得触网、不得调用真实外部 LLM。
- 如新增依赖，必须同步更新 `requirements.txt`。
- 不执行 `git push`、`git reset --hard`、强制推送等危险操作，除非用户明确确认。
- 每完成一个可独立验证阶段，按项目规范单独提交。

---

## 3. Project Structure

目标结构优先复用现有目录，保持局部改动。

```text
pagent/
  app/
    tracing/
      events.py                 # TraceEvent schema、事件枚举、脱敏摘要工具
      emitter.py                # TraceEmitter 接口与默认 logger sink
      progress.py               # trace event -> 前端进度视图映射
    nodes/
      drafting_parse_input.py   # DraftingParseInputNode 试点接入 trace emitter
    prompts/
      ...                       # prompt 仍集中维护，不内联到 trace 逻辑
  tests/
    test_trace_events.py
    test_drafting_parse_input_node.py
  SPEC.md
```

如项目已有 trace / logging 模块，应优先扩展现有模块，不强行新增 `app/tracing/`。最终文件位置以现有代码结构为准，但职责边界保持一致。

### 3.1 TraceEvent schema

统一事件事实流建议字段：

```json
{
  "trace_id": "string",
  "span_id": "string | null",
  "parent_span_id": "string | null",
  "workflow_id": "string | null",
  "workspace_id": "string | null",
  "node_name": "drafting_parse_input",
  "agent_name": "drafting_parse_input_agent",
  "agent_run_id": "string | null",
  "event": "agent_started",
  "status": "started | completed | failed | skipped",
  "tool_name": "string | null",
  "tool_call_id": "string | null",
  "input_summary": "string | null",
  "output_summary": "string | null",
  "progress_label": "string | null",
  "progress_message": "string | null",
  "duration_ms": 0,
  "error_type": "string | null",
  "error_message": "string | null",
  "metadata": {},
  "timestamp": "ISO-8601"
}
```

要求：

- `event` 使用稳定英文名。
- `message` / `progress_message` 可使用中文。
- `input_summary` / `output_summary` 只能保存摘要、长度、类型、数量等脱敏信息。
- `metadata` 只放短字段，不放长正文、完整 prompt、完整工具参数或密钥。
- 如项目已接入 OpenTelemetry，应复用已有 `trace_id` / `span_id`，禁止自造冲突字段。

### 3.2 事件枚举

第一阶段至少覆盖：

| event | 触发时机 | 典型字段 |
| --- | --- | --- |
| `agent_started` | `create_agent` 执行开始 | `node_name`, `agent_name`, `agent_run_id` |
| `agent_completed` | agent 正常完成 | `duration_ms`, `output_summary` |
| `agent_failed` | agent 执行失败 | `error_type`, `error_message` |
| `agent_tool_call_started` | agent 准备调用工具 | `tool_name`, `tool_call_id`, `input_summary` |
| `agent_tool_call_completed` | 工具调用成功返回 | `tool_name`, `tool_call_id`, `duration_ms`, `output_summary` |
| `agent_tool_call_failed` | 工具调用失败 | `tool_name`, `tool_call_id`, `error_type`, `error_message` |
| `node_progress` | 节点产生用户可理解进度 | `progress_label`, `progress_message` |

后续可扩展 `model_stream_started`、`model_stream_delta`、`model_stream_completed`，但本阶段不要求捕获 token 级流式输出。

### 3.3 TraceEmitter 接口

建议接口：

```python
class TraceEmitter:
    """发送节点和 agent 执行过程中的结构化 trace event。"""

    def emit(self, event: TraceEvent) -> None:
        """发送单个 trace event。"""
```

要求：

- 节点构造参数可选传入 emitter；未传时使用安全 no-op 或默认 logger emitter。
- emitter 不应影响主流程成功失败；日志写入失败最多降级为 warning。
- 不为单个节点新增专用配置项；如需配置，应保持通用作用域。
- 事件创建逻辑尽量复用 helper，避免每个节点手写字段拼装。

### 3.4 后端日志 sink

第一阶段实现 logger sink：

- 使用项目现有 logger 体系。
- 输出结构化字段，包含 `event`, `trace_id`, `node_name`, `agent_name`, `tool_name`, `status`, `duration_ms` 等。
- `event` 为英文稳定字段，`message` 为中文可读描述。
- 异常事件保留堆栈，但不记录敏感输入。

### 3.5 前端进度视图

前端进度流不是第二套事实流，而是从 TraceEvent 映射出的视图字段。

示例映射：

| 原始 event | progress_label | progress_message |
| --- | --- | --- |
| `agent_started` | `解析输入` | `正在解析交底材料和用户要求` |
| `agent_tool_call_started` | `调用工具` | `正在调用工具补充解析上下文` |
| `agent_tool_call_completed` | `工具完成` | `工具调用已完成，正在汇总结果` |
| `agent_completed` | `解析完成` | `输入解析完成` |
| `agent_failed` | `解析失败` | `输入解析失败，请查看错误信息或重试` |

要求：

- 前端文案必须来自受控映射，不直接暴露工具原始参数或模型原始输出。
- 本阶段只保留映射函数 / 字段，不实现推送接口。
- 后续 SSE / WebSocket / API 可以消费同一 TraceEvent。

### 3.6 `DraftingParseInputNode` 试点

试点范围：

- 在节点开始执行 agent 时发送 `agent_started`。
- 捕获工具调用开始、成功、失败事件。
- agent 完成时发送 `agent_completed`。
- agent 异常时发送 `agent_failed`，并保留异常堆栈到后端日志。
- 继续保持现有节点输入输出契约，不因 trace 改变业务结果。

优先使用 LangChain / `create_agent` 官方 callback 或 stream event 机制获取细粒度事件；如果现有版本能力不足，可先通过节点级 wrapper / tool wrapper 发出关键事件，但接口要允许后续切换为官方事件源。

---

## 4. Code Style

- 优先最小化、局部化改动，复用现有 logger、trace、node、tool helper。
- 所有公开类、函数、方法必须写中文 Google 风格 docstring，包含 Args / Returns / Raises（如有）。
- 注释和日志沿用中文风格；日志 `event` 字段使用稳定英文。
- 行内注释只解释不直观的边界、脱敏、降级和 callback 适配逻辑。
- Prompt 不内联散落在业务逻辑里，trace 逻辑不得拼接 prompt 内容。
- 外部 / 用户 / 附件 / 检索内容必须作为数据处理，不得进入高优先级指令。
- 不使用用户输入拼接 shell 命令或 SQL。
- 不把密钥、完整 API Key、附件正文、prompt 全文、长原文、工具完整输入输出写入日志、trace 或长期记忆。
- 删除或替换旧实现时直接清理无用代码，不保留无意义兼容壳。

---

## 5. Testing Strategy

### 5.1 单元测试

`tests/test_trace_events.py`：

- TraceEvent 必填字段完整。
- `event` / `status` 枚举值受控。
- `input_summary` / `output_summary` 不包含长文本。
- 敏感字段名如 `api_key`、`token`、`secret`、`password` 不进入公开事件。
- progress 映射能从同一 TraceEvent 生成前端可读字段。

### 5.2 节点试点测试

`tests/test_drafting_parse_input_node.py`：

- fake agent 成功时发送 `agent_started` 与 `agent_completed`。
- fake tool 成功时发送 `agent_tool_call_started` 与 `agent_tool_call_completed`。
- fake tool 失败时发送 `agent_tool_call_failed`，节点按既有失败语义处理。
- fake agent 失败时发送 `agent_failed`，错误信息可解释且不泄露原文。
- 未传 emitter 时节点仍可正常执行。

### 5.3 回归测试

- `conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py`
- `conda run -n autoGLM pytest`
- `conda run -n autoGLM python -m compileall app tests`

要求：

- 默认测试不触网、不调用真实外部 LLM。
- 使用 fake agent / fake tool / fake emitter 验证事件顺序与字段。
- 测试只断言稳定字段，不依赖易变的完整日志文本。

---

## 6. Boundaries

### 6.1 Always do

- 使用一套统一 TraceEvent 事实流，技术日志和前端进度都从它派生。
- 先在 `DraftingParseInputNode` 试点，schema / emitter 按全局复用设计。
- 优先使用官方 callback / stream event 机制；不足时用 wrapper 过渡，但保持接口可替换。
- 所有日志事件使用稳定英文 `event`。
- 前端进度文案通过受控映射生成。
- trace / 日志必须脱敏，只记录摘要、长度、数量、状态、耗时和错误类型。
- emitter 失败不得破坏主业务流程。
- 默认测试不访问真实网络和真实外部 LLM。
- 配置项保持通用作用域，不绑定单个临时 Node。

### 6.2 Ask first

- 是否实现 SSE / WebSocket / API 推送。
- 是否把 trace event 持久化到数据库或 workspace artifact。
- 是否将所有 drafting 节点一次性接入 emitter。
- 是否捕获 token 级模型流式输出。
- 是否调整现有 logger / OpenTelemetry 基础设施。
- 是否新增第三方 tracing / observability 依赖。

### 6.3 Never do

- 不维护两套互相分叉的技术日志事件和前端进度事件。
- 不把 `create_agent` 活动继续作为完全黑盒隐藏在节点内部。
- 不把完整 prompt、交底书正文、检索正文、工具完整输入输出写入日志或 trace。
- 不记录 API key、token、secret、password 等敏感信息。
- 不在本阶段迁移所有节点到 `create_agent`。
- 不在本阶段实现完整前端 UI。
- 不为单个节点新增临时专用全局配置。
- 不通过 shell 拼接用户输入执行命令。

---

## 7. Acceptance Criteria

### 7.1 架构验收

- 存在统一 TraceEvent schema 与 TraceEmitter 边界。
- 后端日志 sink 与前端进度映射复用同一 TraceEvent。
- `DraftingParseInputNode` 能通过 emitter 输出 agent / tool 执行事件。
- 未传 emitter 时保持安全默认行为。

### 7.2 可观测验收

- 一次 `DraftingParseInputNode` 执行可以看到 agent 开始、工具调用、工具返回、agent 完成或失败。
- 每个事件包含 `trace_id`、`node_name`、`event`、`status`、时间信息和必要摘要。
- 工具失败和 agent 失败有可解释错误事件。
- 日志可按稳定 `event` 字段检索。

### 7.3 安全验收

- trace / 日志不包含交底书正文、prompt 全文、工具完整输入输出或密钥。
- 前端进度视图不暴露技术敏感细节。
- emitter 异常不会导致主流程失败。

### 7.4 工程验收

- 相关单元测试通过。
- drafting 相关回归通过。
- 全量测试与 compileall 通过。
