# R5 意图识别实质化 + 专利问答 QA 回答闭环执行计划

## Context

R5 要解决两个当前阻塞可用性的占位实现：`IntentRouterNode` 仍是简单关键词匹配，且 `qa` 宽泛关键词会抢占“权利要求有什么问题”这类输入；`PatentQASkill` 默认写死 fake 响应且 prompt 内联，`QANode` 虽已有本地检索与 trace，但 provenance 回链、护栏与真实 LLM 闭环还不完整。

目标是在最小、局部改动前提下，复用现有 `WorkflowState`、`NodeResult`、`SkillContext`、`build_llm_client()`、`FakeLLMClient`、`LocalRetrievalTool` 与 `query_rewrite` prompt 模式，完成 R5 SPEC。

## 依赖图

```text
任务 0 计划文档落地
  ↓
任务 1 安全配置前置检查
  ↓
任务 2 意图识别最小闭环：schema + prompt + keyword fast path + bug 修复
  ↓
任务 3 意图识别 LLM fallback + 低置信追问
  ↓
任务 4 QA skill 闭环：prompt 模块化 + build_llm_client 默认路径
  ↓
任务 5 QA node 闭环：provenance 注入 + 护栏 trace + 依据不足路径
  ↓
任务 6 dispatch 回归 + 最终验收
```

## 关键复用点

- `app/models/schemas.py`：复用 `PatentQAResult`、`SkillContext`、`WorkflowState`、`NodeResult`，新增 `IntentClassification`。
- `app/tools/llm.py`：复用 `LLMMessage`、`LLMClient`、`FakeLLMClient`、`build_llm_client()`。
- `app/prompts/query_rewrite.py`：复用六要素、`<data>` 数据隔离、仅输出 JSON 的 prompt 组织风格。
- `app/tools/retrieval.py`：复用 `LocalRetrievalTool` 和 `RetrievalResult.provenance`。
- `app/services/agent_dispatch_service.py`：保留现有 `normalize_input → query_rewrite → intent_router → workflow/orchestrator` 顺序。

## 可执行任务

### 任务 0：落地计划文件

**修改文件**
- `tasks/plan.md`
- `tasks/todo.md`

**实施内容**
- 将本执行计划写入 `tasks/plan.md`。
- 将任务拆成可勾选清单写入 `tasks/todo.md`，包含文件范围、验收标准、验证命令和阻塞关系。

**验收标准**
- 两个文件存在且内容与 R5 SPEC 对齐。
- `tasks/todo.md` 按垂直切片组织，不只按 schema/prompt/node 横向分层。

**验证**
- 人工检查 `tasks/plan.md`、`tasks/todo.md`。

### 任务 1：安全配置前置检查

**修改文件**
- `app/core/config.py`（仅当存在硬编码式真实 LLM 默认值时）
- 可能更新：`tests/test_core_config_logging.py`、`tests/test_llm_tool.py`

**实施内容**
- 检查并移除源码内看起来像真实密钥、真实 endpoint、真实默认模型的硬编码默认值。
- 保持无有效配置时 `build_llm_client()` 返回 `FakeLLMClient()`，避免默认测试触网。
- 不引入新配置抽象。

**验收标准**
- 默认配置不包含真实 API Key / endpoint / 模型凭据。
- 默认测试不会触发真实 LLM 或网络请求。
- `to_public_dict()` 仍不暴露密钥。

**验证**
```bash
pytest tests/test_core_config_logging.py tests/test_llm_tool.py
```

### 任务 2：意图识别最小闭环与盖词 bug 修复

**修改文件**
- `app/models/schemas.py`
- `app/prompts/intent_router.py`
- `app/nodes/intent_router.py`
- `tests/test_intent_router_node.py`

**实施内容**
- 新增 `IntentClassification`，intent 枚举为 `claim_generation | claim_revision | translation | qa | unknown`，confidence 限制在 `0.0~1.0`。
- 新增 intent router prompt 模块。
- 调整 keyword fast path，使权利要求相关语义优先于 `qa` 宽泛词。
- 关键词命中直接返回，不调用 LLM。
- 写入 `state.intent` 和 `state.dialog_context["intent_classification"]`。
- 增加“我的权利要求有什么问题”回归测试。

**验收标准**
- 关键词命中各 intent 时不调用 LLM。
- “权利要求有什么问题”路由到权利要求相关路径而非 QA。
- trace 包含 `intent_router_completed`，data 至少含 `intent`、`source: keyword`、`confidence`。
- prompt 模块满足六要素、数据隔离、仅输出 JSON。

**验证**
```bash
pytest tests/test_intent_router_node.py
```

### 任务 3：意图识别 LLM fallback 与低置信追问

**修改文件**
- `app/nodes/intent_router.py`
- `tests/test_intent_router_node.py`
- `tests/test_agent_dispatch_service.py`

**实施内容**
- 为 `IntentRouterNode` 增加可注入 `llm_client`，未注入时使用 `build_llm_client()`。
- 快路未命中时调用 LLM，并用 Pydantic 校验输出。
- 默认阈值 `confidence_threshold=0.6`。
- `confidence < threshold` 或 `intent == "unknown"` 时返回 `NodeResult.need_user_input()`，输出澄清问题和支持任务类型。
- LLM 异常、结构化错误、非法 JSON、schema 校验失败时记录 `intent_router_failed_fallback` 并返回 unknown 追问。
- `next_node` 只由代码固定映射。

**验收标准**
- 快路未命中 + stub LLM 高置信时成功路由，并产生 `source: llm` trace。
- 低置信 / unknown 进入澄清，不继续 workflow。
- LLM 异常降级不崩溃。
- `agent_dispatch_service` 能消费澄清结果。

**验证**
```bash
pytest tests/test_intent_router_node.py tests/test_agent_dispatch_service.py
```

### 任务 4：QA skill 真实化与 prompt 模块化

**修改文件**
- `app/prompts/patent_qa.py`
- `app/skills/patent_qa.py`
- `tests/test_patent_qa_skill.py`

**实施内容**
- 新增 `app/prompts/patent_qa.py`，导出 `PATENT_QA_SYSTEM_PROMPT`、`PATENT_QA_OUTPUT_SCHEMA`、`PATENT_QA_FEW_SHOT_EXAMPLES`、`build_patent_qa_user_prompt()`。
- 从 `PatentQASkill` 移除内联长 prompt，改用 prompt 模块。
- `PatentQASkill.__init__` 默认改为 `llm_client or build_llm_client()`。
- 保留现有 `SkillContext`、`LLMMessage`、`PatentQAResult.model_json_schema()` 与 Pydantic 校验流程。
- prompt 明确数据隔离、仅输出 JSON、不得编造来源。

**验收标准**
- 默认构造路径经 `build_llm_client()`。
- 单元测试不触网。
- messages 分层清晰：system / task / user_data。
- prompt 包含 `<data>` 或等价隔离声明。
- 合法 fake 响应可解析为 `PatentQAResult`。
- 非法响应仍由 node 兜底。

**验证**
```bash
pytest tests/test_patent_qa_skill.py
```

### 任务 5：QA node provenance 回链与 bounded 护栏

**修改文件**
- `app/nodes/qa.py`
- `tests/test_qa_node.py`
- 可能更新：`tests/test_patent_qa_skill.py`

**实施内容**
- 在 `QANode` 中将 `RetrievalResult` 转换为带来源的数据块，传给 `PatentQASkill`。
- 继续写入 `state.dialog_context["qa_retrieval_results"]`。
- 无检索命中时确保输出“依据不足”，必要时在 node 侧补充 basis guard。
- 保持 bounded 行为：`max_steps <= 0`、`token_budget <= 0`、`timeout_seconds <= 0` 时不检索；检索异常返回空 evidence 并继续生成结构化答复；限制 top_k 和单条 evidence 长度。
- trace 不记录完整问题或完整检索正文。

**验收标准**
- 检索命中时 `qa_result.basis` 含真实 provenance 来源。
- 无命中时回答诚实说明依据不足，不编造来源。
- 护栏触发时不调用 retrieval tool，且有可断言 trace。
- 检索异常不导致 node failed；skill schema 非法仍返回 `qa_failed`。

**验证**
```bash
pytest tests/test_qa_node.py tests/test_patent_qa_skill.py
```

### 任务 6：dispatch 回归与最终验收

**修改文件**
- `tests/test_agent_dispatch_service.py`
- 必要时小范围调整 `app/services/agent_dispatch_service.py`

**实施内容**
- 补充或更新入口回归：预处理顺序、`raw_input`、`qa` intent workflow、“权利要求有什么问题”路由、unknown / 低置信追问结构。
- 不改 API 响应结构，除非为兼容 `requires_user_input` 必要。

**验收标准**
- R5 相关测试全部通过。
- 全量测试通过。
- 编译检查通过。
- 默认测试不触网。

**验证**
```bash
pytest tests/test_intent_router_node.py tests/test_patent_qa_skill.py tests/test_qa_node.py tests/test_agent_dispatch_service.py
pytest
python -m compileall app tests
```

## 风险与约束

- 默认真实 LLM 调用风险：所有测试必须显式注入 fake/stub；无有效配置时保持 fake。
- Schema 改动风险：不改 `WorkflowState` 顶层结构，分类详情放入 `dialog_context["intent_classification"]`，保持兼容。
- Prompt 输出不稳定：所有 LLM 输出都经 Pydantic 校验；非法输出降级，不冒泡裸异常。
- Evidence 膨胀风险：优先在 `QANode` 做简单 top_k 和长度限制，不新增复杂 token 预算器。
- 来源伪造风险：prompt 禁止编造来源；node 测试锁定 basis 必须含真实 provenance 或说明依据不足。
