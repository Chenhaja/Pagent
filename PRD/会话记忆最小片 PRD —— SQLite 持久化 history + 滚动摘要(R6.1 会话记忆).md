<aside>
 🎯

一句话:用 SQLite 持久化多轮对话历史与滚动摘要,在 `query_rewrite` 之前把历史注入 `state.dialog_context["history"]`,**修好「问题改写遇到上下文没有」**。形态为「会话记忆」这一薄片,不触及四类记忆全量与 Notion Wiki(见 Requirements R6 / D4)。

</aside>

## 1. 背景与问题

现状(已读代码确认):

- `app/nodes/query_rewrite.py` 已经会读取 `state.dialog_context.get("history", [])`:**有历史**才调 LLM 改写为自包含问题;**无历史**直接 `query_rewrite_skipped(reason=no_history)` 放行。
- 但 `app/services/agent_dispatch_service.py::dispatch()` 每次都 `WorkflowState(raw_input=..., claims_draft=...)` **全新构造**,`dialog_context` 恒为空 → 改写**永远走 skip 分支** → 指代(它/上述/这个)与省略无法消解 = 用户说的「上下文没有」。
- `app/memory/store.py` 的 `LocalMemoryStore` 仅为**进程内 list**:无持久化、无跨请求、无摘要;`MemoryType` 虽含 `"session"` 但从未被使用。

结论:本片要补的不是改写算法,而是**会话历史的「持久化 → 注入 → 压缩」闭环**。

## 2. 目标 / 非目标

**目标**

- G1 **SQLite 持久化**:按 `session_id` 存多轮 `{role, content}`,跨请求可读。
- G2 **历史注入**:`dispatch` 在 `query_rewrite` 前把历史写入 `state.dialog_context["history"]`,格式与 `query_rewrite` 期望一致(`list[{role, content}]`)。
- G3 **滚动摘要(压缩)**:历史超过窗口/预算时,用 `llm_cheap_model` 增量摘要早期轮次,窗口原文 + 摘要一并注入。
- G4 **落库时机**:每轮请求结束后写入 `user` 与 `assistant` 两条 turn;`raw_input` 永远保留。
- G5 **可替换抽象**:定义 `SessionMemoryStore` 协议,SQLite 为默认实现,内存/Notion 可作 adapter(对齐 D4)。
- G6 **优雅降级**:DB 不可用 / 摘要失败时退化为「无历史」继续主流程,绝不阻断(沿用 `query_rewrite` 的降级哲学)。

**非目标**

- 不实现 案件 / 用户画像 / 经验 三类长期记忆写入(留待后续)。
- 不做向量化语义召回(本片只按 `session_id` 做顺序历史 + 摘要)。
- 不改 `query_rewrite` 的改写算法本身。
- 不引入 Redis(SQLite 默认;Redis 作为后续 adapter)。

## 3. 范围

- 新增 `app/memory/session_store.py`:`SessionMemoryStore` 协议 + `SqliteSessionStore` 实现 + `build_session_store(settings)` 工厂。
- 新增 `app/memory/summarizer.py`(或并入 session_store):滚动摘要器,调 `build_llm_client(...)` 的便宜档。
- 改 `app/services/agent_dispatch_service.py`:`dispatch` 增加 `session_id` 参数;预处理前 `load → 注入`;响应后 `append turn`,必要时触发摘要。
- 改 `app/core/config.py`:新增 memory 配置项。
- 保留 `LocalMemoryStore` 与其 gating,不破坏其 API。

## 4. 流程位置

```
dispatch(raw_input, session_id)
   ↓ (session_id 存在)
session_store.build_context(session_id) → 注入 state.dialog_context["history"]/["session_summary"]
   ↓
normalize_input → query_rewrite(吃到 history,走 completed) → intent_router → workflow ...
   ↓ (响应后)
session_store.append_turn(user) / append_turn(assistant) → 触发滚动摘要(超阈值时)
```

## 5. 数据模型(SQLite)

| 表          | 字段                                                         | 说明               |
| ----------- | ------------------------------------------------------------ | ------------------ |
| `sessions`  | `session_id TEXT PK`, `created_at`, `updated_at`             | 会话元数据         |
| `turns`     | `id PK`, `session_id`, `turn_index`, `role`, `content`, `created_at` | 逐轮原文(已脱敏)   |
| `summaries` | `session_id TEXT PK`, `summary`, `covered_turn_index`, `updated_at` | 早期轮次的滚动摘要 |

- `role ∈ {user, assistant}`;`turns` 按 `session_id, turn_index` 升序。
- SQLite 文件路径来自配置;加入 `.gitignore`。

## 6. 接口契约

`SessionMemoryStore`(Protocol):

| 方法             | 签名                                                | 说明                                            |
| ---------------- | --------------------------------------------------- | ----------------------------------------------- |
| `load_history`   | `(session_id, max_turns) -> list[dict]`             | 返回最近 N 轮 `{role, content}`                 |
| `append_turn`    | `(session_id, role, content) -> None`               | 追加一条 turn(入库前脱敏)                       |
| `load_summary`   | `(session_id) -> str                                | None`                                           |
| `upsert_summary` | `(session_id, summary, covered_turn_index) -> None` | 写/更新摘要                                     |
| `build_context`  | `(session_id) -> dict`                              | 返回 `{"history": [...], "session_summary": str |

- `history` 元素严格为 `{"role": "user"|"assistant", "content": str}`,与 `build_query_rewrite_user_prompt` 一致。

## 7. 压缩策略(滚动摘要)

- **窗口**:保留最近 `N` 轮原文(`PAGENT_MEMORY_HISTORY_WINDOW`,默认 6 = 3 问 3 答)。
- **触发**:`turns` 超窗口 **或** 估算 token 超 `PAGENT_MEMORY_TOKEN_BUDGET` 时,把窗口外早期轮次交给便宜模型**增量摘要**(prompt 走指令/数据分离,history 包进 `<data>`)。
- **注入(零改造取舍)**:为不改 `query_rewrite` 算法,把摘要作为一条合成项 `{"role": "assistant", "content": "[早期对话摘要] ..."}` 放在 `history` **头部**,使改写节点零改造即可吃到压缩上下文;同时另存 `dialog_context["session_summary"]` 供后续显式使用。
- **失败降级**:摘要失败 → 仅注入窗口原文 + trace `memory_summary_failed_fallback`。

## 8. dispatch 接线

`dispatch(raw_input, claims_draft=None, session_id=None)`:

- `session_id` 为空 → 跳过记忆(行为同今天),trace `session_memory_skipped(reason=no_session)`。
- 有 `session_id` → `ctx = store.build_context(session_id)`;`state.dialog_context["history"] = ctx["history"]`(含摘要头);执行 `normalize → query_rewrite → intent → workflow`。
- 响应后:`append_turn(session_id, "user", raw_input)`;若有最终答复文本 `append_turn(session_id, "assistant", answer)`;按阈值触发摘要。
- **gating 区分**:会话历史**不等于**长期记忆固化,可直接写;但入库前过脱敏(`redaction_enabled`)。这与 `LocalMemoryStore._can_write` 针对 `model_output` 的**长期记忆** gating 是两件事,不要混用。

## 9. 配置(`app/core/config.py`,沿用 `PAGENT_` 前缀)

| 配置                           | 默认                               | 说明                  |
| ------------------------------ | ---------------------------------- | --------------------- |
| `PAGENT_MEMORY_ENABLED`        | `true`                             | 总开关                |
| `PAGENT_MEMORY_DB_PATH`        | `./pagent_memory.db`               | SQLite 路径           |
| `PAGENT_MEMORY_HISTORY_WINDOW` | `6`                                | 窗口轮数              |
| `PAGENT_MEMORY_TOKEN_BUDGET`   | `1500`                             | 触发摘要的 token 预算 |
| `PAGENT_MEMORY_SUMMARY_MODEL`  | 回退 `llm_cheap_model`→`llm_model` | 摘要模型档            |

## 10. 安全与合规

- 入库与入 prompt 前**过脱敏**;`allow_cloud_sensitive_content=False` 时摘要不发送完整敏感原文。
- `trace` 只落事件名 + 计数,不落原文 / 隐私。
- SQLite 文件加入 `.gitignore`。

## 11. 验收标准 / 测试

`tests/test_session_store.py`、`tests/test_agent_dispatch_service.py`:

- [ ]  有 `session_id` 多轮:第二轮 `dialog_context["history"]` 非空,`query_rewrite` 走 `query_rewrite_completed` 而非 `skipped`。
- [ ]  持久化:新建 store 实例仍能 `load` 到上轮 history(跨「请求」)。
- [ ]  压缩:超过窗口 → 早期轮次被摘要,history 受限,`summary` 存在。
- [ ]  降级:DB 路径不可写 → 不抛错,退化无历史,trace `session_memory_unavailable`。
- [ ]  `raw_input` 不变;脱敏生效。
- [ ]  无 `session_id` → 行为与当前一致(回归)。

## 12. 风险与取舍

- **摘要塞进 history 头部**以零改造 `query_rewrite`:已接受;后续可让其 prompt 显式接 `session_summary` 字段。
- **SQLite 并发有限**:原型够用;高并发换 Redis / Postgres adapter。
- **token 估算用字符近似**:够用,后续接 tokenizer。