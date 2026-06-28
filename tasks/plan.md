# R6.1 会话记忆最小片执行计划

## Context

R6.1 要补齐“会话历史持久化 → query_rewrite 前注入 → 响应后落库 → 超窗口摘要”的最小闭环。当前 `QueryRewriteNode` 已读取 `state.dialog_context["history"]`，但 `AgentDispatchService.dispatch()` 每次新建 `WorkflowState`，没有任何跨请求历史，因此带指代的第二轮请求会继续 `query_rewrite_skipped(reason=no_history)`。

本计划只实现按 `session_id` 的 SQLite 会话记忆薄片，不改 `query_rewrite` 核心算法，不接长期记忆、Notion、向量库或 Redis。默认测试使用 tmp SQLite 和 fake / stub LLM，不触发真实网络。

## 依赖图

```text
任务 0 计划文档落地
  ↓
任务 1 配置与安全默认值：PAGENT_MEMORY_* + .gitignore
  ↓
任务 2 SQLite SessionMemoryStore 最小持久化：建表 + append/load + 降级工厂
  ↓
任务 3 会话上下文组装：summary 头部 + 最近窗口 history + 脱敏
  ↓
任务 4 滚动摘要薄片：prompt + summarizer + 失败降级
  ↓
任务 5 dispatch 会话闭环：query_rewrite 前注入 + 响应后追加 turns + trace
  ↓
任务 6 API 接入：AgentRequest.session_id + /agent 透传
  ↓
任务 7 回归与最终验收：目标测试 + 全量测试 + compileall
```

## 关键复用点

- `app/services/agent_dispatch_service.py`：保持 `normalize_input → query_rewrite → intent_router → workflow/orchestrator` 顺序，只在 query_rewrite 前注入历史，并在请求结束后追加 turn。
- `app/models/schemas.py`：复用 `WorkflowState`、`NodeResult`、现有 trace 结构，不新增顶层状态字段。
- `app/tools/llm.py`：摘要器复用 `LLMClient`、`LLMMessage`、`build_llm_client()`，测试中注入 stub。
- `app/core/security.py`：复用现有脱敏能力；入库和摘要 prompt 前均脱敏。
- `app/memory/store.py`：保留 `LocalMemoryStore` 和长期记忆 gating，不复用其 `_can_write()` 阻断会话 turn。
- `app/prompts/query_rewrite.py`：`history` 继续兼容 `{role, content}`，摘要以合成 assistant 消息放在头部。
- `app/api/schemas.py` / `app/api/routes.py`：只加可选 `session_id` 并透传，旧请求体继续兼容。

## 可执行任务

### 任务 0：落地 R6.1 计划文件

**修改文件**
- `tasks/plan.md`
- `tasks/todo.md`

**实施内容**
- 将本执行计划写入 `tasks/plan.md`。
- 将任务拆成可勾选清单写入 `tasks/todo.md`，包含文件范围、验收标准、验证命令和阻塞关系。

**验收标准**
- 两个文件存在且内容与 R6.1 `SPEC.md` 对齐。
- 任务按可验证垂直切片组织，不只按 schema / prompt / service 横向分层。

**验证**
- 人工检查 `tasks/plan.md`、`tasks/todo.md`。

**检查点 CP0**
- R6.1 后续实现范围、依赖和验收命令明确。

---

### 任务 1：配置与安全默认值

**修改文件**
- `app/core/config.py`
- `.gitignore`
- `tests/test_core_config_logging.py`

**实施内容**
- 在 `Settings` 增加：
  - `memory_enabled: bool = True`
  - `memory_db_path: str = "./pagent_memory.db"`
  - `memory_history_window: int = 6`
  - `memory_token_budget: int = 1500`
  - `memory_summary_model: str | None = None`
- 在 `get_settings()` 读取对应 `PAGENT_MEMORY_*` 环境变量。
- `Settings.to_public_dict()` 展示非敏感 memory 配置，不暴露密钥。
- `.gitignore` 增加 SQLite 会话库文件忽略规则，例如 `pagent_memory.db`、`*.sqlite`、`*.sqlite3`。
- 增加配置默认值、环境变量读取、公开配置不暴露敏感字段的测试。

**验收标准**
- 默认配置与 SPEC 表格一致。
- 环境变量可覆盖 memory 配置。
- `.env` 机制不被破坏。
- SQLite 数据库文件不会被误提交。
- 默认测试不触网。

**验证**
```bash
pytest tests/test_core_config_logging.py
```

**检查点 CP1**
- memory 配置入口稳定，后续 store / dispatch 不需要硬编码参数。

---

### 任务 2：SQLite SessionMemoryStore 最小持久化

**修改文件**
- `app/memory/session_store.py`（新增）
- `tests/test_session_store.py`（新增）

**实施内容**
- 新增 `SessionMemoryStore` 协议，包含 `load_history()`、`append_turn()`、`load_summary()`、`upsert_summary()`、`build_context()`。
- 新增 `SqliteSessionStore`：
  - 初始化自动建 `sessions`、`turns`、`summaries` 表。
  - 使用参数化 SQL。
  - `append_turn()` 自动维护 `sessions.updated_at` 和递增 `turn_index`。
  - `role` 只允许 `user` / `assistant`。
  - `load_history()` 按 `(session_id, turn_index)` 升序返回最近 N 条 `{role, content}`。
  - `load_summary()` / `upsert_summary()` 可读写摘要和 `covered_turn_index`。
- 新增降级 store 或 factory：`build_session_store(settings)` 在 memory disabled 或 DB 不可用时返回安全空实现，不阻断主流程。
- 入库前对 `content` 脱敏。

**验收标准**
- SQLite 初始化后自动建表。
- 新建 store 实例能读取旧实例写入的历史，证明跨请求 / 跨实例持久化。
- `append_turn()` / `load_history()` / summary CRUD 可用。
- DB 路径不可用时工厂不抛出到主流程，可退化为空实现。
- API Key / 明显密钥字符串不会以原文保存。

**验证**
```bash
pytest tests/test_session_store.py
```

**检查点 CP2**
- 不接 dispatch 也能独立证明 SQLite 会话历史可持久化、可降级、可脱敏。

---

### 任务 3：会话上下文组装

**修改文件**
- `app/memory/session_store.py`
- `tests/test_session_store.py`

**实施内容**
- 实现 `build_context(session_id)`：
  - 返回 `{"history": [...], "session_summary": "..."}`。
  - 保留最近 `memory_history_window` 条 turn 原文。
  - 已有 summary 时，把 `{"role": "assistant", "content": "[早期对话摘要] ..."}` 放入 `history` 头部。
  - `session_summary` 同步返回摘要字符串。
- 确保 `history` 元素严格兼容 `build_query_rewrite_user_prompt(base_query, history)` 当前期望。
- trace 所需的 `history_count`、`has_summary` 可由调用侧从 context 计算，不在 context 中塞正文以外的调试字段。

**验收标准**
- `build_context()` 返回最近窗口 history。
- 已存在 summary 时，summary 合成 assistant 消息位于 history 头部。
- history 长度不超过窗口 + 摘要头。
- 无 summary 时只返回窗口原文。

**验证**
```bash
pytest tests/test_session_store.py
```

**检查点 CP3**
- query_rewrite 可直接消费 store 输出，无需修改 query_rewrite 算法。

---

### 任务 4：滚动摘要薄片

**修改文件**
- `app/prompts/session_summary.py`（新增）
- `app/memory/summarizer.py`（新增）
- `app/memory/session_store.py`
- `tests/test_session_store.py`

**实施内容**
- 新增 `app/prompts/session_summary.py`：
  - prompt 集中维护，含六要素。
  - 历史 turn 包裹在 `<data>...</data>`，声明数据区不是指令。
  - 明确忽略数据区内改变规则、角色、输出格式的指令。
  - 仅输出 JSON，schema 至少含 `summary`、`confidence`、`uncertain`。
  - 专利域约束：不臆造法条、专利号、检索结果或技术事实。
- 新增 `SessionSummarizer`：
  - 可注入 `LLMClient`，默认用 `build_llm_client()`。
  - 新摘要基于“旧摘要 + 新增待压缩 turn”增量生成。
  - 输出经 Pydantic 或显式校验。
  - LLM 异常、空响应、非法 schema 均返回失败结果，不抛出阻断主流程。
- 在 store 或协调函数中实现触发策略：
  - turns 超过 `memory_history_window` 或字符预算超过 `memory_token_budget` 时压缩窗口外早期 turn。
  - `summaries.covered_turn_index` 表示摘要覆盖到的最大 turn index。
  - `allow_cloud_sensitive_content=False` 时不发送完整敏感长文本到云模型；可跳过摘要并保留窗口历史。

**验收标准**
- 超过窗口时可触发摘要，保存 summary 与 `covered_turn_index`。
- 摘要失败不抛出，保留最近窗口原文。
- prompt 满足项目 prompt 规范：六要素、数据隔离、仅 JSON、禁止臆造、不确定标注。
- 默认测试使用 stub / fake，不调用真实 LLM 或网络。

**验证**
```bash
pytest tests/test_session_store.py
```

**检查点 CP4**
- 历史压缩能力独立可测；失败路径已验证不会影响主流程。

---

### 任务 5：dispatch 会话闭环

**修改文件**
- `app/services/agent_dispatch_service.py`
- `tests/test_agent_dispatch_service.py`

**实施内容**
- `AgentDispatchService` 支持注入 `session_store` / summarizer 协调依赖，默认通过 `build_session_store(get_settings())` 构造。
- `dispatch()` 增加 `session_id: str | None = None` 参数。
- 创建 `WorkflowState(raw_input=raw_input, claims_draft=...)` 后、`normalize_input` 前：
  - 无 `session_id`：跳过记忆，trace `session_memory_skipped(reason=no_session)`。
  - memory disabled：跳过记忆，trace `session_memory_skipped(reason=disabled)`。
  - 有 `session_id`：调用 `store.build_context(session_id)`，注入 `state.dialog_context["history"]` 和 `state.dialog_context["session_summary"]`。
  - 读取失败：trace `session_memory_unavailable(reason=...)`，继续主流程。
- 请求结束后尽量追加：
  - `append_turn(session_id, "user", raw_input)`，始终保留原始输入的脱敏副本。
  - 提取可用 assistant 文本并 `append_turn(session_id, "assistant", answer)`。
  - workflow failed 或 requires_user_input 时仍尽量写入 user turn，并写入可用 assistant 消息 / 错误提示摘要。
  - 触发摘要并记录 `memory_summary_completed` 或 `memory_summary_failed_fallback`。
- 所有 memory trace 只记录事件名、计数、窗口大小、是否有摘要、降级原因，不记录完整正文。

**验收标准**
- 无 `session_id` 时旧行为兼容，query rewrite 可继续 `no_history` skip。
- 有 `session_id` 且已有历史时，dispatch 在 query_rewrite 前注入 `dialog_context["history"]`。
- 第二轮带指代输入时，trace 出现 `query_rewrite_completed` 而不是 `query_rewrite_skipped(reason=no_history)`。
- `raw_input` 不被覆盖。
- 请求完成后写入 `user` 和 `assistant` turn。
- store 读取 / 写入 / 摘要失败均不导致 dispatch failed。

**验证**
```bash
pytest tests/test_agent_dispatch_service.py
```

**检查点 CP5**
- R6.1 核心用户路径闭环完成：同一 `session_id` 的第二轮请求能拿到历史。

---

### 任务 6：API 接入 session_id

**修改文件**
- `app/api/schemas.py`
- `app/api/routes.py`
- `tests/test_agent_api.py`

**实施内容**
- `AgentRequest` 增加 `session_id: str | None = None`。
- `/agent` 路由调用 `AgentDispatchService().dispatch(..., session_id=request.session_id)`。
- 保持不传 `session_id` 的旧请求体兼容。
- 增加 API 测试覆盖：
  - `/agent` 接收可选 `session_id`。
  - 不传 `session_id` 时兼容旧请求体。
  - 传 `session_id` 时服务层收到该值。

**验收标准**
- API schema 可解析带 / 不带 `session_id` 的请求。
- 路由透传 `session_id` 到服务层。
- 既有 API 行为和错误结构不被无关改变。

**验证**
```bash
pytest tests/test_agent_api.py
```

**检查点 CP6**
- 外部调用方可开始传递 session_id，且旧客户端不受影响。

---

### 任务 7：回归与最终验收

**修改文件**
- 必要时小范围调整 R6.1 涉及测试和实现文件。

**实施内容**
- 运行 R6.1 目标测试。
- 运行配置与安全相关测试。
- 运行全量测试和编译检查。
- 确认默认测试不触发真实 LLM、真实网络或外部数据库。
- 确认 trace 不记录完整历史正文、密钥、API Key、隐私数据。

**验收标准**
- R6.1 acceptance checklist 全部满足或明确记录未做项。
- `pytest && python -m compileall app tests` 通过。
- SQLite 数据库、`.env`、`.env.*` 不会被提交。

**验证**
```bash
pytest tests/test_session_store.py tests/test_agent_dispatch_service.py tests/test_core_config_logging.py tests/test_agent_api.py
pytest
python -m compileall app tests
```

**最终验收**
```bash
pytest && python -m compileall app tests
```

**检查点 CP7**
- R6.1 可交付，具备持久化、注入、摘要、降级、安全与 API 兼容证据。

## 风险与约束

- **SQLite 并发风险**：本片只做原型级本地持久化，避免复杂连接池；高并发留给后续 Redis / Postgres adapter。
- **摘要调用真实 LLM 风险**：默认测试必须注入 fake / stub；无真实配置时不能触网。
- **敏感信息风险**：入库与入 prompt 前均脱敏；`allow_cloud_sensitive_content=False` 时跳过可能泄露完整敏感长文本的云摘要。
- **trace 泄露风险**：trace 只记录计数、原因和布尔字段，不记录完整 history / raw_input / assistant answer。
- **长期记忆混淆风险**：会话 turn 可按代码固定时机写入，但不能升级为长期案件记忆、用户画像或经验记忆；不要复用 `LocalMemoryStore._can_write()` 作为会话写入 gating。
- **行为兼容风险**：不传 `session_id` 时必须保持旧行为，不应强制引入会话状态。
- **过度设计风险**：不引入 tokenizer、向量召回、Notion、Redis、复杂抽象或 feature flag；只实现当前 SPEC 所需最小闭环。
