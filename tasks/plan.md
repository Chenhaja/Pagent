# Pagent R12 专利文书生成缺口修复实施计划

## 目标与范围

本计划基于根目录 `SPEC.md`，用于修复 R12 指出的专利文书生成工具实现缺口。本轮只生成 `tasks/plan.md` 与 `tasks/todo.md`，不修改实现代码、不运行测试、不提交 git。

用户补充命名约定：

- 原 SPEC 中 `todo_middleware` 统一按 `todo_prompt` 理解。
- 原 SPEC 中 `write_todos` 工具统一按 `todo` 工具理解。
- 后续实现文件、prompt 模块、工具名和测试命名均优先使用 `todo_prompt` / `todo`。

R12 范围：

- 增强 `draft_workspace`：项目工作区、目录结构、相对路径 key、`list`、`merge`、默认内存 key-store、可选磁盘落盘。
- 修复 `skill_loader`：读取 Markdown 技能文档，不读取 `app/skills/*.py` 源码。
- 修复 `patent_search`：接入 SerpAPI 检索后端，受联网门控和 SerpAPI Key 配置控制，默认离线安全降级，不伪造 evidence。
- 增加 `todo` 工具和 `todo_prompt`：Leader 与 9 个子代理各自维护独立 todo 状态并注入上下文。
- 落地 R12 PRD §4 Prompt 原文：Leader + 9 个子代理 Prompt，只做工具名等价替换。
- 子代理从 8 个占位工具升级为 9 个真实 LLM subagent，拆分 `description_writer_part1` / `description_writer_part2`。
- 更新 `drafting_leader`：按 R12 顺序委托、审查、缺文件重试、最终交付。

当前只读探索结论：

- `app/tools/draft_workspace.py` 当前只支持扁平安全 key 的 `write` / `read`，且默认 `draft_workspace_dir` 为 `.pagent_drafts`，与 R12 的“默认内存、磁盘可选”不一致。
- `app/tools/skill_loader.py` 当前白名单指向 `.py` 文件，并默认读取 `app/skills`，与 R12 Markdown 技能文档要求不一致。
- `app/tools/patent_search.py` 当前是 stub：联网关闭返回 `network_disabled`，联网开启返回 fake evidence。
- `app/tools/subagents/__init__.py` 当前只有 8 个子代理，且只是读取 source artifact 后拼标题写回，没有 LLM、Prompt、工具访问和 9 环节拆分。
- `app/prompts/patent_drafting_sop.py` 与 `app/prompts/patent_drafting_subagents.py` 当前是 R11 简化版，不是 R12 PRD §4 原文。
- `app/nodes/drafting_leader.py` 当前按 8 个旧 subagent 顺序执行，不使用 workspace `list` 审查，也没有 R12 的重委托与 9 环节流程。
- `tests/test_subagent_tools.py` 当前断言 8 个子代理和拼标题行为，需改为 R12 的 9 个 LLM subagent 契约。

---

## 依赖图

```text
P0 需求命名与配置契约对齐
  ├─> P1 draft_workspace 垂直切片
  │     ├─> P4 子代理真实执行
  │     │     └─> P5 Leader 编排审查
  │     │           └─> P6 端到端回归
  │     └─> P5 Leader 编排审查
  ├─> P2 skill_loader 垂直切片
  │     └─> P4 子代理真实执行
  ├─> P3 patent_search 垂直切片
  │     └─> P4 patent_searcher 子代理
  ├─> P3.5 todo / todo_prompt 垂直切片
  │     ├─> P4 子代理真实执行
  │     └─> P5 Leader 编排审查
  └─> P6 端到端回归
```

说明：

- `draft_workspace` 是所有子代理和 Leader 审查的基础，必须先落地。
- `skill_loader` 与 `patent_search` 可并行实现，但它们分别阻塞专利写作类子代理和 `patent_searcher`。
- `todo` 工具与 `todo_prompt` 需在子代理和 Leader 接入前完成，否则上下文注入契约无法测试。
- Prompt 与子代理应作为一条完整垂直切片落地：Prompt 常量 → fake LLM 调用 → workspace 写入 → ToolRegistry 注册 → 测试。

---

## 阶段计划

### P0 — 需求命名与基础配置对齐

#### 目标

将 R12 实施命名和配置口径固定下来，避免后续文件、工具名、测试名反复迁移。

#### 覆盖范围

- `app/core/config.py`
- `SPEC.md` 后续如需同步命名，另行确认后再改。
- 测试中的工具名、prompt 模块名约定。

#### 实施要点

- 新增或修正配置默认值：`draft_workspace_dir` 默认应为空字符串，表示内存 key-store。
- 增加或确认 `skill_dir`，默认 `app/skills_docs`。
- 增加或确认 `patent_search_top_k`，默认 10。
- 增加 SerpAPI Key 敏感配置（`SERPAPI_API_KEY` / `PAGENT_SERPAPI_API_KEY`），不得进入 `to_public_dict()`、日志或 trace。
- 如果需要独立 drafting 步数配置，沿用现有通用配置优先，不新增单 Node 临时配置。
- 命名统一：`app/prompts/todo_prompt.py`、工具名 `todo`、测试文件建议 `tests/test_todo_tool.py`。

#### 验收标准

- 配置默认值、环境变量读取、`to_public_dict()` 覆盖完整。
- `draft_workspace_dir=""` 表示内存模式。
- 公开配置不包含敏感字段。
- 后续文档与测试不再出现 `todo_middleware` / `write_todos` 新命名。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_core_config_logging.py
conda run -n autoGLM python -m compileall app tests
```

#### 检查点

- 确认 `todo` 工具命名已经被用户接受。
- 确认 `PAGENT_SKILL_DIR` 默认值使用 `app/skills_docs`。

---

### P1 — `draft_workspace` 项目工作区垂直切片

#### 目标

让 Leader 和子代理可以通过项目工作区完成 artifact 写入、读取、枚举和合并。

#### 覆盖范围

- `app/tools/draft_workspace.py`
- `app/orchestrator/tool_registry.py`
- `tests/test_draft_workspace.py` 或现有 native tool 测试

#### 实施要点

- 支持动作：`write`、`read`、`list`、`merge`。
- 支持项目根：`temp_[uuid]/`。
- 内建逻辑目录：`01_input`、`02_research`、`03_outline`、`04_content`、`05_final`。
- artifact key 改为相对路径，例如 `04_content/abstract.md`。
- 默认内存 store；仅 `PAGENT_DRAFT_WORKSPACE_DIR` 非空时落盘。
- 保留 key 白名单、防路径逃逸、内容截断。
- `merge` 按顺序读取 source keys，合并后写入 output key。

#### 验收标准

- 内存模式下不创建磁盘文件。
- 磁盘模式下所有路径均位于 workspace 根目录内。
- `list` 可按 prefix 枚举 artifact。
- `merge` 可生成 `04_content/description.md` 与 `05_final/complete_patent.md`。
- 非法 key（绝对路径、`..`、非法字符）被拒绝。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_draft_workspace.py
conda run -n autoGLM python -m compileall app tests
```

#### 建议提交

```text
feat(tool): 增强专利文书工作区能力
```

---

### P2 — `skill_loader` Markdown 技能文档垂直切片

#### 目标

将技能加载从读取 Python 源码修复为读取独立 Markdown 技能 / SOP 文档。

#### 覆盖范围

- `app/tools/skill_loader.py`
- `app/skills_docs/`
- `app/orchestrator/tool_registry.py`
- `tests/test_skill_loader.py`

#### 实施要点

- 使用 `PAGENT_SKILL_DIR` / `settings.skill_dir`。
- 白名单技能建议包括：`patent_drafting`、`mermaid`。
- 文件扩展名限定 `.md`。
- 防路径穿越。
- 不读取、不返回 `app/skills/*.py` 内容。
- 技能文档只作为数据上下文，不提升为系统指令。

#### 验收标准

- 能读取白名单 Markdown 技能文档。
- 请求未知技能返回 `skill_unavailable` 或等价安全错误。
- 请求 `.py` 或路径穿越被拒绝。
- `ToolRegistry` 中 `skill_loader` 描述更新为 Markdown 技能文档加载。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_skill_loader.py
conda run -n autoGLM python -m compileall app tests
```

#### 建议提交

```text
fix(tool): 改为加载专利 Markdown 技能文档
```

---

### P3 — `patent_search` SerpAPI 检索与离线降级垂直切片

#### 目标

将专利检索从 fake evidence stub 升级为基于 SerpAPI 的检索工具，并保持默认离线可测。

#### 覆盖范围

- `app/tools/patent_search.py`
- `app/orchestrator/tool_registry.py`
- `tests/test_patent_search.py`

#### 实施要点

- 定义 SerpAPI provider 抽象，测试中注入 fake provider。
- 输入支持 `query`、`top_k`、`country`、`status`。
- 默认 `country=CN`、`status=GRANT`、`top_k=settings.patent_search_top_k`。
- `allow_network=False`、外部工具未授权或未配置 SerpAPI Key 时返回 skipped/degraded，不触网。
- SerpAPI Key 从 `SERPAPI_API_KEY` / `PAGENT_SERPAPI_API_KEY` 或配置读取，作为敏感配置处理。
- SerpAPI 调用异常、限流或返回异常时返回安全降级结果。
- 真实联网 SerpAPI 测试必须标记 `network`，不在默认测试中触发。

#### 验收标准

- 空 query 返回明确错误。
- 离线模式不触网且不伪造 evidence。
- fake provider 能模拟 SerpAPI 返回 Top-K、CN、GRANT 结构化结果。
- 结果字段包含来源 provenance。
- 未配置 SerpAPI Key 时不触网并返回明确 reason。
- SerpAPI Key 不进入公开配置、日志或 trace。
- 默认测试不依赖真实网络。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_patent_search.py
conda run -n autoGLM python -m compileall app tests
```

#### 检查点

- 检索后端已明确使用 SerpAPI；仍需在实现前确认采用直接 HTTP 调用还是 SDK，以及具体查询参数映射。

#### 建议提交

```text
feat(tool): 接入 SerpAPI 专利检索接口
```

---

### P3.5 — `todo` 工具与 `todo_prompt` 垂直切片

#### 目标

实现 R12 规划能力：Leader 与每个子代理各自维护 todo 状态，并在后续上下文中注入当前 todo 列表。

#### 覆盖范围

- `app/tools/todo.py`
- `app/prompts/todo_prompt.py`
- `app/orchestrator/tool_registry.py`
- `tests/test_todo_tool.py`

#### 实施要点

- 工具名为 `todo`。
- Prompt 模块为 `app/prompts/todo_prompt.py`。
- 输入为完整 todo 列表，每项包含 `text` 与 `status`。
- 状态枚举：`pending`、`in_progress`、`done`。
- 状态按 owner 隔离：Leader 与 9 个子代理各自一份。
- 每步 agent 上下文注入当前 todo 列表。
- todo 状态不影响最大步数、token 预算或超时硬门控。

#### 验收标准

- 非法 status 被拒绝。
- 同一 owner 更新会覆盖完整列表。
- 不同 owner 状态互不污染。
- 可渲染当前 todo 列表供 Leader / 子代理 prompt 注入。
- `ToolRegistry` 注册 `todo`，不注册 `write_todos`。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_todo_tool.py
conda run -n autoGLM python -m compileall app tests
```

#### 建议提交

```text
feat(drafting): 增加文书生成 todo 工具
```

---

### P4 — R12 Prompt 与 9 个真实子代理垂直切片

#### 目标

用 R12 PRD §4 原文替换 R11 简化 Prompt，并将 8 个占位子代理升级为 9 个真实 LLM subagent。

#### 覆盖范围

- `app/prompts/patent_drafting_leader.py`
- `app/prompts/subagents/*.py`
- `app/tools/subagents/__init__.py`
- 如需：`app/tools/subagents/base.py`
- `tests/test_subagent_tools.py`

#### 实施要点

- Leader Prompt 使用 R12 §4.1 原文。
- 子代理 Prompt 使用 R12 §4.3 - §4.11 原文。
- `todo_prompt` 使用 R12 §4.2 原文，但工具名按用户要求改为 `todo`。
- 子代理清单改为 9 个：
  1. `input_parser`
  2. `patent_searcher`
  3. `outline_generator`
  4. `abstract_writer`
  5. `claims_writer`
  6. `description_writer_part1`
  7. `description_writer_part2`
  8. `diagram_generator`
  9. `markdown_merger`
- 每个子代理调用 LLM 或可注入 fake LLM，不再拼标题。
- 子代理按角色限制工具：workspace / skill_loader / office_to_md / file_extract / patent_search / todo。
- 子代理输出写入 R12 目录 key，只返回 `{artifact_key, done, note?}`。

#### 验收标准

- `tests/test_subagent_tools.py` 断言 9 个子代理。
- 每个子代理使用对应 Prompt 常量。
- fake LLM 被调用，旧“拼标题”行为测试删除或改写。
- 子代理不接受长正文 `content`。
- 子代理产物写入 workspace 相对路径 key。
- `description_writer_part2` 使用 `draft_workspace.merge` 合并说明书。
- `markdown_merger` 使用 `draft_workspace.merge` 生成终稿。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_subagent_tools.py
conda run -n autoGLM python -m compileall app tests
```

#### 建议提交

```text
feat(drafting): 接入 R12 子代理提示词
```

---

### P5 — `drafting_leader` R12 编排审查垂直切片

#### 目标

让 Leader 严格按 R12 顺序创建项目工作区、委托 9 个子代理、审查输出文件、缺失重试并交付最终路径。

#### 覆盖范围

- `app/nodes/drafting_leader.py`
- `app/prompts/patent_drafting_leader.py`
- `tests/test_drafting_leader.py`
- `tests/test_patent_drafting_workflow.py`

#### 实施要点

- 将旧 8 工具顺序替换为 R12 9 环节顺序。
- 输入文档先写入 `01_input/raw_document.*` 或等价 source artifact。
- 子代理参数只传 source / input / output artifact key。
- 每个子代理完成后调用 workspace `list` 审查输出是否存在。
- 缺文件时最多重委托 5 次。
- 最终交付 `05_final/complete_patent.md` 与 `05_final/summary_report.md` key。
- trace 只记录工具名、artifact key、长度、状态、错误摘要。

#### 验收标准

- 调用顺序严格匹配 R12。
- `list` 审查缺失文件行为可测。
- 超过重试上限返回失败原因或 `drafting_incomplete=True`。
- 最终 state 包含完整文书和评审报告引用。
- Leader 使用 `todo`，不使用 `write_todos`。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_drafting_leader.py
conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py
conda run -n autoGLM python -m compileall app tests
```

#### 建议提交

```text
fix(drafting): 修复专利文书生成编排缺口
```

---

### P6 — 端到端回归与收尾

#### 目标

验证 R12 缺口修复后的完整专利文书生成链路，确保默认离线、无真实 LLM、无真实网络也可测试。

#### 覆盖范围

- 全部 R12 相关测试
- 既有 agentic / attachment / security / config 回归
- compileall

#### 实施要点

- 使用 fake LLM / fake search provider / tmp workspace。
- 覆盖附件或检索数据中的 prompt injection 不改变行为。
- 覆盖 trace / log 脱敏。
- 覆盖默认不触网。
- 检查 diff 中无密钥、临时文件、无关改动。

#### 验收标准

- `patent_drafting` 端到端输出摘要、权利要求书、说明书、说明书附图、完整文书、评审报告。
- 全量 pytest 通过。
- compileall 通过。
- 默认测试不访问真实网络和真实外部 LLM。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_draft_workspace.py tests/test_skill_loader.py tests/test_patent_search.py tests/test_todo_tool.py tests/test_subagent_tools.py tests/test_drafting_leader.py tests/test_patent_drafting_workflow.py
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests
```

#### 建议提交

```text
test(drafting): 补充 R12 文书生成回归测试
```

---

## 关键文件

- `SPEC.md`
- `app/core/config.py`
- `app/tools/draft_workspace.py`
- `app/tools/skill_loader.py`
- `app/tools/patent_search.py`
- `app/tools/todo.py`
- `app/tools/subagents/__init__.py`
- `app/tools/subagents/base.py`
- `app/prompts/patent_drafting_leader.py`
- `app/prompts/todo_prompt.py`
- `app/prompts/subagents/*.py`
- `app/nodes/drafting_leader.py`
- `app/orchestrator/tool_registry.py`
- `tests/test_draft_workspace.py`
- `tests/test_skill_loader.py`
- `tests/test_patent_search.py`
- `tests/test_todo_tool.py`
- `tests/test_subagent_tools.py`
- `tests/test_drafting_leader.py`
- `tests/test_patent_drafting_workflow.py`

---

## 风险与防护

| 风险 | 防护 |
| --- | --- |
| R12 Prompt 原文较长，手工迁移易误改语义 | 从 PRD §4 逐段搬运；测试只验证存在与绑定，不重写语义 |
| workspace 从磁盘默认切到内存影响现有测试 | P1 先改测试，覆盖内存和磁盘双模式 |
| 子代理接入 LLM 后默认测试不稳定 | 使用 fake LLM 注入；真实 LLM 不进入默认测试 |
| `patent_search` 真实后端不确定 | 先实现 provider 抽象和 fake provider；真实联网后端作为需确认项 |
| todo 命名与 SPEC 旧名称不一致 | 本计划统一使用 `todo_prompt` / `todo`，实现前如需同步 SPEC 再单独修改 |
| Leader 重试导致测试复杂 | fake workspace / fake subagent 精确控制缺文件场景 |
| 日志泄露正文 | trace/log 只断言 key、长度、状态，不记录正文 |

---

## 文档任务检查点

- [x] `tasks/plan.md` 已更新为 R12 计划。
- [x] `tasks/todo.md` 应更新为 R12 todo。
- [x] 已按用户补充统一使用 `todo_prompt` / `todo` 命名。
- [x] 本轮不修改实现代码。
- [x] 本轮不运行测试。
- [x] 本轮不提交 git。
