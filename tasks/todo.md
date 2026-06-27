# 下一阶段任务清单

## Phase 0：计划确认与基线保护

- [x] T0.1 固化基线测试
  - 验收：明确当前 `pytest` 基线，当前基线为 99 passed。
  - 验证：`pytest`

## Phase 1：P0 LLM 调用闭环最小切片

- [x] T1.1 扩展 LLM 配置与安全默认值
  - 验收：LLM 配置全部来自环境变量 / 默认值；脱敏默认开启；不泄露 API Key。
  - 验证：`pytest tests/test_core_config_logging.py tests/test_security_compliance.py`

- [x] T1.2 实现 LLM Protocol、结构化错误和 Fake 兼容
  - 验收：Fake 与真实 client 调用形态一致；错误结构化；trace 不含敏感内容。
  - 验证：`pytest tests/test_llm_tool.py tests/test_security_compliance.py`

- [x] T1.3 实现 OpenAICompatibleClient 的最小真实调用路径
  - 验收：默认测试不触网；显式开启后可真实调用兼容端点并解析 schema。
  - 验证：`pytest tests/test_llm_tool.py`

## Checkpoint 1

- [x] LLM 抽象、Fake、真实 client、配置、安全默认值全部完成。

## Phase 2：P0 Feature extraction 垂直真实 LLM 切片

- [x] T2.1 扩展 SkillContext 与 Prompt 分层结构
  - 验收：`prompt_layers`、`safety_policy` 可用，旧测试兼容。
  - 验证：`pytest tests/test_skill_context.py`

- [x] T2.2 让 `feature_extraction` skill 构造 prompt 并调用 LLM 抽象
  - 验收：Fake LLM 返回结构化特征时写入 state；错误时结构化失败。
  - 验证：`pytest tests/test_feature_extraction_skill.py tests/test_feature_extract_node.py tests/test_llm_tool.py`

## Checkpoint 2

- [x] 至少一个 skill 完成 prompt + LLM 抽象 + schema 校验闭环。

## Phase 3：P0 编排闭环与统一入口

- [x] T3.1 元数据化 WorkflowRegistry
  - 验收：claim_generation / translation / claim_revision / qa 均可查询；claim_generation 包含 completeness_gate。
  - 验证：`pytest tests/test_workflow_registry.py tests/test_phase3_workflows.py`

- [x] T3.2 Orchestrator 支持 `next_node` 与有界回环
  - 验收：合法跳转可执行；非法跳转和超限回环结构化失败。
  - 验证：`pytest tests/test_orchestrator_engine.py tests/test_node_result.py`

- [ ] T3.3 增加信息完整性 gate
  - 验收：信息缺失时追问；信息充足时进入 feature_extract。
  - 验证：`pytest tests/test_claim_generation_e2e.py tests/test_completeness_gate_node.py`

- [ ] T3.4 统一 AgentDispatchService 到 registry + orchestrator
  - 验收：同一请求只 normalize 一次；显式 API 也通过 known intent workflow。
  - 验证：`pytest tests/test_agent_dispatch_service.py tests/test_known_intent_services.py tests/test_claim_generation_e2e.py tests/test_translate_e2e.py tests/test_revision_e2e.py`

## Checkpoint 3

- [ ] 统一 orchestrator 成为唯一业务编排入口，QA workflow 已注册。

## Phase 4：P0/P1 QA 落点

- [ ] T4.1 增加 patent_qa skill、qa node 与 QA schema
  - 验收：`qa` 意图能跑完整 workflow，输出结构化答案。
  - 验证：`pytest tests/test_patent_qa_skill.py tests/test_qa_node.py tests/test_workflow_registry.py tests/test_agent_dispatch_service.py`

- [ ] T4.2 增加统一 Agent API endpoint
  - 验收：POST `/agent` 支持 QA、权利要求生成、翻译、修改路径。
  - 验证：`pytest tests/test_agent_api.py tests/test_api_error_responses.py`

## Checkpoint 4

- [ ] P0 完成：统一入口 + QA + LLM 抽象 + 编排闭环可端到端验证。

## Phase 5：P1 改写、检索与 bounded ReAct

- [ ] T5.1 normalize_input 支持基于对话历史的意图前改写
  - 验收：结合 dialog_context 生成自包含 normalized_input；不覆盖 raw_input。
  - 验证：`pytest tests/test_normalize_input_node.py tests/test_agent_dispatch_service.py`

- [ ] T5.2 增加 retrieval tool mock / 本地接口
  - 验收：本地检索可预测返回，结果带 provenance。
  - 验证：`pytest tests/test_retrieval_tool.py`

- [ ] T5.3 QA 内 bounded ReAct 最小实现
  - 验收：限定 retrieval 工具、最大步数、token 预算、超时；输出 trace。
  - 验证：`pytest tests/test_qa_node.py tests/test_retrieval_tool.py`

## Checkpoint 5

- [ ] P1 QA + 检索智能增强完成。

## Phase 6：P1 本地记忆与 provenance

- [ ] T6.1 增加 memory 抽象与本地 store
  - 验收：会话、案件、用户画像、经验记忆可本地读写；写入带 provenance。
  - 验证：`pytest tests/test_memory_store.py`

- [ ] T6.2 实现 memory gating
  - 验收：未经校验与用户确认的模型输出不能写入长期记忆。
  - 验证：`pytest tests/test_memory_store.py tests/test_security_compliance.py`

## Checkpoint 6

- [ ] 记忆能力可用且只使用本地 store，不接外部 wiki。

## Phase 7：P2 安全、审计与目录对齐

- [ ] T7.1 LLM trace 持久化接口
  - 验收：trace 可写入抽象 sink，默认不记录敏感内容。
  - 验证：`pytest tests/test_security_compliance.py tests/test_llm_tool.py`

- [ ] T7.2 API routes 目录对齐
  - 验收：现有 endpoints 不变，新增 `/agent` endpoint，路由结构清晰。
  - 验证：`pytest tests/test_health.py tests/test_claim_generation_api.py tests/test_translate_api.py tests/test_revision_api.py tests/test_agent_api.py`

- [ ] T7.3 质量工具评估
  - 验收：如引入 ruff / mypy，配置最小化，不做大规模格式重排。
  - 验证：`ruff check .`、`mypy app`、`pytest`

## Final Checkpoint

- [ ] 全量测试通过：`pytest`
- [ ] 默认测试不触网。
- [ ] 日志 / trace 不含密钥、完整技术交底、完整译文或隐私内容。
- [ ] 生成结果持续包含辅助初稿免责声明。
