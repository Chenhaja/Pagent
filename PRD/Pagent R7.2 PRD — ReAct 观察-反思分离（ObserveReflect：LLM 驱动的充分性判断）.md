<aside>
 🔎

把 R7.1 落地后仍是启发式的 **Observation/充分性判断** 升级为**独立的 LLM 反思阶段**:在 `tool.run()` 之后、能读到 observation 正文的前提下,由 LLM 判断“证据是否充分、要不要继续、下一步 query 怎么改”。核心是把**行动决策(Act)**与**观察反思(Observe/Reflect)**从同一次 `ReActDecision` 里拆开,恢复真正的 Thought–Action–Observation 三段式。
 关联:承接 R7.1《LLM 驱动的 ReAct 主循环》(policy/工具卡片已落地),本轮只补 Observe/Reflect 这一段与相关数据契约。

</aside>

## 1. 背景与问题

R7.1 已落地(commit `8de8c90b`):`react_policy.py` 有 `LLMReActPolicy` / `ToolCard`,`BoundedReActLoop` 接了 `policy` / `tool_cards`,Act 侧(选工具 + 改写 query)已由 LLM 驱动。但 **Observation / 充分性判断仍是启发式,且 Act 与 Observe 被压进同一次决策**。

| 环节                | 现状代码(`8de8c90b`)                                         | 问题                                                         |
| ------------------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| 决策时机            | `decision = self._decide(...)` 一次吐出 `thought+action+tool_input+stop+sufficient`,**在 `tool.run()` 之前** | LLM 在没看到本步 observation 时就把 `sufficient` 定了,时间点早一拍 |
| Act 与 Observe 融合 | `ReActDecision` 同时含 `action` 与 `stop/sufficient`         | “观察后的反思”被塞进“行动决策”,本步 observation 在本步内无 LLM 环节读它 |
| 充分性判断          | `if decision.sufficient or observation.sufficient`;`observation.sufficient` 来自 `KBRetrievalTool` 的 `sufficient=bool(evidence)` | OR 让纯启发式(有结果即停)直接短路收敛,非 LLM 判断            |
| scratchpad          | `_build_scratchpad_item` 只存 `observation_count / top_score / error`,**不含 evidence 正文** | 下一步 LLM 读 scratchpad 也读不到观察内容,无法内容级判断充分 |
| `use_llm_judge`     | `__init__` 存了 `self.use_llm_judge`,`run()` 及辅助方法**从未引用** | 死配置:开了也不生效,充分性仍走 OR 启发式                     |

> 一句话:现在的“LLM 驱动”只覆盖 Act 侧;Observe/充分性仍是 `bool(evidence)`,且与 Act 融合、时间点错位、看不到正文。

## 2. 目标与非目标

**目标(本轮 P0)**

- 新增**独立的 Observe/Reflect 阶段**:发生在 `tool.run()` 之后,输入包含**本步 observation 正文摘要**,由 LLM 产出 `{sufficient, reason, next_query_hint}`。
- 把 `sufficient` 从**行动前**的 `ReActDecision` 中移除或降级为非权威“计划提示”,消除 Act/Observe 融合。
- **真正接线 `use_llm_judge`**:开启时以 reflect 结果为准,关闭时回退到确定性阈值(不再无脑 `bool(evidence)`)。
- scratchpad 携带 **observation 内容摘要**(截断 + 脱敏),让后续决策/反思是内容级 grounded 的。
- reflect 的 `next_query_hint` 回灌下一步 Act,形成“观察驱动的 query 改写”闭环。
- 预算(步数/token/超时)、白名单、指令-数据分离、脱敏仍由代码**硬约束**;reflect 失败确定性降级,循环不中断。

**非目标**

- 不改检索算法(R4.3 四件套)与工具注册机制(R7.1 已含 `tool_cards`)。
- 不改会话记忆注入 QA 回答那条链路(已在近期提交落地)。
- 不做并行多工具 / 多智能体。
- 不在本轮默认开启外部工具(仍受 `agentic_external_tools_enabled` 控制)。

## 3. 方案设计

### 3.1 恢复三段式主循环(`app/orchestrator/react_loop.py`)

每步顺序改为:

1. 预算检查(步数/超时/token)—— 不变,代码强约束。
2. **Act**:`decision = policy.decide(...)` → 只产 `thought + action + tool_input`(不再权威判定 sufficient)。
3. `decision.stop or action is None` → 收敛(`policy_stop`)。
4. 白名单 / schema 校验 → 非法则降级 heuristic。
5. `observation = tool.run(decision.tool_input)`。
6. **Observe/Reflect(新增)**:`reflection = policy.reflect(task_input, observation_digest, scratchpad, step_index)` → `{sufficient, reason, next_query_hint}`。
7. 充分性收敛:`use_llm_judge` 开 → 以 `reflection.sufficient` 为准;关 → 回退阈值(如 `top_score ≥ 阈值` 且 `evidence 非空`)。
8. 未收敛 → 用 `reflection.next_query_hint` 更新下一步 `task_input`/query;写 scratchpad(含正文摘要)。
9. Trace:新增 `react_reflect_step`,保留 `react_policy_step` / `react_main_step` / `react_main_converged`。

> reflect 调用失败(errors/非 dict/超时)→ 当步回退确定性阈值判断,`fallback_used=true`,循环不中断。

### 3.2 Policy 扩展(`app/orchestrator/react_policy.py`)

```python
@dataclass
class ReflectResult:
    sufficient: bool           # 证据是否充分
    reason: str                # 判断依据摘要(仅 trace,不回传用户)
    next_query_hint: str | None # 下一步检索 query 改写建议

class ReActPolicy(Protocol):
    def decide(self, task_input, allowed_tools, scratchpad, step_index) -> ReActDecision: ...
    def reflect(self, task_input, observation_digest, scratchpad, step_index) -> ReflectResult: ...
```

- `LLMReActPolicy.reflect`:用 `LLMClient.generate(messages, output_schema=REACT_REFLECT_SCHEMA, trace_context={"task_type":"react_reflect", "node_name":...})` 实现。
- `HeuristicReActPolicy.reflect`:封装现有 `bool(evidence)` / `top_score` 阈值逻辑,作为降级实现。
- `ReActDecision` 移除 `sufficient`(或保留但循环不再据其收敛,标注为 planning-only)。

### 3.3 反思输出 schema(`app/prompts/react_policy.py` 追加)

```json
{
  "type": "object",
  "properties": {
    "sufficient": {"type": "boolean"},
    "reason": {"type": "string"},
    "next_query_hint": {"type": ["string", "null"]}
  },
  "required": ["sufficient", "reason"]
}
```

- system:固定角色 + 规则(只依据给定 observation 判断、指令与数据分离、不得编造证据)。
- user:任务 + **本步 observation 正文摘要(截断)** + scratchpad 摘要。

### 3.4 observation 正文摘要(`react_loop.py`)

- 新增 `_build_observation_digest(observation)`:取 evidence 前 N 条,每条 `content[:摘要长度]` + 关键 provenance(source/document_id/score),整体再做长度上限截断。
- `_build_scratchpad_item` 增加 `observation_digest`(截断后的正文摘要)字段,替代“只有 count/score”。
- 摘要遵守 `redaction_enabled` / `allow_cloud_sensitive_content`;reflect 的 `reason` 原文不落库、不回传用户,trace 仅记长度。

### 3.5 配置(`app/core/config.py`)

| 新增/调整键                        | 默认                                           | 说明                                      |
| ---------------------------------- | ---------------------------------------------- | ----------------------------------------- |
| `react_use_llm_judge`              | `true`                                         | **真正接线**:开→reflect 判定;关→阈值兜底  |
| `react_sufficient_score_threshold` | `0.5`                                          | `use_llm_judge=false` 时的 top_score 阈值 |
| `react_observation_digest_chars`   | `600`                                          | 单步 observation 摘要总字符上限           |
| `react_reflect_model`              | 空→回退 `react_policy_model`/`llm_cheap_model` | 反思用模型档位                            |

### 3.6 Trace 事件

- 新增 `react_reflect_step`:`{node_name, step_index, sufficient, reason_len, next_query_hint_present, driver}`。
- `react_main_converged.reason` 枚举保持:`sufficient / policy_stop / max_steps / token_budget / timeout / tool_unavailable`;`sufficient` 现由 reflect(或阈值)决定。
- reflect LLM 的 `LLMResponse.trace` 经 sink 记录(脱敏,仅 input_chars/model/duration)。

## 4. 数据契约

- `ReflectResult`:`{sufficient, reason, next_query_hint}`(见 3.2)。
- `ReActDecision`:移除权威 `sufficient`(planning-only 或删除)。
- scratchpad item:新增 `observation_digest`(截断正文),保留 `step_index / tool_name / observation_count / top_score / error / external`。
- `ToolObservation`(沿用):`{tool_name, evidence, sufficient, error, external, top_score}`;`sufficient` 保留作阈值兜底输入,不再是唯一收敛依据。
- `ReActOutcome`(沿用):`{evidence, reason, steps_used, tool_calls, trace_events, external_tools_used, driver, fallback_used}`。

## 5. 验收标准

- [ ]  `tool.run()` 之后存在独立 reflect 调用:trace 出现 `react_reflect_step`。
- [ ]  `use_llm_judge=true` 且 LLM 可用时,收敛由 `reflection.sufficient` 决定(可通过注入 FakeLLM 决策序列验证)。
- [ ]  `use_llm_judge=false` 时回退 `react_sufficient_score_threshold` 阈值,不再无脑 `bool(evidence)`。
- [ ]  `ReActDecision` 不再单独触发 `sufficient` 收敛(grep 确认循环不读 `decision.sufficient`)。
- [ ]  scratchpad 与 reflect 输入包含 observation 正文摘要(截断 ≤ `react_observation_digest_chars`)。
- [ ]  多步场景下 `reflection.next_query_hint` 改变下一步 query(证明观察驱动改写)。
- [ ]  reflect 失败 → 当步回退阈值,`fallback_used=true`,循环不崩。
- [ ]  预算硬约束:`steps_used ≤ react_max_steps`,不超时、不超 token。

## 6. 测试计划

- 新增 `tests/test_react_reflect.py`:reflect 解析、schema 校验、next_query_hint 回灌、降级。
- 更新 `tests/test_react_policy.py`:`ReActDecision` 不含权威 sufficient。
- 更新 `tests/test_agentic_loop.py`:三段式顺序、reflect 收敛、阈值兜底、observation_digest 写入 scratchpad。
- 更新 `tests/test_qa_node.py`:注入 FakeLLM reflect 序列,断言收敛原因与步数。
- 更新 `tests/test_core_config_logging.py`:`to_public_dict` 覆盖新增 `react_*` 键。

## 7. 项目结构变更

```jsx
app/orchestrator/
  react_loop.py        # 改造:Act/Observe 拆段,tool.run 后 reflect,observation_digest,接线 use_llm_judge
  react_policy.py      # 新增 reflect() + ReflectResult;ReActDecision 去权威 sufficient
app/prompts/
  react_policy.py      # 追加 REACT_REFLECT_SCHEMA + 反思 prompt
app/core/config.py     # 新增 react_sufficient_score_threshold / react_observation_digest_chars / react_reflect_model
tests/
  test_react_reflect.py # 新增
  test_agentic_loop.py  # 更新
```

## 8. 实施顺序

1. 定义 `ReflectResult` 与 `REACT_REFLECT_SCHEMA` + 反思 prompt。
2. `HeuristicReActPolicy.reflect`(抽出现有阈值逻辑),保证降级行为可预期。
3. `LLMReActPolicy.reflect`(基于 `LLMClient.generate` + output_schema)。
4. `react_loop`:插入 `_build_observation_digest` + reflect 调用 + `use_llm_judge` 门控 + next_query_hint 回灌。
5. 从 `ReActDecision` 收敛路径摘除 `decision.sufficient`。
6. 接入 `config.py` 新键。
7. 补测试与回归对齐。

## 9. DoD

- [ ]  Observe/Reflect 阶段落地,LLM 与阈值双实现可切换。
- [ ]  `use_llm_judge` 真正生效(可观测:trace `driver` 与 `react_reflect_step`)。
- [ ]  scratchpad/reflect 输入含 observation 正文摘要。
- [ ]  `pytest && python -m compileall app tests` 通过。

## 10. 风险与缓解

| 风险                                    | 缓解                                                        |
| --------------------------------------- | ----------------------------------------------------------- |
| reflect 多一次 LLM 调用,放大延迟/成本   | cheap 模型档位 + 低温 + observation 摘要截断 + 步数预算保守 |
| LLM 误判充分性(过早停/不停)             | 阈值兜底 + 预算硬上限 + schema 约束 + `reason` 可审计       |
| observation 正文进 prompt 引发敏感/注入 | 指令-数据分离 + `redaction_enabled`  • 摘要不落原文         |
| 无 key 环境回归漂移                     | Fake 下强制阈值兜底,回归断言行为一致                        |

------

> 说明:本 PRD 只覆盖“Observe/Reflect 观察-反思分离”。Act 侧(工具路由 + query 改写)已在 R7.1 落地,会话记忆注入 QA 回答已在近期提交落地,均不在本轮范围。