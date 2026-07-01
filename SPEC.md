# 会话记忆注入 QA 回答规格说明

## 1. Objective

### 目标

本规格目标是让专利 QA 回答模型真正具备会话记忆：在 `PatentQASkill` 调用 LLM 时，将 `state.dialog_context["history"]` 展开为原生 `user` / `assistant` 消息，插入 system 之后、本轮任务与数据块之前；本轮检索结果、权利要求和当前问题仍保留在 `<data>` 数据块中，继续保持指令与外部数据分离。

完成标准：

- `AgentDispatchService._inject_session_context` 既有行为不变，继续把 `session_store.build_context(session_id)` 的结果写入 `state.dialog_context["history"]` 与 `state.dialog_context["session_summary"]`。
- `QueryRewriteNode` 既有 history 消费逻辑不变，继续用于当前问题指代消解 / 改写。
- `QANode.run` 构造 `SkillContext.state_snapshot` 时注入 `history`，来源为 `state.dialog_context.get("history") or []`。
- `PatentQASkill.run` 组装 LLM messages 时使用 `[system] + history 原生消息 + [task, user_data]`。
- history 中 `role="assistant"` 的 turn 映射为 `LLMMessage(role="assistant")`，其他有效 turn 映射为 `LLMMessage(role="user")`。
- 空 history / 无 session / NullSessionStore 时，messages 自动退回 `[system, task, user_data]` 三条，不改变现有 QA 行为。
- `build_patent_qa_user_prompt(question, retrieval_results, claims_draft)` 签名与职责不变，只承载本轮当前问题、检索结果、权利要求，不包含历史。
- system prompt 增加约束：历史仅用于理解本轮指代与延续，答复依据仍必须来自本轮 `<data>` 中的 retrieval_results / 权利要求 / 用户问题，不得把历史内容当作已证实事实或来源。
- `qa_completed` trace data 增加 `history_msg_count`，用于验证历史消息实际进入 QA 回答链路。
- 结构化输出契约不变，仍通过 `output_schema=PATENT_QA_OUTPUT_SCHEMA` 与 `PatentQAResult.model_validate` 验证。

### 目标用户

- 专利 QA 终端用户：可以自然追问“再详细点”“把上一条用通俗话讲”“继续说明上一点”。
- QA 节点与 workflow：在保持检索证据边界的同时获得多轮对话上下文。
- 开发与测试人员：可以通过 fake LLM 捕获 messages、trace 和 basis 行为，稳定验收会话记忆是否注入。

### 非目标

- 不做结构化 `qa_result` / basis / provenance 回写 session。
- 不改 session 存储后端，不引入 Redis 或新数据库。
- 不做语义历史召回、跨会话 case memory 或长期用户画像。
- 不改检索、ReAct 主循环、意图路由或 query rewrite 的现有职责。
- 不把检索原文、法条、专利文本等外部不可信内容改为原生消息；这些内容仍必须留在 `<data>` 数据块内。
- 不新增 LLMClient 接口或改造 OpenAI-compatible client，复用现有 `LLMClient.generate(messages=...)` 能力。

---

## 2. Commands

项目使用 conda 环境 `autoGLM`。所有 Python / pytest / 脚本命令必须通过 `conda run -n autoGLM` 执行，不能依赖 `conda activate` 的跨命令状态。

```bash
# QA 节点记忆注入测试
conda run -n autoGLM pytest tests/test_qa_node.py

# PatentQASkill 消息组装与数据块隔离测试
conda run -n autoGLM pytest tests/test_patent_qa_skill.py

# agentic QA 集成回归测试
conda run -n autoGLM pytest tests/test_agentic_qa_integration.py

# 本需求目标测试
conda run -n autoGLM pytest tests/test_qa_node.py tests/test_patent_qa_skill.py tests/test_agentic_qa_integration.py

# 全量测试
conda run -n autoGLM pytest

# 编译检查
conda run -n autoGLM python -m compileall app tests scripts
```

验收命令：

```bash
conda run -n autoGLM pytest tests/test_qa_node.py tests/test_patent_qa_skill.py tests/test_agentic_qa_integration.py
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests scripts
```

约束：

- 默认测试必须使用 fake / stub LLM 捕获 `generate(messages=...)`，不调用真实付费模型。
- 默认测试不触网、不连接真实外部检索源。
- 不新增依赖；如确需新增，必须先确认并同步 `requirements.txt`。
- 不执行破坏性 git / 文件命令。

---

## 3. Project Structure

目标结构：

```text
pagent/
  app/
    nodes/
      qa.py                         # QANode.run 注入 history 到 SkillContext.state_snapshot
    skills/
      patent_qa.py                  # PatentQASkill.run 展开 history 为原生 messages
    prompts/
      patent_qa.py                  # QA system prompt 增加历史仅作上下文、不作依据约束
    tools/
      llm.py                        # 复用 LLMClient.generate(messages=..., output_schema=...)
    services/
      agent_dispatch.py             # 保持 _inject_session_context 既有行为
    session/
      store.py                      # 保持 build_context / load_history 既有行为
  tests/
    test_qa_node.py                 # 验证 SkillContext 含 history、空会话回归、qa_completed trace
    test_patent_qa_skill.py         # 验证 messages 顺序、角色映射、数据块隔离、结构化输出
    test_agentic_qa_integration.py  # 验证多轮追问与 basis 不把历史当来源
  SPEC.md                           # 本规格
```

### 3.1 QANode 契约

`QANode.run` 构造 `SkillContext` 时必须包含：

```python
context = SkillContext(
    task_type="patent_qa",
    state_snapshot={
        "question": question,
        "claims_draft": state.claims_draft,
        "validation_report": state.validation_report,
        "retrieval_results": evidence,
        "history": state.dialog_context.get("history") or [],
    },
)
```

要求：

- `history` 只来自 `state.dialog_context`，不直接读取 session store，避免重复职责。
- `session_summary` 不单独注入；摘要如存在，应已由 `build_context` 合成为 history 首个 `[早期对话摘要]` turn。
- 空 history 使用空列表，不能传 `None` 导致 skill 层分支复杂化。
- QA 完成 trace `qa_completed` 的 data 增加 `history_msg_count`，值为实际传入 skill / 注入 messages 的有效历史消息数。

### 3.2 PatentQASkill 消息组装契约

`PatentQASkill.run` 必须按以下顺序组装 messages：

```python
history = context.state_snapshot.get("history") or []
prompt_layers = self._build_prompt_layers(context)

messages = [LLMMessage(role="system", content=prompt_layers["system"])]
messages.extend(_build_history_messages(history))
messages.extend([
    LLMMessage(role="user", content=prompt_layers["task"]),
    LLMMessage(role="user", content=prompt_layers["user_data"]),
])

response = self.llm_client.generate(
    messages=messages,
    output_schema=PATENT_QA_OUTPUT_SCHEMA,
    trace_context=trace_context,
)
```

历史 turn 映射规则：

- `turn.get("role") == "assistant"` 映射为 `LLMMessage(role="assistant")`。
- 其他非空内容 turn 默认映射为 `LLMMessage(role="user")`。
- `content` 使用 `str(turn.get("content", ""))`，去除纯空白内容。
- 不在注入端重复脱敏，沿用入库时 `redact_sensitive_text` 的结果。
- 摘要 turn 不去重；如果 `build_context` 已把摘要作为首个 `[早期对话摘要]` assistant turn，skill 层按普通 assistant 历史消息处理。

### 3.3 Prompt 契约

`build_patent_qa_user_prompt(question, retrieval_results, claims_draft)` 保持原签名和职责：

- 当前问题进入本轮 `<data>`。
- 本轮 retrieval_results 进入本轮 `<data>`。
- 本轮 claims_draft 进入本轮 `<data>`。
- history 不得进入 `user_data` 的 `<data>`。

QA system prompt 必须补充安全约束：

```text
历史消息是既往对话上下文，仅用于理解本轮指代与延续；答复依据仍必须来自本轮 <data> 的 retrieval_results / 权利要求 / 用户问题，不得把历史内容当作已证实的事实或来源。
```

Prompt 仍需满足项目六要素规范：

- 任务目标：回答专利 QA 问题，并输出结构化 JSON。
- 上下文 / 判定规则：区分历史上下文与本轮证据，basis 只能来自真实 evidence / 权利要求 / 用户问题。
- 角色：熟悉专利业务的专家。
- 受众：专利 QA 用户与结构化结果解析器。
- 样例：保留或补充结构化输出示例。
- 输出格式：仅输出 `PatentQAResult` JSON，字段类型、必填项和不确定性标注清晰。

### 3.4 数据契约

`SkillContext.state_snapshot` 新增可选字段：

```json
{
  "history": [
    {"role": "user", "content": "上一轮用户问题"},
    {"role": "assistant", "content": "上一轮模型回答"}
  ]
}
```

要求：

- `history` 是 list；空会话为 `[]`。
- turn 至少消费 `role` 与 `content` 字段；其他字段如 timestamp / metadata 可忽略。
- 不要求新增 Pydantic model 或 schema，保持局部改动。
- 不改变 `PatentQAResult` schema。

### 3.5 Trace 契约

复用现有 `session_memory_loaded`：

```json
{
  "event": "session_memory_loaded",
  "history_count": 4,
  "has_summary": true
}
```

扩展 `qa_completed`：

```json
{
  "event": "qa_completed",
  "history_msg_count": 4
}
```

约束：

- trace 不记录完整历史正文、完整检索正文、完整权利要求草稿或密钥。
- `history_msg_count` 统计实际注入的非空历史消息数。
- 无 session / 空 history 时 `history_msg_count=0`。

---

## 4. Code Style

### 基本原则

- 最小化、局部化改动，优先修改 `QANode.run`、`PatentQASkill.run`、QA prompt 与相关测试。
- 复用现有 `LLMClient.generate`、`LLMMessage`、`SkillContext`，不要新增 LLM 接口或大型抽象。
- 复用现有 `build_patent_qa_user_prompt`，不要把 history 塞入数据块。
- 公共函数、公共方法、公共类必须添加中文 Google 风格 docstring，包含 Args / Returns / Raises（如有）。
- 简单私有 helper 可使用一行中文概述；只在历史角色映射、安全边界等不直观处加行内注释。
- 日志 / trace 使用稳定英文事件名，message 可用中文。
- 不记录完整历史、完整 query、完整 retrieval_results、完整 claims_draft 或密钥。

### Prompt 风格

- prompt 继续集中在 `app/prompts/` 模块，不内联散落在业务逻辑中。
- 运行时变量使用具名占位符，不通过随意字符串拼接混合指令和数据。
- 外部 / 用户 / 检索数据必须包裹在 `<data>...</data>` 或等价分隔符内，并声明数据区不作为指令。
- 历史消息作为原生 messages 注入，但 system 必须声明历史只作上下文、不作证据来源。
- 输出强制 JSON，保留 `output_schema=PATENT_QA_OUTPUT_SCHEMA`。
- 专利域默认约束必须保留：禁止臆造、不确定显式标注、使用规范术语。

### 错误处理与兜底

- history 缺失、为空、turn 结构不完整时不得中断 QA。
- 单条 history content 为空白时跳过。
- 非 `assistant` role 统一按 `user` 处理，避免未知角色传给底层 LLM provider。
- LLM 结构化输出失败时沿用现有错误路径，不为 history 注入新增复杂降级。
- 如未来遇到 token 超预算，再评估单轮 content 截断；本阶段不新增截断配置。

---

## 5. Testing Strategy

### QANode 测试

必须覆盖：

- 有 `state.dialog_context["history"]` 时，`SkillContext.state_snapshot["history"]` 与输入 history 一致。
- 无 `dialog_context` / 无 `history` / history 为 `None` 时，传入 skill 的 history 为 `[]`。
- `session_summary` 不作为单独字段传入 QA skill；摘要只通过 history 中的合成 turn 出现。
- `qa_completed` trace 包含 `history_msg_count`。
- 空会话路径 QA 行为与改动前一致。

### PatentQASkill 测试

必须覆盖：

- fake `LLMClient` 捕获 `generate(messages=...)`，messages 顺序为 `system → 历史 user/assistant → task → user_data`。
- store / context 中 assistant turn 映射为 `role="assistant"`。
- store / context 中 user turn 映射为 `role="user"`。
- 未知 role 的非空 turn 映射为 `role="user"`。
- 空白 content turn 被跳过，不进入 messages。
- `user_data` 的 `<data>` 只包含当前问题、retrieval_results、claims_draft，不包含历史内容。
- history 为空时 messages 恢复三条：`system → task → user_data`。
- 多轮 messages 下仍返回合法 `PatentQAResult`，`model_validate` 通过。

### 集成 / 回归测试

必须覆盖：

- 有 session、有历史时，`generate` 收到 `[system] + history + [task, user_data]`。
- 摘要作为首个 `[早期对话摘要]` assistant 消息出现且仅一次。
- 第 2 轮问“把上一条用更通俗的话讲一遍”时，fake LLM 能看到上一轮 assistant 内容。
- basis 仍只回链真实 evidence / 权利要求 / 用户问题，不把历史文本当作来源。
- 无 session_id / NullSessionStore 时，messages 退回三条且 QA 输出与基线一致。

### 验收口径

- `conda run -n autoGLM pytest tests/test_qa_node.py tests/test_patent_qa_skill.py tests/test_agentic_qa_integration.py` 通过。
- `conda run -n autoGLM pytest` 通过。
- `conda run -n autoGLM python -m compileall app tests scripts` 通过。
- 默认测试不触网、不调用真实付费 LLM。
- `user_data` 中搜索不到历史 turn 的独有文本。
- trace 中有 `history_msg_count` 且不包含完整历史正文。

---

## 6. Boundaries

### Always do

- 始终把外部检索原文、法条、专利文本、权利要求草稿等不可信 / 证据数据留在 `<data>` 数据块内。
- 始终把历史消息作为上下文而非证据来源使用。
- 始终在 system prompt 中声明历史不作为已证实事实或来源。
- 始终让 basis 只回链本轮真实 evidence / 权利要求 / 用户问题。
- 始终保留空会话三消息回归路径。
- 始终使用 fake / stub LLM 做默认测试。
- 始终使用 `conda run -n autoGLM` 执行 Python、pytest 和脚本命令。
- 始终避免新增单 Node 临时配置。

### Ask first

- 是否调用真实 LLM 做人工多轮验收。
- 是否允许向云模型发送完整历史对话与敏感专利材料。
- 是否新增 history content 截断策略或 token 预算配置。
- 是否调整 session history_window / memory_history_window。
- 是否新增依赖或改造 session store。
- 是否改变 `PatentQAResult` schema 或 basis 结构。

### Never do

- 不把 history 拼进 `build_patent_qa_user_prompt` 的 `<data>`。
- 不把 retrieval_results / 外部专利文本改为原生 assistant / user 历史消息。
- 不把历史内容作为 basis 来源、证据 provenance 或已证实事实。
- 不伪造检索来源、法条、专利号、法律状态或官费信息。
- 不在 trace / 日志记录完整历史、完整检索正文、完整权利要求草稿或密钥。
- 不在默认测试中触网、下载模型或调用真实付费服务。
- 不为本需求引入跨会话语义召回、长期记忆或新存储后端。

---

## 7. Functional Acceptance Checklist

- [ ] `QANode.run` 将 `state.dialog_context.get("history") or []` 注入 `SkillContext.state_snapshot`。
- [ ] `PatentQASkill.run` 将 history 展开为原生 `LLMMessage`。
- [ ] messages 顺序为 `[system] + history + [task, user_data]`。
- [ ] assistant turn 映射为 `role="assistant"`。
- [ ] user / 未知 role turn 映射为 `role="user"`。
- [ ] 空白 content turn 被跳过。
- [ ] history 为空时 messages 退回 `[system, task, user_data]`。
- [ ] `build_patent_qa_user_prompt` 签名不变。
- [ ] `user_data` 不包含历史内容。
- [ ] retrieval_results / claims_draft / 当前问题 仍在 `<data>` 中。
- [ ] system prompt 增加“历史仅供理解、不作依据”约束。
- [ ] `qa_completed` trace 增加 `history_msg_count`。
- [ ] trace 不记录完整历史正文。
- [ ] 摘要作为 `[早期对话摘要]` assistant turn 出现且不重复。
- [ ] basis 不把历史内容当作来源。
- [ ] 多轮追问 fake/integration 测试能证明 QA LLM 看到上一轮回答。
- [ ] 无 session / NullSessionStore 回归不破坏。
- [ ] 结构化输出仍通过 `PatentQAResult.model_validate`。
- [ ] `conda run -n autoGLM pytest tests/test_qa_node.py tests/test_patent_qa_skill.py tests/test_agentic_qa_integration.py` 通过。
- [ ] `conda run -n autoGLM pytest` 通过。
- [ ] `conda run -n autoGLM python -m compileall app tests scripts` 通过。

---

## 8. Implementation Order

1. 更新 `PatentQASkill` 测试：先用 fake LLM 捕获 messages，写出历史消息顺序、角色映射、数据块隔离、空 history 回归断言。
2. 更新 `QANode` 测试：断言 `SkillContext.state_snapshot` 包含 `history`，并断言 `qa_completed.history_msg_count`。
3. 修改 `QANode.run`：从 `state.dialog_context` 注入 `history`。
4. 修改 QA system prompt：增加历史仅作上下文、不作依据的约束句。
5. 修改 `PatentQASkill.run`：将 history 展开为原生 `LLMMessage` 并插入 messages。
6. 补充 / 更新集成测试：覆盖多轮追问、摘要 turn、basis 不回链历史、无 session 回归。
7. 运行目标测试、全量 pytest 和 compileall。
