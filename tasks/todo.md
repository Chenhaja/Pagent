# 通用 LangChain Agent 与 Policy File Tools Todo

## 任务清单

- [ ] [Phase 0] 完成规划文档。
  - 依赖：`SPEC.md` 已确认。
  - 验收：`tasks/plan.md`、`tasks/todo.md` 覆盖目标、依赖图、垂直切片、验收标准、验证命令、阶段检查点。
  - 验证：`git status`。

- [x] [Phase 1] 实现 `FileToolPolicy` 与 policy 单测。
  - 依赖：Phase 0。
  - 验收：支持 `readRoots`、`writeRoots`、`allowGlobs`、`denyGlobs`；默认拒绝未显式允许的读写；写权限不能由读权限推导；deny 优先；拒绝 `../`、绝对路径、`.env`、`secrets/`、`*.pem`、`*.key`。
  - 验证：`conda run -n autoGLM pytest tests/test_file_tool_policy.py && conda run -n autoGLM python -m compileall app tests`。

- [ ] [Phase 2] 实现通用 file tools 并接入 policy。
  - 依赖：Phase 1。
  - 验收：提供稳定工具名 `read_file`、`write_file`；工具执行前调用 policy；policy 拒绝时不访问 workspace；返回受控 JSON 错误且不泄露敏感路径细节。
  - 验证：`conda run -n autoGLM pytest tests/test_file_tool_policy.py tests/test_langchain_agent_runner.py && conda run -n autoGLM python -m compileall app tests`。

- [ ] [Phase 3] 实现通用 `LangChainAgentRunner`。
  - 依赖：Phase 2。
  - 验收：支持 node/agent/stage/prompt/allowed_tools/file_policy/output/fallback/settings/workspace/trace 参数；只把 `allowed_tools` 白名单工具传给 `create_agent`；middleware 上下文正确；LLM 不可用时 fallback 写目标 artifact；observation 不返回长正文。
  - 验证：`conda run -n autoGLM pytest tests/test_langchain_agent_runner.py tests/test_workflow_trace_events.py && conda run -n autoGLM python -m compileall app tests`。

- [ ] [Phase 4] 迁移 input parser 路径并删除 `LangChainInputParserAgent`。
  - 依赖：Phase 3。
  - 验收：`DraftingParseInputNode` 默认使用通用 runner；通过参数传入 `INPUT_PARSER_PROMPT`、`allowed_tools`、file policy；只读 `01_input/raw_document.md`、只写 `01_input/parsed_info.json`；fallback 仍写合法 JSON object；代码和测试不再依赖 `LangChainInputParserAgent`。
  - 验证：`conda run -n autoGLM pytest tests/test_input_parser_agent.py tests/test_drafting_research_nodes.py tests/test_workflow_trace_events.py && conda run -n autoGLM python -m compileall app tests`。

- [ ] [Phase 5] 迁移 drafting research/content 路径并删除 `LangChainDraftingAgent`。
  - 依赖：Phase 4。
  - 验收：`DraftingPatentSearchNode`、大纲、权利要求、说明书、附图、摘要、合并节点默认使用通用 runner；各 node 用参数传入 prompt、`allowed_tools`、file policy；只能读取声明输入 artifact、写声明输出 artifact；代码和测试不再依赖 `LangChainDraftingAgent`。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_agent.py tests/test_drafting_research_nodes.py tests/test_drafting_content_nodes.py tests/test_workflow_trace_events.py && conda run -n autoGLM python -m compileall app tests`。

- [ ] [Phase 6] 清理导出、旧引用与安全回归。
  - 依赖：Phase 5。
  - 验收：`app/tools/subagents/__init__.py` 导出更新；全仓代码无 `LangChainDraftingAgent` / `LangChainInputParserAgent` 可用引用；`allowed_tools` 未声明工具不会传给 `create_agent`；policy 默认拒绝和 deny 优先测试通过；trace/log 不含 prompt 全文、长正文、完整工具输入输出、本地敏感路径、API key、token、secret、password。
  - 验证：`conda run -n autoGLM pytest tests/test_file_tool_policy.py tests/test_langchain_agent_runner.py tests/test_input_parser_agent.py tests/test_drafting_agent.py tests/test_security_compliance.py tests/test_workflow_trace_events.py && conda run -n autoGLM python -m compileall app tests`。

- [ ] [Phase 7] 全量回归与提交准备。
  - 依赖：Phase 6。
  - 验收：`conda run -n autoGLM pytest` 通过；`conda run -n autoGLM python -m compileall app tests` 通过；diff 只包含本需求相关改动；无临时文件、密钥或无关改动。
  - 验证：`conda run -n autoGLM pytest && conda run -n autoGLM python -m compileall app tests && git status && git diff`。

## 当前检查点

- Phase 0 完成后：只改规划文档，等待用户审阅。
- Phase 1 完成后：policy 语义稳定，尚未接入工具执行。
- Phase 2 完成后：通用 file tools 可独立按 policy 读写 workspace。
- Phase 3 完成后：通用 runner 可独立把 wrapped tools 交给 `create_agent`。
- Phase 4 完成后：input parser 真实路径完成通用 runner 迁移。
- Phase 5 完成后：drafting 真实路径完成通用 runner 迁移，旧业务 Agent 类删除。
- Phase 6 完成后：旧引用、安全回归、trace 回归清理完成。
- Phase 7 完成后：全量回归通过，等待是否 commit / push 的明确指令。
