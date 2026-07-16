# 专利文书 workflow create_agent 拓扑改造 Todo

## 任务清单

- [ ] [Phase 0] 创建 `tasks/plan.md` 和 `tasks/todo.md`。
  - 依赖：无。
  - 验收：文档包含目标拓扑、边界、任务依赖、验收标准、验证命令、阶段检查点。
  - 验证：`git status`。

- [ ] [Phase 1] 新增通用 drafting create_agent runner，并补 runner 单测。
  - 依赖：Phase 0。
  - 验收：默认 LLM 不可用时不触网并写 fallback artifact；fake create_agent 可验证 middleware；工具只能读写 allowlist artifact；NodeResult / ToolObservation 不返回完整正文。
  - 验证：`conda run -n autoGLM pytest tests/test_input_parser_agent.py tests/test_workflow_trace_events.py && conda run -n autoGLM python -m compileall app tests`。

- [ ] [Phase 2] 改造 `DraftingPatentSearchNode`，补 `prior_art_analysis.json` 兼容 artifact。
  - 依赖：Phase 1。
  - 验收：默认路径使用 create_agent runner；可注入 fake runner；检索失败安全降级；`prior_art_md` 对应 artifact 不缺失；trace 不泄露长正文或敏感字段。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_research_nodes.py tests/test_workflow_trace_events.py && conda run -n autoGLM python -m compileall app tests`。

- [ ] [Phase 3a] 改造 `DraftingGenerateOutlineNode`。
  - 依赖：Phase 2。
  - 验收：默认使用 `OUTLINE_GENERATOR_PROMPT + create_agent`；不依赖旧 drawing/style guide；fallback 写 `03_outline/patent_outline.md`。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_content_nodes.py`。

- [ ] [Phase 3b] 新增 `DraftingClaimsWriterNode`。
  - 依赖：Phase 3a。
  - 验收：默认使用 `CLAIMS_WRITER_PROMPT + create_agent`；fallback 写 `04_content/claims.md`；output 只含短字段。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_content_nodes.py`。

- [ ] [Phase 3c] 新增 `DraftingDescriptionWriterNode`，内部 Part1/Part2。
  - 依赖：Phase 3b。
  - 验收：单 workflow 节点内部串行调用 Part1/Part2；写 part artifacts 和 `04_content/description.md`；两段 trace 汇总同一 NodeResult。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_content_nodes.py`。

- [ ] [Phase 3d] 新增 `DraftingDiagramGeneratorNode`。
  - 依赖：Phase 3c。
  - 验收：默认使用 `DIAGRAM_GENERATOR_PROMPT + create_agent`；fallback 写 `04_content/figures.md`。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_content_nodes.py`。

- [ ] [Phase 3e] 新增 `DraftingAbstractWriterNode`。
  - 依赖：Phase 3d。
  - 验收：默认使用 `ABSTRACT_WRITER_PROMPT + create_agent`；fallback 写 `04_content/abstract.md`。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_content_nodes.py tests/test_patent_drafting_workflow.py`。

- [ ] [Phase 4] 改造 `DraftingMergeDocumentNode` 为 agent merger + fallback。
  - 依赖：Phase 3e。
  - 验收：默认使用 `MARKDOWN_MERGER_PROMPT + create_agent`；fallback 可离线拼接完整文书；输出 `complete_patent_key` 稳定；不改变 finalize API 字段语义。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_content_nodes.py tests/test_patent_drafting_workflow.py tests/test_workflow_trace_events.py && conda run -n autoGLM python -m compileall app tests`。

- [ ] [Phase 5] 更新 `workflow_defs.py` 和 `AgentDispatchService` 注册。
  - 依赖：Phase 4。
  - 验收：`patent_drafting` 返回新节点列表；主流程不包含旧 gate/guidance/sections/review；服务能按新节点跑完整流程；API 返回字段兼容；QA workflow 不受影响。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_workflow_defs.py tests/test_workflow_registry.py tests/test_patent_drafting_workflow.py tests/test_agent_api.py tests/test_orchestrator_engine.py && conda run -n autoGLM python -m compileall app tests`。

- [ ] [Phase 6] 补 trace / security / offline 回归。
  - 依赖：Phase 5。
  - 验收：新增 create_agent 节点 trace 进入 `WorkflowState.trace`；trace 不含 prompt 全文、长正文、完整工具输入输出、本地路径、API key、token、secret、password；默认测试不触网；没有新增依赖。
  - 验证：`conda run -n autoGLM pytest tests/test_input_parser_agent.py tests/test_workflow_trace_events.py tests/test_drafting_research_nodes.py tests/test_drafting_content_nodes.py tests/test_security_compliance.py && conda run -n autoGLM python -m compileall app tests`。

- [ ] [Phase 7] 全量 pytest、compileall、清理未用引用。
  - 依赖：Phase 6。
  - 验收：`conda run -n autoGLM pytest` 通过；`conda run -n autoGLM python -m compileall app tests` 通过；diff 只包含本需求相关改动。
  - 验证：`git status && git diff`。

## 当前检查点

- Phase 0 完成后：只改执行文档。
- Phase 1 完成后：通用 runner 独立可验证。
- Phase 2 完成后：research path 独立通过。
- Phase 3 完成后：内容 artifacts 全部由显式节点生成。
- Phase 4 完成后：merge agent 与 fallback 都可用。
- Phase 5 完成后：主 workflow 切换完成并通过端到端测试。
- Phase 6 完成后：trace 和安全回归通过。
- Phase 7 完成后：全量回归通过，等待是否 push 的明确指令。
