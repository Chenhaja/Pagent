# Pagent WorkflowTraceEvent 可观测性规格

## 1. Objective

### 1.1 背景

当前项目已有 workflow trace：各节点通过 `NodeResult.trace_events` 返回事件，`Orchestrator` 再写入 `WorkflowState.trace`。但这些事件目前多为自由 dict，字段不统一，适合作为内部审计补充，却不适合作为后续前端进度展示或跨节点统一可观测协议。

`DraftingParseInputNode` 已初步接入 `create_agent`，但 agent 内部活动不可见，例如工具调用、工具返回、模型执行失败等。这个问题不应通过另起一套 agent trace 解决，而应通过**schema 化当前 Workflow trace**解决。

本规格目标是定义统一 `WorkflowTraceEvent` schema，由现有 `NodeResult.trace_events` / `WorkflowState.trace` 统一管理。QA、translate、query_rewrite、drafting 等所有 workflow node 都应能使用同一 schema；第一阶段只在 `DraftingParseInputNode` 试点 agent / tool 细粒度事件。

### 1.2 目标

- 将当前 workflow trace 规范化为统一 `WorkflowTraceEvent` schema。
- `NodeResult.trace_events` 直接承载 `WorkflowTraceEvent`，`WorkflowState.trace` 是统一管理 / 存储 / 审计入口。
- schema 面向全 workflow，覆盖普通 node、agent node、tool call、error、progress 等执行事实。
- 后端技术日志和前端进度视图都从 `WorkflowTraceEvent` 派生，不维护两套事实流。
- 第一阶段只在 `DraftingParseInputNode` / `LangChainInputParserAgent` 试点 agent / tool 内部活动可观测。
- 第一阶段只实现 logger sink 与 progress projection，不实现 SSE、WebSocket、API 推送或前端 UI。

完成标准：

- `WorkflowTraceEvent` 可表达普通节点事件、agent 生命周期事件、tool 调用事件、失败事件和进度事件。
- `DraftingParseInputNode` 执行时能在 workflow trace 中看到 agent start / completed / failed、tool call / result / error。
- QA / translate / query_rewrite 等非文书节点至少有 schema 级样例或测试，证明该 schema 不绑定 drafting。
- 后端日志可从同一 `WorkflowTraceEvent` 输出稳定英文 `event` 和结构化字段。
- 前端进度可从同一 `WorkflowTraceEvent` 投影出稳定 `ProgressEvent` 视图。
- trace / 日志 / progress 不记录交底书正文、prompt 全文、工具完整输入输出、API key、token 或隐私数据。
- 默认测试不触网、不调用真实外部 LLM。

### 1.3 目标用户

- 后端维护者：通过 workflow trace 和日志排查节点、agent、tool 的执行过程。
- 后续前端：通过 progress projection 展示用户可理解的办理进度。
- workflow node 开发者：用统一 `WorkflowTraceEvent` 记录 QA、translate、query_rewrite、drafting 等节点事件。
- agent 节点开发者：复用同一 schema 记录 agent / tool 内部活动。

### 1.4 非目标

- 不另起一套独立于 workflow trace 的 agent trace 事实流。
- 不在本阶段迁移所有节点到新 schema。
- 不在本阶段迁移所有节点到 `create_agent`。
- 不在本阶段实现完整前端 UI、SSE、WebSocket 或 API 推送。
- 不在本阶段持久化 trace 到数据库或 workspace artifact。
- 不记录完整 prompt、完整原文、完整工具输入输出或敏感信息。

---

## 2. Commands

项目使用 conda 环境 `autoGLM`。所有 Python / pytest / 脚本命令必须通过 `conda run -n autoGLM` 执行。

```bash
# WorkflowTraceEvent schema / projection / sink 单元测试
conda run -n autoGLM pytest tests/test_workflow_trace_events.py

# LangChain input parser agent trace 试点测试
conda run -n autoGLM pytest tests/test_input_parser_agent.py

# DraftingParseInputNode trace 试点测试
conda run -n autoGLM pytest tests/test_drafting_research_nodes.py

# 相关 drafting 回归测试
conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py

# 全量回归
conda run -n autoGLM pytest

# 编译检查
conda run -n autoGLM python -m compileall app tests
```

约束：

- 默认测试不得触网、不得调用真实外部 LLM。
- 如新增依赖，必须同步更新 `requirements.txt`；本阶段优先不新增依赖。
- 不执行 `git push`、`git reset --hard`、强制推送等危险操作，除非用户明确确认。
- 每完成一个可独立验证阶段，按项目规范单独提交。

---

## 3. Project Structure

目标结构优先复用现有目录，保持局部改动。

```text
pagent/
  app/
    tracing/
      workflow_trace.py        # WorkflowTraceEvent schema、事件枚举、脱敏摘要、NodeResult trace 适配
      progress.py              # WorkflowTraceEvent -> ProgressEvent projection
      sinks.py                 # logger sink / no-op sink / 测试用 memory sink
    nodes/
      drafting_research.py     # DraftingParseInputNode 试点接入 WorkflowTraceEvent
    tools/
      subagents/
        input_parser_agent.py  # LangChainInputParserAgent 捕获 agent / tool 事件
  tests/
    test_workflow_trace_events.py
    test_input_parser_agent.py
    test_drafting_research_nodes.py
  SPEC.md
```

如实现时发现已有更合适的 trace 模块，应优先扩展现有模块，不强行新增目录。但职责边界必须保持：schema、progress projection、sink / emitter 分离。

### 3.1 WorkflowTraceEvent schema

`NodeResult.trace_events` 应逐步承载以下 schema。第一阶段允许兼容旧 `{"event": ..., "data": ...}` 事件，但新增 agent / tool 事件必须使用新 schema。

```json
{
  "schema_version": "1",
  "trace_id": "string | null",
  "span_id": "string | null",
  "parent_span_id": "string | null",
  "workflow_id": "string | null",
  "session_id": "string | null",
  "request_id": "string | null",
  "node_name": "string",
  "node_type": "normal | agent | tool | gate",
  "event": "node_started",
  "status": "started | running | completed | failed | skipped | waiting",
  "stage": "string | null",
  "agent_name": "string | null",
  "agent_run_id": "string | null",
  "tool_name": "string | null",
  "tool_call_id": "string | null",
  "input_summary": "string | null",
  "output_summary": "string | null",
  "duration_ms": 0,
  "error_type": "string | null",
  "error_message": "string | null",
  "progress": {
    "visible": true,
    "stage": "drafting.parse_input",
    "label": "解析输入",
    "message": "正在解析交底材料和用户要求",
    "order": 10
  },
  "metadata": {},
  "timestamp": "ISO-8601"
}
```

要求：

- `event` 使用稳定英文名。
- `node_name` 适用于所有 workflow node，不得绑定 drafting。
- `stage` 建议使用命名空间：`drafting.parse_input`、`qa.retrieval`、`translate.translation`、`query_rewrite.rewrite`。
- `progress` 是前端视图投影所需信息，必须受控生成，不能直接暴露工具原始参数。
- `input_summary` / `output_summary` 只能保存摘要、长度、类型、数量等脱敏信息。
- `metadata` 只放短字段，不放长正文、完整 prompt、完整工具参数或密钥。
- 如项目已接入 OpenTelemetry，应复用已有 `trace_id` / `span_id`，禁止自造冲突字段。

### 3.2 事件枚举

通用事件：

| event | 触发时机 |
| --- | --- |
| `workflow_started` | workflow 开始 |
| `workflow_completed` | workflow 成功完成 |
| `workflow_failed` | workflow 失败 |
| `node_started` | 节点开始 |
| `node_completed` | 节点成功完成 |
| `node_failed` | 节点失败 |
| `node_skipped` | 节点跳过 |
| `progress_updated` | 节点产生用户可见进度 |

agent / tool 事件：

| event | 触发时机 |
| --- | --- |
| `agent_started` | agent 开始 |
| `agent_completed` | agent 正常完成 |
| `agent_failed` | agent 执行失败 |
| `tool_call_started` | 工具调用开始 |
| `tool_call_completed` | 工具调用成功返回 |
| `tool_call_failed` | 工具调用失败 |

第一阶段重点实现 `DraftingParseInputNode` 的 `agent_*` 和 `tool_call_*`，但 schema 必须能表达 QA / translate / query_rewrite 的普通节点和工具事件。

### 3.3 WorkflowTraceEmitter / sink

建议接口：

```python
class WorkflowTraceEmitter:
    """发送 workflow trace 事件。"""

    def emit(self, event: WorkflowTraceEvent) -> None:
        """发送单个 WorkflowTraceEvent。"""
```

要求：

- 节点或 runner 可选传入 emitter；未传时使用安全 no-op 或默认 logger sink。
- emitter 不应影响主流程成功失败；日志写入失败最多降级为 warning。
- emitter 输出的事件应可进入 `NodeResult.trace_events`，并可由 logger sink 输出结构化日志。
- 不为单个节点新增专用配置项；如需配置，应保持通用作用域。

### 3.4 WorkflowState.trace 管理

目标关系：

```text
Node / Agent / Tool
  ↓ emit WorkflowTraceEvent
NodeResult.trace_events
  ↓ Orchestrator._record_trace_events()
WorkflowState.trace
  ├─ logger sink：后端技术日志
  └─ progress projection：前端进度视图
```

要求：

- `WorkflowState.trace` 是统一事实源的 workflow 内承载，不为前端另起事实流。
- 前端不直接消费原始 `WorkflowState.trace`，而是消费 `ProgressEvent` projection。
- 第一阶段不要求重写 `Orchestrator._record_trace_events()`，但新增事件必须能被它安全记录。
- 旧格式 trace 可兼容保留，新格式应逐步成为默认。

### 3.5 ProgressEvent projection

`ProgressEvent` 是从 `WorkflowTraceEvent` 投影出的前端视图，不是第二套事实事件。

```json
{
  "trace_id": "string | null",
  "workflow_id": "string | null",
  "node_name": "drafting_parse_input",
  "stage": "drafting.parse_input",
  "status": "running",
  "label": "解析输入",
  "message": "正在解析交底材料和用户要求",
  "visible": true,
  "order": 10,
  "timestamp": "ISO-8601"
}
```

要求：

- 只投影 `progress.visible=true` 的事件。
- 文案来自受控映射或事件内受控 progress 字段。
- 不暴露 `tool_call_id`、artifact key、工具原始参数、模型原始输出。
- schema 兼容非 drafting stage，例如 `qa.retrieval`、`translate.translation`、`query_rewrite.rewrite`。
- 本阶段只实现 projection / mapper，不实现推送接口。

### 3.6 `DraftingParseInputNode` 试点

试点范围：

- 在 `LangChainInputParserAgent` 开始执行 agent 时发送 `agent_started`。
- 捕获 `read_source_artifact`、`write_parsed_info`、`file_extract`、`office_to_md` 的工具调用开始、成功、失败事件。
- agent 完成时发送 `agent_completed`。
- agent 异常时发送 `agent_failed`，并保留异常堆栈到后端日志。
- 继续保持现有节点输入输出契约，不因 trace 改变业务结果。
- `DraftingParseInputNode` 继续保留业务 trace，如 source 写入、parsed info 写入；新增 agent / tool 事件使用 `WorkflowTraceEvent` schema。

优先使用 LangChain / `create_agent` 官方 callback 或 stream event 机制获取细粒度事件；如果现有版本能力不足，可先通过节点级 wrapper / tool wrapper 发出关键事件，但接口要允许后续切换为官方事件源。

---

## 4. Code Style

- 优先最小化、局部化改动，复用现有 logger、workflow trace、node、tool helper。
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

### 5.1 Schema / projection 测试

`tests/test_workflow_trace_events.py`：

- `WorkflowTraceEvent` 必填字段完整。
- `event` / `status` / `node_type` 枚举值受控。
- `input_summary` / `output_summary` 不包含长文本。
- 敏感字段名如 `api_key`、`token`、`secret`、`password` 不进入公开事件。
- `WorkflowTraceEvent` 可作为 `NodeResult.trace_events` 元素被安全记录。
- `ProgressEvent` projection 只输出 `visible=true` 的受控字段。
- 至少包含一个非 drafting 样例，例如 `qa.retrieval` 或 `translate.translation`，防止 schema 被设计成文书专用。

### 5.2 input parser agent 测试

`tests/test_input_parser_agent.py`：

- fake agent 成功时发送 `agent_started` 与 `agent_completed`。
- fake tool 成功时发送 `tool_call_started` 与 `tool_call_completed`。
- fake tool 失败或返回 error 时发送 `tool_call_failed`。
- fake agent 失败时发送 `agent_failed`，错误信息可解释且不泄露原文。
- 未传 emitter 时现有行为不变。

### 5.3 节点试点测试

`tests/test_drafting_research_nodes.py` 或 `tests/test_drafting_parse_input_node.py`：

- `DraftingParseInputNode` 成功执行时，workflow trace 包含 source 写入、agent started、tool call、agent completed、input parsed。
- agent 失败并 fallback 时，workflow trace 包含 `agent_failed`，节点仍按现有失败 / fallback 语义处理。
- `NodeResult.output` 不包含长正文。
- trace 不包含 prompt 全文、交底书正文、工具完整输入输出或密钥。

### 5.4 回归测试

- `conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py`
- `conda run -n autoGLM pytest tests/test_security_compliance.py`
- `conda run -n autoGLM pytest`
- `conda run -n autoGLM python -m compileall app tests`

要求：

- 默认测试不触网、不调用真实外部 LLM。
- 使用 fake agent / fake tool / fake emitter 验证事件顺序与字段。
- 测试只断言稳定字段，不依赖易变的完整日志文本。

---

## 6. Boundaries

### 6.1 Always do

- 将当前 workflow trace schema 化为 `WorkflowTraceEvent`，由 `NodeResult.trace_events` / `WorkflowState.trace` 统一管理。
- schema 设计面向全部 workflow node，不绑定 drafting。
- 第一阶段只在 `DraftingParseInputNode` 试点 agent / tool 细粒度事件。
- 后端日志和前端 progress 都从 `WorkflowTraceEvent` 派生。
- 前端消费 `ProgressEvent` projection，不直接消费原始 `WorkflowState.trace`。
- 优先使用官方 callback / stream event 机制；不足时用 wrapper 过渡，但保持接口可替换。
- trace / 日志 / progress 必须脱敏，只记录摘要、长度、数量、状态、耗时和错误类型。
- emitter 失败不得破坏主业务流程。
- 默认测试不访问真实网络和真实外部 LLM。
- 配置项保持通用作用域，不绑定单个临时 Node。

### 6.2 Ask first

- 是否实现 SSE / WebSocket / API 推送。
- 是否把 workflow trace 持久化到数据库或 workspace artifact。
- 是否将 QA / translate / query_rewrite / drafting 全部迁移到新 schema。
- 是否捕获 token 级模型流式输出。
- 是否调整现有 `WorkflowState.trace` 存储结构。
- 是否新增第三方 tracing / observability 依赖。

### 6.3 Never do

- 不另起一套独立于 workflow trace 的 agent trace 事实流。
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

- 存在统一 `WorkflowTraceEvent` schema。
- `NodeResult.trace_events` / `WorkflowState.trace` 是统一管理入口。
- 后端日志 sink 与前端 progress projection 复用同一 `WorkflowTraceEvent`。
- schema 至少通过一个非 drafting 样例验证通用性。
- `DraftingParseInputNode` 能通过 workflow trace 输出 agent / tool 执行事件。

### 7.2 可观测验收

- 一次 `DraftingParseInputNode` 执行可以看到 agent 开始、工具调用、工具返回、agent 完成或失败。
- 每个新事件包含 `schema_version`、`node_name`、`node_type`、`event`、`status`、时间信息和必要摘要。
- 工具失败和 agent 失败有可解释错误事件。
- 日志可按稳定 `event` 字段检索。

### 7.3 前端视图验收

- `ProgressEvent` projection 可从 `WorkflowTraceEvent` 生成。
- 前端视图字段稳定：`stage`、`status`、`label`、`message`、`visible`、`order`、`timestamp`。
- 前端视图不暴露技术敏感细节、工具完整参数或模型原始输出。

### 7.4 安全验收

- trace / 日志不包含交底书正文、prompt 全文、工具完整输入输出或密钥。
- emitter 异常不会导致主流程失败。

### 7.5 工程验收

- 相关单元测试通过。
- drafting 相关回归通过。
- 全量测试与 compileall 通过。
