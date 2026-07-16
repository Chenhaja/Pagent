# 案件级 Workspace 生命周期与 Agent 工具稳定性改造 Todo

## 任务清单

- [x] [Task 1] 实现案件生命周期 API。
  - 依赖：`SPEC.md`。
  - 验收：新增 `CaseService`、`POST /agent/cases`、`AgentRequest.case_id`、`WorkflowState.case_id/workspace_id`，`/agent` 校验未知 case 并透传 case/workspace 标识。
  - 验证：`conda run -n autoGLM pytest tests/test_case_service.py tests/test_agent_api.py`；相关 dispatch/API/input/attachment/workflow 回归；`conda run -n autoGLM python -m compileall app tests scripts`。
  - 状态：已提交 `5e2a91f feat(agent): 新增案件生命周期 API`。

- [x] [Task 2] 复用案件 workspace。
  - 依赖：Task 1。
  - 验收：`DraftWorkspaceTool` 新增可选 `workspace_name` 且保留旧 `project_id` 行为；`AgentDispatchService` 通过 `CaseService.get_workspace(case_id)` 构造同案 workspace；patent drafting 节点复用同一 workspace；不同 `session_id` 仍只影响 session memory。
  - 验证：`conda run -n autoGLM pytest tests/test_case_service.py tests/test_agent_dispatch_service.py tests/test_patent_drafting_workflow.py`；`conda run -n autoGLM pytest tests/test_draft_workspace.py`；`conda run -n autoGLM python -m compileall app tests scripts`。

- [x] [Task 3] 绑定附件到案件并导入 workspace。
  - 依赖：Task 2。
  - 验收：`/agent/attachments` 必填 `case_id`；`AttachmentService.save_upload(..., case_id=case_id)` 校验 case；metadata 记录 `case_id`、`workspace_artifact_key`；抽取正文写入案件 workspace；`load_document(..., case_id=case_id)` 校验归属；跨 case 读取返回 `attachment_not_found`；dispatch 注入附件使用当前 `case_id`。
  - 验证：`conda run -n autoGLM pytest tests/test_attachment_upload.py tests/test_attachment_inject.py`；`conda run -n autoGLM pytest tests/test_agent_api.py tests/test_patent_drafting_workflow.py`；`conda run -n autoGLM python -m compileall app tests scripts`。

- [ ] [Checkpoint] Case workspace + attachments。
  - 依赖：Task 3。
  - 验收：`/agent/cases` -> `/agent/attachments` -> `/agent` 的同案流程可运行；同一 case 的附件正文和 agent artifacts 落在同一 workspace；不存在无 `case_id` 的生产入口兼容逻辑。
  - 验证：Task 2-3 相关测试和 compileall 通过。

- [x] [Task 4] 扩展目录工具与 file policy。
  - 依赖：Task 2。
  - 验收：`DraftWorkspaceTool` 支持 `mkdir`、`list_directory`；`list_directory` 只列直接子项；内存模式可推导目录；LangChain file tools 暴露 `mkdir`、`list_directory`；读类工具走 read policy，写类工具走 write policy；runner file policy prompt 说明当前 case workspace 相对路径；需要目录能力的 drafting agent 显式加入 allowed tools。
  - 验证：`conda run -n autoGLM pytest tests/test_draft_workspace.py tests/test_file_tool_policy.py tests/test_langchain_agent_runner.py`；`conda run -n autoGLM python -m compileall app tests scripts`。

- [x] [Task 5] 改造 skill list/load。
  - 依赖：Task 4。
  - 验收：registry 使用真实文档 `patent_guide`、`mermaid_flowchart`、`mermaid_sequence_diagram` 并包含 description；`action="list"` 只返回 `name + description`；`action="load"` 精确加载正文；未知 name/路径穿越/旧猜测名称安全失败；LangChain adapters 暴露 `list_skills()`、`load_skill(name)`；新 drafting allowed tools 使用 `list_skills`、`load_skill`。
  - 验证：`conda run -n autoGLM pytest tests/test_skill_loader.py tests/test_new_native_tools.py`；`conda run -n autoGLM pytest tests/test_langchain_agent_runner.py tests/test_drafting_content_nodes.py`；`conda run -n autoGLM python -m compileall app tests scripts`。

- [ ] [Checkpoint] Agent tools stability。
  - 依赖：Task 5。
  - 验收：file tools 支持读、写、建目录、列目录且均受 policy 约束；skill list/load 新流程通过测试；旧 `skill_loader` 失败的现有回归已按新 registry 或兼容策略修复。
  - 验证：Task 4-5 相关测试和 compileall 通过。

- [ ] [Task 6] 接入 LangChain todo middleware。
  - 依赖：Task 5。
  - 验收：`todo_prompt.py` 不再出现 `write_todos`；状态统一为 `pending`、`in_progress`、`done`；删除“已完成”作为状态枚举；`LangChainAgentRunner` 封装 `_todo_middleware()`；`create_agent` middleware 包含 trace + todo；导入失败记录 warning/trace 并只保留 trace middleware；不自研 todo 判定或门禁。
  - 验证：`conda run -n autoGLM pytest tests/test_todo_tool.py tests/test_langchain_agent_runner.py`；`conda run -n autoGLM python -m compileall app tests scripts`。

- [ ] [Task 7] 全量验证与收尾。
  - 依赖：Task 6。
  - 验收：分阶段验证命令全部通过；全量 pytest 通过；compileall 通过；diff 不包含无关改动、临时文件、密钥或调试代码；每个完成阶段都有独立 commit。
  - 验证：`conda run -n autoGLM pytest tests/test_case_service.py`；`conda run -n autoGLM pytest tests/test_agent_api.py tests/test_attachment_upload.py tests/test_attachment_inject.py`；`conda run -n autoGLM pytest tests/test_draft_workspace.py tests/test_file_tool_policy.py tests/test_langchain_agent_runner.py`；`conda run -n autoGLM pytest tests/test_skill_loader.py tests/test_todo_tool.py`；`conda run -n autoGLM pytest`；`conda run -n autoGLM python -m compileall app tests scripts`；`git status --short`。

## 当前检查点

- Task 1 已完成并提交。
- 下一步从 Task 2 开始：复用案件 workspace。
- 用户已确认当前 `/plan` 只生成/更新计划文件，不继续实现。
