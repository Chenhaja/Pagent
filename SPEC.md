# 案件级 Workspace 生命周期与 Agent 工具稳定性改造规格

## 1. Objective

### 1.1 背景

当前 Agent 文书生成链路存在三类稳定性问题：

1. 文件工具能力不足，缺少目录创建与目录枚举能力，且 workspace 生命周期不清晰。
2. skill 通过粗粒度工具名加载，Agent 可能猜错 skill 名称或加载过时文档。
3. todo 机制依赖 prompt 约束，容易被模型跳过或使用旧工具名/旧状态枚举。

本次改造目标是在不引入 UI、不重做工具系统的前提下，新增案件级 workspace 生命周期：调用方必须先通过后端 API 创建 `case_id`，同时绑定 `.draft_workspace/tmp_{uuid}`；同一 `case_id` 下多个 `session_id`、附件和 Agent 文件操作复用同一个 workspace，并继续由 file policy 做路径约束。

### 1.2 目标用户

- 后端 API 调用方：需要明确创建案件并在后续 `/agent`、附件上传中携带 `case_id`。
- Patent drafting workflow 维护者：需要让同一案件多会话复用同一文书 workspace。
- Agent/subagent 工具维护者：需要更稳定的 file tools、skill tools 和 todo middleware 接入方式。
- 测试与安全维护者：需要验证跨案件隔离、路径约束、skill 精确加载和 todo middleware 降级行为。

### 1.3 目标

- 新增案件生命周期服务与 `POST /agent/cases` API。
- `/agent` 必须携带已创建的 `case_id`；缺失或不存在时拒绝，不隐式创建案件。
- `WorkflowState` 传递 `case_id`、`workspace_id`，用于 trace 和工作流上下文，不保存绝对路径。
- 同一 `case_id` 下不同 `session_id` 共享同一 `DraftWorkspaceTool` workspace；session memory 仍按 `session_id` 独立。
- 附件上传必须绑定 `case_id`，附件 metadata 记录案件归属，并将抽取正文导入案件 workspace。
- 附件读取按 `case_id` 校验归属；跨案件访问返回 `attachment_not_found`，不泄露附件存在性。
- 扩展 `DraftWorkspaceTool` 和 LangChain file tools，支持 `mkdir`、`list_directory`，并继续受 file policy 约束。
- skill 工具改为 `list_skills()` -> `load_skill(name)`，只接受 registry 中真实精确名称。
- 接入 LangChain `create_agent` 官方 todo middleware；修正 todo prompt 中旧工具名和旧状态枚举。
- 保留安全降级：todo middleware 导入失败时记录 warning/trace，仅禁用 todo middleware，不让所有 Agent 不可用。

### 1.4 验收标准

- `POST /agent/cases` 返回 `case_id`、`workspace_id`、相对 `workspace_path`，不暴露绝对路径。
- 案件元数据保存到 `.draft_workspace/cases/{case_id}.json`；workspace 目录为 `.draft_workspace/tmp_{workspace_id}`。
- `/agent` 缺少或传入不存在 `case_id` 时返回明确错误。
- 同一 `case_id` 多个 `session_id` 复用同一个 `.draft_workspace/tmp_{workspace_id}`。
- `/agent` 响应透传 `case_id`、`workspace_id`。
- `/agent/attachments` 必填 `case_id`；metadata 记录 `case_id` 和 `workspace_artifact_key`。
- 附件抽取正文写入当前案件 workspace，例如 `01_input/attachments/{attachment_id}/extracted.md` 或 `.txt`。
- 跨 case 加载附件被拒绝并返回 `attachment_not_found`。
- `mkdir`、`list_directory` 成功时只作用于当前案件 workspace；越权路径被 file policy 拒绝。
- skill list 只返回 `name + description`；load 只接受 registry 中存在的精确 name。
- 新流程 allowed tools 使用 `list_skills`、`load_skill`，不再引导 Agent 猜 `skill_loader(skill_name)`。
- `app/prompts/todo_prompt.py` 不再出现 `write_todos`；状态统一为 `pending`、`in_progress`、`done`。
- `LangChainAgentRunner` 调用 `create_agent` 时传入 trace middleware 和 todo middleware；todo middleware 导入失败时安全降级。

### 1.5 非目标

- 不引入 UI。
- 不重做整体工具系统或 file policy 架构。
- 不改变 session memory 的隔离维度；会话历史仍按 `session_id` 独立。
- 不允许 `/agent` 无 `case_id` 时隐式创建案件。
- 不放宽路径安全策略，不允许绝对路径、`..`、路径逃逸或非法字符。
- 不新增依赖；如确需新增依赖，必须先确认并同步 `requirements.txt`。
- 不执行 `git push`、`git reset --hard`、强制推送等危险操作，除非用户明确要求。

---

## 2. Commands

所有 Python、pytest、脚本命令必须使用 conda 环境 `autoGLM`，每条命令独立带 `conda run -n autoGLM`。

### 2.1 分阶段验证命令

```bash
conda run -n autoGLM pytest tests/test_case_service.py
conda run -n autoGLM pytest tests/test_agent_api.py tests/test_attachment_upload.py tests/test_attachment_inject.py
conda run -n autoGLM pytest tests/test_draft_workspace.py tests/test_file_tool_policy.py tests/test_langchain_agent_runner.py
conda run -n autoGLM pytest tests/test_skill_loader.py tests/test_todo_tool.py
conda run -n autoGLM python -m compileall app tests scripts
```

### 2.2 全量回归

```bash
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests scripts
```

### 2.3 约束

- 默认测试不得触网，不得调用真实外部 LLM。
- 每完成一个可独立验证阶段，按项目规范单独 commit；只 `git add` 本阶段相关文件。
- 允许更新旧测试以匹配新的案件生命周期约束：旧 `/agent` 测试应先创建 `case_id`，而不是放宽生产逻辑。

---

## 3. Project Structure

本次改造主要涉及以下模块：

```text
pagent/
  app/
    api/
      routes.py                 # /agent/cases、/agent、/agent/attachments API
      schemas.py                # AgentRequest、CaseCreateResponse、附件响应 schema
    models/
      schemas.py                # WorkflowState case_id/workspace_id
    services/
      case_service.py           # 案件元数据与 workspace 生命周期
      agent_dispatch_service.py # case 校验、workspace 注入、响应透传
      attachment_service.py     # 附件绑定 case 与导入 workspace
    tools/
      draft_workspace.py        # workspace_name、mkdir、list_directory
      skill_loader.py           # list/load skill registry
      subagents/
        file_tools.py           # LangChain mkdir/list_directory/list_skills/load_skill
        file_policy.py          # 路径规范化与读写约束，小改仅限暴露问题
        agent_runner.py         # file policy prompt、todo middleware、tool 白名单
        __init__.py             # 如有 allowed tools 导出需同步更新
    orchestrator/
      tool_registry.py          # native skill registry 兼容与工具注册
    nodes/
      drafting_research.py      # 复用案件 workspace，allowed_tools 更新
      drafting_content.py       # 复用案件 workspace，allowed_tools 更新
    prompts/
      todo_prompt.py            # LangChain todo middleware prompt
  tests/
    test_case_service.py
    test_agent_api.py
    test_attachment_upload.py
    test_attachment_inject.py
    test_draft_workspace.py
    test_file_tool_policy.py
    test_langchain_agent_runner.py
    test_skill_loader.py
    test_todo_tool.py
```

### 3.1 数据关系

```text
case_id
  -> .draft_workspace/cases/{case_id}.json
      -> workspace_id
      -> workspace_path = .draft_workspace/tmp_{workspace_id}
  -> DraftWorkspaceTool(workspace_name="tmp_{workspace_id}")
  -> attachments metadata.case_id
  -> AgentDispatchService state.case_id/state.workspace_id
```

### 3.2 生命周期

1. 调用 `POST /agent/cases` 创建案件。
2. 调用方在 `/agent` 和 `/agent/attachments` 中携带 `case_id`。
3. `AgentDispatchService` 校验 case 存在，并构造当前案件 workspace。
4. 附件上传保存原始文件到 attachment storage，同时将抽取正文写入案件 workspace。
5. Patent drafting 节点和 LangChain file tools 只访问当前案件 workspace 内的 artifact 相对路径。

---

## 4. Code Style

遵循项目现有规范：

- 优先最小化、局部化改动。
- 复用现有 helper，不随意引入新抽象。
- 注释、docstring、日志 message 沿用中文风格。
- 新增公开函数、方法、类必须有中文 Google 风格 docstring，包含 Args、Returns、Raises（如有）。
- 只在“为什么这样做”不直观处加行内注释。
- 不硬编码密钥、凭证、API Key。
- 数据库访问使用参数化查询；本次无数据库 schema 改造。
- 不用不可信输入拼接 shell 命令或 SQL。
- 路径处理必须使用现有安全函数和 file policy，不绕过 `_is_safe_key()`、`_is_safe_prefix()`、`_path_for()`。
- API 只返回展示用相对路径，不返回 workspace 绝对路径。
- 删除旧兼容壳时必须确认无引用；短期可保留内部 `skill_loader` 兼容旧测试和非 LangChain registry，但新流程不得依赖它。

---

## 5. Testing Strategy

### 5.1 TDD 要求

每个阶段先补或改测试，再实现最小代码通过测试。

### 5.2 单元与集成测试重点

- Case service：创建、读取、未知 case、metadata 文件与 workspace 目录。
- Agent API：创建 case、`/agent` 必填 `case_id`、未知 case 错误、响应透传。
- Dispatch：同一 case 多 session 复用同一 workspace；session memory 不串扰。
- Attachment：上传必填 `case_id`；metadata 记录 case；导入 workspace；跨 case 读取拒绝。
- Draft workspace：`workspace_name` 兼容旧 `project_id`；`mkdir` 幂等；`list_directory` 只列直接子项；内存模式目录结构可推导。
- File tools/policy：`read_file`、`list_directory` 用 read policy；`write_file`、`mkdir` 用 write policy；越权路径不访问 workspace。
- Skill loader：`list` 只返回 name/description；`load` 精确加载真实 registry；未知 skill 拒绝。
- Agent runner：allowed tools 暴露 `list_skills`、`load_skill`、`mkdir`、`list_directory`；file policy prompt 说明当前 case workspace 相对路径；middleware 包含 trace + todo。
- Todo prompt：不出现 `write_todos`；状态枚举只包含 `pending`、`in_progress`、`done`。

### 5.3 回归策略

- 允许更新旧测试，让 `/agent` 测试先创建 `case_id`。
- 不允许通过让生产代码隐式创建 case 来兼容旧测试。
- 每个阶段运行阶段相关测试和 compileall。
- 全部阶段完成后运行全量 pytest 和 compileall。

---

## 6. Boundaries

### 6.1 Always do

- `/agent` 与附件上传都显式使用已创建 `case_id`。
- 所有 workspace 文件操作都使用当前 case workspace 内的 artifact 相对路径。
- 所有文件访问先走 file policy，再调用 `DraftWorkspaceTool.run()`。
- 跨案件附件访问返回 `attachment_not_found`，不泄露附件是否存在。
- 每个可独立验证阶段单独测试、单独 commit。
- 所有命令使用 `conda run -n autoGLM`。

### 6.2 Ask first

- 新增外部依赖。
- 改变 API 生命周期约定，例如允许无 `case_id` 自动创建案件。
- 引入 UI 或重做工具系统。
- 删除大范围旧兼容能力。
- 执行 push、reset、force push、删除分支等高风险 git 操作。

### 6.3 Never do

- 不在 `/agent` dispatch 内隐式创建 case。
- 不返回 workspace 绝对路径。
- 不绕过 `_is_safe_key()`、`_is_safe_prefix()`、`_path_for()` 或 file policy。
- 不允许绝对路径、`..`、路径逃逸、非法字符通过文件工具。
- 不把 session memory 改成按 case 混合存储。
- 不记录密钥、完整 API Key、隐私数据、长原文/译文或绝对敏感路径到日志/trace。

---

## 7. Implementation Slices

### Slice 1: 案件生命周期 API

- 新增 `CaseService`、`POST /agent/cases`、`CaseCreateResponse`。
- `AgentRequest` 增加必填 `case_id`。
- `WorkflowState` 增加 `case_id`、`workspace_id`。
- `/agent` 校验 case 存在并透传 case/workspace 标识。

### Slice 2: 案件 workspace 复用

- `DraftWorkspaceTool` 支持 `workspace_name="tmp_{uuid}"`。
- `AgentDispatchService` 通过 `CaseService.get_workspace(case_id)` 构造同一案件 workspace。
- Patent drafting 节点复用同一个 workspace；不同 `session_id` 不影响 workspace 选择。

### Slice 3: 附件绑定案件

- `/agent/attachments` 增加必填 `case_id` 表单字段。
- `AttachmentService.save_upload(..., case_id=case_id)` 校验 case 并写 metadata。
- 抽取正文导入案件 workspace。
- `load_document(attachment_id, case_id=case_id)` 校验归属。
- Dispatch 注入附件时使用当前 `case_id`。

### Slice 4: 目录工具与 file policy

- `DraftWorkspaceTool` 新增 `mkdir`、`list_directory`。
- `build_file_tools()` 新增 `mkdir(path)`、`list_directory(path="")`。
- runner file policy prompt 同步说明 read/write tools 和当前 case workspace 相对路径。
- 需要目录能力的 drafting agent allowed tools 显式加入目录工具。

### Slice 5: Skill list/load

- skill registry 更新为真实文档：`patent_guide`、`mermaid_flowchart`、`mermaid_sequence_diagram`。
- registry 增加 description。
- `SkillLoaderTool.run()` 支持 `action="list"` 与 `action="load"`。
- LangChain adapters 暴露 `list_skills()`、`load_skill(name)`。
- 新流程 allowed tools 使用 `list_skills`、`load_skill`。

### Slice 6: Todo middleware

- 修正 `app/prompts/todo_prompt.py` 的工具名和状态枚举。
- `LangChainAgentRunner` 封装 `_todo_middleware()`。
- `create_agent(..., middleware=[trace_middleware, todo_middleware])`。
- 导入失败时记录 warning/trace 并降级为只使用 trace middleware。

### Slice 7: 全量验证

- 运行指定分阶段测试、全量 pytest、compileall。
- 修复回归问题。
- 确认 diff 只包含本需求相关改动。
