# R7.1 LLM 驱动 ReAct 主循环实施计划

## 背景

R7.1 要把当前 `BoundedReActLoop` 从“按 `allowed_tools` 下标确定性执行工具”的执行器，升级为 LLM 驱动的受限 ReAct 主循环。每步由 `ReActPolicy` 基于任务、工具卡片、scratchpad / observation 决策 `thought`、`action`、`tool_input`、`stop`、`sufficient`，但预算、白名单、超时、外部工具开关、敏感内容限制仍由代码强约束。

本计划只拆解实现路径与验收任务，不生成业务代码。

## 当前代码基线

- `app/orchestrator/react_loop.py` 已有 `ReActBudget`、`ToolObservation`、`ReActOutcome`、`BoundedReActLoop`，但仍按 `allowed_tools[min(step_index, len(allowed_tools)-1)]` 选工具，工具入参固定为 `{"query": task_input, "step_index": step_index}`。
- `ReActOutcome` 还没有 `driver` / `fallback_used` 字段。
- trace 有 `react_main_step` / `react_main_converged`，但 `react_main_step.data.decision` 仍是固定 `continue_or_converge`。
- `app/orchestrator/tool_registry.py` 已有 `ToolSpec`、`ToolRegistry`、`KBRetrievalTool`、外部工具注册，但 `ToolSpec` 还没有 `description` / `input_schema`，registry 还没有 `tool_cards()`。
- `app/nodes/qa.py` 已委派 `BoundedReActLoop`，但仍使用 `retrieval_max_steps` 等旧预算配置，未注入 policy。
- `app/core/config.py` 已有 `retrieval_*` 与 `agentic_*` 配置，但没有 `react_policy_driver`、`react_max_steps`、`react_policy_model`、`react_policy_temperature`、`react_use_llm_judge`、`react_token_budget`、`react_timeout_seconds`。
- `app/tools/llm.py` 已有 `LLMClient.generate(messages, output_schema, trace_context)`、`FakeLLMClient`、`OpenAICompatibleClient`，可复用实现 `LLMReActPolicy`。

## 依赖图

```text
SPEC.md
  -> app/prompts/react_policy.py
      -> REACT_DECISION_SCHEMA
      -> build_react_policy_messages(...)
      -> app/orchestrator/react_policy.py

  -> app/orchestrator/react_policy.py
      -> ReActDecision / ReActPolicy
      -> HeuristicReActPolicy
      -> LLMReActPolicy
      -> app/orchestrator/react_loop.py
      -> tests/test_react_policy.py

  -> app/orchestrator/tool_registry.py
      -> ToolCard / ToolSpec.description / ToolSpec.input_schema
      -> ToolRegistry.tool_cards(...)
      -> tool_input schema 校验输入来源
      -> app/orchestrator/react_loop.py
      -> tests/test_agentic_tools.py

  -> app/core/config.py
      -> react_* Settings 字段
      -> PAGENT_REACT_* 环境变量读取
      -> to_public_dict()
      -> app/nodes/qa.py
      -> tests/test_core_config_logging.py

  -> app/orchestrator/react_loop.py
      -> policy 注入
      -> 每步 policy.decide(...)
      -> action / schema 校验
      -> fallback heuristic
      -> react_policy_step trace
      -> ReActOutcome.driver / fallback_used
      -> tests/test_agentic_loop.py

  -> app/nodes/qa.py
      -> _build_react_loop 注入 policy / react_* 预算
      -> 默认 Fake / 无 LLM 时 heuristic
      -> tests/test_qa_node.py

  -> final verification
      -> tests/test_react_policy.py
      -> tests/test_agentic_loop.py
      -> tests/test_qa_node.py
      -> tests/test_core_config_logging.py
      -> pytest / compileall
```

## 垂直切片原则

每个任务都交付一条可验证路径：

1. 先让 policy + prompt 在 fake LLM 下可解析、可降级。
2. 再让工具卡片和 schema 进入主循环决策边界。
3. 再改造主循环，每步通过 policy 决策并执行 fallback。
4. 再把 QA 和配置接到新主循环。
5. 最后回归 trace、安全和全量验收。

---

## Phase 0 — 迁移口径确认

### 目标

在改代码前确认会影响兼容行为的口径。

### 决策

1. `retrieval_max_steps` 到 `react_max_steps`：默认按 SPEC 保留一个版本兼容读取；新代码优先用 `react_max_steps`。
2. `react_policy_driver` 默认 `llm`，但无完整 LLM 配置时自动 heuristic，不触网。
3. `react_use_llm_judge=true` 时优先使用 `decision.sufficient`；为 `false` 时使用 observation / evidence 阈值兜底。
4. 外部工具仍沿用 R7 开关，本轮不接真实服务。

### 验收标准

- 上述口径体现在 plan / todo 中。
- 默认测试不依赖真实 LLM 或真实外部工具。

### Checkpoint 0

人工确认后进入 Phase 1。

---

## Phase 1 — Policy 与 prompt 最小闭环

### 目标

新增 `ReActPolicy` 抽象、LLM 决策 schema 和 prompt，让 fake LLM 能生成结构化决策，失败时能转为可控错误供主循环 fallback。

### 涉及文件

- `app/orchestrator/react_policy.py`
- `app/prompts/react_policy.py`
- `tests/test_react_policy.py`

### 实施要点

- 新增 `ReActDecision` dataclass。
- 新增 `ReActPolicy` protocol。
- 新增 `HeuristicReActPolicy`，封装旧逻辑：按工具顺序选工具、原始 query、简单 sufficient 判断。
- 新增 `LLMReActPolicy`，复用 `LLMClient.generate(messages=..., output_schema=..., trace_context={"task_type": "react_policy"})`。
- 新增 `REACT_DECISION_SCHEMA`，设置 required、类型约束、`additionalProperties: False`。
- 新增 prompt builder，满足六要素、JSON 输出、指令 / 数据分离和专利域约束。
- `thought` 只保留短摘要，不要求完整推理链。

### 验收标准

- fake LLM 返回合法 dict 时可解析为 `ReActDecision`。
- 缺少 required、类型错误、LLM errors、非 dict 内容会触发可识别失败路径。
- `LLMReActPolicy` 传入 `model`、`temperature=0.0`、`timeout` 和 trace_context。
- prompt 不内联在业务逻辑中。

### 验证命令

```bash
conda run -n autoGLM pytest tests/test_react_policy.py
```

### Checkpoint 1

policy 单元测试通过后，才能让主循环依赖 policy。

---

## Phase 2 — 工具卡片与 schema 边界

### 目标

让工具 registry 能向 policy 暴露安全的工具描述和输入 schema，并为主循环校验 `tool_input` 提供依据。

### 涉及文件

- `app/orchestrator/tool_registry.py`
- `tests/test_agentic_tools.py`
- `tests/test_react_policy.py`

### 实施要点

- 新增 `ToolCard` dataclass：`name`、`description`、`input_schema`。
- 扩展 `ToolSpec`：增加 `description`、`input_schema`，保留 `runner`、`external`、`enabled`。
- `ToolRegistry.tool_cards(allowed_tools)` 仅返回已注册、已启用、且在 allowed 列表内的工具卡片。
- 为 `kb_retrieval` 定义 schema：至少支持 `query`，可选 `top_k`、`as_of`、`fetch_k`。
- 为 `websearch`、`legal_status`、`official_fee` 定义默认关闭下的输入 schema 和描述。
- 明确 schema 校验由主循环执行；registry 负责提供 metadata。

### 验收标准

- 默认 `kb_retrieval` tool card 有 description 和 input_schema。
- 禁用外部工具不出现在可用 cards 中。
- 未注册工具不会生成 card。
- schema 不包含密钥或敏感配置。

### 验证命令

```bash
conda run -n autoGLM pytest tests/test_agentic_tools.py tests/test_react_policy.py
```

### Checkpoint 2

工具卡片稳定后，主循环才能把 allowed tool cards 传给 policy。

---

## Phase 3 — 主循环 policy 驱动改造

### 目标

改造 `BoundedReActLoop`，每步先经 policy 决策，再由代码校验并执行工具。保留预算硬约束和 heuristic fallback。

### 涉及文件

- `app/orchestrator/react_loop.py`
- `app/orchestrator/react_policy.py`
- `app/orchestrator/tool_registry.py`
- `tests/test_agentic_loop.py`
- `tests/test_react_policy.py`

### 实施要点

- `BoundedReActLoop.__init__` 支持注入 `policy`、`heuristic_policy`、`tool_specs` 或 `tool_registry` 可用 metadata。
- `run()` 中维护 scratchpad：每步只保存 thought_len / action / observation_count / top_score / error 等摘要。
- 每步调用 `policy.decide(task_input, allowed_tool_cards, scratchpad, step_index)`。
- 校验 `decision.action`：必须在 allowed tools 且工具存在；非法时 fallback 或 `tool_unavailable`。
- 校验 `decision.tool_input`：至少确保 required 字段存在、类型基本匹配，失败时 fallback。
- `decision.stop` 或 `action is None` 时收敛为 `sufficient` 或 `policy_stop`。
- 执行 `tool.run(decision.tool_input)`，不再固定传入原始 query。
- `react_use_llm_judge=true` 时使用 `decision.sufficient`；false 时使用 observation / evidence 兜底。
- LLM policy 失败、非法 action、schema 失败时当步使用 `HeuristicReActPolicy`。
- `ReActOutcome` 扩展 `driver` 和 `fallback_used`。
- 新增 `react_policy_step` trace，且不记录完整 `thought` / query / evidence。
- `react_main_converged` 增加 `driver` 和 `fallback_used`。
- 删除或限定 `continue_or_converge` 只在 heuristic 分支出现。

### 验收标准

- LLM driver 下 trace 出现 `react_policy_step`，`driver="llm"`。
- 第二步可使用不同 `tool_input.query`，证明基于 observation 改写。
- `decision.sufficient=true` 以 `sufficient` 收敛。
- `decision.stop=true` 且未充分时以 `policy_stop` 收敛。
- 非法 action / LLM failure / schema failure 不崩溃，`fallback_used=true`。
- 任何路径 `steps_used <= react_max_steps`。
- trace 不包含完整 thought、完整 query、完整正文或密钥。

### 验证命令

```bash
conda run -n autoGLM pytest tests/test_agentic_loop.py tests/test_react_policy.py
```

### Checkpoint 3

主循环 policy 驱动路径通过后，才能改配置和 QA 接入。

---

## Phase 4 — react_* 配置接入

### 目标

新增 R7.1 通用配置，支持 LLM / heuristic driver、步数、模型、温度、LLM judge、token 和 timeout 预算。

### 涉及文件

- `app/core/config.py`
- `tests/test_core_config_logging.py`

### 实施要点

- 新增 `react_policy_driver: str = "llm"`。
- 新增 `react_max_steps: int = 4`。
- 新增 `react_policy_model: str | None = None`。
- 新增 `react_policy_temperature: float = 0.0`。
- 新增 `react_use_llm_judge: bool = True`。
- 新增 `react_token_budget`，默认沿用 `retrieval_token_budget`。
- 新增 `react_timeout_seconds`，默认沿用 `retrieval_timeout_seconds`。
- 读取 `PAGENT_REACT_*` 环境变量。
- `to_public_dict()` 暴露非敏感 react 配置。
- 兼容：若未设置 `PAGENT_REACT_MAX_STEPS`，可让 QA / build loop 使用 `react_max_steps` 默认 4；`retrieval_max_steps` 仍保留但不再作为新主循环首选。
- 不新增 `qa_*` 配置。

### 验收标准

- 默认值符合 SPEC。
- 环境变量覆盖生效。
- 公开配置包含非敏感 `react_*`。
- 敏感字段仍不出现在 public dict。

### 验证命令

```bash
conda run -n autoGLM pytest tests/test_core_config_logging.py
```

### Checkpoint 4

配置测试通过后，才让 QA 构建 loop 时依赖这些字段。

---

## Phase 5 — QA 接入 policy 驱动主循环

### 目标

更新 `QANode._build_react_loop`，按配置构建 LLM / heuristic policy，并把 react_* 预算传入主循环。

### 涉及文件

- `app/nodes/qa.py`
- `app/tools/llm.py`（只复用 build_llm_client）
- `tests/test_qa_node.py`
- `tests/test_agentic_qa_integration.py`（如需要更新）

### 实施要点

- `QANode.__init__` 预算默认从 `react_max_steps`、`react_token_budget`、`react_timeout_seconds` 继承。
- 保持构造参数覆盖语义：`settings.xxx if arg is None else arg`。
- `_build_react_loop` 构建 registry 后传入 available tools 和 tool cards。
- 根据 `react_policy_driver` 和 LLM 配置选择 `LLMReActPolicy` 或 `HeuristicReActPolicy`。
- 无 LLM 配置时不触网，自动 heuristic。
- QA 仍默认 allowed tools 为 `agentic_default_tools`，通常仅 `kb_retrieval`。
- 保持 `_build_evidence`、依据不足提示、法规 stale 提示、`qa_completed` trace。

### 验收标准

- QA 可注入 FakeLLMClient 决策序列并断言工具调用顺序。
- 无 LLM 配置时 QA 行为与旧确定性循环一致。
- `react_max_steps` 生效，默认不再被 `retrieval_max_steps=1` 限制。
- 外部工具开关关闭时，即使 LLM 选择外部工具也不得调用。
- QA 最终 `basis` 仍只回链真实 evidence。

### 验证命令

```bash
conda run -n autoGLM pytest tests/test_qa_node.py tests/test_agentic_loop.py
```

### Checkpoint 5

QA policy 路径通过后，再做 trace / 旧常量清理。

---

## Phase 6 — Trace、安全与旧行为清理

### 目标

确保观测字段完整、敏感信息不泄露，并清理旧确定性 trace 常量。

### 涉及文件

- `app/orchestrator/react_loop.py`
- `app/orchestrator/react_policy.py`
- `tests/test_agentic_loop.py`
- `tests/test_qa_node.py`

### 实施要点

- `react_policy_step` 只记录 `thought_len` 或安全摘要，不落完整 thought。
- `react_main_step` 不记录完整 query / evidence。
- `react_main_converged` 记录 `driver`、`fallback_used`。
- LLM trace_context 不包含 raw input、api_key、完整 prompt。
- 搜索 `continue_or_converge`，删除或限制在 heuristic 分支。
- 确认 `fallback_used` 在 outcome 和 trace 可观测。

### 验收标准

- trace 断言覆盖完整 thought / query / content 不泄露。
- `driver` / `fallback_used` 在 outcome 和 converged trace 中可见。
- `continue_or_converge` 不再作为主循环固定常量。

### 验证命令

```bash
conda run -n autoGLM pytest tests/test_agentic_loop.py tests/test_qa_node.py
```

### Checkpoint 6

trace 与安全断言通过后，进入总体验收。

---

## Phase 7 — 回归与总体验收

### 目标

完成目标测试、全量测试和编译检查，确认 R7.1 默认路径不触网、不调用真实付费服务。

### 涉及文件

- `tests/test_react_policy.py`
- `tests/test_agentic_loop.py`
- `tests/test_qa_node.py`
- `tests/test_core_config_logging.py`
- `tasks/plan.md`
- `tasks/todo.md`

### 实施要点

- 目标测试先跑，定位 R7.1 相关失败。
- 全量 pytest 确认旧功能不回归。
- compileall 确认新增模块语法正确。
- 更新 todo 勾选状态。

### 验收标准

- 目标测试通过。
- 全量测试通过。
- compileall 通过。
- 默认测试不触网、不调用真实 LLM。

### 验证命令

```bash
conda run -n autoGLM pytest tests/test_react_policy.py tests/test_agentic_loop.py tests/test_qa_node.py tests/test_core_config_logging.py
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests scripts
```

## 风险与控制

- **风险：LLM 选错或幻觉工具。** 控制：白名单强校验、schema 校验、非法 action fallback。
- **风险：无 key 环境回归。** 控制：build loop 自动 heuristic，FakeLLMClient 测试覆盖。
- **风险：默认步数从 1 变 4 导致测试变化。** 控制：QA 测试显式断言 react_* 默认与覆盖行为。
- **风险：trace 泄露 thought / query / evidence。** 控制：新增负向断言。
- **风险：配置语义分叉。** 控制：新代码优先 react_*，retrieval_* 只做兼容来源。

## 总体验证计划

```bash
conda run -n autoGLM pytest tests/test_react_policy.py
conda run -n autoGLM pytest tests/test_agentic_tools.py tests/test_react_policy.py
conda run -n autoGLM pytest tests/test_agentic_loop.py tests/test_react_policy.py
conda run -n autoGLM pytest tests/test_core_config_logging.py
conda run -n autoGLM pytest tests/test_qa_node.py tests/test_agentic_loop.py
conda run -n autoGLM pytest tests/test_react_policy.py tests/test_agentic_loop.py tests/test_qa_node.py tests/test_core_config_logging.py
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests scripts
```
