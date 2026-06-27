# 下一阶段可执行计划

## 1. 目标

基于 `SPEC.md`，将下一阶段拆成按价值闭环交付的垂直切片。每个任务都应包含必要的 schema / tool / skill / node / workflow / API 或服务入口 / 测试，避免只做横向底座而不可验证。

总目标：

- P0：OpenAI 兼容 LLM 抽象可用；统一入口真正经 workflow registry + orchestrator；权利要求生成具备信息完整性 gate 与校验回环；QA 不再断头。
- P1：Prompt 分层、双层改写、mock 检索 + bounded ReAct、本地长期记忆抽象逐步落地。
- P2：安全、审计、目录对齐和质量工具按风险补齐。

## 2. 当前代码现状

- `app/tools/llm.py`：只有 `FakeLLMClient` 和简单 `LLMResponse`，尚无真实 OpenAI 兼容 client、结构化错误、重试和 trace。
- `app/orchestrator/engine.py`：按 list 顺序执行 node，不支持 `next_node`、回环上限或 workflow 元数据。
- `app/orchestrator/workflow_defs.py`：已有 claim_generation / translation / claim_revision，缺少 QA，workflow_def 仍是简单 list。
- `app/services/agent_dispatch_service.py`：执行 normalize + intent_router 后再分派到各业务 service，尚未统一交给同一个 orchestrator。
- `app/nodes/intent_router.py`：能识别 qa，但 next_node 指向不存在的 `report_write`，registry 也没有 qa workflow。
- `app/skills/*`：大多仍是 fake / 固定输出，未构造分层 prompt。
- `app/main.py`：已有显式 claims / translate API，尚缺统一 Agent 入口 API。
- `app/models/schemas.py`：已有核心 claim / state / node result，但缺少 LLM 错误、trace、QA、检索、记忆相关 schema。

## 3. 依赖图

```text
配置与安全基础
  → LLM Protocol + 结构化错误 + trace
    → Prompt 分层与 Skill 实质化
      → Feature extraction 真实 LLM 切片
      → Claim writing 真实 LLM 切片

WorkflowState / NodeResult 扩展
  → WorkflowRegistry 元数据化
    → Orchestrator next_node + bounded loop
      → completeness_gate
      → claim_check 回环
      → 统一 Agent dispatch
      → QA workflow

Retrieval mock 接口
  → QA node 基础回答
    → bounded ReAct

Memory 抽象 + gating
  → provenance / source_trace 回链
    → claim / QA / retrieval trace 增强

API 目录对齐
  → 统一 Agent endpoint
  → 显式 API 复用 known intent workflow
```

## 4. 执行阶段

### Phase 0：计划确认与基线保护

#### T0.1 固化基线测试

目标：确认当前测试可作为后续重构护栏。

验收标准：

- 明确当前测试基线。
- 如存在已有失败项，记录失败原因，不混入后续功能任务。

验证：

```bash
pytest
```

检查点：基线清楚后再进入实现。

---

### Phase 1：P0 LLM 调用闭环最小切片

#### T1.1 扩展 LLM 配置与安全默认值

涉及文件：

- `app/core/config.py`
- `app/core/security.py`
- `tests/test_core_config_logging.py`
- `tests/test_security_compliance.py`

验收标准：

- 从环境变量读取 `base_url`、`model`、`api_key`、`temperature`、`max_tokens`、`timeout`、`retry_count`、`retry_backoff`。
- 预留 cheap/strong 两档配置字段，但默认单模型可运行。
- 脱敏开关默认开启；默认不允许发送完整敏感材料。
- 不在日志、trace、异常、repr 中暴露 API Key。

验证：

```bash
pytest tests/test_core_config_logging.py tests/test_security_compliance.py
```

#### T1.2 实现 LLM Protocol、结构化错误和 Fake 兼容

涉及文件：

- `app/tools/llm.py`
- `app/models/schemas.py`
- `tests/test_llm_tool.py`

验收标准：

- 定义 LLM client Protocol，支持 `messages`、`output_schema`、模型参数、trace 上下文。
- `FakeLLMClient` 实现同一协议，可模拟成功、空响应、拒答、解析失败、限流、超时。
- 统一返回结构包含 `parsed` / `raw_text` / `errors` / `trace`。
- 不向上抛裸异常，错误映射为结构化 error code。

验证：

```bash
pytest tests/test_llm_tool.py tests/test_security_compliance.py
```

#### T1.3 实现 OpenAICompatibleClient 最小真实调用路径

涉及文件：

- `app/tools/llm.py`
- `requirements.txt`
- `tests/test_llm_tool.py`

验收标准：

- 支持 `base_url`、`model`、`api_key`、`temperature`、`max_tokens`、`timeout`。
- 优先传 `response_format`，provider 不支持时降级严格 JSON prompt + 本地校验。
- 支持超时、限流、provider error 的结构化错误。
- 真实调用测试默认跳过，必须通过环境变量显式开启。

验证：

```bash
pytest tests/test_llm_tool.py
```

手动验证（仅用户允许真实调用时）：

```bash
PAGENT_LLM_REAL_TEST=1 pytest tests/test_llm_tool.py -k real
```

**Checkpoint 1**：LLM 抽象、Fake、真实 client、配置、安全默认值全部完成。

---

### Phase 2：P0 Feature extraction 垂直真实 LLM 切片

#### T2.1 扩展 SkillContext 与 Prompt 分层结构

涉及文件：

- `app/models/schemas.py`
- `tests/test_skill_context.py`

验收标准：

- `SkillContext` 增加 `prompt_layers`、`safety_policy`。
- 保持已有字段兼容。
- `to_payload()` 输出包含新字段。

验证：

```bash
pytest tests/test_skill_context.py
```

#### T2.2 让 `feature_extraction` skill 构造 prompt 并调用 LLM 抽象

涉及文件：

- `app/skills/feature_extraction.py`
- `app/nodes/feature_extract.py`
- `tests/test_feature_extraction_skill.py`
- `tests/test_feature_extract_node.py`

验收标准：

- skill 默认注入 Fake LLM，生产可注入 OpenAICompatibleClient。
- 构造 system / task / data / output contract 分层 prompt。
- 用户材料作为数据块传入，不覆盖系统指令。
- 使用 `FeatureExtractionResult` 作为输出 schema。
- LLM 错误转为 node 的结构化失败或追问。

验证：

```bash
pytest tests/test_feature_extraction_skill.py tests/test_feature_extract_node.py tests/test_llm_tool.py
```

**Checkpoint 2**：至少一个 skill 已从固定 fake 输出升级为 prompt + LLM 抽象 + schema 校验。

---

### Phase 3：P0 编排闭环与统一入口

#### T3.1 元数据化 WorkflowRegistry

涉及文件：

- `app/orchestrator/workflow_defs.py`
- `tests/test_workflow_registry.py`

验收标准：

- workflow_def 支持节点顺序、回环上限、已知 intent、起始节点等元数据。
- claim_generation / translation / claim_revision / qa 都可查询。
- claim_generation 插入 `completeness_gate`。
- 未知 intent 返回空或结构化错误。

验证：

```bash
pytest tests/test_workflow_registry.py tests/test_phase3_workflows.py
```

#### T3.2 Orchestrator 支持 `next_node` 与有界回环

涉及文件：

- `app/orchestrator/engine.py`
- `app/models/schemas.py`
- `tests/test_orchestrator_engine.py`
- `tests/test_node_result.py`

验收标准：

- 主路径仍按 workflow_def 确定性顺序执行。
- `NodeResult.next_node` 可跳转到 workflow 内合法节点。
- 支持最大回环次数。
- 非法 next_node 返回结构化错误。
- `requires_user_input` 时暂停并返回。

验证：

```bash
pytest tests/test_orchestrator_engine.py tests/test_node_result.py
```

#### T3.3 增加信息完整性 gate

涉及文件：

- `app/nodes/completeness_gate.py`
- `app/orchestrator/workflow_defs.py`
- `tests/test_completeness_gate_node.py`
- `tests/test_claim_generation_e2e.py`

验收标准：

- 明显缺少技术方案、结构、效果、差异点时返回 `requires_user_input`。
- 追问面向普通发明人。
- 信息足够时进入 `feature_extract`。

验证：

```bash
pytest tests/test_claim_generation_e2e.py tests/test_completeness_gate_node.py
```

#### T3.4 统一 AgentDispatchService 到 registry + orchestrator

涉及文件：

- `app/services/agent_dispatch_service.py`
- `app/services/workflow_service.py`
- `app/services/translate_service.py`
- `app/services/revision_service.py`
- `tests/test_agent_dispatch_service.py`
- `tests/test_known_intent_services.py`

验收标准：

- dispatch 只做 normalize、intent_router、workflow selection、orchestrator.run。
- 同一请求只 normalize 一次。
- 显式业务 API 使用 known intent 选择 workflow，不绕开 orchestrator。
- 保持现有 API 响应兼容。

验证：

```bash
pytest tests/test_agent_dispatch_service.py tests/test_known_intent_services.py tests/test_claim_generation_e2e.py tests/test_translate_e2e.py tests/test_revision_e2e.py
```

**Checkpoint 3**：统一 orchestrator 成为唯一业务编排入口，QA workflow 已注册。

---

### Phase 4：P0/P1 QA 落点

#### T4.1 增加 patent_qa skill、qa node 与 QA schema

涉及文件：

- `app/skills/patent_qa.py`
- `app/nodes/qa.py`
- `app/models/schemas.py`
- `app/orchestrator/workflow_defs.py`
- `tests/test_patent_qa_skill.py`
- `tests/test_qa_node.py`

验收标准：

- QA 输出包含 answer、basis、risk_notes、next_steps、disclaimer_hint。
- 初版可用 Fake LLM + prompt + schema 校验。
- intent_router 中 qa next_node 指向 `qa`。
- `qa` intent 能跑完整 workflow。

验证：

```bash
pytest tests/test_patent_qa_skill.py tests/test_qa_node.py tests/test_workflow_registry.py tests/test_agent_dispatch_service.py
```

#### T4.2 增加统一 Agent API endpoint

涉及文件：

- `app/main.py` 或 `app/api/routes/agent.py`
- `tests/test_agent_api.py`

验收标准：

- POST `/agent` 接收 `raw_input`、可选 `dialog_context`、可选 `claims_draft`。
- 调用 `AgentDispatchService.dispatch()`。
- 响应包含 intent、workflow、status、result、trace、disclaimer。
- QA、权利要求生成、翻译、修改至少各有一个 API case。

验证：

```bash
pytest tests/test_agent_api.py tests/test_api_error_responses.py
```

**Checkpoint 4**：P0 完成。统一入口 + QA + LLM 抽象 + 编排闭环可端到端验证。

---

### Phase 5：P1 改写、检索与 bounded ReAct

#### T5.1 normalize_input 支持基于对话历史的意图前改写

涉及文件：

- `app/nodes/normalize_input.py`
- `tests/test_normalize_input_node.py`

验收标准：

- 使用 `dialog_context` 补全指代和省略。
- 不臆测、不新增技术内容。
- 无历史时退化为轻量规范化。
- `raw_input` 始终保留。

验证：

```bash
pytest tests/test_normalize_input_node.py tests/test_agent_dispatch_service.py
```

#### T5.2 增加 retrieval tool mock / 本地接口

涉及文件：

- `app/tools/retrieval.py`
- `tests/test_retrieval_tool.py`

验收标准：

- 定义 query、top_k、filters、results、provenance schema。
- 默认 mock / 本地数据，不接真实源。
- trace 记录 query 摘要、结果数量、耗时，不记录过长原文。

验证：

```bash
pytest tests/test_retrieval_tool.py
```

#### T5.3 QA 内 bounded ReAct 最小实现

涉及文件：

- `app/nodes/qa.py`
- `app/tools/retrieval.py`
- `app/skills/patent_qa.py`
- `tests/test_qa_node.py`

验收标准：

- 限定工具集为 retrieval。
- 设置最大步数、token 预算、超时。
- 输出结构化 answer + basis + provenance。
- 失败时降级为无检索回答或结构化错误。
- trace 可看到每步检索与决策摘要。

验证：

```bash
pytest tests/test_qa_node.py tests/test_retrieval_tool.py
```

**Checkpoint 5**：P1 QA + 检索智能增强完成。

---

### Phase 6：P1 本地记忆与 provenance

#### T6.1 增加 memory 抽象与本地 store

涉及文件：

- `app/memory/session.py`
- `app/memory/case_store.py`
- `app/memory/user_profile.py`
- `app/memory/wiki.py`
- `tests/test_memory_store.py`

验收标准：

- 可读写会话、案件、用户画像、经验记忆。
- 默认本地内存或文件 store。
- 写入必须带 provenance。
- 不接外部 wiki。

验证：

```bash
pytest tests/test_memory_store.py
```

#### T6.2 实现 memory gating

涉及文件：

- `app/memory/*`
- `app/models/schemas.py`
- `tests/test_memory_store.py`
- `tests/test_security_compliance.py`

验收标准：

- 写入长期记忆必须包含 `validated=True` 与 `user_confirmed=True`。
- 未确认输出只允许进入会话临时记忆或拒绝写入。
- Claim `source_trace` 与检索 provenance 可回链。

验证：

```bash
pytest tests/test_memory_store.py tests/test_security_compliance.py
```

**Checkpoint 6**：记忆能力可用且只使用本地 store，不接外部 wiki。

---

### Phase 7：P2 安全、审计与目录对齐

#### T7.1 LLM trace 持久化接口

涉及文件：

- `app/core/logging.py`
- `app/tools/llm.py`
- `app/models/schemas.py`
- `tests/test_security_compliance.py`

验收标准：

- trace 可写入抽象 sink。
- 默认 sink 可为内存 / 文件。
- 不记录密钥、完整技术交底、完整译文或隐私内容。

验证：

```bash
pytest tests/test_security_compliance.py tests/test_llm_tool.py
```

#### T7.2 API routes 目录对齐

涉及文件：

- `app/main.py`
- `app/api/routes/*.py`
- API 测试

验收标准：

- 现有 endpoints 不变。
- 新 `/agent` endpoint 存在。
- 路由结构清晰。

验证：

```bash
pytest tests/test_health.py tests/test_claim_generation_api.py tests/test_translate_api.py tests/test_revision_api.py tests/test_agent_api.py
```

#### T7.3 质量工具评估

验收标准：

- 如引入 ruff / mypy，配置最小化，不做大规模格式重排。
- 不为质量工具引入与当前任务无关的大范围改动。

验证：

```bash
ruff check .
mypy app
pytest
```

**Checkpoint 7**：P2 完成，进入发布前综合验证。

## 5. 综合验收

P0 完成标准：

```bash
pytest tests/test_llm_tool.py tests/test_security_compliance.py tests/test_orchestrator_engine.py tests/test_workflow_registry.py tests/test_agent_dispatch_service.py tests/test_claim_generation_e2e.py tests/test_translate_e2e.py tests/test_revision_e2e.py tests/test_qa_node.py tests/test_agent_api.py
```

P1 完成标准：

```bash
pytest tests/test_normalize_input_node.py tests/test_retrieval_tool.py tests/test_qa_node.py tests/test_memory_store.py
```

最终完成标准：

```bash
pytest
```

## 6. 风险与控制

| 风险 | 控制 |
| --- | --- |
| 默认测试误触真实 LLM | 真实调用必须环境变量显式开启 |
| 回环变成无限循环 | workflow 元数据中设置最大回环次数 |
| dispatch 继续双轨 | 统一入口和显式 API 都必须经 registry + orchestrator |
| skill 一次性大改导致失控 | 先做 `feature_extraction` 一个垂直切片 |
| QA ReAct 失控 | 限定工具集、步数、token、超时 |
| 记忆误写长期 store | memory gating 强制 validated + user_confirmed |
| 敏感材料泄露 | 脱敏默认开启，完整材料外发需显式允许 |
