# R7.1 LLM 驱动 ReAct 主循环 Todo

## Phase 0 — 迁移口径确认

- [x] 确认 `retrieval_max_steps` 到 `react_max_steps` 的兼容口径。
  - 验收：新代码优先 `react_max_steps`，旧 `retrieval_max_steps` 保留为兼容配置。
- [x] 确认 `react_policy_driver` 默认行为。
  - 验收：默认 `llm`，无完整 LLM 配置时自动 heuristic，不触网。
- [x] 确认 `react_use_llm_judge` 行为。
  - 验收：开启时优先 `decision.sufficient`，关闭时用 observation / evidence 兜底。
- [x] 确认外部工具本轮不接真实服务。
  - 验收：沿用 R7 开关，默认关闭，测试不触网。

## Phase 1 — Policy 与 prompt 最小闭环

- [x] 新增 `app/orchestrator/react_policy.py`。
  - 验收：模块可导入，公共类 / 方法有中文 docstring。
- [x] 定义 `ReActDecision`。
  - 验收：字段包含 `thought`、`action`、`tool_input`、`stop`、`sufficient`。
- [x] 定义 `ReActPolicy` protocol。
  - 验收：`decide(task_input, allowed_tools, scratchpad, step_index)` 返回 `ReActDecision`。
- [x] 实现 `HeuristicReActPolicy`。
  - 验收：封装旧确定性逻辑，默认 query 仍来自原始 `task_input`。
- [x] 实现 `LLMReActPolicy`。
  - 验收：调用 `LLMClient.generate(messages=..., output_schema=..., trace_context={"task_type": "react_policy"})`。
- [x] 新增 `app/prompts/react_policy.py`。
  - 验收：prompt 不内联在业务逻辑中。
- [x] 定义 `REACT_DECISION_SCHEMA`。
  - 验收：包含 required、类型约束、`additionalProperties: False`。
- [x] 编写 react policy prompt builder。
  - 验收：覆盖任务目标、上下文 / 判定规则、角色、受众、样例、输出格式六要素。
- [x] 实现 prompt 指令 / 数据分离。
  - 验收：用户任务、工具卡片、scratchpad 作为数据区传入。
- [x] 新增 `tests/test_react_policy.py`。
  - 验收：覆盖合法决策、缺字段、类型错误、LLM error、trace_context。
- [x] 验证 Phase 1。
  - 命令：`conda run -n autoGLM pytest tests/test_react_policy.py`

## Phase 2 — 工具卡片与 schema 边界

- [x] 新增 `ToolCard` dataclass。
  - 验收：字段包含 `name`、`description`、`input_schema`。
- [x] 扩展 `ToolSpec.description`。
  - 验收：每个默认工具有用途描述。
- [x] 扩展 `ToolSpec.input_schema`。
  - 验收：每个默认工具有结构化输入 schema。
- [x] 实现 `ToolRegistry.tool_cards(...)`。
  - 验收：只返回已注册、已启用、且被允许的工具卡片。
- [x] 为 `kb_retrieval` 定义输入 schema。
  - 验收：`query` 必填，可选 `top_k`、`as_of`、`fetch_k`。
- [x] 为 `websearch` 定义输入 schema 与描述。
  - 验收：默认关闭时不出现在可用 cards 中。
- [x] 为 `legal_status` 定义输入 schema 与描述。
  - 验收：默认关闭时不出现在可用 cards 中。
- [x] 为 `official_fee` 定义输入 schema 与描述。
  - 验收：默认关闭时不出现在可用 cards 中。
- [x] 更新 `tests/test_agentic_tools.py`。
  - 验收：覆盖 tool cards、禁用工具、未注册工具、schema 元数据。
- [x] 验证 Phase 2。
  - 命令：`conda run -n autoGLM pytest tests/test_agentic_tools.py tests/test_react_policy.py`

## Phase 3 — 主循环 policy 驱动改造

- [x] 扩展 `ReActOutcome.driver`。
  - 验收：outcome 可观测 `llm` / `heuristic`。
- [x] 扩展 `ReActOutcome.fallback_used`。
  - 验收：policy 失败或非法 action 后为 `True`。
- [x] 修改 `BoundedReActLoop.__init__` 支持注入 policy。
  - 验收：测试可注入 fake / scripted policy。
- [x] 修改 `BoundedReActLoop.__init__` 支持工具卡片 metadata。
  - 验收：run 时能把 allowed tool cards 传给 policy。
- [x] 在 `run()` 中维护 scratchpad。
  - 验收：scratchpad 只含摘要，不含完整 query / evidence 正文。
- [x] 每步调用 `policy.decide(...)`。
  - 验收：不再按下标固定选工具作为主路径。
- [x] 校验 `decision.action` 白名单。
  - 验收：未知、禁用、未允许工具不会被调用。
- [x] 校验 `decision.tool_input` schema。
  - 验收：缺少必填字段或类型不匹配时 fallback。
- [x] 支持 `policy_stop` 收敛。
  - 验收：`decision.stop=true` 且未充分时 reason 为 `policy_stop`。
- [x] 支持 LLM judge 开关。
  - 验收：`react_use_llm_judge=false` 时不使用 `decision.sufficient` 直接收敛。
- [x] 执行工具时使用 `decision.tool_input`。
  - 验收：多步场景第二步 query 可不同于首步。
- [x] 实现当步 fallback 到 `HeuristicReActPolicy`。
  - 验收：LLM error、非法 action、schema error 不导致循环崩溃。
- [x] 新增 `react_policy_step` trace。
  - 验收：包含 `node_name`、`step_index`、`tool_name`、`thought_len`、`stop`、`sufficient`、`driver`。
- [x] 扩展 `react_main_converged` trace。
  - 验收：包含 `driver`、`fallback_used`。
- [x] 清理固定 `continue_or_converge` 主路径。
  - 验收：仅允许在 heuristic 分支出现，或完全删除。
- [x] 更新 `tests/test_agentic_loop.py`。
  - 验收：覆盖 llm driver、多步 query 改写、policy_stop、fallback、预算硬约束。
- [x] 验证 Phase 3。
  - 命令：`conda run -n autoGLM pytest tests/test_agentic_loop.py tests/test_react_policy.py`

## Phase 4 — react_* 配置接入

- [ ] 新增 `react_policy_driver` 配置。
  - 验收：默认 `llm`，`PAGENT_REACT_POLICY_DRIVER` 可覆盖。
- [ ] 新增 `react_max_steps` 配置。
  - 验收：默认 `4`，`PAGENT_REACT_MAX_STEPS` 可覆盖。
- [ ] 新增 `react_policy_model` 配置。
  - 验收：默认空，policy 可回退 `llm_cheap_model` / `llm_model`。
- [ ] 新增 `react_policy_temperature` 配置。
  - 验收：默认 `0.0`，环境变量可覆盖。
- [ ] 新增 `react_use_llm_judge` 配置。
  - 验收：默认 `True`，环境变量可覆盖。
- [ ] 新增 `react_token_budget` 配置。
  - 验收：默认沿用 retrieval token budget，环境变量可覆盖。
- [ ] 新增 `react_timeout_seconds` 配置。
  - 验收：默认沿用 retrieval timeout，环境变量可覆盖。
- [ ] 更新 `get_settings()` 环境变量读取。
  - 验收：所有 `PAGENT_REACT_*` 生效。
- [ ] 更新 `Settings.to_public_dict()`。
  - 验收：非敏感 `react_*` 可见，密钥仍不可见。
- [ ] 更新 `tests/test_core_config_logging.py` 默认值测试。
  - 验收：新增 react 默认字段均被断言。
- [ ] 更新 `tests/test_core_config_logging.py` 环境变量测试。
  - 验收：新增 `PAGENT_REACT_*` 均被断言。
- [ ] 更新 `tests/test_core_config_logging.py` 公开配置测试。
  - 验收：新增 react 字段在 public dict 中。
- [ ] 验证 Phase 4。
  - 命令：`conda run -n autoGLM pytest tests/test_core_config_logging.py`

## Phase 5 — QA 接入 policy 驱动主循环

- [ ] 修改 `QANode.__init__` 默认预算来源。
  - 验收：默认继承 `react_max_steps`、`react_token_budget`、`react_timeout_seconds`。
- [ ] 保持 QANode 构造参数覆盖语义。
  - 验收：`0` / `False` 等有效值不被 `or` 吞掉。
- [ ] 修改 `QANode._build_react_loop` 构建 policy。
  - 验收：按 `react_policy_driver` 选择 LLM 或 heuristic。
- [ ] 无 LLM 配置时自动 heuristic。
  - 验收：默认测试不触网。
- [ ] QA 构建 loop 时传入 tool cards / registry metadata。
  - 验收：policy 可见工具描述和 schema。
- [ ] QA 注入 FakeLLMClient 决策序列测试。
  - 验收：工具调用顺序、query 改写、收敛 reason 可断言。
- [ ] QA 无 LLM 回归测试。
  - 验收：行为与旧确定性循环一致。
- [ ] QA 外部工具关闭测试。
  - 验收：LLM 选择外部工具也不会调用。
- [ ] QA basis 回链测试。
  - 验收：最终 basis 仍只引用真实 evidence 来源。
- [ ] 验证 Phase 5。
  - 命令：`conda run -n autoGLM pytest tests/test_qa_node.py tests/test_agentic_loop.py`

## Phase 6 — Trace、安全与旧行为清理

- [ ] 确认 `react_policy_step` 不记录完整 thought。
  - 验收：trace 中只有 `thought_len` 或安全摘要。
- [ ] 确认 trace 不记录完整 query。
  - 验收：负向测试包含敏感 query 字符串。
- [ ] 确认 trace 不记录完整 evidence 正文。
  - 验收：负向测试包含敏感 evidence 字符串。
- [ ] 确认 LLM trace_context 不含 raw input / api_key。
  - 验收：FakeLLMClient trace 中不出现敏感字段。
- [ ] 搜索并清理 `continue_or_converge`。
  - 验收：仅保留在 heuristic 分支或已删除。
- [ ] 确认 outcome 与 converged trace 都有 `driver`。
  - 验收：测试断言字段存在。
- [ ] 确认 outcome 与 converged trace 都有 `fallback_used`。
  - 验收：fallback 场景测试断言为 `True`。
- [ ] 验证 Phase 6。
  - 命令：`conda run -n autoGLM pytest tests/test_agentic_loop.py tests/test_qa_node.py`

## Phase 7 — 回归与总体验收

- [ ] 运行 R7.1 目标测试。
  - 命令：`conda run -n autoGLM pytest tests/test_react_policy.py tests/test_agentic_loop.py tests/test_qa_node.py tests/test_core_config_logging.py`
- [ ] 运行全量测试。
  - 命令：`conda run -n autoGLM pytest`
- [ ] 运行编译检查。
  - 命令：`conda run -n autoGLM python -m compileall app tests scripts`
- [ ] 确认默认测试不触网。
  - 验收：真实 LLM、websearch、legal_status、official_fee 均未调用。
- [ ] 更新 todo 完成状态。
  - 验收：已完成项勾选，延期项保留未勾选并说明原因。
