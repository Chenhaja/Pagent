# R11 patent_drafting 实施计划

## 目标与范围

本计划基于根目录 `SPEC.md` 与 R11 PRD，用于落地 `patent_drafting` 专利文书生成流程。本轮只生成实施计划与任务清单文档，不修改 `app/`、`tests/` 或任何实现代码。

R11 范围：

- 新增 `patent_drafting` workflow，用于编排完整专利文书生成。
- 先删除旧 `claim_generation` / `claim_revision` 流程，避免新旧权利要求链路并存。
- 不引入 MCP 或外部 agent 框架。
- 复用 R10 附件上传、解析与 `WorkflowState.documents` 通道。
- 复用现有 bounded ReAct、`ToolRegistry`、预算控制和 trace 模式。
- 新增 native tools 与 subagent-as-tool 仅作为本地工具能力接入。

当前只读探索结论：

- `app/orchestrator/workflow_defs.py` 当前仍注册 `claim_generation` / `claim_revision`，需在 Phase 0 删除，并新增 `patent_drafting`。
- `app/services/agent_dispatch_service.py` 当前仍 import/use `WorkflowService`、`RevisionService`，并分派旧 claim intent；后续需删除旧分支并新增 `patent_drafting` 分支。
- `app/nodes/qa.py` 是 bounded ReAct 节点最佳模板，可复用其 `BoundedReActLoop`、`ReActBudget`、`ToolRegistry`、预算覆盖和 trace 模式。
- R10 附件链路已存在：`AttachmentService`、`file_extract`、`office_to_md`、`WorkflowState.documents`，R11 应复用，不重新实现上传/解析链路。
- 旧 claim 代码和测试分布广，必须把“删除旧 claim 流程”作为独立、可验证、可提交的首阶段。

---

## 依赖图

```text
P0 删除旧 claim 流程
  ├─> P1 配置与 WorkflowState 契约
  │     ├─> P2 native tools
  │     │     └─> P3 subagent-as-tool
  │     │           └─> P4 drafting_leader
  │     │                 └─> P5 workflow / intent / dispatch / API 接入
  │     │                       └─> P6 端到端与回归
  │     └─> P5 workflow / intent / dispatch / API 接入
  └─> P6 端到端与回归
```

---

## 阶段计划

### P0 删除旧 `claim_generation` / `claim_revision`

#### 目标

移除旧权利要求生成与修改流程，确保后续 `patent_drafting` 不与旧 claim workflow、intent、service、prompt 和测试并存。

#### 覆盖范围

- 删除或迁移旧 claim nodes。
- 删除旧 claim skills。
- 删除 `WorkflowService`、`RevisionService` 等旧 claim service 使用点。
- 清理 `workflow_defs` 中的旧 workflow 注册。
- 清理 intent router 中旧 claim intent 分支。
- 清理旧 claim prompt。
- 清理 API schema/routes 中只服务旧 claim 流程的字段或分支。
- 删除、迁移或改写旧 claim 测试。
- 新增旧代码删除守卫测试，例如 `tests/test_claim_code_removed.py`。

#### 验收标准

- 旧 intent 不可路由。
- 旧 workflow 不存在。
- 旧模块无 import 残留。
- `pytest` 收集通过。
- `compileall` 通过。
- 删除范围只覆盖旧 claim 流程，不影响 R10 附件链路和 QA 链路。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_claim_code_removed.py
conda run -n autoGLM python -m compileall app tests
```

#### 建议提交

```text
refactor(claim): 删除旧权利要求生成流程
```

---

### P1 配置与 `WorkflowState` 契约

#### 目标

新增 R11 专利文书生成所需的系统级配置与 `WorkflowState` Markdown 产物字段，形成后续 tools、subagent、leader 和 workflow 的稳定契约。

#### 覆盖范围

- 更新 `app/core/config.py`。
- 更新 `app/models/schemas.py`。
- 更新配置测试与 state 测试。

#### 实施要点

- 新增 drafting 系统级配置、环境变量读取、`to_public_dict()`、配置测试。
- 配置命名保持通用系统能力，不绑定单个临时节点。
- Node/模块可通过构造参数覆盖全局配置，默认继承时用 `None` 表示未传值。
- 新增 Markdown 产物字段：
  - `input_points_md`
  - `prior_art_md`
  - `outline_md`
  - `abstract_md`
  - `claims_md`
  - `description_md`
  - `figures_md`
  - `complete_patent_md`
  - `drafting_incomplete`

#### 验收标准

- 新增配置有默认值、环境变量读取、`to_public_dict()` 和测试覆盖。
- 敏感配置不进入公开配置或日志。
- `WorkflowState` 新字段默认值安全，不破坏既有状态初始化。
- Markdown 产物字段可被后续 node 和 workflow 稳定读写。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_core_config_logging.py tests/test_workflow_state.py
conda run -n autoGLM python -m compileall app tests
```

#### 建议提交

```text
feat(config): 增加专利文书生成配置
```

---

### P2 native tools

#### 目标

新增 R11 所需 native tools，并接入现有 `ToolRegistry`，为 subagent-as-tool 与 leader ReAct 提供离线可测、路径安全、可降级的本地工具能力。

#### 覆盖范围

- 新增 `app/tools/draft_workspace.py`。
- 新增 `app/tools/skill_loader.py`。
- 新增 `app/tools/patent_search.py`。
- 更新 `app/orchestrator/tool_registry.py`。
- 新增或更新 native tool 测试。

#### 实施要点

- `draft_workspace.py`：管理 drafting workspace artifact 的读写，限制 key 和路径，防止目录穿越。
- `skill_loader.py`：按白名单读取专利 drafting 所需技能或模板，不加载任意路径。
- `patent_search.py`：默认离线 skipped/fake；联网能力必须受配置门控，联网测试单独标记 `network`。
- 所有工具返回结构化结果，异常安全降级，不把长正文写入 trace/log。
- 接入 `ToolRegistry` 时保持工具名稳定、白名单明确。

#### 验收标准

- native tools 离线可测。
- workspace 路径安全。
- patent search 默认不误触网。
- 异常返回结构化错误或 skipped，不抛出裸异常到 ReAct 主循环。
- trace/log 只记录 artifact key、长度、数量、状态等元数据。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_new_native_tools.py tests/test_agentic_tools.py
conda run -n autoGLM python -m compileall app tests
```

#### 建议提交

```text
feat(tool): 增加专利文书 native 工具
```

---

### P3 subagent-as-tool

#### 目标

新增本地 subagent-as-tool 能力，把专利文书生成拆成可被 leader 调用的 8 个子代理工具，且子代理只通过 workspace key 读取正文，避免长正文在工具参数中反复传递。

#### 覆盖范围

- 新增 `app/tools/subagents/`。
- 实现 8 个子代理与对应 prompt。
- 新增 `tests/test_subagent_tools.py`。

#### 实施要点

- 子代理统一返回 Markdown + `artifact_key` + `done`。
- 子代理只按 workspace key 读取正文，不接收长正文。
- prompt 集中放在 `app/prompts/` 或 subagent 专用 prompts 模块，避免散落在业务逻辑。
- 每个 prompt 遵守项目六要素规范、指令与数据分离、结构化输出和专利域约束。
- 子代理工具不写长期记忆，不把未人审正文写入 trace/log。

#### 验收标准

- 8 个子代理可被 `ToolRegistry` 或 leader 白名单调用。
- 每个子代理输出包含 Markdown artifact、`artifact_key`、`done`。
- 长正文只通过 workspace key 读取。
- 子代理失败时返回可恢复状态，不导致 leader 非预期崩溃。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_subagent_tools.py
conda run -n autoGLM python -m compileall app tests
```

#### 建议提交

```text
feat(drafting): 增加专利文书子代理工具
```

---

### P4 `drafting_leader`

#### 目标

新增 `drafting_leader` 编排节点，复用 `QANode` 的 bounded ReAct 模式，按 SOP 调用 native tools 与 subagent-as-tool 生成完整专利文书 Markdown。

#### 覆盖范围

- 新增 `app/nodes/drafting_leader.py`。
- 新增 `app/prompts/patent_drafting_sop.py`。
- 新增 `tests/test_drafting_leader.py`。
- 复用并覆盖测试 `tests/test_agentic_loop.py`、`tests/test_react_policy.py`。

#### 实施要点

- 以 `app/nodes/qa.py` 为实现模板。
- 复用 `BoundedReActLoop`、`ReActBudget`、`ToolRegistry`、预算覆盖和 trace 模式。
- SOP 明确步骤顺序：输入整理、现有技术、提纲、摘要、权利要求、说明书、附图说明、完整文书整合。
- 工具调用使用白名单，不允许 leader 调用任意工具。
- 预算耗尽或子代理未完成时设置 `drafting_incomplete=True`。
- trace 脱敏，只记录步骤、工具名、artifact key、长度、状态和错误摘要。

#### 验收标准

- leader 按 SOP 调用工具，顺序可测。
- 工具白名单生效。
- 预算命中时 `drafting_incomplete=True`。
- 生成的 Markdown 写入对应 `WorkflowState` 字段。
- trace 不含附件正文、完整专利正文或隐私内容。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_drafting_leader.py tests/test_agentic_loop.py tests/test_react_policy.py
conda run -n autoGLM python -m compileall app tests
```

#### 建议提交

```text
feat(drafting): 增加专利文书编排节点
```

---

### P5 workflow / intent / dispatch / API 接入

#### 目标

把 `patent_drafting` 接入 intent、workflow registry、dispatch 和 API 响应链路，替代旧 claim intent/workflow，并确保未人审完整文书不进入长期记忆。

#### 覆盖范围

- 更新 `IntentClassification`。
- 更新 `IntentRouterNode`。
- 更新 `app/prompts/intent_router.py`。
- 更新 `WorkflowRegistry` / `app/orchestrator/workflow_defs.py`。
- 更新 `AgentDispatchService`。
- 更新 API schema/routes 中必要的兼容字段。
- 新增 E2E workflow/API 测试。

#### 实施要点

- 新增 `patent_drafting` intent。
- 删除旧 claim workflow 注册与 dispatch 分支。
- 新增 `patent_drafting` workflow，节点包含前置标准化、router 后的 drafting leader 等必要环节。
- `AgentDispatchService` 新增 `patent_drafting` dispatch。
- `complete_patent_md` 在未人审前不写入长期记忆。
- API 响应保留兼容字段时只添加必要映射，不恢复旧 claim 流程。
- 附件输入继续复用 `WorkflowState.documents`，不重复实现上传/解析。

#### 验收标准

- `patent_drafting` 能被 router 分类并进入新 workflow。
- 旧 `claim_generation` / `claim_revision` 不再可路由或执行。
- dispatch 不再 import/use 旧 claim service。
- `complete_patent_md` 可在响应中返回，但不进入长期记忆。
- R10 附件注入测试仍通过。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_workflow_registry.py tests/test_intent_router_node.py tests/test_agent_dispatch_service.py
conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py tests/test_agent_api.py tests/test_attachment_inject.py
conda run -n autoGLM python -m compileall app tests
```

#### 建议提交

```text
feat(drafting): 接入专利文书生成流程
```

---

### P6 端到端与回归

#### 目标

完成 R11 端到端验证、离线回归、防注入、trace 脱敏、网络测试标记和全量回归，确保新流程可独立验证并不破坏 R10 附件链路。

#### 覆盖范围

- 完整 Markdown 输出验证。
- 离线测试与网络测试标记检查。
- prompt injection / 数据区隔离验证。
- trace/log 脱敏验证。
- 全量 pytest 与 compileall。

#### 实施要点

- 覆盖完整 Markdown 输出：摘要、权利要求、说明书、附图说明、完整文书。
- 覆盖附件数据中的注入式文本不会改变系统指令、输出格式或 router 判定。
- 覆盖 patent search 默认 skipped/fake，联网测试单独标记 `network`。
- 覆盖 trace/log 不含附件正文、完整专利正文、API Key 或隐私内容。
- 运行全量回归。

#### 验收标准

- `patent_drafting` E2E 测试通过。
- 安全合规、附件抽取和附件注入测试通过。
- 全量 pytest 通过。
- compileall 通过。
- diff 无无关改动、无密钥、无临时文件。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py
conda run -n autoGLM pytest tests/test_security_compliance.py tests/test_attachment_extract.py tests/test_attachment_inject.py
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests
```

#### 建议提交

```text
test(drafting): 补充专利文书生成回归测试
```

---

## 关键文件

- `app/orchestrator/workflow_defs.py`
- `app/services/agent_dispatch_service.py`
- `app/models/schemas.py`
- `app/nodes/intent_router.py`
- `app/prompts/intent_router.py`
- `app/nodes/qa.py`（实现模板）
- `app/orchestrator/react_loop.py`
- `app/orchestrator/react_policy.py`
- `app/orchestrator/tool_registry.py`
- `app/services/attachment_service.py`
- `app/tools/file_extract.py`
- `app/tools/office_to_md.py`

---

## 风险与防护

| 风险 | 防护 |
| --- | --- |
| 旧 claim 字段被 QA/report 间接依赖 | 实施前逐项 grep，必要时改为 `documents` 或新 drafting 字段；P0 独立提交并验证 |
| Leader ReAct 失控 | 工具白名单 + `ReActBudget` + SOP 顺序测试 + `drafting_incomplete` 兜底 |
| 附件正文污染记忆或 trace | 沿用 `WorkflowState.documents`；只记录长度、数量、artifact key 和状态 |
| `patent_search` 误触网 | 默认 skipped/fake；联网能力受配置门控；联网测试单独标记 `network` |
| 未人审完整文书进入长期记忆 | dispatch/API 层增加测试，确认 `complete_patent_md` 不写入长期 memory |
| 新旧 intent 并存导致路由歧义 | P0 删除旧 claim intent，P5 只新增 `patent_drafting` |
| Prompt 散落在业务逻辑中 | drafting SOP 与 subagent prompt 集中放入 `app/prompts/` 或专用 prompts 模块 |

---

## 文档任务检查点

- [x] `tasks/plan.md` 包含依赖图、阶段计划、验收标准、验证命令和检查点。
- [x] `tasks/todo.md` 应包含可执行 checklist。
- [x] 本轮不修改实现代码。
- [x] 本轮不运行测试。
- [x] 本轮不提交 git。
