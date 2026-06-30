# R7 Agentic 编排 Todo

## Phase 0 — 决策与迁移口径确认

- [ ] 确认旧 `retrieval_react_*` 配置直接删除或保留兼容窗口。
  - 验收：实现前有明确口径；测试按该口径编写。
- [ ] 确认外部工具本轮只做 stub / 关闭，或接入真实服务。
  - 验收：若接真实服务，补充密钥、安全和默认测试 stub 要求。
- [ ] 确认工具选择本轮使用 deterministic policy，LLM router 仅预留或实现。
  - 验收：主循环测试不依赖真实 LLM。

## Phase 1 — 主循环最小闭环

- [ ] 新增 `app/orchestrator/react_loop.py`。
  - 验收：模块可导入，公共类 / 函数有中文 docstring。
- [ ] 定义 `ReActBudget` / `ReActOutcome` / `ToolObservation` 或等价结构。
  - 验收：能表达 evidence、trace、收敛原因、steps_used、tool_calls。
- [ ] 实现 bounded ReAct 主循环。
  - 验收：支持 reason -> act -> observe -> judge -> converge。
- [ ] 支持 `sufficient` 收敛。
  - 验收：fake 工具首轮证据充分时只调用 1 次。
- [ ] 支持 `max_steps` 收敛。
  - 验收：证据不足时达到步数上限停止。
- [ ] 支持 `token_budget` 收敛。
  - 验收：预算耗尽时不继续调用工具。
- [ ] 支持 `timeout` 收敛。
  - 验收：超时时返回 outcome，不裸抛。
- [ ] 支持 `tool_unavailable` / `unsafe_request` 收敛。
  - 验收：未知工具、不可用工具、越权请求不执行工具。
- [ ] 输出 `react_main_step` trace。
  - 验收：包含 `node_name`、`step_index`、`tool_name`、`input_len`、`observation_count`、`external`。
- [ ] 输出 `react_main_converged` trace。
  - 验收：包含 `reason`、`steps_used`、`tool_calls`、`total_evidence`、`external_tools_used`。
- [ ] 新增 `tests/test_agentic_loop.py`。
  - 验收：覆盖充分、步数、预算、超时、工具不可用、trace、异常降级。
- [ ] 验证 Phase 1。
  - 命令：`conda run -n autoGLM pytest tests/test_agentic_loop.py`

## Phase 2 — 工具注册与 `kb_retrieval`

- [ ] 新增 `app/orchestrator/tool_registry.py`。
  - 验收：工具必须显式注册，不能动态 import 任意工具。
- [ ] 定义工具元数据和统一运行接口。
  - 验收：包含工具名、external 标记、启用条件、输入校验、run 行为。
- [ ] 实现 `kb_retrieval` 工具适配器。
  - 验收：复用 `build_retriever(settings).search(...)`。
- [ ] 归一化 KB observation 为 evidence。
  - 验收：保留 `document_id`、`source`、`locator`、`doc_type`、score / similarity。
- [ ] 保留法规时效字段。
  - 验收：`law_name`、`version`、`effective_date`、`expiry_date`、`status`、`retrieved_at` 可进入 evidence。
- [ ] 拒绝未注册工具。
  - 验收：返回安全失败 observation 或 `tool_unavailable`。
- [ ] 拒绝禁用工具。
  - 验收：开关关闭时不调用工具 run。
- [ ] 新增 `tests/test_agentic_tools.py` 工具注册测试。
  - 验收：白名单、未注册、禁用、非法输入、异常降级均覆盖。
- [ ] 回归 `tests/test_retrieval_tool.py`。
  - 验收：R4.3 检索四件套不被破坏。
- [ ] 验证 Phase 2。
  - 命令：`conda run -n autoGLM pytest tests/test_agentic_tools.py tests/test_retrieval_tool.py`

## Phase 3 — 配置迁移与工具开关

- [ ] 新增 `agentic_enabled` 配置。
  - 验收：默认值和 `PAGENT_AGENTIC_ENABLED` 覆盖生效。
- [ ] 新增 `agentic_external_tools_enabled` 配置。
  - 验收：默认关闭外部工具。
- [ ] 新增 `agentic_default_tools` 配置。
  - 验收：默认值为 `kb_retrieval`。
- [ ] 新增 `websearch_enabled` 配置。
  - 验收：默认 `False`，可由 `PAGENT_WEBSEARCH_ENABLED` 覆盖。
- [ ] 新增 `legal_status_enabled` 配置。
  - 验收：默认 `False`，可由 `PAGENT_LEGAL_STATUS_ENABLED` 覆盖。
- [ ] 新增 `official_fee_enabled` 配置。
  - 验收：默认 `False`，可由 `PAGENT_OFFICIAL_FEE_ENABLED` 覆盖。
- [ ] 复用 `retrieval_max_steps` / `retrieval_token_budget` / `retrieval_timeout_seconds` 作为主循环预算。
  - 验收：不新增 `qa_*` 预算配置。
- [ ] 删除或迁移 `retrieval_react_min_results`。
  - 验收：按 Phase 0 决策同步默认值、env、public dict、测试。
- [ ] 删除或迁移 `retrieval_react_min_score`。
  - 验收：按 Phase 0 决策同步默认值、env、public dict、测试。
- [ ] 删除或迁移 `retrieval_react_use_llm_judge`。
  - 验收：按 Phase 0 决策同步默认值、env、public dict、测试。
- [ ] 更新 `to_public_dict()`。
  - 验收：非敏感 agentic 配置可见，敏感字段仍不可见。
- [ ] 更新 `tests/test_core_config_logging.py`。
  - 验收：默认值、环境变量、公开配置、敏感字段排除均覆盖。
- [ ] 验证 Phase 3。
  - 命令：`conda run -n autoGLM pytest tests/test_core_config_logging.py`

## Phase 4 — QA 收编到 R7 主循环

- [ ] 修改 `QANode.__init__` 注入或构造 R7 主循环 / tool registry。
  - 验收：测试可注入 fake loop，不触网。
- [ ] 修改 `QANode.run()` 委派 R7 主循环。
  - 验收：不再调用 `_retrieve_loop`。
- [ ] QA 默认工具白名单只包含 `kb_retrieval`。
  - 验收：外部工具未显式启用时不可达。
- [ ] 将 `ReActOutcome.evidence` 写入 `state.dialog_context["qa_retrieval_results"]`。
  - 验收：PatentQASkill 能消费 evidence。
- [ ] 保留 `PatentQASkill` 最终回答链路。
  - 验收：`qa_result` 结构不回归。
- [ ] 保留法规过时提示。
  - 验收：stale law evidence 仍追加核对提示。
- [ ] 保留依据不足提示。
  - 验收：非 `sufficient` 或无 evidence 时追加 `INSUFFICIENT_EVIDENCE_WARNING`。
- [ ] 保留 `qa_completed` trace。
  - 验收：包含 `basis_count`、`has_retrieval`、`evidence_versions` 或等价字段。
- [ ] 删除 `_retrieve`。
  - 验收：生产代码无该 QA 私有检索 helper。
- [ ] 删除 `_retrieve_loop`。
  - 验收：生产代码无 `_retrieve_loop`。
- [ ] 删除 `_accumulate_results` / `_result_key`。
  - 验收：去重逻辑迁移到主循环或工具层。
- [ ] 删除 `_is_evidence_sufficient` / `_top_score` / `_get_result_score`。
  - 验收：充分性判断迁移到主循环策略。
- [ ] 删除 `_estimate_evidence_tokens`。
  - 验收：预算估算迁移到主循环。
- [ ] 删除 `_rewrite_query`。
  - 验收：工具决策 / query 改写不在 QA 私有循环中。
- [ ] 删除 `_build_converged_trace` / `_build_convergence`。
  - 验收：收敛 trace 由主循环输出。
- [ ] 更新 `tests/test_qa_node.py`。
  - 验收：QA 委派、默认 KB、风险提示、法规提示、trace、basis 回链均覆盖。
- [ ] 迁移或删除 `tests/test_qa_react_loop.py`。
  - 验收：有效用例进入 `test_agentic_loop.py` / `test_qa_node.py`。
- [ ] 验证 Phase 4。
  - 命令：`conda run -n autoGLM pytest tests/test_qa_node.py tests/test_agentic_loop.py`

## Phase 5 — 外部工具 stub 与 provenance

- [ ] 新增或预留 `app/tools/websearch.py`。
  - 验收：默认关闭或 stub，不触网。
- [ ] 新增或预留 `app/tools/legal_status.py`。
  - 验收：默认关闭或 stub，不触网。
- [ ] 新增或预留 `app/tools/official_fee.py`。
  - 验收：默认关闭或 stub，不触网。
- [ ] 外部工具启用需同时满足全局外部工具开关和单工具开关。
  - 验收：任一开关关闭都不调用工具。
- [ ] websearch evidence 保留 URL / title / retrieved_at / source_type。
  - 验收：无 URL 或来源时不可进入 `basis`。
- [ ] legal status evidence 保留来源 / 查询时间 / 法律状态 / 核对提示。
  - 验收：不能凭模型生成法律状态。
- [ ] official fee evidence 保留来源 / 查询时间 / 适用范围 / 核对提示。
  - 验收：不能凭模型生成官费。
- [ ] 外部工具失败返回可恢复 observation。
  - 验收：主循环收敛为 `tool_unavailable` 或继续使用已有 evidence。
- [ ] 更新 `tests/test_agentic_tools.py` 外部工具覆盖。
  - 验收：默认关闭、显式启用、provenance、无来源过滤均覆盖。
- [ ] 验证 Phase 5。
  - 命令：`conda run -n autoGLM pytest tests/test_agentic_tools.py`

## Phase 6 — Prompt / LLM router 预留（可选）

- [ ] 决定本轮是否实现 LLM router。
  - 验收：若不实现，本阶段标记为 deferred，不阻塞 R7 默认路径。
- [ ] 如实现，新增 `app/prompts/react_router.py`。
  - 验收：prompt 集中维护，不内联业务逻辑。
- [ ] prompt 覆盖六要素。
  - 验收：任务目标、上下文/判定规则、角色、受众、样例、输出格式齐全。
- [ ] prompt 做指令 / 数据分离。
  - 验收：用户输入、检索结果、websearch 内容均在数据区。
- [ ] prompt 要求仅输出 JSON。
  - 验收：字段、枚举、required、additionalProperties 约束清晰。
- [ ] 代码对白名单做最终裁决。
  - 验收：LLM 输出未注册工具也不会调用。
- [ ] 非法 JSON / 异常回退 deterministic policy。
  - 验收：默认测试不调用真实 LLM。
- [ ] 验证 Phase 6。
  - 命令：`conda run -n autoGLM pytest tests/test_agentic_loop.py`

## Phase 7 — 回归、清理与验收

- [ ] 搜索 `_retrieve_loop` 残留。
  - 验收：生产代码无残留；如测试迁移说明中出现需合理。
- [ ] 搜索 `qa_react_step` / `qa_react_converged` 残留。
  - 验收：旧 trace 断言迁移为 `react_main_*`。
- [ ] 确认 `app/tools/retrieval.py` 未被删除或重写。
  - 验收：检索回归测试通过。
- [ ] 确认默认测试不触网。
  - 验收：外部工具均 fake / stub / disabled。
- [ ] 运行目标测试。
  - 命令：`conda run -n autoGLM pytest tests/test_agentic_loop.py tests/test_qa_node.py tests/test_core_config_logging.py`
- [ ] 运行全量测试。
  - 命令：`conda run -n autoGLM pytest`
- [ ] 运行编译检查。
  - 命令：`conda run -n autoGLM python -m compileall app tests scripts`
- [ ] 更新 `tasks/plan.md` 和 `tasks/todo.md` 状态。
  - 验收：已完成项勾选，延期项保留未勾选并说明原因。
