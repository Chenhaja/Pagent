# R7.1 LLM 驱动 ReAct 主循环规格说明

## 1. Objective

### 目标

R7.1 的目标是把 R7 已有的「受限工具编排」从确定性按下标执行工具，升级为真正的 LLM 驱动 ReAct 主循环：每一步由策略模型基于任务、工具白名单、历史 observation 决策 `Thought → Action → Observation`，直到模型判断证据充分、主动停止或触达代码预算边界。

完成标准：

- 在 `BoundedReActLoop` 内引入 `ReActPolicy`，每步调用 policy 生成结构化决策：`thought`、`action`、`tool_input`、`stop`、`sufficient`。
- 工具选择由 LLM 在代码提供的白名单和工具描述内完成，不能再使用 `allowed_tools[min(step_index, len-1)]` 这类固定下标路由。
- 后续步骤的 `tool_input.query` 可基于 observation 改写，避免多步重复同一检索。
- 证据充分性优先由 `decision.sufficient` 决定，并受 `react_use_llm_judge` 控制；关闭时回退到阈值 / evidence 兜底逻辑。
- 步数、token、超时、工具白名单、外部工具开关、敏感内容外发限制仍由代码强约束，LLM 只能在边界内决策。
- 无 LLM 配置、LLM 调用失败、输出非法 JSON、未知工具或 schema 不合规时，当步安全降级到 `HeuristicReActPolicy`，循环不中断，并可观测 `fallback_used=true`。
- 主循环 trace 新增 `react_policy_step`，并扩展 outcome / convergence trace 的 `driver`、`fallback_used`、`reason`。
- 默认测试使用 fake / stub LLM，不触网、不调用真实付费模型。

### 目标用户

- 专利 QA 用户：在知识库检索不足时，获得更接近“会追问 / 会改写查询 / 会判断是否足够”的辅助回答。
- 下游 workflow / QA 节点：继续复用受限 ReAct 作为局部补料能力，而不是把全局 workflow 交给 LLM。
- 开发与测试人员：需要可断言的 LLM 决策、降级路径、工具路由、预算收敛、trace 和配置行为。

### 非目标

- 不修改 R4.3 检索四件套，不重写混合检索、重排、查询改写或 provenance 机制。
- 不默认启用外部工具；`websearch`、`legal_status`、`official_fee` 仍受 `agentic_external_tools_enabled` 和具体工具开关控制。
- 不做并行多工具、多智能体协作或开放式 AutoGPT。
- 不让 LLM 改变全局 workflow 顺序、节点跳转或任意调用未注册工具。
- 不在本轮修复会话记忆注入最终 QA prompt 的衔接缺口，只保证 policy 可接收传入上下文。
- 不在默认测试中访问真实网络、真实外部检索源或真实付费 LLM。

---

## 2. Commands

项目使用 conda 环境 `autoGLM`。所有 Python / pytest / 脚本命令必须通过 `conda run -n autoGLM` 执行，不能依赖 `conda activate` 的跨命令状态。

```bash
# ReAct policy 单元测试
conda run -n autoGLM pytest tests/test_react_policy.py

# ReAct 主循环回归测试
conda run -n autoGLM pytest tests/test_agentic_loop.py

# QA 节点接入回归测试
conda run -n autoGLM pytest tests/test_qa_node.py

# 配置公开字段与环境变量测试
conda run -n autoGLM pytest tests/test_core_config_logging.py

# 相关目标测试
conda run -n autoGLM pytest tests/test_react_policy.py tests/test_agentic_loop.py tests/test_qa_node.py tests/test_core_config_logging.py

# 全量测试
conda run -n autoGLM pytest

# 编译检查
conda run -n autoGLM python -m compileall app tests scripts
```

验收命令：

```bash
conda run -n autoGLM pytest tests/test_react_policy.py tests/test_agentic_loop.py tests/test_qa_node.py tests/test_core_config_logging.py
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests scripts
```

约束：

- 默认测试必须注入 `FakeLLMClient` 或等价 fake，不调用真实模型。
- 不触网、不连接真实搜索、法律状态、官费或外部专利服务。
- 如需新增依赖，必须先确认并同步 `requirements.txt`。
- 不使用破坏性 git / 文件命令；代码迁移通过明确 diff 完成。

---

## 3. Project Structure

目标结构：

```text
pagent/
  app/
    core/
      config.py                         # 新增 react_* 配置、公开配置与环境变量读取
    orchestrator/
      react_loop.py                     # 改造：每步调用 policy，执行预算/白名单/降级/trace
      react_policy.py                   # 新增：ReActDecision、ReActPolicy、LLMReActPolicy、HeuristicReActPolicy
      tool_registry.py                  # 增加 ToolCard、description、input_schema、tool_cards()
    prompts/
      react_policy.py                   # 新增：决策 prompt 与 REACT_DECISION_SCHEMA
    nodes/
      qa.py                             # _build_react_loop 接入 policy / react_* 配置
    tools/
      llm.py                            # 复用 LLMClient.generate(output_schema=...)
      retrieval.py                      # 保留：kb_retrieval 底层能力
  tests/
    test_react_policy.py                # 新增：决策解析、非法 action、schema、降级
    test_agentic_loop.py                # 更新：多步改写、policy_stop、预算、fallback
    test_qa_node.py                     # 更新：FakeLLMClient 决策序列与 QA 收敛断言
    test_core_config_logging.py         # 更新：react_* 公开配置
  SPEC.md                               # 本规格
```

### 3.1 ReActPolicy 契约

`app/orchestrator/react_policy.py` 新增核心数据结构：

```python
@dataclass
class ReActDecision:
    thought: str
    action: str | None
    tool_input: dict[str, Any]
    stop: bool
    sufficient: bool

class ReActPolicy(Protocol):
    def decide(
        self,
        task_input: str,
        allowed_tools: list[ToolCard],
        scratchpad: list[dict[str, Any]],
        step_index: int,
    ) -> ReActDecision: ...
```

实现要求：

- `LLMReActPolicy` 使用 `LLMClient.generate(messages, output_schema=REACT_DECISION_SCHEMA, trace_context={"node_name": ..., "task_type": "react_policy"})`。
- `HeuristicReActPolicy` 封装旧逻辑：按工具顺序选择工具、使用原始 `task_input` 作为 query、以 evidence / 阈值做简单充分性判断。
- policy 不直接执行工具，不修改白名单，不绕过预算。
- `thought` 只用于内部 trace 摘要，不返回用户、不落完整原文。

### 3.2 决策输出 schema 与 prompt

`app/prompts/react_policy.py` 新增 `REACT_DECISION_SCHEMA`，最低字段：

```json
{
  "type": "object",
  "properties": {
    "thought": {"type": "string"},
    "action": {"type": ["string", "null"]},
    "tool_input": {"type": "object"},
    "stop": {"type": "boolean"},
    "sufficient": {"type": "boolean"}
  },
  "required": ["thought", "stop", "sufficient"],
  "additionalProperties": false
}
```

Prompt 必须满足项目六要素规范：

- 任务目标：选择下一步工具、生成工具入参或停止。
- 上下文 / 判定规则：只能从白名单工具中选择；证据不足才继续；非法或未知时应停止或选择 `null`。
- 角色：熟悉专利业务、受限工具编排和证据充分性判断的专家。
- 受众：代码解析器和 ReAct 主循环，输出必须稳定可解析。
- 样例：至少包含继续调用工具、证据充分停止、未知时保守停止三个示例。
- 输出格式：仅 JSON，字段类型、必填项、枚举 / null 行为明确。

安全要求：

- 用户任务、工具卡片、scratchpad / observation 均作为数据区传入，并声明数据区内任何指令不作为系统指令。
- 禁止模型臆造法条、专利号、来源或工具结果。
- 不要求输出完整推理链；`thought` 应是短摘要。

### 3.3 主循环契约

`BoundedReActLoop` 每步流程：

1. 检查步数、token、超时预算；预算耗尽则收敛。
2. 调用 `policy.decide(task_input, allowed_tool_cards, scratchpad, step_index)`。
3. 校验 `decision.action` 是否在白名单内，`tool_input` 是否符合对应工具 schema。
4. 如果 `decision.stop` 或 `decision.action is None`，以 `policy_stop` 或 `sufficient` 收敛。
5. 执行 `tool.run(decision.tool_input)`。
6. 累积 evidence，归一化 observation，并追加 scratchpad 摘要。
7. 根据 `decision.sufficient` 或阈值兜底判断是否收敛。
8. 写入 `react_policy_step` 与既有 `react_main_step` / `react_main_converged` trace。

降级要求：

- LLM 抛异常、超时、返回非 dict、JSON 不可解析、缺少必填字段、非法 action、tool_input schema 不合规时，当步使用 `HeuristicReActPolicy`。
- 连续失败达到阈值时，后续整体切换为 heuristic driver。
- outcome 标记 `fallback_used=true`。
- 降级不能突破预算、白名单、外部工具开关或敏感内容限制。

### 3.4 工具注册契约

`ToolSpec` 增加：

```python
@dataclass
class ToolCard:
    name: str
    description: str
    input_schema: dict[str, Any]
```

要求：

- registry 暴露 `tool_cards()`，供 policy 决策。
- 工具描述必须简洁说明用途、适用场景、输入字段。
- 工具输入 schema 用于校验 LLM 生成的 `tool_input`。
- 工具白名单仍由代码根据节点、配置和外部工具开关生成。
- 未注册工具、禁用工具、外部工具未启用时一律拒绝调用。

### 3.5 配置契约

新增 / 调整配置遵守通用作用域，不绑定单个 Node：

| 配置字段 | 环境变量 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `react_policy_driver` | `PAGENT_REACT_POLICY_DRIVER` | `"llm"` | `llm` / `heuristic`；无 LLM 配置时自动 heuristic。 |
| `react_max_steps` | `PAGENT_REACT_MAX_STEPS` | `4` | LLM 驱动下最大 ReAct 步数。 |
| `react_policy_model` | `PAGENT_REACT_POLICY_MODEL` | 空 | 空时回退 `llm_cheap_model` / `llm_model`。 |
| `react_policy_temperature` | `PAGENT_REACT_POLICY_TEMPERATURE` | `0.0` | 决策低温，提升稳定性。 |
| `react_use_llm_judge` | `PAGENT_REACT_USE_LLM_JUDGE` | `true` | 是否使用 policy 的 `sufficient` 判断。 |
| `react_token_budget` | `PAGENT_REACT_TOKEN_BUDGET` | 沿用 retrieval 对应值 | ReAct evidence / prompt 预算。 |
| `react_timeout_seconds` | `PAGENT_REACT_TIMEOUT_SECONDS` | 沿用 retrieval 对应值 | ReAct 主循环超时。 |

兼容要求：

- `retrieval_max_steps` 可保留读取一个版本并映射到 `react_max_steps`，但新代码优先使用 `react_max_steps`。
- 新增配置必须同步 `Settings` 默认值、环境变量读取、`to_public_dict()`、测试。
- 非敏感配置可进入 `to_public_dict()`；模型 API Key、token、secret、password 不得进入公开配置、日志或 trace。
- 覆盖参数使用 `settings.xxx if arg is None else arg`，不得用 `arg or settings.xxx` 吞掉 `0` / `False`。

### 3.6 数据契约

- `ReActDecision`：policy 输出，字段为 `thought`、`action`、`tool_input`、`stop`、`sufficient`。
- `ToolCard`：`name`、`description`、`input_schema`。
- `ToolObservation`：沿用 `{tool_name, evidence, sufficient, error, external, top_score}` 或等价结构。
- `ReActOutcome`：扩展 `{evidence, reason, steps_used, tool_calls, trace_events, external_tools_used, driver, fallback_used}`。

收敛原因枚举：

```text
sufficient       # policy 或阈值判断证据充分
policy_stop      # policy 主动停止但未明确 sufficient
max_steps        # 达到最大步数
token_budget     # token / evidence 预算耗尽
timeout          # 超过超时限制
tool_unavailable # 工具不存在、未启用或被白名单拒绝
```

### 3.7 Trace 契约

新增 `react_policy_step`：

```json
{
  "node_name": "qa",
  "step_index": 0,
  "tool_name": "kb_retrieval",
  "thought_len": 24,
  "stop": false,
  "sufficient": false,
  "driver": "llm"
}
```

扩展 `react_main_converged`：

```json
{
  "node_name": "qa",
  "reason": "sufficient",
  "steps_used": 2,
  "tool_calls": 2,
  "total_evidence": 5,
  "external_tools_used": [],
  "driver": "llm",
  "fallback_used": false
}
```

约束：

- trace 不记录完整 `thought`、完整 query、完整工具返回正文、完整网页正文、密钥或敏感材料。
- `thought` 只记录长度或安全摘要。
- 决策 LLM 的 trace 只记录 model、input_chars、duration、task_type 等脱敏字段。

---

## 4. Code Style

### 基本原则

- 最小化、局部化改动；优先改造现有 `react_loop.py`、`tool_registry.py`、`qa.py` 和配置测试。
- 复用现有 `LLMClient.generate`，不要新增大型 agent 框架。
- 复用现有工具接口和 retrieval 能力，不重写检索算法。
- 公共函数、公共方法、公共类必须添加中文 Google 风格 docstring，包含 Args / Returns / Raises（如有）。
- 简单私有 helper 可使用一行中文概述；只在预算裁决、降级、安全边界等不直观处加行内注释。
- 日志 / trace 使用稳定英文事件名，message 可用中文。
- 不记录完整敏感正文、完整 query、完整 `thought`、完整工具 observation 或密钥。

### Prompt 风格

- prompt 集中在 `app/prompts/react_policy.py`，不得内联散落在业务逻辑里。
- 使用具名占位符，不通过字符串拼接混合系统指令和用户 / 检索数据。
- 外部 / 用户 / 检索数据必须包裹在 `<data>...</data>` 或等价分隔符内，并声明数据区不作为指令。
- 输出强制 JSON，schema 设置 `required`、类型约束、枚举 / null 行为和 `additionalProperties: false`。
- 专利域默认约束必须写入：禁止臆造、不确定显式标注、使用规范术语。

### 错误处理与降级

- LLM 或工具异常不得裸异常中断 QA；应记录 warning / trace，走 heuristic 或基于已有 evidence 收敛。
- 非法 action、未知工具、禁用工具、schema 不合规必须拒绝调用。
- 预算 `<= 0` 时不调用工具，直接按对应 reason 收敛。
- 超时检查必须在循环中生效，不能只在循环结束后检查。
- 外部工具未启用时，即使 LLM 选择也不得调用。

---

## 5. Testing Strategy

### ReActPolicy 测试

必须覆盖：

- `LLMReActPolicy` 能解析合法结构化决策。
- 缺少必填字段、非 dict、非法 JSON 或类型错误时触发降级。
- action 为未知工具时被主循环拒绝并降级或停止。
- `tool_input.query` 可由 FakeLLMClient 在第二步改写，且主循环实际使用改写后的 query。
- `HeuristicReActPolicy` 行为与旧确定性循环一致。
- 无 LLM 配置或 FakeLLMClient 模拟失败时，driver 自动回退 heuristic。

### ReAct 主循环测试

必须覆盖：

- LLM 配置齐全时，trace 出现 `react_policy_step` 且 `driver="llm"`。
- 多步场景中第二步 `tool_input.query` 与首步不同。
- `decision.sufficient=true` 时以 `sufficient` 收敛。
- `decision.stop=true` 且证据未充分时以 `policy_stop` 收敛。
- `react_use_llm_judge=false` 时回退阈值 / evidence 兜底。
- 非法 action / LLM 失败时当步 fallback，循环不崩，`fallback_used=true`。
- 任何情况下 `steps_used <= react_max_steps`。
- token 预算耗尽时以 `token_budget` 收敛。
- 超时时以 `timeout` 收敛。
- 工具不可用时以 `tool_unavailable` 收敛。

### QA 节点测试

必须覆盖：

- `QANode._build_react_loop` 正确注入 policy、driver、react_* 配置。
- QA 注入 `FakeLLMClient` 决策序列后，工具调用顺序与收敛原因可断言。
- 默认只开放 `kb_retrieval`；外部工具开关关闭时 LLM 选择外部工具也不得调用。
- 主循环返回 evidence 后，最终 QA `basis` 仍只回链真实来源。
- 依据不足、预算耗尽或工具不可用时仍输出风险提示。

### 配置测试

必须覆盖：

- `react_policy_driver`、`react_max_steps`、`react_policy_model`、`react_policy_temperature`、`react_use_llm_judge`、`react_token_budget`、`react_timeout_seconds` 默认值正确。
- 对应 `PAGENT_REACT_*` 环境变量可覆盖。
- `to_public_dict()` 包含非敏感 `react_*` 配置。
- API Key、token、secret、password 不进入公开配置、日志或 trace。
- `retrieval_max_steps` 兼容映射到 `react_max_steps` 的行为有测试覆盖，或明确删除旧兼容并同步测试。

### Trace 测试

必须覆盖：

- 每步写入 `react_policy_step`。
- `react_policy_step` 包含 `node_name`、`step_index`、`tool_name`、`thought_len`、`stop`、`sufficient`、`driver`。
- `react_policy_step` 不包含完整 `thought`、完整 query、完整正文或密钥。
- 收敛 trace 包含 `driver` 与 `fallback_used`。
- `continue_or_converge` 在生产代码中删除，或仅保留在 heuristic 分支。

### 验收口径

- `conda run -n autoGLM pytest tests/test_react_policy.py tests/test_agentic_loop.py tests/test_qa_node.py tests/test_core_config_logging.py` 通过。
- `conda run -n autoGLM pytest` 通过。
- `conda run -n autoGLM python -m compileall app tests scripts` 通过。
- 默认测试不触网、不调用真实付费 LLM。
- 搜索 `continue_or_converge`，仅允许出现在 heuristic 分支或已删除。

---

## 6. Boundaries

### Always do

- 始终由代码强制预算、白名单、超时、外部工具开关和敏感内容限制。
- 始终让 LLM 只输出结构化决策，不直接执行工具。
- 始终校验 action 与 tool_input schema 后再调用工具。
- 始终在 LLM 失败、非法 action 或 schema 不合规时安全降级。
- 始终保留无 LLM 环境下的确定性 heuristic 行为。
- 始终使用 fake / stub / monkeypatch 做默认测试。
- 始终使用 `conda run -n autoGLM` 执行 Python、pytest 和脚本命令。
- 始终避免新增绑定单 Node 的配置名。

### Ask first

- 是否调用真实 LLM 做人工验收。
- 是否允许向云模型发送完整敏感专利材料。
- 是否接入真实 websearch、法律状态或官费服务。
- 是否新增外部 SDK 或依赖。
- 是否保留旧 `retrieval_max_steps` 到 `react_max_steps` 的兼容窗口。
- 是否提高 `react_max_steps`、token 预算或超时上限。

### Never do

- 不让 LLM 调用未注册工具、任意函数、任意 URL 或改变全局 workflow。
- 不做无界循环、跨会话无限 ReAct 或开放式 AutoGPT。
- 不伪造检索来源、网页来源、法条、专利号、法律状态或官费信息。
- 不在 trace / 日志记录完整 `thought`、完整 query、完整工具返回正文、完整敏感材料或密钥。
- 不在默认测试中触网、下载模型或调用真实付费服务。
- 不让预算耗尽、超时、工具失败或 LLM 失败导致裸异常中断 QA。

---

## 7. Functional Acceptance Checklist

- [ ] 新增 `app/orchestrator/react_policy.py`。
- [ ] 新增 `app/prompts/react_policy.py` 与 `REACT_DECISION_SCHEMA`。
- [ ] 实现 `ReActDecision` / `ReActPolicy` / `LLMReActPolicy` / `HeuristicReActPolicy`。
- [ ] `BoundedReActLoop` 每步通过 policy 决策。
- [ ] `BoundedReActLoop` 校验 action 白名单和 tool_input schema。
- [ ] `BoundedReActLoop` 支持 LLM 失败当步 fallback。
- [ ] outcome 扩展 `driver` 与 `fallback_used`。
- [ ] trace 新增 `react_policy_step`。
- [ ] `react_main_converged` 扩展 `driver` 与 `fallback_used`。
- [ ] `ToolSpec` 增加 `description` 与 `input_schema`。
- [ ] registry 暴露 `tool_cards()`。
- [ ] 新增 `react_*` 配置与 `PAGENT_REACT_*` 环境变量读取。
- [ ] `react_*` 非敏感配置进入 `to_public_dict()`。
- [ ] `QANode._build_react_loop` 接入 policy 和 react_* 配置。
- [ ] 多步场景支持基于 observation 改写 query。
- [ ] `react_use_llm_judge=false` 时回退阈值兜底。
- [ ] 无 LLM 环境行为与旧确定性循环一致。
- [ ] 非法 action / LLM 失败不会导致循环崩溃。
- [ ] 任何情况下 `steps_used <= react_max_steps`。
- [ ] 默认测试使用 FakeLLMClient，不触网、不调用真实付费服务。
- [ ] `conda run -n autoGLM pytest` 通过。
- [ ] `conda run -n autoGLM python -m compileall app tests scripts` 通过。

---

## 8. Implementation Order

1. 定义 `ReActDecision`、`ToolCard`、决策 schema 与 prompt。
2. 抽出 `HeuristicReActPolicy`，保持旧确定性行为不变。
3. 实现 `LLMReActPolicy`，基于 `LLMClient.generate` 与结构化 schema。
4. 改造 `BoundedReActLoop`：policy 注入、决策校验、fallback、trace、outcome 扩展。
5. 改造 `tool_registry`：补充工具描述、输入 schema、`tool_cards()`。
6. 接入 `config.py` 的 `react_*` 配置与公开配置。
7. 更新 `QANode._build_react_loop`，让 QA 使用 policy 驱动主循环。
8. 新增 / 更新测试：`test_react_policy.py`、`test_agentic_loop.py`、`test_qa_node.py`、`test_core_config_logging.py`。
9. 运行目标测试、全量 pytest 和 compileall。
