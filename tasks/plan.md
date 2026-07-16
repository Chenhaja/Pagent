# Implementation Plan: 案件级 Workspace 生命周期与 Agent 工具稳定性改造

## Overview

本计划基于 `SPEC.md`，在已完成的案件创建 API 基础上，继续实现案件 workspace 复用、附件绑定案件、目录文件工具、skill list/load、LangChain todo middleware 和全量验证。目标是不引入 UI、不重做工具系统，同时让同一 `case_id` 下多个 `session_id`、附件和 agent 文件操作复用同一个 `.draft_workspace/tmp_{workspace_id}`，并继续由 file policy 约束所有文件路径。

## Current Baseline

已完成并提交：

- `CaseService` 基础创建/读取能力。
- `POST /agent/cases`。
- `AgentRequest.case_id` 必填。
- `WorkflowState.case_id` / `workspace_id`。
- `/agent` 校验未知 case 并透传 `case_id` / `workspace_id`。

后续任务从 workspace 复用开始，不重复实现已完成切片。

## Architecture Decisions

- **案件是 workspace 生命周期入口**：`/agent` 与 `/agent/attachments` 不隐式创建 case，调用方必须先调用 `/agent/cases`。
- **workspace 只通过 ID 和相对展示路径暴露**：API 返回 `.draft_workspace/tmp_{workspace_id}`，内部可解析到磁盘路径，但不向调用方暴露绝对路径。
- **同案共享 workspace，会话记忆独立**：`case_id` 决定 workspace；`session_id` 仍只决定 session memory，避免历史串扰。
- **文件访问双层约束**：`DraftWorkspaceTool` 保留自身安全 key/path 校验，LangChain file tools 先通过 `FileToolPolicy` 再调用 workspace。
- **skill 从“猜名称”变成“列举后精确加载”**：新 LangChain tools 暴露 `list_skills()` 和 `load_skill(name)`；旧 `skill_loader` 仅可短期作为内部兼容。
- **todo 使用官方 middleware，失败降级**：runner 接入 LangChain todo middleware；导入失败时记录 warning/trace 并仅禁用 todo middleware。

## Dependency Graph

```text
已完成 Task 1: 案件生命周期 API
  -> Task 2: 案件 workspace 复用
      -> Task 3: 附件绑定案件并导入 workspace
      -> Task 4: 目录工具与 file policy
          -> Task 5: Skill list/load 与 allowed tools 更新
              -> Task 6: Todo middleware 接入
                  -> Task 7: 全量验证与收尾
```

关键依赖：

1. 附件导入 workspace 依赖同一 case workspace 可被 service/dispatch 构造。
2. LangChain `mkdir` / `list_directory` 依赖 `DraftWorkspaceTool` 先具备目录 action。
3. Skill list/load 需要同步 `SkillLoaderTool`、LangChain adapters、allowed tools 和旧 registry 测试。
4. Todo middleware 最后接入，避免和文件/skill 工具变更互相干扰。

## Task List

## Task 2: 复用案件 workspace

**Description:** 让 `/agent` dispatch 和 patent drafting 节点根据 `case_id` 使用同一 `DraftWorkspaceTool(workspace_name="tmp_{workspace_id}")`，同一案件不同 session 复用 workspace，session memory 仍独立。

**Acceptance criteria:**

- [ ] `DraftWorkspaceTool` 保留旧 `project_id` 行为，并新增可选 `workspace_name`。
- [ ] `workspace_name="tmp_{workspace_id}"` 时磁盘路径为 `<draft_workspace_dir>/tmp_{workspace_id}`；未传入时仍为 `<draft_workspace_dir>/temp_{project_id}`。
- [ ] `AgentDispatchService` 通过 `CaseService.get_workspace(case_id)` 获取 workspace 信息并传给 patent drafting 相关节点。
- [ ] 同一 `case_id` 下多个 `session_id` 共享同一个 workspace。
- [ ] session memory 仍按 `session_id` 读写，互不串扰。

**Verification:**

- [ ] `conda run -n autoGLM pytest tests/test_case_service.py tests/test_agent_dispatch_service.py tests/test_patent_drafting_workflow.py`
- [ ] `conda run -n autoGLM pytest tests/test_draft_workspace.py`
- [ ] `conda run -n autoGLM python -m compileall app tests scripts`

**Dependencies:** Task 1.

**Files likely touched:**

- `app/tools/draft_workspace.py`
- `app/services/case_service.py`
- `app/services/agent_dispatch_service.py`
- `app/nodes/drafting_research.py`
- `app/nodes/drafting_content.py`
- `tests/test_draft_workspace.py`
- `tests/test_agent_dispatch_service.py`
- `tests/test_patent_drafting_workflow.py`

**Estimated scope:** Medium.

---

## Task 3: 绑定附件到案件并导入 workspace

**Description:** 附件上传和读取都绑定 `case_id`；保存原始附件到现有 attachment storage，同时将抽取正文写入案件 workspace，并在 dispatch 注入附件时校验归属。

**Acceptance criteria:**

- [ ] `/agent/attachments` 增加必填 `case_id` 表单字段。
- [ ] `AttachmentService.save_upload(..., case_id=case_id)` 校验 case 存在。
- [ ] 附件 `metadata.json` 增加 `case_id`、`workspace_artifact_key`。
- [ ] 抽取正文写入案件 workspace：`01_input/attachments/{attachment_id}/extracted.md` 或 `.txt`。
- [ ] `AttachmentService.load_document(attachment_id, case_id=case_id)` 校验附件归属。
- [ ] 跨 case 读取附件返回 `attachment_not_found`，不泄露附件存在性。
- [ ] `AgentDispatchService._inject_attachments()` 使用当前 `case_id` 加载附件。

**Verification:**

- [ ] `conda run -n autoGLM pytest tests/test_attachment_upload.py tests/test_attachment_inject.py`
- [ ] `conda run -n autoGLM pytest tests/test_agent_api.py tests/test_patent_drafting_workflow.py`
- [ ] `conda run -n autoGLM python -m compileall app tests scripts`

**Dependencies:** Task 2.

**Files likely touched:**

- `app/api/routes.py`
- `app/api/schemas.py`
- `app/services/attachment_service.py`
- `app/services/agent_dispatch_service.py`
- `tests/test_attachment_upload.py`
- `tests/test_attachment_inject.py`
- `tests/test_agent_api.py`

**Estimated scope:** Medium.

---

## Checkpoint: Case workspace + attachments

- [ ] `/agent/cases` -> `/agent/attachments` -> `/agent` 的同案流程可运行。
- [ ] 同一 case 的附件正文和 agent artifacts 落在同一 workspace。
- [ ] 不存在无 `case_id` 的生产入口兼容逻辑。
- [ ] 相关测试与 compileall 通过。

---

## Task 4: 扩展目录工具与 file policy

**Description:** 为 workspace 与 LangChain file tools 增加目录创建和目录枚举能力，确保目录操作仍只作用于当前案件 workspace，且必须先通过 file policy。

**Acceptance criteria:**

- [ ] `DraftWorkspaceTool.run()` 支持 `action="mkdir"`，在 workspace 内幂等创建目录。
- [ ] `DraftWorkspaceTool.run()` 支持 `action="list_directory"`，只列指定目录直接子目录和文件，不递归返回全部内容。
- [ ] 内存模式通过 artifact key 前缀推导目录结构，测试环境可运行。
- [ ] `build_file_tools()` 暴露 `mkdir(path: str)`、`list_directory(path: str = "")`。
- [ ] `read_file`、`list_directory` 使用 `policy.check("read", path)`。
- [ ] `write_file`、`mkdir` 使用 `policy.check("write", path)`。
- [ ] `LangChainAgentRunner._file_policy_prompt()` 说明所有路径都是当前 case workspace 内相对路径。
- [ ] 需要目录能力的 drafting agent 在 `allowed_tools` 中显式加入 `mkdir` / `list_directory`。

**Verification:**

- [ ] `conda run -n autoGLM pytest tests/test_draft_workspace.py tests/test_file_tool_policy.py tests/test_langchain_agent_runner.py`
- [ ] `conda run -n autoGLM python -m compileall app tests scripts`

**Dependencies:** Task 2.

**Files likely touched:**

- `app/tools/draft_workspace.py`
- `app/tools/subagents/file_tools.py`
- `app/tools/subagents/agent_runner.py`
- `app/tools/subagents/file_policy.py`
- `app/nodes/drafting_research.py`
- `app/nodes/drafting_content.py`
- `tests/test_draft_workspace.py`
- `tests/test_file_tool_policy.py`
- `tests/test_langchain_agent_runner.py`

**Estimated scope:** Medium.

---

## Task 5: 改造 skill list/load

**Description:** 更新 skill registry 为真实文档和 description，LangChain 新流程通过 `list_skills()` 查看可用 skill，再用 `load_skill(name)` 精确加载，避免模型猜旧名称。

**Acceptance criteria:**

- [ ] registry 使用真实文档：`patent_guide`、`mermaid_flowchart`、`mermaid_sequence_diagram`。
- [ ] registry 每项包含 `description`。
- [ ] `SkillLoaderTool.run({"action": "list"})` 只返回 `name + description`，不返回正文。
- [ ] `SkillLoaderTool.run({"action": "load", "name": name})` 只接受 registry 中存在的精确 name。
- [ ] 未知 name、路径穿越、旧猜测名称安全失败。
- [ ] `build_react_tool_adapters()` 暴露 `list_skills()`、`load_skill(name: str)`。
- [ ] 新 drafting allowed tools 使用 `list_skills`、`load_skill`，不再依赖 `skill_loader`。
- [ ] 可短期保留内部 `skill_loader` 兼容旧 registry/测试，但新流程不引导使用它。

**Verification:**

- [ ] `conda run -n autoGLM pytest tests/test_skill_loader.py tests/test_new_native_tools.py`
- [ ] `conda run -n autoGLM pytest tests/test_langchain_agent_runner.py tests/test_drafting_content_nodes.py`
- [ ] `conda run -n autoGLM python -m compileall app tests scripts`

**Dependencies:** Task 4.

**Files likely touched:**

- `app/tools/skill_loader.py`
- `app/tools/subagents/file_tools.py`
- `app/tools/subagents/agent_runner.py`
- `app/orchestrator/tool_registry.py`
- `app/nodes/drafting_content.py`
- `app/tools/subagents/__init__.py`
- `tests/test_skill_loader.py`
- `tests/test_new_native_tools.py`
- `tests/test_langchain_agent_runner.py`

**Estimated scope:** Medium.

---

## Checkpoint: Agent tools stability

- [ ] file tools 支持读、写、建目录、列目录且均受 policy 约束。
- [ ] skill list/load 新流程通过测试。
- [ ] 旧 `skill_loader` 失败的现有回归已按新 registry 或兼容策略修复。
- [ ] 相关测试与 compileall 通过。

---

## Task 6: 接入 LangChain todo middleware

**Description:** 修正 todo prompt 的工具名和状态枚举，并在 `LangChainAgentRunner` 中接入 LangChain 官方 todo middleware；导入失败时安全降级。

**Acceptance criteria:**

- [ ] `app/prompts/todo_prompt.py` 不再出现 `write_todos`。
- [ ] todo 状态统一为 `pending`、`in_progress`、`done`。
- [ ] 删除“已完成”作为状态枚举的表述。
- [ ] `LangChainAgentRunner` 增加 `_todo_middleware()` 封装官方 todo middleware。
- [ ] `create_agent(..., middleware=[trace_middleware, todo_middleware])`。
- [ ] todo middleware 导入失败时记录 warning/trace，并只保留 trace middleware。
- [ ] 不自研 todo 判定、拦截或门禁逻辑。
- [ ] `app/tools/todo.py` 不作为本次 LangChain todo 机制核心依赖。

**Verification:**

- [ ] `conda run -n autoGLM pytest tests/test_todo_tool.py tests/test_langchain_agent_runner.py`
- [ ] `conda run -n autoGLM python -m compileall app tests scripts`

**Dependencies:** Task 5.

**Files likely touched:**

- `app/prompts/todo_prompt.py`
- `app/tools/subagents/agent_runner.py`
- `tests/test_todo_tool.py`
- `tests/test_langchain_agent_runner.py`

**Estimated scope:** Small.

---

## Task 7: 全量验证与收尾

**Description:** 运行本需求指定的分阶段测试、全量 pytest 和 compileall，修复回归问题，确认 diff 只包含本需求相关改动。

**Acceptance criteria:**

- [ ] 分阶段验证命令全部通过。
- [ ] `conda run -n autoGLM pytest` 通过。
- [ ] `conda run -n autoGLM python -m compileall app tests scripts` 通过。
- [ ] diff 不包含无关改动、临时文件、密钥或调试代码。
- [ ] 每个完成阶段都有独立 commit。

**Verification:**

- [ ] `conda run -n autoGLM pytest tests/test_case_service.py`
- [ ] `conda run -n autoGLM pytest tests/test_agent_api.py tests/test_attachment_upload.py tests/test_attachment_inject.py`
- [ ] `conda run -n autoGLM pytest tests/test_draft_workspace.py tests/test_file_tool_policy.py tests/test_langchain_agent_runner.py`
- [ ] `conda run -n autoGLM pytest tests/test_skill_loader.py tests/test_todo_tool.py`
- [ ] `conda run -n autoGLM pytest`
- [ ] `conda run -n autoGLM python -m compileall app tests scripts`
- [ ] `git status --short`

**Dependencies:** Task 6.

**Files likely touched:**

- Test files only if regressions require test alignment.
- Implementation files only for regression fixes tied to prior tasks.

**Estimated scope:** Small.

---

## Final Checkpoint

- [ ] 创建案件、上传附件、运行 Agent、目录工具、skill list/load、todo middleware 全链路验收标准满足。
- [ ] 全量测试与编译通过。
- [ ] 工作区干净或仅包含用户明确保留的计划文件。
- [ ] 准备交付人工 review。

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| 旧测试依赖无 `case_id` 调用 `/agent` | Medium | 按 SPEC 更新测试先创建 case，不放宽生产逻辑。 |
| `DraftWorkspaceTool` 新 `workspace_name` 破坏旧 `project_id` 行为 | High | 明确保留默认 `<draft_workspace_dir>/temp_{project_id}`，新增测试覆盖兼容。 |
| 附件跨 case 校验泄露存在性 | High | 不匹配统一返回 `attachment_not_found`。 |
| 目录枚举递归返回过多内容 | Medium | `list_directory` 只返回直接子项，递归仍用旧 list 或后续专门设计。 |
| LangChain todo middleware 导出路径不稳定 | Medium | 封装导入失败降级，记录 warning/trace，不阻断 agent。 |
| skill 旧名称测试与新 registry 冲突 | Medium | 更新测试断言新真实名称；必要时保留内部兼容但不进入新流程。 |

## Parallelization Opportunities

- Task 3（附件绑定）和 Task 4（目录工具）都依赖 Task 2，但彼此大体独立，可在 Task 2 完成后并行探索。
- Task 5 依赖 Task 4 的 allowed tools 语义，需后置。
- Task 6 只影响 runner middleware 与 prompt，可在 Task 5 稳定后独立完成。

## Open Questions

- 无。用户已确认：本 SPEC 仅覆盖当前范围；`/agent` 无 `case_id` 必须拒绝；当前规划后不自动实现；允许更新旧测试以匹配新的案件生命周期约束。
