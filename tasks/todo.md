# 会话记忆注入 QA 回答 Todo

## Phase 0 — 口径确认与测试切入点

- [ ] 确认本需求不改 session store / dispatch 注入链路。
  - 验收：`AgentDispatchService._inject_session_context` 和 `SqliteSessionStore.build_context` 保持职责不变。
  - 验证：代码 review 确认未修改 session 存储结构。
- [ ] 确认摘要只通过 history 首个 assistant turn 注入。
  - 验收：不把 `session_summary` 作为单独字段传给 `PatentQASkill`。
  - 验证：QANode 测试断言 state_snapshot 不依赖 `session_summary`。
- [ ] 确认本阶段不新增 history 截断配置。
  - 验收：无新增 `qa_*` / `history_*` 临时配置。
  - 验证：代码 review 和配置测试。

## Phase 1 — PatentQASkill 消息契约测试与实现

- [ ] 新增 PatentQASkill history messages 顺序测试。
  - 验收：fake LLM 捕获 messages，顺序为 `system → 历史 user/assistant → task → user_data`。
  - 验证：`conda run -n autoGLM pytest tests/test_patent_qa_skill.py`
- [ ] 新增 assistant turn 角色映射测试。
  - 验收：`{"role": "assistant"}` 映射为 `LLMMessage(role="assistant")`。
  - 验证：`conda run -n autoGLM pytest tests/test_patent_qa_skill.py`
- [ ] 新增 user / 未知 role 映射测试。
  - 验收：user 和未知 role 的非空 turn 均映射为 `LLMMessage(role="user")`。
  - 验证：`conda run -n autoGLM pytest tests/test_patent_qa_skill.py`
- [ ] 新增空白 content 跳过测试。
  - 验收：`""` / 纯空白 content 不进入 messages。
  - 验证：`conda run -n autoGLM pytest tests/test_patent_qa_skill.py`
- [ ] 新增空 history 三消息回归测试。
  - 验收：history 缺失或为空时 messages roles 为 `system,user,user`。
  - 验证：`conda run -n autoGLM pytest tests/test_patent_qa_skill.py`
- [ ] 实现 history 到原生 LLMMessage 的转换。
  - 验收：`PatentQASkill.run` 使用 `[system] + history_messages + [task, user_data]` 调用 `generate`。
  - 验证：`conda run -n autoGLM pytest tests/test_patent_qa_skill.py`
- [ ] 保持 PatentQASkill 结构化输出契约不变。
  - 验收：`output_schema=PATENT_QA_OUTPUT_SCHEMA` 仍传入，`PatentQAResult.model_validate` 仍执行。
  - 验证：现有 invalid output 测试继续通过。

## Phase 2 — 数据块隔离与 prompt 安全边界

- [ ] 新增 user_data 不含 history 测试。
  - 验收：history 独有文本不出现在 `messages[-1].content`。
  - 验证：`conda run -n autoGLM pytest tests/test_patent_qa_skill.py`
- [ ] 确认 `build_patent_qa_user_prompt` 签名不变。
  - 验收：仍为 `(question, retrieval_results, claims_draft)`。
  - 验证：现有 prompt 测试和代码 review。
- [ ] 更新 QA system prompt 历史安全约束。
  - 验收：prompt 明确历史仅用于理解本轮指代与延续，不作为已证实事实或来源。
  - 验证：prompt 测试断言包含关键约束文本。
- [ ] 保持 `<data>` 只承载本轮数据。
  - 验收：当前 question、retrieval_results、claims_draft 仍在 `<data>`；history 不在 `<data>`。
  - 验证：`conda run -n autoGLM pytest tests/test_patent_qa_skill.py`
- [ ] 确认 prompt 六要素和专利域约束未被破坏。
  - 验收：任务目标、上下文、角色、受众、样例、输出格式仍存在；禁止臆造和不确定标注仍存在。
  - 验证：prompt 测试 / review。

## Phase 3 — QANode 注入 history 与 trace 计数

- [ ] 新增 QANode 传递 history 测试。
  - 验收：`RecordingQASkill.contexts[0].state_snapshot["history"]` 等于 `state.dialog_context["history"]`。
  - 验证：`conda run -n autoGLM pytest tests/test_qa_node.py`
- [ ] 新增 QANode 空 history 测试。
  - 验收：无 `history` 或 `history=None` 时传给 skill 的 history 为 `[]`。
  - 验证：`conda run -n autoGLM pytest tests/test_qa_node.py`
- [ ] 修改 `QANode.run` 注入 history。
  - 验收：`SkillContext.state_snapshot` 包含 `"history": state.dialog_context.get("history") or []`。
  - 验证：`conda run -n autoGLM pytest tests/test_qa_node.py`
- [ ] 新增 `qa_completed.history_msg_count` trace 测试。
  - 验收：有有效历史消息时计数为有效非空 content 数；空 history 时为 0。
  - 验证：`conda run -n autoGLM pytest tests/test_qa_node.py`
- [ ] 修改 `qa_completed` trace 添加 `history_msg_count`。
  - 验收：trace data 包含 `basis_count`、`has_retrieval`、`evidence_versions`、`history_msg_count`。
  - 验证：`conda run -n autoGLM pytest tests/test_qa_node.py`
- [ ] 确认 trace 不记录完整历史正文。
  - 验收：`qa_completed` 只含计数字段，不含 history 文本。
  - 验证：QANode trace 断言 / review。
- [ ] 确认不单独传 `session_summary` 到 skill。
  - 验收：`state_snapshot` 不新增 `session_summary` 字段。
  - 验证：QANode 测试或代码 review。

## Phase 4 — 集成场景与 basis 回归

- [ ] 新增多轮追问可见上一轮 assistant 内容测试。
  - 验收：当前问题为“把上一条用更通俗的话讲一遍”时，fake LLM 捕获 messages 中有上一轮 assistant 内容。
  - 验证：`conda run -n autoGLM pytest tests/test_agentic_qa_integration.py`
- [ ] 新增摘要 turn 注入测试。
  - 验收：`[早期对话摘要]` 作为 assistant message 出现且仅一次。
  - 验证：`conda run -n autoGLM pytest tests/test_agentic_qa_integration.py tests/test_patent_qa_skill.py`
- [ ] 新增 basis 不引用历史测试。
  - 验收：输出 basis 来自真实 evidence locator/source 或用户问题，不包含历史独有文本。
  - 验证：`conda run -n autoGLM pytest tests/test_agentic_qa_integration.py`
- [ ] 新增无 session / 空 history 回归测试。
  - 验收：messages 退回三条，QA 结构化输出正常。
  - 验证：`conda run -n autoGLM pytest tests/test_agentic_qa_integration.py tests/test_patent_qa_skill.py`
- [ ] 确认 agentic 检索回归不破坏。
  - 验收：预算 guard、sufficient evidence、retrieval failure 等现有集成测试继续通过。
  - 验证：`conda run -n autoGLM pytest tests/test_agentic_qa_integration.py`

## Phase 5 — 总体验收与提交准备

- [ ] 运行目标测试。
  - 命令：`conda run -n autoGLM pytest tests/test_qa_node.py tests/test_patent_qa_skill.py tests/test_agentic_qa_integration.py`
  - 验收：全部通过。
- [ ] 运行全量测试。
  - 命令：`conda run -n autoGLM pytest`
  - 验收：全部通过。
- [ ] 运行编译检查。
  - 命令：`conda run -n autoGLM python -m compileall app tests scripts`
  - 验收：无语法错误。
- [ ] 确认默认测试不调用真实 LLM / 外部服务。
  - 验收：使用 fake / stub LLM，未访问 websearch、legal_status、official_fee 或付费模型。
  - 验证：测试实现 review。
- [ ] 检查无无关改动。
  - 验收：diff 只包含本需求相关代码、测试、tasks 文档。
  - 验证：`git diff`。
- [ ] 准备阶段性提交。
  - 验收：只 stage 本需求相关文件，提交信息使用 `<type>(scope): <summary>` 中文动词开头格式。
  - 验证：提交前 `git status`。
