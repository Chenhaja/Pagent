<aside>
 🎯

**一句话目标**：QA 就是专利领域多轮聊天——把 `state.dialog_context` 里的 `history` 以**原生 user/assistant 消息**注入 `PatentQASkill` 的 LLM 调用（本轮检索结果/权利要求仍留 `<data>` 数据块），让回答模型真正“有记忆”，支撑“再详细点”“把上一条用通俗话讲”这类追问。

</aside>

## 1. 背景与问题

当前会话记忆链路**读进来了，却没喂给回答模型**：

- `AgentDispatchService._inject_session_context` 在 query_rewrite 前调用 `session_store.build_context(session_id)`，已把结果写入 `state.dialog_context["history"]` 和 `state.dialog_context["session_summary"]`。
- 但只有 `QueryRewriteNode` 消费 `dialog_context["history"]`（做指代消解 / 改写问题）。
- `QANode.run` 构造 `SkillContext(state_snapshot={question, claims_draft, validation_report, retrieval_results})` 时**没有读取 history / session_summary**，`PatentQASkill._build_prompt_layers` 与 `build_patent_qa_user_prompt` 也只接收 `question / retrieval_results / claims_draft`。

**结果**：回答模型看不到既往对话内容。query_rewrite 只能把“当前问题”改写成自包含，但无法让模型看到“上一轮自己答了什么”，因此“基于上一条继续/改写/通俗化”这类多轮需求答不好。

### 为什么不和 query_rewrite 重复

query_rewrite 只重写**问题本身**（指代消解），不把**历史答案内容**交给回答模型。二者互补：改写解决“这一句在问什么”，记忆注入解决“结合之前说过的内容来答”。

## 2. 现状 vs 目标（chat-native）

| 环节                          | 现状                                                | 目标                                                |
| ----------------------------- | --------------------------------------------------- | --------------------------------------------------- |
| `_inject_session_context`     | 已写入 `dialog_context.history` / `session_summary` | 不变                                                |
| `QueryRewriteNode`            | 已用 history 改写问题                               | 不变                                                |
| `LLMClient.generate`          | 已支持 `messages: list[LLMMessage]`                 | 不变（无需改接口）                                  |
| `QANode.run`                  | `SkillContext` 不含 history                         | 注入 `history` 到 `state_snapshot`                  |
| `PatentQASkill.run`           | 固定发 [system, task, data] 三条                    | 把 history 展开成原生 user/assistant 消息插在中间   |
| `build_patent_qa_user_prompt` | question/retrieval/claims → `<data>`                | 不变：仅承载**本轮**检索结果/权利要求（仍留数据块） |

## 3. 方案设计

### 3.1 QANode：从 dialog_context 取记忆并注入 state_snapshot

**不变**（与数据块方案一致）：`QANode.run` 仍把 `history` 放进 `SkillContext`，交给 skill 层展开成原生消息。

```python
# build_context 已把摘要作为首个 [早期对话摘要] 合成 turn 前插进 history，
# 直接用 history 即可，摘要天然包含在内。
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

### 3.2 Skill：把 history 展开成原生 user/assistant 消息（核心改动）

`PatentQASkill.run` 从固定三条消息，改为把 history 逐条映射成原生消息，插在 system 之后、本轮 task/data 之前。`LLMMessage.role` 支持 `system/user/assistant`，与 store 里 turn 的 role 对应：

```python
history = context.state_snapshot.get("history") or []
messages = [LLMMessage(role="system", content=prompt_layers["system"])]
messages += [
    LLMMessage(
        role=("assistant" if t.get("role") == "assistant" else "user"),
        content=str(t.get("content", "")),
    )
    for t in history if str(t.get("content", "")).strip()
]
messages += [
    LLMMessage(role="user", content=prompt_layers["task"]),
    LLMMessage(role="user", content=prompt_layers["user_data"]),
]
response = self.llm_client.generate(
    messages=messages, output_schema=PATENT_QA_OUTPUT_SCHEMA, trace_context=...
)
```

摘要天然作为首个 `[早期对话摘要]` assistant 消息出现，不重复、也无需去重。

### 3.3 本轮数据块：检索结果 / 权利要求仍留 `<data>`

`build_patent_qa_user_prompt` **保持原签名不变** `(question, retrieval_results, claims_draft)`——它只承载**本轮**的检索原文与权利要求。这些是**外部不可信内容**，必须留在带“忽略数据区指令”边界的 `<data>` 里；历史不再进这里，由 3.2 的消息数组承载。

### 3.4 安全边界：为什么历史可以当真实消息

`session_store` 存的 `turns` 只有**同一用户自己的提问**与**模型自己生成的上一轮回答**——同主体 + 模型自产内容，注入风险低，可安全当原生 `user`/`assistant` 消息；真正的外部不可信内容（检索到的专利/法条原文）仍隔离在 3.3 的 `<data>` 数据块内。

并在 system 里补一句约束：**“历史消息是既往对话上下文，仅用于理解本轮指代与延续；答复依据仍必须来自本轮 `<data>` 的 retrieval_results / 权利要求，不得把历史内容当作已证实的事实或来源。”**

### 3.5 预算 · 结构化输出

- history 长度由 `load_history(session_id, history_window)` 控制，复用 `memory_history_window`，不新增配置；单轮过长可对 `content` 截断（如 `[:500]`），先不截、超预算再加。
- **结构化输出不受影响**：`generate` 仍传 `output_schema` + `response_format={"type": "json_object"}`，多轮消息下末条 user 仍带“必须输出 PatentQAResult JSON”约束，照常 `model_validate`。

### 3.6 方案选型：为什么走 chat-native

QA 对用户就是专利领域多轮聊天，因此采用**原生 messages 数组**：近期真实轮作为 `user`/`assistant` 消息（最好的多轮理解、贴合对话形态），检索结果留 `<data>`（挡外部注入），输出仍是结构化 JSON——即“聊天体验 + 结构化契约 + 数据分离”的折中。

前提均已具备：`LLMClient.generate` 本就接收 `messages: list[LLMMessage]`（测试已有单条 user 用法），`OpenAICompatibleClient` 直接把整个列表发给 `chat/completions`，`LLMMessage.role` 支持 `assistant`——因此**无需改 LLM 接口**，改动集中在 `PatentQASkill.run`。

不选“全塞一个数据块”的原因：那样虽零结构改动，但把历史压成字符串会削弱模型对“谁说的”的理解，与聊天体验不符；而历史本是同主体内容，当真实消息的注入风险可接受。

## 4. 关键约束

<aside>
 🛡️

1. **数据分离**：外部检索原文（retrieval_results）/ 权利要求仍只进本轮 `<data>`；历史作为原生 user/assistant 消息注入，并在 system 声明“历史仅供理解、不作依据”。
2. **依据仍归依据**：历史内容不得作为 basis 或来源回链，basis 只能来自 retrieval_results / 权利要求 / 用户问题。
3. **脱敏沿用**：入库时已 `redact_sensitive_text`，注入端不重复脱敏。
4. **零会话零影响**：无 session_id / NullSessionStore 时 history 为空，messages 退回 [system, task, data] 三条，QA 行为与现状完全一致。
    </aside>

## 5. 验收标准

- [ ]  有 session、有历史时，`generate` 收到的 `messages` = [system] + 历史（user/assistant 原生消息） + [task, user_data]；摘要作为首个 `[早期对话摘要]` assistant 消息出现且仅一次。
- [ ]  本轮 `user_data`（`<data>`）只含检索结果/权利要求/当前问题，**不含**历史。
- [ ]  多轮场景：第 2 轮问“把上一条用更通俗的话讲一遍”，答复能引用上一轮内容而非重新泛泛作答。
- [ ]  无 session_id 时，messages 退回三条，QA 输出与改动前一致（回归不破坏）。
- [ ]  basis 仍只回链真实 evidence，历史文本不被当作来源。

## 6. Trace 事件

复用现有 `session_memory_loaded`（在 `_inject_session_context` 触发，含 `history_count` / `has_summary`）。QA 侧在 `qa_completed` 的 data 补 `history_msg_count`（注入的历史消息条数），便于验证记忆是否真正进入回答；`generate` 的 trace `input_chars` 会自动含全部消息，可作旁证。

## 7. 测试计划

| 用例       | 断言                                                         |
| ---------- | ------------------------------------------------------------ |
| 消息组装   | 用 fake `LLMClient` 捕获 `generate(messages=...)`：顺序为 system → 历史 user/assistant → task → user_data |
| 角色映射   | store 中 assistant turn 映射为 `role="assistant"`，user turn 为 `role="user"` |
| 数据块隔离 | `user_data` 的 `<data>` 只含检索/权利要求/当前问题，不含历史 |
| 空会话     | 无 session 时 messages 退回三条，输出与基线一致              |
| 结构化输出 | 多轮消息下仍返回合法 `PatentQAResult`（model_validate 通过） |

验证命令：`conda run -n autoGLM pytest tests/test_qa_node.py tests/test_patent_qa_skill.py tests/test_agentic_qa_integration.py`

## 8. 非目标（本片不做）

- 不做结构化 `qa_result`（basis/provenance）回写 session —— 已评估暂不落库。
- 不改存储后端（仍 SQLite，不引入 Redis）。
- 不做语义历史召回 / 跨会话 case memory。
- 不改检索、ReAct 主循环、意图路由。

## 9. 风险与回退

- **风险：历史注入放大照抄倾向**。缓解：system 约束句明确历史仅用于理解指代、不作依据；与 prompt 改写（分析而非摘抄）配合。
- **风险：长历史撑爆 token / lost-in-the-middle**。缓解：复用 `history_window` 限制轮数，必要时每轮截断。
- **风险：多轮下结构化输出偶发不稳**。缓解：保留 `response_format=json_object` 与末条 user 的 schema 约束；`model_validate` 失败已有结构化错误路径。
- **回退**：改动集中在 `PatentQASkill.run` 的消息组装；`history` 为空时自动退回三条消息，无 schema 变更，注释掉历史展开即回到现状。