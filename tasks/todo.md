# R5 Todo

## Phase 0: 计划文档

- [x] 写入 `tasks/plan.md`
  - 文件范围：`tasks/plan.md`
  - 验收：包含 R5 背景、依赖图、任务拆分、风险约束和验证命令。
  - 验证：人工检查。
  - 阻塞：无。
- [x] 写入 `tasks/todo.md`
  - 文件范围：`tasks/todo.md`
  - 验收：按垂直切片组织任务，包含文件范围、验收标准、验证命令和阻塞关系。
  - 验证：人工检查。
  - 阻塞：无。

## Phase 1: 安全前置

- [x] 核查 LLM 默认配置安全性
  - 文件范围：`app/core/config.py`、`app/tools/llm.py`、`tests/test_core_config_logging.py`、`tests/test_llm_tool.py`
  - 验收：默认配置不包含真实 API Key / endpoint / 模型凭据；无有效配置时 `build_llm_client()` 返回 `FakeLLMClient`；`to_public_dict()` 不暴露密钥。
  - 验证：`pytest tests/test_core_config_logging.py tests/test_llm_tool.py`
  - 阻塞：Phase 0。

## Phase 2: 意图识别最小闭环

- [x] 新增 `IntentClassification`
  - 文件范围：`app/models/schemas.py`
  - 验收：intent 枚举为 `claim_generation | claim_revision | translation | qa | unknown`，confidence 限制在 `0.0~1.0`。
  - 验证：`pytest tests/test_intent_router_node.py`
  - 阻塞：Phase 1。
- [x] 新增 intent_router prompt
  - 文件范围：`app/prompts/intent_router.py`
  - 验收：导出 system prompt、output schema、user prompt builder；满足六要素、数据隔离、仅输出 JSON。
  - 验证：`pytest tests/test_intent_router_node.py`
  - 阻塞：Phase 1。
- [x] 修复关键词优先级 bug
  - 文件范围：`app/nodes/intent_router.py`
  - 验收：权利要求相关语义优先于 `qa` 宽泛词；关键词命中不调用 LLM；trace 含 `intent`、`source: keyword`、`confidence`。
  - 验证：`pytest tests/test_intent_router_node.py`
  - 阻塞：新增 schema 与 prompt。
- [x] 补关键词快路测试
  - 文件范围：`tests/test_intent_router_node.py`
  - 验收：“我的权利要求有什么问题”不路由到 QA；各关键词命中不调用 LLM。
  - 验证：`pytest tests/test_intent_router_node.py`
  - 阻塞：关键词逻辑修改。

## Phase 3: 意图识别 LLM fallback

- [x] 增加 llm_client 注入与 build_llm_client 默认路径
  - 文件范围：`app/nodes/intent_router.py`
  - 验收：未注入时使用 `build_llm_client()`；关键词快路仍不会调用 LLM。
  - 验证：`pytest tests/test_intent_router_node.py`
  - 阻塞：Phase 2。
- [x] 增加低置信追问
  - 文件范围：`app/nodes/intent_router.py`、`tests/test_intent_router_node.py`
  - 验收：`confidence < 0.6` 或 `unknown` 返回 `NodeResult.need_user_input()`，包含普通发明人可理解的澄清问题和支持任务类型。
  - 验证：`pytest tests/test_intent_router_node.py`
  - 阻塞：LLM fallback。
- [x] 增加异常降级 trace
  - 文件范围：`app/nodes/intent_router.py`、`tests/test_intent_router_node.py`、`tests/test_agent_dispatch_service.py`
  - 验收：LLM 异常、非法 JSON、schema 校验失败记录 `intent_router_failed_fallback` 并降级追问；dispatch 能消费澄清结果。
  - 验证：`pytest tests/test_intent_router_node.py tests/test_agent_dispatch_service.py`
  - 阻塞：低置信追问。

## Phase 4: QA skill

- [x] 新增 patent_qa prompt
  - 文件范围：`app/prompts/patent_qa.py`
  - 验收：导出 system prompt、output schema、few-shot、user prompt builder；外部数据隔离；仅输出 JSON；禁止编造来源。
  - 验证：`pytest tests/test_patent_qa_skill.py`
  - 阻塞：Phase 3。
- [x] PatentQASkill 默认使用 build_llm_client
  - 文件范围：`app/skills/patent_qa.py`
  - 验收：默认构造经 `build_llm_client()`；保留 `PatentQAResult` schema 校验；测试显式 fake/stub 不触网。
  - 验证：`pytest tests/test_patent_qa_skill.py`
  - 阻塞：新增 prompt。
- [x] 更新 skill 测试
  - 文件范围：`tests/test_patent_qa_skill.py`
  - 验收：messages 分层清晰，合法 fake 可解析，非法响应仍按既有策略抛错。
  - 验证：`pytest tests/test_patent_qa_skill.py`
  - 阻塞：skill 修改。

## Phase 5: QA node

- [x] 注入 provenance evidence
  - 文件范围：`app/nodes/qa.py`、`tests/test_qa_node.py`
  - 验收：检索结果传给 skill 时包含 `content`、`provenance.source`、`provenance.document_id` 或已有 id、`score`；`qa_result.basis` 含真实 provenance 来源。
  - 验证：`pytest tests/test_qa_node.py tests/test_patent_qa_skill.py`
  - 阻塞：Phase 4。
- [x] 增加无依据路径
  - 文件范围：`app/nodes/qa.py`、`tests/test_qa_node.py`
  - 验收：无检索命中时回答说明依据不足，不编造来源。
  - 验证：`pytest tests/test_qa_node.py`
  - 阻塞：provenance evidence。
- [x] 增加护栏与 trace 测试
  - 文件范围：`app/nodes/qa.py`、`tests/test_qa_node.py`
  - 验收：bounded 参数无效时不调用 retrieval tool；检索异常不导致 node failed；trace 含 `steps_used`、`result_count`、`token_budget`、`timeout_seconds`、`basis_count`、`has_retrieval`，且不记录完整正文。
  - 验证：`pytest tests/test_qa_node.py tests/test_patent_qa_skill.py`
  - 阻塞：无依据路径。

## Phase 6: 回归验收

- [ ] 更新 dispatch 回归
  - 文件范围：`tests/test_agent_dispatch_service.py`、必要时 `app/services/agent_dispatch_service.py`
  - 验收：预处理顺序仍为 `normalize_input → query_rewrite → intent_router`；`raw_input` 不被覆盖；`qa` intent 进入 QA workflow；“权利要求有什么问题”不进入 QA；unknown / 低置信返回前端可消费追问结构。
  - 验证：`pytest tests/test_agent_dispatch_service.py`
  - 阻塞：Phase 5。
- [ ] 运行 R5 目标测试
  - 文件范围：R5 修改涉及的源码与测试。
  - 验收：目标测试全部通过，默认测试不触网。
  - 验证：`pytest tests/test_intent_router_node.py tests/test_patent_qa_skill.py tests/test_qa_node.py tests/test_agent_dispatch_service.py`
  - 阻塞：dispatch 回归。
- [ ] 运行最终验收
  - 文件范围：全项目。
  - 验收：全量测试和编译检查通过。
  - 验证：`pytest && python -m compileall app tests`
  - 阻塞：R5 目标测试。
