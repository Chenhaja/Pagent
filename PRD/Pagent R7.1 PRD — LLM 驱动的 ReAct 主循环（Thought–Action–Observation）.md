<aside>
 🧠

把 R7 的「受限工具编排」从**确定性按下标跑工具**升级为**LLM 驱动的 ReAct**：每步由 LLM 产出 Thought → Action(选工具+入参) → 观察结果 → 再决策,直到自认充分或触达预算。预算/白名单/超时仍由代码强约束,LLM 只负责“怎么想、用哪个工具、是否停”。
 关联:承接 R7《Agentic 编排》，前置 R4.3 检索四件套、R5.3 bounded 循环骨架。

</aside>

## 1. 背景与问题

当前实现(commit `33d70fbe`)名为 ReAct，实际是**确定性工具执行器**,AI 没有进入回路:

| 环节   | 现状代码                                                     | 问题                                       |
| ------ | ------------------------------------------------------------ | ------------------------------------------ |
| 选工具 | `react_loop.py`:`tool_name = allowed_tools[min(step_index, len-1)]` | 按数组下标顺序取,不是决策,谈不上“工具路由” |
| 推理   | 无任何 LLM 调用;trace 里 `"decision": "continue_or_converge"` 是写死常量 | 没有 Thought,谈不上 Reasoning              |
| 入参   | 每步都 `tool.run({"query": task_input, ...})`,`task_input` 恒定 | query 从不改写,多步只是重复同一检索        |
| 充分性 | `KBRetrievalTool`:`sufficient=bool(evidence)`                | 有结果即停,启发式,非模型判断               |
| 预算   | `retrieval_max_steps` 默认 **1**                             | 默认单发,循环/多工具跑不起来               |

> LLM 能力其实已具备:`app/tools/llm.py` 的 `LLMClient.generate(messages, output_schema, trace_context)` 支持结构化 JSON 输出(`response_format=json_object`)与降级,但主循环一次都没调用它。

## 2. 目标与非目标

**目标(本轮 P0)**

- 在 `BoundedReActLoop` 内引入 **ReActPolicy**:每步调用 LLM,产出结构化 `{thought, action{tool, tool_input}, stop, sufficient}`。
- 工具选择由 LLM 在**白名单 + 工具描述**内决策(真正的工具路由),而非下标遍历。
- 支持**基于观察改写 query / 追问**:每步 `tool_input` 由 LLM 依据已有 observation 生成。
- 充分性由 LLM 判断(带阈值兜底),替代 `sufficient=bool(evidence)`。
- 预算(步数/token/超时)、白名单、指令-数据分离、脱敏仍由代码**硬约束**,LLM 不能突破。
- **无 LLM / 调用失败时确定性降级**到现有 bounded 逻辑,行为可预期。

**非目标**

- 不改检索算法本身(R4.3 四件套)。
- 不在本轮启用外部工具默认开(websearch/legal_status/official_fee 仍受 `agentic_external_tools_enabled` 控制)。
- 不做并行多工具、多智能体协作(留后续)。
- 会话记忆进 prompt 的修复单独立项(见 R7 PRD 衔接缺口),本轮只保证 policy 能接收传入的上下文。

## 3. 方案设计

### 3.1 ReActPolicy 接口(新增 `app/orchestrator/react_policy.py`)

```python
@dataclass
class ReActDecision:
    thought: str                     # 仅用于 trace 摘要,不回传用户
    action: str | None               # 选中的工具名;None 表示直接停止
    tool_input: dict[str, Any]       # LLM 生成的结构化入参(含改写后的 query)
    stop: bool                       # 是否结束循环
    sufficient: bool                 # 是否认为证据已充分

class ReActPolicy(Protocol):
    def decide(
        self,
        task_input: str,
        allowed_tools: list[ToolCard],   # 工具名 + 描述 + 入参 schema
        scratchpad: list[dict[str, Any]],# 历史 thought/action/observation 摘要
        step_index: int,
    ) -> ReActDecision: ...
```

- `LLMReActPolicy`:用 `LLMClient.generate(messages, output_schema=REACT_DECISION_SCHEMA, trace_context={"node_name":..., "task_type":"react_policy"})` 实现。
- `HeuristicReActPolicy`:封装现有“按下标选工具 + `bool(evidence)`”逻辑,作为降级实现。

### 3.2 决策输出 schema(新增 `app/prompts/react_policy.py`)

```json
{
  "type": "object",
  "properties": {
    "thought": {"type": "string"},
    "action": {"type": ["string", "null"]},
    "tool_input": {"type": "object"},
    "stop": {"type": "boolean"},
    "sufficient": {"type": "boolean"}
  },
  "required": ["thought", "stop", "sufficient"]
}
```

- system prompt 固定角色 + 规则(只能从白名单选工具、必须结构化输出、指令与数据分离)。
- user 层携带:任务、可用工具卡片(名称/用途/入参字段)、已累积 observation 摘要(截断)。

### 3.3 主循环改造(`app/orchestrator/react_loop.py`)

每步流程改为:

1. 预算检查(步数/超时/token)—— 不变,代码强约束。
2. `decision = policy.decide(task_input, allowed_tool_cards, scratchpad, step_index)`。
3. **校验**:`decision.action` 必须在白名单内;非法/未知 → 记 trace 并按策略降级或停止。
4. 若 `decision.stop` 或 `decision.action is None` → 收敛(reason=`policy_stop` / `sufficient`)。
5. 执行 `tool.run(decision.tool_input)`,累积 evidence,写 `scratchpad`。
6. 充分性:`decision.sufficient`(LLM) 或 evidence 阈值兜底 → 收敛。
7. 记 `react_policy_step` trace(thought 只记长度/摘要,不落原文)。

> LLM 决策失败(errors/非 dict/超时)→ 当步回退到 `HeuristicReActPolicy`,循环不中断;连续失败达阈值 → 整体降级为确定性模式并置 `fallback_used=true`。

### 3.4 工具描述(`app/orchestrator/tool_registry.py`)

给 `ToolSpec` 增加 `description` 与 `input_schema`,由 registry 暴露 `tool_cards()`,供 policy 作为可选项传给 LLM —— 这是“工具路由”的信息基础。

### 3.5 配置(`app/core/config.py`)

| 新增/调整键                                    | 默认                                  | 说明                                              |
| ---------------------------------------------- | ------------------------------------- | ------------------------------------------------- |
| `react_policy_driver`                          | `"llm"`                               | `llm` / `heuristic`;无 LLM 配置时自动按 heuristic |
| `react_max_steps`                              | `4`                                   | LLM 驱动下的最大步数(替代默认 1 的单发)           |
| `react_policy_model`                           | 空→回退 `llm_cheap_model`/`llm_model` | 决策用模型档位                                    |
| `react_policy_temperature`                     | `0.0`                                 | 决策低温,保证稳定                                 |
| `react_use_llm_judge`                          | `true`                                | 充分性交给 LLM,阈值兜底                           |
| `react_token_budget` / `react_timeout_seconds` | 沿用 retrieval 对应值                 | 供 `ReActBudget`                                  |

> 兼容:保留读取旧 `retrieval_max_steps` 一个版本并映射到 `react_max_steps`,随后下线。

### 3.6 Trace 事件

- 新增 `react_policy_step`:`{node_name, step_index, tool_name, thought_len, stop, sufficient, driver}`。
- 复用 `react_main_step` / `react_main_converged`;`converged.reason` 扩展枚举:`sufficient / policy_stop / max_steps / token_budget / timeout / tool_unavailable`。
- 决策 LLM 的 `LLMResponse.trace` 经 sink 记录(已脱敏,只记 input_chars/model/duration)。

### 3.7 安全与约束(不可退让)

- 预算、白名单、超时由**循环代码**强制,LLM 输出仅在这些边界内生效。
- 指令-数据分离:工具卡片/观察作为 data 层,不与 system 指令混写。
- 敏感内容遵守 `redaction_enabled` / `allow_cloud_sensitive_content`;thought 原文不落库、不返回用户。
- 非法 action、越界 tool_input 一律拒绝并降级。

## 4. 数据契约

- `ReActDecision`(见 3.1)—— policy 输出。
- `ToolCard`:`{name, description, input_schema}`。
- `ToolObservation`(沿用):`{tool_name, evidence, sufficient, error, external, top_score}`。
- `ReActOutcome`(沿用,扩展 `driver` 与 `fallback_used` 字段):`{evidence, reason, steps_used, tool_calls, trace_events, external_tools_used, driver, fallback_used}`。

## 5. 验收标准

- [ ]  LLM 配置齐全时,QA 走真实 policy:trace 出现 `react_policy_step`,`driver="llm"`,且工具由 LLM 选定。
- [ ]  多步场景下,后续步 `tool_input.query` 与首步不同(证明基于观察改写)。
- [ ]  充分性由 `decision.sufficient` 决定,`react_use_llm_judge=false` 时回退阈值。
- [ ]  非法 action / LLM 失败 → 当步降级 heuristic,循环不崩,`fallback_used=true`。
- [ ]  无 LLM(FakeLLMClient)时行为与旧确定性循环一致(回归对齐)。
- [ ]  预算硬约束:任何情况下 `steps_used ≤ react_max_steps`,不超时、不超 token。
- [ ]  `grep -r "continue_or_converge" app` 仅存在于 heuristic 分支(或删除)。

## 6. 测试计划

- 新增 `tests/test_react_policy.py`:LLM 决策解析、非法 action、schema 校验、降级。
- 更新 `tests/test_agentic_loop.py`(或现有 react_loop 测试):多步改写、policy_stop、预算收敛、fallback。
- 更新 `tests/test_qa_node.py`:QA 注入 `FakeLLMClient` 决策序列,断言工具调用顺序与收敛原因。
- 更新 `tests/test_core_config_logging.py`:`to_public_dict` 覆盖新增 `react_*` 键。
- 用 `FakeLLMClient(response=...)` 注入固定决策,避免真实网络。

## 7. 项目结构变更

```
app/orchestrator/
  react_loop.py        # 改造:每步调用 policy,预算/校验/降级
  react_policy.py      # 新增:ReActPolicy / LLMReActPolicy / HeuristicReActPolicy
  tool_registry.py     # 增加 description/input_schema + tool_cards()
app/prompts/
  react_policy.py      # 新增:决策 system/user prompt + REACT_DECISION_SCHEMA
app/core/config.py     # 新增 react_* 配置键
tests/
  test_react_policy.py # 新增
  test_agentic_loop.py # 更新
```

## 8. 实施顺序

1. 定义 `ReActDecision` / `ToolCard` / 决策 schema 与 prompt。
2. 实现 `HeuristicReActPolicy`(把现有逻辑抽出),保证行为不变。
3. 实现 `LLMReActPolicy`(基于 `LLMClient.generate` + output_schema)。
4. 改造 `BoundedReActLoop`:policy 注入、校验、降级、trace。
5. `tool_registry` 增加工具卡片信息。
6. 接入 `config.py` 的 `react_*` 键与 `QANode._build_react_loop`。
7. 补测试与回归对齐。

## 9. DoD

- [ ]  `react_policy.py` 落地,LLM 与 heuristic 双实现可切换。
- [ ]  `BoundedReActLoop` 每步经 policy 决策且预算硬约束不被突破。
- [ ]  新增 `react_*` 配置进入 `to_public_dict`。
- [ ]  `pytest && python -m compileall app tests` 通过。
- [ ]  `driver` / `fallback_used` 在 trace 与 outcome 中可观测。

## 10. 风险与缓解

| 风险                      | 缓解                                                       |
| ------------------------- | ---------------------------------------------------------- |
| LLM 决策不稳定/幻觉选工具 | 白名单强校验 + 低温 + schema + 阈值兜底                    |
| 多步放大延迟与成本        | `react_max_steps` 保守(4)+ token/超时预算 + cheap 模型档位 |
| 无 key 环境回归漂移       | Fake 下强制 heuristic,回归断言行为一致                     |
| thought 泄漏敏感内容      | 不落原文、不返回用户,trace 仅记长度                        |

------

> 说明:本 PRD 只覆盖“把 ReAct 变成 LLM 驱动”。会话历史真正进入 `patent_qa` 等 skill 的 prompt、QA 答案落库修复,属于会话记忆衔接缺口,建议随后单独一节推进。