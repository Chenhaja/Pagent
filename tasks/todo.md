# R11 patent_drafting Todo

## Phase 0 — 删除旧 claim 流程

- [x] 新增 `tests/test_claim_code_removed.py`。
  - 验收：测试覆盖旧 intent 不可路由、旧 workflow 不存在、旧模块无 import 残留。
  - 验证：`conda run -n autoGLM pytest tests/test_claim_code_removed.py`
- [x] 删除旧 claim nodes / skills / services。
  - 验收：旧 `claim_generation` / `claim_revision` 执行入口不存在。
  - 验证：旧代码删除守卫测试与 compileall。
- [x] 清理 `workflow_defs` 中旧 claim workflow 注册。
  - 验收：registry 不再包含 `claim_generation` / `claim_revision`。
  - 验证：`conda run -n autoGLM pytest tests/test_workflow_registry.py tests/test_claim_code_removed.py`
- [x] 清理 dispatch 中旧 claim 分支。
  - 验收：`AgentDispatchService` 不再 import/use `WorkflowService`、`RevisionService` 或旧 claim workflow。
  - 验证：`conda run -n autoGLM pytest tests/test_agent_dispatch_service.py tests/test_claim_code_removed.py`
- [x] 清理 intent router / prompts / schemas 中旧 claim intent。
  - 验收：旧 claim intent 不可分类或执行。
  - 验证：`conda run -n autoGLM pytest tests/test_intent_router_node.py tests/test_claim_code_removed.py`
- [x] 删除或迁移旧 claim 测试。
  - 验收：pytest 收集不引用已删除模块。
  - 验证：`conda run -n autoGLM pytest tests/test_claim_code_removed.py`
- [x] 运行 P0 验证命令。
  - 验收：P0 目标测试和编译通过。
  - 验证：`conda run -n autoGLM pytest tests/test_claim_code_removed.py && conda run -n autoGLM python -m compileall app tests`

## Phase 1 — 配置与 WorkflowState

- [x] 更新 `app/core/config.py`。
  - 验收：新增 drafting 系统级配置、默认值、`PAGENT_*` 环境变量读取。
  - 验证：`conda run -n autoGLM pytest tests/test_core_config_logging.py`
- [x] 更新 `to_public_dict()`。
  - 验收：非敏感 drafting 配置进入公开配置；敏感项不暴露。
  - 验证：配置测试。
- [x] 更新 `app/models/schemas.py`。
  - 验收：`WorkflowState` 新增 `input_points_md`、`prior_art_md`、`outline_md`、`abstract_md`、`claims_md`、`description_md`、`figures_md`、`complete_patent_md`、`drafting_incomplete`。
  - 验证：`conda run -n autoGLM pytest tests/test_workflow_state.py`
- [x] 更新配置与 state 测试。
  - 验收：默认值、环境变量覆盖、公开配置、state 默认初始化均被覆盖。
  - 验证：`conda run -n autoGLM pytest tests/test_core_config_logging.py tests/test_workflow_state.py`
- [x] 运行 P1 验证命令。
  - 验收：P1 目标测试和编译通过。
  - 验证：`conda run -n autoGLM pytest tests/test_core_config_logging.py tests/test_workflow_state.py && conda run -n autoGLM python -m compileall app tests`

## Phase 2 — native tools

- [x] 新增 `app/tools/draft_workspace.py`。
  - 验收：支持 artifact 读写，key/path 安全，不允许目录穿越。
  - 验证：`conda run -n autoGLM pytest tests/test_new_native_tools.py`
- [x] 新增 `app/tools/skill_loader.py`。
  - 验收：按白名单加载 drafting 所需 skill/template，不读取任意路径。
  - 验证：native tool 测试。
- [x] 新增 `app/tools/patent_search.py`。
  - 验收：默认 skipped/fake；联网受配置门控；异常安全降级。
  - 验证：native tool 测试；联网测试单独标记 `network`。
- [x] 注册 `ToolRegistry`。
  - 验收：三个 native tools 可通过稳定工具名调用。
  - 验证：`conda run -n autoGLM pytest tests/test_agentic_tools.py tests/test_new_native_tools.py`
- [x] 新增 `tests/test_new_native_tools.py`。
  - 验收：覆盖离线可测、路径安全、联网门控、异常降级。
  - 验证：`conda run -n autoGLM pytest tests/test_new_native_tools.py`
- [x] 运行 P2 验证命令。
  - 验收：P2 目标测试和编译通过。
  - 验证：`conda run -n autoGLM pytest tests/test_new_native_tools.py tests/test_agentic_tools.py && conda run -n autoGLM python -m compileall app tests`

## Phase 3 — subagent-as-tool

- [x] 新增 `app/tools/subagents/`。
  - 验收：目录下包含统一子代理工具接口与注册入口。
  - 验证：`conda run -n autoGLM pytest tests/test_subagent_tools.py`
- [x] 实现 8 个子代理工具。
  - 验收：每个子代理统一返回 Markdown + `artifact_key` + `done`。
  - 验证：subagent 工具测试。
- [x] 实现子代理 prompt。
  - 验收：prompt 集中维护，覆盖任务目标、上下文/判定规则、角色、受众、样例、输出格式。
  - 验证：prompt 结构测试或 review。
- [x] 限制子代理只按 workspace key 读取正文。
  - 验收：工具参数不接收长正文；正文通过 `draft_workspace` 读取。
  - 验证：subagent 工具测试。
- [x] 新增 `tests/test_subagent_tools.py`。
  - 验收：覆盖成功、失败、artifact 写入、`done` 状态和参数安全。
  - 验证：`conda run -n autoGLM pytest tests/test_subagent_tools.py`
- [x] 运行 P3 验证命令。
  - 验收：P3 目标测试和编译通过。
  - 验证：`conda run -n autoGLM pytest tests/test_subagent_tools.py && conda run -n autoGLM python -m compileall app tests`

## Phase 4 — drafting_leader

- [x] 新增 `app/prompts/patent_drafting_sop.py`。
  - 验收：SOP prompt 集中维护，明确步骤顺序和输出约束。
  - 验证：leader 测试或 prompt review。
- [x] 新增 `app/nodes/drafting_leader.py`。
  - 验收：复用 `QANode` bounded ReAct 模式，接入 `BoundedReActLoop`、`ReActBudget`、`ToolRegistry`。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_leader.py`
- [x] 实现工具白名单。
  - 验收：leader 只能调用 drafting 允许的 native tools 与 subagent tools。
  - 验证：leader 测试。
- [x] 实现 SOP 顺序控制。
  - 验收：输入整理、现有技术、提纲、摘要、权利要求、说明书、附图说明、完整文书整合顺序可测。
  - 验证：leader 测试。
- [x] 实现预算与 incomplete 兜底。
  - 验收：预算耗尽或子代理未完成时设置 `drafting_incomplete=True`。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_leader.py tests/test_react_policy.py`
- [x] 实现 trace 脱敏。
  - 验收：trace 只含工具名、artifact key、长度、状态、错误摘要，不含正文。
  - 验证：leader 测试或安全测试。
- [x] 新增 `tests/test_drafting_leader.py`。
  - 验收：覆盖调用顺序、工具白名单、预算命中、trace 脱敏、state 字段写入。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_leader.py`
- [x] 运行 P4 验证命令。
  - 验收：P4 目标测试和编译通过。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_leader.py tests/test_agentic_loop.py tests/test_react_policy.py && conda run -n autoGLM python -m compileall app tests`

## Phase 5 — workflow / intent / dispatch / API

- [x] 更新 intent schema/router/prompt。
  - 验收：新增 `patent_drafting` intent；旧 claim intent 不再可路由。
  - 验证：`conda run -n autoGLM pytest tests/test_intent_router_node.py`
- [x] 更新 workflow registry。
  - 验收：新增 `patent_drafting` workflow；删除旧 claim workflow。
  - 验证：`conda run -n autoGLM pytest tests/test_workflow_registry.py`
- [x] 更新 `AgentDispatchService`。
  - 验收：新增 `patent_drafting` dispatch；删除旧 claim 分支；未人审 `complete_patent_md` 不写长期记忆。
  - 验证：`conda run -n autoGLM pytest tests/test_agent_dispatch_service.py`
- [x] 更新 API 兼容字段。
  - 验收：API 可返回 drafting Markdown 产物；不恢复旧 claim workflow。
  - 验证：`conda run -n autoGLM pytest tests/test_agent_api.py`
- [x] 新增 E2E 测试。
  - 验收：`patent_drafting` 从请求到 workflow 输出完整 Markdown 产物。
  - 验证：`conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py`
- [x] 验证附件接入仍复用 R10 链路。
  - 验收：`WorkflowState.documents` 被 drafting 消费；上传/解析链路无重复实现。
  - 验证：`conda run -n autoGLM pytest tests/test_attachment_inject.py`
- [x] 运行 P5 验证命令。
  - 验收：P5 目标测试和编译通过。
  - 验证：`conda run -n autoGLM pytest tests/test_workflow_registry.py tests/test_intent_router_node.py tests/test_agent_dispatch_service.py && conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py tests/test_agent_api.py tests/test_attachment_inject.py && conda run -n autoGLM python -m compileall app tests`

## Phase 6 — 回归与收尾

- [x] 验证完整 Markdown 输出。
  - 验收：摘要、权利要求、说明书、附图说明、完整文书字段齐全。
  - 验证：`conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py`
- [x] 运行安全合规与附件回归。
  - 验收：防注入、附件抽取、附件注入测试通过。
  - 验证：`conda run -n autoGLM pytest tests/test_security_compliance.py tests/test_attachment_extract.py tests/test_attachment_inject.py`
- [x] 检查 trace/log 脱敏。
  - 验收：trace/log 不含附件正文、完整专利正文、API Key 或隐私内容。
  - 验证：安全测试或 caplog/trace 断言。
- [x] 检查网络测试标记。
  - 验收：`patent_search` 默认离线；联网测试单独标记 `network`。
  - 验证：native tool 测试与测试标记 review。
- [x] 运行全量 pytest。
  - 验收：全量测试通过。
  - 验证：`conda run -n autoGLM pytest`
- [x] 运行 compileall。
  - 验收：`app` 和 `tests` 编译通过。
  - 验证：`conda run -n autoGLM python -m compileall app tests`
- [x] 检查无无关改动。
  - 验收：diff 仅包含 R11 相关改动，无密钥、临时文件、调试代码。
  - 验证：`git status` / `git diff`
