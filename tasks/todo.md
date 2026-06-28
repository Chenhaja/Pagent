# R6.1 Todo

## Phase 0: 计划文档

- [x] 写入 `tasks/plan.md`
  - 文件范围：`tasks/plan.md`
  - 验收：包含 R6.1 背景、依赖图、垂直任务拆分、检查点、风险约束和验证命令。
  - 验证：人工检查。
  - 阻塞：无。
- [x] 写入 `tasks/todo.md`
  - 文件范围：`tasks/todo.md`
  - 验收：任务清单包含文件范围、验收标准、验证命令和阻塞关系。
  - 验证：人工检查。
  - 阻塞：无。

## Phase 1: 配置与安全默认值

- [x] 增加 `PAGENT_MEMORY_*` 配置
  - 文件范围：`app/core/config.py`、`tests/test_core_config_logging.py`
  - 验收：`Settings` 含 `memory_enabled`、`memory_db_path`、`memory_history_window`、`memory_token_budget`、`memory_summary_model`；默认值与 SPEC 一致；环境变量可覆盖。
  - 验证：`pytest tests/test_core_config_logging.py`
  - 阻塞：Phase 0。
- [x] 更新公开配置输出
  - 文件范围：`app/core/config.py`、`tests/test_core_config_logging.py`
  - 验收：`to_public_dict()` 展示非敏感 memory 配置，不暴露 `llm_api_key` 或密钥值。
  - 验证：`pytest tests/test_core_config_logging.py`
  - 阻塞：增加 memory 配置。
- [x] 忽略 SQLite 会话库文件
  - 文件范围：`.gitignore`
  - 验收：`pagent_memory.db`、`*.sqlite`、`*.sqlite3` 等本地数据库文件不会被 git 跟踪。
  - 验证：人工检查 `.gitignore`。
  - 阻塞：Phase 0。

## Phase 2: SQLite SessionMemoryStore 最小持久化

- [x] 新增 `SessionMemoryStore` 协议和空降级实现
  - 文件范围：`app/memory/session_store.py`、`tests/test_session_store.py`
  - 验收：协议包含 `load_history`、`append_turn`、`load_summary`、`upsert_summary`、`build_context`；空实现用于 memory disabled / DB 不可用降级。
  - 验证：`pytest tests/test_session_store.py`
  - 阻塞：Phase 1。
- [x] 实现 SQLite 自动建表
  - 文件范围：`app/memory/session_store.py`、`tests/test_session_store.py`
  - 验收：初始化 `SqliteSessionStore` 后自动建 `sessions`、`turns`、`summaries` 表；使用参数化 SQL。
  - 验证：`pytest tests/test_session_store.py`
  - 阻塞：SessionMemoryStore 协议。
- [x] 实现 append/load 历史持久化
  - 文件范围：`app/memory/session_store.py`、`tests/test_session_store.py`
  - 验收：`append_turn()` 写入脱敏后的 user / assistant turn；`load_history()` 按 turn_index 升序返回最近 N 条；新 store 实例可读取旧实例数据。
  - 验证：`pytest tests/test_session_store.py`
  - 阻塞：SQLite 自动建表。
- [x] 实现 summary CRUD 和工厂降级
  - 文件范围：`app/memory/session_store.py`、`tests/test_session_store.py`
  - 验收：`load_summary()` / `upsert_summary()` 可读写 summary 与 `covered_turn_index`；`build_session_store(settings)` 在 DB 不可用或 disabled 时安全降级。
  - 验证：`pytest tests/test_session_store.py`
  - 阻塞：append/load 历史持久化。

## Phase 3: 会话上下文组装

- [x] 实现 `build_context()` 窗口历史
  - 文件范围：`app/memory/session_store.py`、`tests/test_session_store.py`
  - 验收：`build_context(session_id)` 返回最近 `memory_history_window` 条 `{role, content}`，格式兼容 query_rewrite。
  - 验证：`pytest tests/test_session_store.py`
  - 阻塞：summary CRUD。
- [x] 实现 summary 头部注入格式
  - 文件范围：`app/memory/session_store.py`、`tests/test_session_store.py`
  - 验收：已有 summary 时，history 头部包含 `{"role": "assistant", "content": "[早期对话摘要] ..."}`；同时返回 `session_summary`。
  - 验证：`pytest tests/test_session_store.py`
  - 阻塞：`build_context()` 窗口历史。
- [x] 锁定 history 长度和兼容性
  - 文件范围：`tests/test_session_store.py`
  - 验收：history 不超过窗口 + 摘要头；无 summary 时不添加合成消息。
  - 验证：`pytest tests/test_session_store.py`
  - 阻塞：summary 头部注入格式。

## Phase 4: 滚动摘要薄片

- [x] 新增 session summary prompt
  - 文件范围：`app/prompts/session_summary.py`
  - 验收：prompt 满足六要素、`<data>` 数据隔离、仅输出 JSON、包含 `summary` / `confidence` / `uncertain` schema、专利域禁止臆造约束。
  - 验证：`pytest tests/test_session_store.py`
  - 阻塞：Phase 3。
- [x] 新增 `SessionSummarizer`
  - 文件范围：`app/memory/summarizer.py`、`tests/test_session_store.py`
  - 验收：可注入 `LLMClient`；默认可使用 `build_llm_client()`；对合法 JSON 输出返回 summary；对异常、空响应、非法 schema 返回失败结果而不抛出阻断主流程。
  - 验证：`pytest tests/test_session_store.py`
  - 阻塞：session summary prompt。
- [x] 实现超窗口 / 超预算摘要触发
  - 文件范围：`app/memory/session_store.py` 或 `app/memory/summarizer.py`、`tests/test_session_store.py`
  - 验收：超过窗口或字符预算时压缩窗口外早期 turn；保存 summary 与 `covered_turn_index`；最近窗口原文仍保留。
  - 验证：`pytest tests/test_session_store.py`
  - 阻塞：`SessionSummarizer`。
- [x] 实现摘要安全降级
  - 文件范围：`app/memory/summarizer.py`、`tests/test_session_store.py`
  - 验收：摘要 LLM 抛错或返回非法 schema 时不抛出；`allow_cloud_sensitive_content=False` 时不发送完整敏感长文本到云模型，可跳过摘要。
  - 验证：`pytest tests/test_session_store.py`
  - 阻塞：摘要触发。

## Phase 5: dispatch 会话闭环

- [ ] 为 dispatch 增加 `session_id` 和 store 注入
  - 文件范围：`app/services/agent_dispatch_service.py`、`tests/test_agent_dispatch_service.py`
  - 验收：`dispatch(raw_input, claims_draft=None, session_id=None)` 可用；服务可注入测试 store；默认通过配置构造 store。
  - 验证：`pytest tests/test_agent_dispatch_service.py`
  - 阻塞：Phase 4。
- [ ] query_rewrite 前注入历史
  - 文件范围：`app/services/agent_dispatch_service.py`、`tests/test_agent_dispatch_service.py`
  - 验收：有 `session_id` 且已有历史时，在 `normalize_input` / `query_rewrite` 前写入 `state.dialog_context["history"]` 和 `state.dialog_context["session_summary"]`；第二轮指代输入走 `query_rewrite_completed`。
  - 验证：`pytest tests/test_agent_dispatch_service.py`
  - 阻塞：dispatch session_id。
- [ ] 无 session 与读取失败降级 trace
  - 文件范围：`app/services/agent_dispatch_service.py`、`tests/test_agent_dispatch_service.py`
  - 验收：无 `session_id` 时行为兼容并 trace `session_memory_skipped(reason=no_session)`；store 读取失败时 trace `session_memory_unavailable` 且主流程继续。
  - 验证：`pytest tests/test_agent_dispatch_service.py`
  - 阻塞：query_rewrite 前注入历史。
- [ ] 请求结束后追加 user / assistant turn
  - 文件范围：`app/services/agent_dispatch_service.py`、`tests/test_agent_dispatch_service.py`
  - 验收：请求完成后追加 `user` raw_input 脱敏副本和可用 assistant 文本；failed / requires_user_input 路径仍尽量写入 user turn；`raw_input` 始终不被覆盖。
  - 验证：`pytest tests/test_agent_dispatch_service.py`
  - 阻塞：降级 trace。
- [ ] dispatch 摘要触发与 trace
  - 文件范围：`app/services/agent_dispatch_service.py`、`tests/test_agent_dispatch_service.py`
  - 验收：响应后触发摘要；成功 trace `memory_summary_completed`；失败 trace `memory_summary_failed_fallback`；trace 不含完整历史正文。
  - 验证：`pytest tests/test_agent_dispatch_service.py`
  - 阻塞：追加 turns。

## Phase 6: API 接入 session_id

- [ ] `AgentRequest` 增加可选 `session_id`
  - 文件范围：`app/api/schemas.py`、`tests/test_agent_api.py`
  - 验收：请求体可带 `session_id`；不带时兼容旧请求体。
  - 验证：`pytest tests/test_agent_api.py`
  - 阻塞：Phase 5。
- [ ] `/agent` 路由透传 `session_id`
  - 文件范围：`app/api/routes.py`、`tests/test_agent_api.py`
  - 验收：路由调用服务层时传递 `session_id=request.session_id`；测试能断言服务层收到该值。
  - 验证：`pytest tests/test_agent_api.py`
  - 阻塞：AgentRequest session_id。

## Phase 7: 回归验收

- [ ] 运行 R6.1 目标测试
  - 文件范围：R6.1 修改涉及的源码与测试。
  - 验收：session store、dispatch、配置、API 目标测试全部通过；默认不触发真实 LLM / 网络。
  - 验证：`pytest tests/test_session_store.py tests/test_agent_dispatch_service.py tests/test_core_config_logging.py tests/test_agent_api.py`
  - 阻塞：Phase 6。
- [ ] 运行全量测试
  - 文件范围：全项目。
  - 验收：全量 pytest 通过。
  - 验证：`pytest`
  - 阻塞：R6.1 目标测试。
- [ ] 运行编译检查
  - 文件范围：`app`、`tests`。
  - 验收：Python 编译检查通过。
  - 验证：`python -m compileall app tests`
  - 阻塞：全量测试。
- [ ] 执行最终验收命令
  - 文件范围：全项目。
  - 验收：`pytest && python -m compileall app tests` 通过；SQLite DB、`.env`、`.env.*` 不被提交；trace 不记录敏感正文。
  - 验证：`pytest && python -m compileall app tests`
  - 阻塞：编译检查。
