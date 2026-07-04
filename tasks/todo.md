# Pagent R12 专利文书生成缺口修复 Todo

## Phase 0 — 需求命名与基础配置对齐

- [ ] 确认并固定命名：`todo_prompt` / `todo`。
  - 验收：计划、任务、后续测试和实现均不新增 `todo_middleware` / `write_todos` 命名。
  - 验证：代码 review 或内容搜索。
- [ ] 更新 `app/core/config.py` 中 workspace、技能目录与 SerpAPI 配置。
  - 验收：`draft_workspace_dir` 默认空字符串；`skill_dir` 默认 `app/skills_docs`；`patent_search_top_k` 默认 10；SerpAPI Key 从 `SERPAPI_API_KEY` / `PAGENT_SERPAPI_API_KEY` 或配置读取且标记为敏感。
  - 验证：`conda run -n autoGLM pytest tests/test_core_config_logging.py`
- [ ] 更新 `to_public_dict()`。
  - 验收：非敏感 R12 配置进入公开配置；敏感项不暴露。
  - 验证：配置测试。
- [ ] 运行 P0 验证命令。
  - 验收：配置测试与编译通过。
  - 验证：`conda run -n autoGLM pytest tests/test_core_config_logging.py && conda run -n autoGLM python -m compileall app tests`

## Phase 1 — `draft_workspace` 项目工作区

- [ ] 新增或改写 `tests/test_draft_workspace.py`。
  - 验收：覆盖内存模式、磁盘模式、目录结构、`write` / `read` / `list` / `merge`、路径安全。
  - 验证：`conda run -n autoGLM pytest tests/test_draft_workspace.py`
- [ ] 将 `DraftWorkspaceTool` 默认存储改为内存 key-store。
  - 验收：`draft_workspace_dir=""` 时不创建磁盘目录或文件。
  - 验证：workspace 测试。
- [ ] 支持磁盘落盘模式。
  - 验收：`PAGENT_DRAFT_WORKSPACE_DIR` 非空时 artifact 落在 workspace 根目录内。
  - 验证：workspace 测试。
- [ ] 支持项目工作区目录结构。
  - 验收：逻辑目录包含 `01_input`、`02_research`、`03_outline`、`04_content`、`05_final`。
  - 验证：workspace 测试。
- [ ] 支持相对路径 artifact key。
  - 验收：允许 `04_content/abstract.md` 等 key；拒绝绝对路径、`..`、非法字符。
  - 验证：workspace 路径安全测试。
- [ ] 实现 `list` 动作。
  - 验收：可按 prefix 枚举目录下 artifact，供 Leader 审查缺文件。
  - 验证：workspace list 测试。
- [ ] 实现 `merge` 动作。
  - 验收：按输入顺序合并多个 artifact 并写入目标 key。
  - 验证：workspace merge 测试。
- [ ] 更新 `ToolRegistry` 中 `draft_workspace` schema 与描述。
  - 验收：schema 支持 `list` / `merge` 所需参数。
  - 验证：tool registry 相关测试。
- [ ] 运行 P1 验证命令。
  - 验收：workspace 测试和编译通过。
  - 验证：`conda run -n autoGLM pytest tests/test_draft_workspace.py && conda run -n autoGLM python -m compileall app tests`

## Phase 2 — `skill_loader` Markdown 技能文档

- [ ] 新增或改写 `tests/test_skill_loader.py`。
  - 验收：覆盖 Markdown 读取、白名单、缺失、路径穿越、拒绝 Python 源码。
  - 验证：`conda run -n autoGLM pytest tests/test_skill_loader.py`
- [ ] 将 `SkillLoaderTool` 默认目录改为 `settings.skill_dir`。
  - 验收：默认指向 `app/skills_docs`，不再指向 `app/skills`。
  - 验证：skill_loader 测试。
- [ ] 将白名单文件改为 Markdown 技能文档。
  - 验收：至少支持 `patent_drafting.md` 与 `mermaid.md`。
  - 验证：skill_loader 测试。
- [ ] 增加 `app/skills_docs/` 必要技能文档。
  - 验收：文档为领域知识 / SOP，不包含可执行 Python 源码。
  - 验证：skill_loader 测试。
- [ ] 保留路径安全校验。
  - 验收：未知技能、路径穿越、`.py` 请求均被拒绝。
  - 验证：skill_loader 安全测试。
- [ ] 更新 `ToolRegistry` 中 `skill_loader` 描述。
  - 验收：描述明确为 Markdown 技能文档加载。
  - 验证：registry 测试或 review。
- [ ] 运行 P2 验证命令。
  - 验收：skill_loader 测试和编译通过。
  - 验证：`conda run -n autoGLM pytest tests/test_skill_loader.py && conda run -n autoGLM python -m compileall app tests`

## Phase 3 — `patent_search` SerpAPI 检索接口与降级

- [ ] 新增或改写 `tests/test_patent_search.py`。
  - 验收：覆盖空 query、联网门控、SerpAPI Key 缺失、fake SerpAPI provider、Top-K、provider 异常、安全降级。
  - 验证：`conda run -n autoGLM pytest tests/test_patent_search.py`
- [ ] 为 `PatentSearchTool` 增加 SerpAPI provider 注入点。
  - 验收：测试可注入 fake SerpAPI provider，不访问真实网络。
  - 验证：patent_search 测试。
- [ ] 支持 R12 输入参数。
  - 验收：支持 `query`、`top_k`、`country`、`status`；默认 CN / GRANT / Top-K。
  - 验证：patent_search 参数测试。
- [ ] 实现联网门控与 SerpAPI Key 缺失降级。
  - 验收：`allow_network=False`、外部工具未授权或未配置 SerpAPI Key 时返回 skipped/degraded，不触网。
  - 验证：patent_search 门控测试。
- [ ] 删除 fake evidence 行为并接入 SerpAPI 结果规范化。
  - 验收：不再返回 `patent_search skipped: {query}` 伪 evidence；联网授权时从 SerpAPI 响应规范化出 title、publication_number、abstract、url、country、status、provenance。
  - 验证：patent_search 测试。
- [ ] 更新 `ToolRegistry` 中 `patent_search` schema 与 SerpAPI 描述。
  - 验收：schema 支持 `top_k`、`country`、`status`；描述明确后端为 SerpAPI。
  - 验证：registry 测试或 review。
- [ ] 运行 P3 验证命令。
  - 验收：patent_search 测试和编译通过。
  - 验证：`conda run -n autoGLM pytest tests/test_patent_search.py && conda run -n autoGLM python -m compileall app tests`

## Phase 3.5 — `todo` 工具与 `todo_prompt`

- [ ] 新增 `app/prompts/todo_prompt.py`。
  - 验收：包含 R12 §4.2 的规划 prompt，工具名按用户要求改为 `todo`。
  - 验证：prompt review 或 prompt 常量测试。
- [ ] 新增 `app/tools/todo.py`。
  - 验收：工具名为 `todo`，输入完整 todo 列表。
  - 验证：`conda run -n autoGLM pytest tests/test_todo_tool.py`
- [ ] 新增 `tests/test_todo_tool.py`。
  - 验收：覆盖状态枚举、owner 隔离、完整列表覆盖、上下文渲染、非法状态拒绝。
  - 验证：`conda run -n autoGLM pytest tests/test_todo_tool.py`
- [ ] 实现状态枚举校验。
  - 验收：只允许 `pending`、`in_progress`、`done`。
  - 验证：todo 工具测试。
- [ ] 实现 owner 隔离。
  - 验收：Leader 与每个子代理 todo 状态互不污染。
  - 验证：todo owner 测试。
- [ ] 实现 todo 上下文渲染。
  - 验收：可将当前 todo 列表注入 Leader / 子代理上下文。
  - 验证：todo 渲染测试。
- [ ] 注册 `todo` 工具。
  - 验收：`ToolRegistry` 可获取 `todo`；不注册 `write_todos`。
  - 验证：registry 测试。
- [ ] 运行 P3.5 验证命令。
  - 验收：todo 测试和编译通过。
  - 验证：`conda run -n autoGLM pytest tests/test_todo_tool.py && conda run -n autoGLM python -m compileall app tests`

## Phase 4 — R12 Prompt 与 9 个真实子代理

- [ ] 新增 `app/prompts/patent_drafting_leader.py`。
  - 验收：包含 R12 §4.1 Leader Prompt 原文，语义不改写。
  - 验证：prompt review。
- [ ] 新增 `app/prompts/subagents/` 下 9 个 prompt 模块。
  - 验收：包含 R12 §4.3 - §4.11 原文；仅做工具名等价替换。
  - 验证：prompt review 或常量存在测试。
- [ ] 改写 `tests/test_subagent_tools.py` 为 R12 契约。
  - 验收：断言 9 个子代理、fake LLM 调用、workspace key 读写、短结果返回。
  - 验证：`conda run -n autoGLM pytest tests/test_subagent_tools.py`
- [ ] 将 `SUBAGENT_DEFINITIONS` 改为 R12 9 环节。
  - 验收：包含 `description_writer_part1` 与 `description_writer_part2`。
  - 验证：subagent 测试。
- [ ] 实现子代理 LLM 调用或可注入 fake LLM。
  - 验收：子代理不再通过拼标题生成内容；测试可证明 fake LLM 被调用。
  - 验证：subagent fake LLM 测试。
- [ ] 为子代理配置受限工具集。
  - 验收：不同角色只能访问规定工具，如 `patent_searcher` 可用 `patent_search`，写作类可用 `skill_loader`。
  - 验证：subagent 工具权限测试。
- [ ] 子代理输出改为 R12 workspace key。
  - 验收：输出写入 `01_input/parsed_info.json`、`02_research/*.md`、`03_outline/patent_outline.md`、`04_content/*.md`、`05_final/*.md`。
  - 验证：subagent artifact 测试。
- [ ] 子代理返回短结果。
  - 验收：返回 `{artifact_key, done, note?}`，不回传长 Markdown 正文。
  - 验证：subagent 返回结构测试。
- [ ] 实现 `description_writer_part2` merge 行为。
  - 验收：使用 workspace `merge` 合并说明书第一部分与具体实施方式临时文件。
  - 验证：subagent part2 测试。
- [ ] 实现 `markdown_merger` merge 行为。
  - 验收：按摘要、权利要求书、说明书、说明书附图顺序合并终稿。
  - 验证：subagent merger 测试。
- [ ] 更新 `ToolRegistry` 注册 9 个子代理。
  - 验收：默认 registry 可获取全部 9 个子代理工具。
  - 验证：subagent registry 测试。
- [ ] 运行 P4 验证命令。
  - 验收：subagent 测试和编译通过。
  - 验证：`conda run -n autoGLM pytest tests/test_subagent_tools.py && conda run -n autoGLM python -m compileall app tests`

## Phase 5 — `drafting_leader` R12 编排审查

- [ ] 改写 `tests/test_drafting_leader.py` 为 R12 顺序。
  - 验收：断言 9 环节顺序、workspace list 审查、缺文件重试、最终输出 key。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_leader.py`
- [ ] 将 Leader 工具顺序改为 R12 9 环节。
  - 验收：顺序为 input_parser → patent_searcher → outline_generator → abstract_writer → claims_writer → description_writer_part1 → description_writer_part2 → diagram_generator → markdown_merger。
  - 验证：leader 顺序测试。
- [ ] Leader 创建或初始化项目工作区。
  - 验收：输入写入 `01_input/`，后续路径符合 R12 目录结构。
  - 验证：leader workspace 测试。
- [ ] Leader 通过 `list` 审查每阶段输出。
  - 验收：每个子代理后检查目标 artifact 是否存在。
  - 验证：leader list 审查测试。
- [ ] Leader 实现缺文件重委托。
  - 验收：缺失文件最多重试 5 次，超过后失败或标记 incomplete。
  - 验证：leader retry 测试。
- [ ] Leader 接入 `todo`。
  - 验收：Leader 可维护并注入自己的 todo 状态；不调用 `write_todos`。
  - 验证：leader todo 测试。
- [ ] 更新 trace / 日志脱敏。
  - 验收：trace 仅含工具名、artifact key、长度、状态、错误摘要。
  - 验证：leader trace 测试。
- [ ] 更新 `tests/test_patent_drafting_workflow.py`。
  - 验收：端到端使用 R12 key 和 9 环节产物。
  - 验证：`conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py`
- [ ] 运行 P5 验证命令。
  - 验收：leader、workflow 测试和编译通过。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_leader.py tests/test_patent_drafting_workflow.py && conda run -n autoGLM python -m compileall app tests`

## Phase 6 — 端到端回归与收尾

- [ ] 运行 R12 相关专项测试。
  - 验收：workspace、skill_loader、patent_search、todo、subagent、leader、workflow 测试通过。
  - 验证：`conda run -n autoGLM pytest tests/test_draft_workspace.py tests/test_skill_loader.py tests/test_patent_search.py tests/test_todo_tool.py tests/test_subagent_tools.py tests/test_drafting_leader.py tests/test_patent_drafting_workflow.py`
- [ ] 运行安全与附件回归。
  - 验收：附件 / 检索数据中的 prompt injection 不改变行为；正文不进日志或 trace。
  - 验证：相关 security / attachment 测试。
- [ ] 检查默认测试不触网、不调用真实外部 LLM。
  - 验收：默认测试使用 fake LLM / fake provider。
  - 验证：测试 review 或 monkeypatch 断言。
- [ ] 运行全量 pytest。
  - 验收：全量测试通过。
  - 验证：`conda run -n autoGLM pytest`
- [ ] 运行 compileall。
  - 验收：`app` 和 `tests` 编译通过。
  - 验证：`conda run -n autoGLM python -m compileall app tests`
- [ ] 检查 diff 无无关改动。
  - 验收：无密钥、无临时文件、无调试代码、无未要求重构。
  - 验证：`git status` / `git diff`
