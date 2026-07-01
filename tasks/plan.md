# 会话记忆注入 QA 回答实施计划

## 背景

本需求要补齐 QA 会话记忆链路：`AgentDispatchService._inject_session_context` 已在 query rewrite 前把 `session_store.build_context(session_id)` 写入 `state.dialog_context["history"]` / `session_summary`，`QueryRewriteNode` 已消费 history 做问题改写，但 `QANode.run` 没有把 history 传给 `PatentQASkill`，最终回答模型只看到 system、task、本轮 `<data>`，看不到上一轮用户问题和模型回答。

目标是采用 chat-native 方案：history 以原生 `user` / `assistant` messages 注入 QA LLM；本轮检索结果、权利要求草稿和当前问题仍留在 `<data>` 数据块，basis 仍只回链本轮真实 evidence / 权利要求 / 用户问题。

本计划只拆解实现路径与验收任务；实现阶段再修改业务代码。

## 当前代码基线

- `app/services/agent_dispatch_service.py`：`_inject_session_context` 已写入 `state.dialog_context["history"]`、`state.dialog_context["session_summary"]`，并记录 `session_memory_loaded` trace。
- `app/memory/session_store.py`：`SqliteSessionStore.build_context` 会在存在 summary 时把 `{"role": "assistant", "content": "[早期对话摘要] ..."}` 作为 history 首条；`NullSessionStore.build_context` 返回空 history。
- `app/nodes/qa.py`：`QANode.run` 当前只把 `question`、`claims_draft`、`validation_report`、`retrieval_results` 放入 `SkillContext.state_snapshot`，未传 history；`qa_completed` trace 未包含 `history_msg_count`。
- `app/skills/patent_qa.py`：`PatentQASkill.run` 固定发送三条 messages：system、task、user_data；未读取 history。
- `app/prompts/patent_qa.py`：`build_patent_qa_user_prompt` 已将 question / retrieval_results / claims_draft 包入 `<data>`；system prompt 尚未明确“历史仅作上下文、不作证据来源”。
- `tests/test_patent_qa_skill.py`：已有 RecordingLLMClient，可扩展断言 messages 顺序、角色映射、数据块隔离。
- `tests/test_qa_node.py`：已有 RecordingQASkill 和 trace 断言，可扩展断言 QANode 传递 history 和 `history_msg_count`。
- `tests/test_agentic_qa_integration.py`：目前覆盖 agentic QA 检索主路径，可新增轻量集成断言空会话 / 多轮 history 传递。

## 依赖图

```text
SPEC.md
  -> session context 基线
      -> app/services/agent_dispatch_service.py       # 保持现状，不改职责
      -> app/memory/session_store.py                  # 保持 summary 合成 history 的现状

  -> QANode history 传递
      -> app/nodes/qa.py                              # state.dialog_context.history -> SkillContext.state_snapshot.history
      -> tests/test_qa_node.py                        # history 传递、空 history、qa_completed.history_msg_count

  -> PatentQASkill chat-native messages
      -> app/skills/patent_qa.py                      # [system] + history + [task, user_data]
      -> app/tools/llm.py                             # 复用 LLMMessage / LLMClient.generate
      -> tests/test_patent_qa_skill.py                # 顺序、角色、空白跳过、结构化输出

  -> Prompt 安全边界
      -> app/prompts/patent_qa.py                     # system prompt 增加历史不作依据约束
      -> tests/test_patent_qa_skill.py                # prompt 包含约束，user_data 不含 history

  -> Integration / regression
      -> tests/test_agentic_qa_integration.py         # 多轮追问可见上一轮回答、basis 不回链历史、无 session 三消息回归

  -> final verification
      -> tests/test_qa_node.py
      -> tests/test_patent_qa_skill.py
      -> tests/test_agentic_qa_integration.py
      -> pytest / compileall
```

## 垂直切片原则

每个任务都交付一条可验证路径，而不是只改一层：

1. 先用测试锁定 skill 端消息契约：fake LLM 捕获 messages，证明 history 能成为原生消息且 user_data 不含历史。
2. 再打通 QANode 到 skill 的最短链路：`state.dialog_context.history` 进入 `SkillContext.state_snapshot.history`，trace 可观测数量。
3. 再补 prompt 安全约束：历史只作上下文，本轮 `<data>` 才是证据来源。
4. 最后做集成回归：多轮追问可见上一轮回答，basis 不把历史当来源，无 session 保持三消息路径。

---

## Phase 0 — 口径确认与测试切入点

### 目标

确认实现不扩大范围，只按 SPEC 做 chat-native 注入，不改 session store、LLMClient、检索或 ReAct 主循环。

### 实施要点

- 明确 `AgentDispatchService._inject_session_context` 和 `SqliteSessionStore.build_context` 作为已完成前置链路，不在本需求改造。
- 摘要 turn 由 `build_context` 注入 history，skill 层不去重、不额外读取 `session_summary`。
- 注入端不重复脱敏，沿用入库时脱敏。
- 本阶段不新增 history 截断配置；如遇 token 预算问题另起需求。

### 验收标准

- plan / todo 中体现上述边界。
- 后续任务不包含 session store 结构改造、跨会话召回或新配置。

### Checkpoint 0

确认计划后进入测试优先实现。

---

## Phase 1 — PatentQASkill 消息契约测试与实现

### 目标

让 `PatentQASkill.run` 在有 history 时发送 `[system] + history 原生消息 + [task, user_data]`；无 history 时保持原三条 messages。

### 涉及文件

- `app/skills/patent_qa.py`
- `tests/test_patent_qa_skill.py`

### 实施要点

- 先扩展 / 新增 tests：使用 `RecordingLLMClient` 捕获 `generate(messages=...)`。
- 新增私有 helper（建议）构造 history messages：
  - assistant turn -> `LLMMessage(role="assistant")`。
  - user / 未知 role turn -> `LLMMessage(role="user")`。
  - `content` 转 `str` 并跳过纯空白。
- `PatentQASkill.run` 保持现有 prompt layer / safety_policy / examples / output_schema 行为。
- messages 顺序：system、有效 history、task、user_data。
- 不改变 `PatentQAResult` schema 和 `LLMClient.generate` 调用接口。

### 验收标准

- 有 history 时 messages roles 为如 `system,user,assistant,user,user,user`（取决于 history 条数，末两条为 task / user_data）。
- assistant role 正确映射为 `assistant`。
- 未知 role 正确降级为 `user`。
- 空白 content 不进入 messages。
- history 为空 / 缺失时 messages 仍为 `system,user,user`。
- 多轮 messages 下仍能 `PatentQAResult.model_validate` 通过。

### 验证命令

```bash
conda run -n autoGLM pytest tests/test_patent_qa_skill.py
```

### Checkpoint 1

skill 端 messages 契约通过后，再接 QANode 上游 history。

---

## Phase 2 — 数据块隔离与 prompt 安全边界

### 目标

确保 history 不进入本轮 `<data>`，并在 system prompt 明确历史只用于理解上下文、不作为依据来源。

### 涉及文件

- `app/prompts/patent_qa.py`
- `tests/test_patent_qa_skill.py`

### 实施要点

- 修改 `PATENT_QA_SYSTEM_PROMPT`，增加约束句：历史消息是既往对话上下文，仅用于理解本轮指代与延续；答复依据仍必须来自本轮 `<data>` 的 retrieval_results / 权利要求 / 用户问题，不得把历史内容当作已证实事实或来源。
- 保持 `build_patent_qa_user_prompt(question, retrieval_results, claims_draft)` 签名不变。
- 增加测试：history 独有文本不出现在 `messages[-1].content` 的 `<data>` 中。
- 增加测试：system prompt 包含“历史”“上下文”“不得把历史内容当作已证实”或等价关键约束。

### 验收标准

- `user_data` 只包含当前 question、retrieval_results、claims_draft。
- history 独有文本只出现在 history messages 中，不出现在 `user_data`。
- prompt 仍保留项目六要素、数据区不作为指令、仅输出 JSON、专利域约束。

### 验证命令

```bash
conda run -n autoGLM pytest tests/test_patent_qa_skill.py
```

### Checkpoint 2

确认数据分离和 prompt 约束后，再做 QANode trace 和上下游集成。

---

## Phase 3 — QANode 注入 history 与 trace 计数

### 目标

让 `QANode.run` 从 `state.dialog_context` 读取 history，放入 `SkillContext.state_snapshot`，并在 `qa_completed` trace 中记录 `history_msg_count`。

### 涉及文件

- `app/nodes/qa.py`
- `tests/test_qa_node.py`

### 实施要点

- 在构造 `SkillContext` 时增加：`"history": state.dialog_context.get("history") or []`。
- 建议在 `QANode.run` 内先计算 `history = state.dialog_context.get("history") or []`，供 state_snapshot 和 trace 复用。
- `history_msg_count` 应统计有效历史消息数。为与 skill 实际注入一致，可采用与 skill helper 相同规则或一个小的本地计数 helper：content 转 str 后非空白才计数。
- 更新现有 `qa_completed` trace 断言，加入 `history_msg_count`。
- 新增测试：有 history 时 `RecordingQASkill.contexts[0].state_snapshot["history"]` 与输入一致。
- 新增测试：无 history / history 为 None 时传 `[]`，trace 为 0。
- 不传 `session_summary` 到 skill。

### 验收标准

- `SkillContext.state_snapshot["history"]` 来源于 `state.dialog_context["history"]`。
- 空 history 路径不报错。
- `qa_completed.data.history_msg_count` 正确，且不记录完整历史正文。
- 既有 evidence、basis、法规 stale、依据不足 warning 测试继续通过。

### 验证命令

```bash
conda run -n autoGLM pytest tests/test_qa_node.py
```

### Checkpoint 3

QANode 传递和 trace 可观测通过后，再做端到端回归。

---

## Phase 4 — 集成场景与 basis 回归

### 目标

用轻量集成测试证明多轮追问时 QA LLM 能看到上一轮 assistant 内容，同时 basis 不把历史当来源；无 session / NullSessionStore 等价空 history 时保持三消息路径。

### 涉及文件

- `tests/test_agentic_qa_integration.py`
- 可选：`tests/test_qa_node.py` / `tests/test_patent_qa_skill.py` 补充更合适的断言

### 实施要点

- 增加一个 recording skill 或真实 `PatentQASkill + RecordingLLMClient` 场景，构造 `WorkflowState.dialog_context["history"]`：
  - user: “上一轮问题”
  - assistant: “上一轮回答独有文本”
  - 当前问题: “把上一条用更通俗的话讲一遍”
- 断言 fake LLM 捕获 messages 中包含上一轮 assistant 内容，且 role 为 assistant。
- 构造 retrieval evidence，断言输出 basis 仍来自 evidence locator/source，而不是历史文本。
- 增加无 history 场景，断言 messages 仍是三条。
- 如摘要场景可低成本覆盖：history 首条为 `[早期对话摘要] ...` assistant，断言出现一次。

### 验收标准

- 多轮追问场景 fake LLM 能看到上一轮 assistant 内容。
- `user_data` 中没有上一轮回答独有文本。
- basis 只引用真实 evidence / 权利要求 / 用户问题，不引用历史独有文本。
- 摘要 turn 如存在，以 assistant 消息出现且不重复。
- 无 session / 空 history 行为不变。

### 验证命令

```bash
conda run -n autoGLM pytest tests/test_agentic_qa_integration.py tests/test_patent_qa_skill.py tests/test_qa_node.py
```

### Checkpoint 4

集成和回归通过后进入总体验收。

---

## Phase 5 — 总体验收与提交准备

### 目标

运行 SPEC 要求的目标测试、全量测试和编译检查，确认无触网、无真实 LLM、无 schema 破坏。

### 涉及文件

- `app/nodes/qa.py`
- `app/skills/patent_qa.py`
- `app/prompts/patent_qa.py`
- `tests/test_qa_node.py`
- `tests/test_patent_qa_skill.py`
- `tests/test_agentic_qa_integration.py`
- `tasks/plan.md`
- `tasks/todo.md`

### 实施要点

- 先跑目标测试，修复与本需求相关失败。
- 再跑全量 pytest，确认旧流程不回归。
- 最后跑 compileall。
- 检查 `git diff`，确认未夹带无关改动。
- 按项目规范：完成这个可独立验证的小功能后再提交；提交前只 stage 相关文件。

### 验收标准

- 目标测试通过。
- 全量测试通过。
- compileall 通过。
- 默认测试未调用真实 LLM / 外部服务。
- `build_patent_qa_user_prompt` 签名未变。
- `PatentQAResult` schema 未变。

### 验证命令

```bash
conda run -n autoGLM pytest tests/test_qa_node.py tests/test_patent_qa_skill.py tests/test_agentic_qa_integration.py
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests scripts
```

## 风险与控制

- **风险：历史被误当证据来源。** 控制：system prompt 明确历史只作上下文；测试断言 basis 不含历史独有文本。
- **风险：历史进入 `<data>` 混淆不可信检索材料边界。** 控制：`build_patent_qa_user_prompt` 签名不变；测试断言 user_data 不含 history。
- **风险：未知 role 传给底层 provider 导致报错。** 控制：非 assistant 统一映射为 user。
- **风险：空 / 畸形 history 破坏 QA。** 控制：空白 content 跳过；缺 history 用 `[]`。
- **风险：trace 泄露历史正文。** 控制：只记录 `history_msg_count`，测试不检查 / 不输出完整历史。
- **风险：长历史 token 增加。** 控制：本阶段复用 history_window，不新增配置；超预算另起截断需求。

## 总体验证计划

```bash
conda run -n autoGLM pytest tests/test_patent_qa_skill.py
conda run -n autoGLM pytest tests/test_qa_node.py
conda run -n autoGLM pytest tests/test_agentic_qa_integration.py tests/test_patent_qa_skill.py tests/test_qa_node.py
conda run -n autoGLM pytest tests/test_qa_node.py tests/test_patent_qa_skill.py tests/test_agentic_qa_integration.py
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests scripts
```
