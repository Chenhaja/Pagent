# R7.2 ReAct Observe/Reflect 观察-反思分离实施计划

## 背景

R7.1 已把 ReAct 的 Act 侧接入 `LLMReActPolicy` 和 `ToolCard`，但当前主循环仍在 `tool.run()` 前由 `ReActDecision.sufficient` 预判充分性，并在 `tool.run()` 后用 `decision.sufficient or observation.sufficient` 收敛。`ToolObservation.sufficient` 目前常由“有 evidence 即 true”的启发式给出，导致 Observation / 充分性判断没有真正被 LLM 读到 observation 正文后判断。

R7.2 目标是把 Act 与 Observe/Reflect 拆开：每步先 `policy.decide` 选工具和 query，再执行 `tool.run`，然后把 observation 正文摘要交给 `policy.reflect`，由 reflect 产出 `{sufficient, reason, next_query_hint}`。开启 `react_use_llm_judge` 时以 reflect 结果收敛；关闭或 reflect 失败时，用 top_score 阈值兜底。

本计划只拆解实现路径与验收任务；实现阶段再修改业务代码。

## 当前代码基线

- `app/orchestrator/react_loop.py`
  - `BoundedReActLoop.__init__` 已有 `use_llm_judge` 参数但 `run()` 未真正使用。
  - `run()` 当前顺序为 decide → tool.run → scratchpad → `decision.sufficient or observation.sufficient` 收敛。
  - `decision.stop` 时会按 `decision.sufficient` 返回 `sufficient` 或 `policy_stop`。
  - `_build_scratchpad_item` 仅记录 count / top_score / error / external，不含 observation 正文摘要。
  - trace 有 `react_policy_step`、`react_main_step`、`react_main_converged`，无 `react_reflect_step`。
- `app/orchestrator/react_policy.py`
  - `ReActDecision` 包含 `sufficient` 权威字段。
  - `ReActPolicy` 只有 `decide(...)`。
  - `HeuristicReActPolicy` 只做按顺序选工具。
  - `LLMReActPolicy.decide` 使用 `REACT_DECISION_SCHEMA` 和 `build_react_policy_messages`。
- `app/prompts/react_policy.py`
  - `REACT_DECISION_SCHEMA` 要求 `sufficient`。
  - 决策 prompt 将 Act 与充分性判断混在同一次输出。
  - 已使用 `<data>` 包裹 task / tools / scratchpad。
- `app/core/config.py`
  - 已有 `react_use_llm_judge`、`react_policy_model`、`react_token_budget` 等。
  - 缺 `react_sufficient_score_threshold`、`react_observation_digest_chars`、`react_reflect_model`。
  - `to_public_dict()` 已公开 `react_use_llm_judge`，但缺新增配置。
- `app/nodes/qa.py`
  - `_build_react_loop()` 已把 `settings.react_use_llm_judge` 传入 loop。
  - `_build_react_policy()` 只按 `react_policy_model or llm_cheap_model or llm_model` 构建 policy，未区分 reflect model。
- `tests/test_agentic_loop.py`
  - 当前测试依赖 `observation.sufficient` 或 `decision.sufficient` 收敛，需要改为 reflect / 阈值口径。
  - `ScriptedPolicy` 只有 `decide`，需扩展 reflect 支持。
- `tests/test_react_policy.py`
  - 只覆盖 decide 解析和 heuristic decide。
  - 需要增加 reflect schema、LLM reflect、heuristic reflect 测试。
- `tests/test_core_config_logging.py`
  - 需补新增配置默认值、环境变量和 public dict 断言。
- `tests/test_react_reflect.py`
  - 尚不存在，需要新增。

## 依赖图

```text
SPEC.md
  -> Config contract
      -> app/core/config.py
      -> tests/test_core_config_logging.py
      -> app/nodes/qa.py                         # 默认 loop/model 读取新配置

  -> Prompt / schema contract
      -> app/prompts/react_policy.py             # REACT_DECISION_SCHEMA 调整 + REACT_REFLECT_SCHEMA + reflect prompt
      -> tests/test_react_policy.py
      -> tests/test_react_reflect.py

  -> Policy contract
      -> app/orchestrator/react_policy.py         # ReflectResult, ReActPolicy.reflect, parse reflect, LLM/Heuristic reflect
      -> app/tools/llm.py                         # 复用 LLMClient.generate / LLMMessage
      -> tests/test_react_policy.py
      -> tests/test_react_reflect.py

  -> Loop contract
      -> app/orchestrator/react_loop.py           # tool.run 后 reflect、digest、threshold、hint 回灌、trace
      -> app/orchestrator/tool_registry.py        # 保持工具卡片和白名单机制不变
      -> tests/test_agentic_loop.py

  -> QA integration
      -> app/nodes/qa.py                          # 注入 react_* 配置，reflect model 回退策略
      -> tests/test_qa_node.py

  -> final verification
      -> tests/test_react_reflect.py
      -> tests/test_react_policy.py
      -> tests/test_agentic_loop.py
      -> tests/test_qa_node.py
      -> tests/test_core_config_logging.py
      -> pytest / compileall
```

## 垂直切片原则

每个阶段都交付一条可验证路径，而不是只改一层：

1. 先补配置和 prompt/schema 的最小契约，让后续 policy / loop 有稳定输入输出。
2. 再实现 reflect policy：从 Fake LLM 到 `ReflectResult`，含错误可降级信号。
3. 再改主循环单步路径：`decide → tool.run → digest → reflect → 收敛/继续`，证明 `decision.sufficient` 不再收敛。
4. 再补多步路径：`next_query_hint` 回灌、scratchpad digest、预算和 fallback。
5. 最后接 QA 默认构建和回归验收。

---

## Phase 0 — 口径确认与基线锁定

### 目标

确认 R7.2 只补 Observe/Reflect，不扩大到检索算法、工具注册、QA 会话记忆或多智能体。

### 实施要点

- 保持 `ToolObservation` / `ReActOutcome` 外部结构基本兼容；如需扩展只做最小字段或构造参数。
- `ReActDecision.sufficient` 优先保留为 planning-only 兼容字段，先从主循环收敛路径摘除；是否彻底删除另行确认。
- `ToolObservation.sufficient` 不再单独触发收敛，只作为兼容字段或阈值兜底参考。
- 默认测试全部使用 fake / stub LLM，不触网、不调用真实模型。
- 不新增依赖。

### 验收标准

- plan / todo 明确上述边界。
- 后续任务不包含检索算法重写、工具注册重写、外部工具默认启用、并行多工具或持久化 reason。

### Checkpoint 0

确认计划后进入测试优先实现。

---

## Phase 1 — 配置与 prompt/schema 契约

### 目标

先建立 reflect 所需的稳定配置、schema 和 prompt，使 policy / loop 后续有明确契约。

### 涉及文件

- `app/core/config.py`
- `app/prompts/react_policy.py`
- `tests/test_core_config_logging.py`
- `tests/test_react_policy.py`
- `tests/test_react_reflect.py`

### 实施要点

- 在 `Settings` 增加：
  - `react_sufficient_score_threshold: float = 0.5`
  - `react_observation_digest_chars: int = 600`
  - `react_reflect_model: str | None = None`
- 在 `get_settings()` 读取：
  - `PAGENT_REACT_SUFFICIENT_SCORE_THRESHOLD`
  - `PAGENT_REACT_OBSERVATION_DIGEST_CHARS`
  - `PAGENT_REACT_REFLECT_MODEL`
- 在 `to_public_dict()` 公开新增非敏感配置。
- 调整 `REACT_DECISION_SCHEMA`：`sufficient` 不再 required；如保留字段，标注 planning-only。
- 新增 `REACT_REFLECT_SCHEMA`，包含 `sufficient`、`reason`、`next_query_hint`，`additionalProperties=False`。
- 新增 `build_react_reflect_messages(task_input, observation_digest, scratchpad, step_index)`：
  - system prompt 覆盖六要素。
  - user prompt 用 `<data>` 包裹任务、digest、scratchpad。
  - 明确数据区指令无效、禁止臆造、不确定时保守 `sufficient=false`。

### 验收标准

- 新增配置默认值、环境变量覆盖、public dict 均有测试。
- `REACT_REFLECT_SCHEMA` required 与 additionalProperties 符合 SPEC。
- reflect prompt 含 observation digest、scratchpad、数据分隔符和安全约束。
- 决策 schema / parser 不再强制权威 sufficient。

### 验证命令

```bash
conda run -n autoGLM pytest tests/test_core_config_logging.py tests/test_react_policy.py tests/test_react_reflect.py
```

### Checkpoint 1

配置和 schema 通过后，再实现 policy reflect，避免 loop 先依赖未稳定契约。

---

## Phase 2 — Policy reflect 能力

### 目标

让 `ReActPolicy` 支持独立 reflect，并提供 LLM 与 heuristic 两套实现。

### 涉及文件

- `app/orchestrator/react_policy.py`
- `app/prompts/react_policy.py`
- `tests/test_react_policy.py`
- `tests/test_react_reflect.py`

### 实施要点

- 新增 `ReflectResult` dataclass：`sufficient`、`reason`、`next_query_hint`。
- 扩展 `ReActPolicy` Protocol：增加 `reflect(...) -> ReflectResult`。
- `LLMReActPolicy.__init__` 增加可选 `reflect_model`，为空时回退 `model`。
- `LLMReActPolicy.reflect`：
  - 调用 `LLMClient.generate(messages=build_react_reflect_messages(...), output_schema=REACT_REFLECT_SCHEMA, model=reflect_model or model, temperature=0.0, timeout=...)`。
  - trace_context 使用 `task_type="react_reflect"` 和 `node_name`。
  - response errors / 输出非法时抛 `ReActPolicyError`。
- 新增 `_parse_reflection(payload)`，校验类型和 required 字段。
- `HeuristicReActPolicy` 增加阈值构造参数，并实现 `reflect(...)`：
  - 从 `observation_digest` 中读取由 loop 提供的 `evidence_count` / `top_score` / `has_error` 等摘要字段；若采用字符串 digest，则需要 loop 另传结构化摘要或在 digest 中保留结构化字段。实现时优先让 digest 是 dict，prompt 层再序列化。
  - `sufficient = evidence_count > 0 and top_score >= threshold and not has_error`。
  - reason 返回短中文原因；`next_query_hint` 默认为 None。
- 保持 `HeuristicReActPolicy.decide` 旧行为。

### 验收标准

- Fake LLM 合法 reflect 输出能解析为 `ReflectResult`。
- Fake LLM 缺字段、类型错误、errors 时抛 `ReActPolicyError`。
- `LLMReActPolicy.reflect` trace task_type 为 `react_reflect`，不暴露原始输入。
- `HeuristicReActPolicy.reflect` 使用 top_score 阈值，不是 `bool(evidence)`。
- `ReActDecision.sufficient` 不再是 parser 必填权威字段。

### 验证命令

```bash
conda run -n autoGLM pytest tests/test_react_policy.py tests/test_react_reflect.py
```

### Checkpoint 2

policy reflect 单元测试通过后，再接主循环。

---

## Phase 3 — 主循环三段式单步收敛

### 目标

将 `BoundedReActLoop.run` 改为每步 `decide → tool.run → observation_digest → reflect → sufficient 判断`，并移除 `decision.sufficient` / `observation.sufficient` 的直接收敛。

### 涉及文件

- `app/orchestrator/react_loop.py`
- `tests/test_agentic_loop.py`

### 实施要点

- `BoundedReActLoop.__init__` 增加：
  - `sufficient_score_threshold: float = 0.5`
  - `observation_digest_chars: int = 600`
- 构造默认 `HeuristicReActPolicy(threshold=sufficient_score_threshold)`。
- 新增 `_build_observation_digest(observation)`，建议返回结构化 dict：
  - `evidence_count`
  - `top_score`
  - `error`
  - `external`
  - `items`: 每条含截断 `content` 与 provenance 摘要
  - `text`: 总体截断后的可读摘要（或只在 prompt build 时序列化）
- 新增 `_reflect(task_input, observation_digest, scratchpad, step_index)`：
  - `use_llm_judge=True` 时优先调用 `self.policy.reflect`。
  - 禁用 judge 或 reflect 异常时调用 `self.heuristic_policy.reflect`。
  - 返回 `(reflection, driver, fallback_used)`。
- `decision.stop or action is None` 固定以 `policy_stop` 收敛，不再看 `decision.sufficient`。
- `tool.run()` 成功后先构造 digest，再 reflect，再写 trace 和 scratchpad。
- sufficient 收敛只看：
  - judge 开启且 reflect 成功：`reflection.sufficient`
  - judge 关闭或 reflect 失败：heuristic threshold reflection 的 `sufficient`
- 新增 `react_reflect_step` trace，仅记录：`node_name`、`step_index`、`sufficient`、`reason_len`、`next_query_hint_present`、`driver`。
- `_build_policy_trace` 可保留 `sufficient` 字段但标记 planning-only；更推荐移除该 trace 字段以降低误导，测试按最终实现调整。

### 验收标准

- 首轮 observation 有 evidence 但 reflect 返回 false 时不收敛。
- reflect 返回 true 时以 `reason=sufficient` 收敛。
- `react_reflect_step` 出现在 `react_main_step` 后、`react_main_converged` 前。
- `use_llm_judge=false` 时即使 policy reflect 可用，也走 threshold 兜底。
- evidence 非空但 top_score 低于阈值时不收敛。
- `decision.sufficient=True` 不会让主循环直接收敛。
- trace 不包含完整 task_input、完整 evidence content、完整 reflect reason。

### 验证命令

```bash
conda run -n autoGLM pytest tests/test_agentic_loop.py
```

### Checkpoint 3

单步三段式和收敛口径通过后，再做多步 hint、scratchpad 和失败降级。

---

## Phase 4 — 多步闭环、scratchpad digest 与失败降级

### 目标

补齐 observation-driven query 改写闭环、scratchpad 内容摘要和 reflect 失败兜底。

### 涉及文件

- `app/orchestrator/react_loop.py`
- `tests/test_agentic_loop.py`
- `tests/test_react_reflect.py`

### 实施要点

- 将 `observation_digest` 写入 scratchpad item，确保长度不超过 `observation_digest_chars`。
- 若 `reflection.next_query_hint` 非空且未收敛，更新下一步 Act 的 `task_input` 或 query 上下文。
  - 推荐最小实现：维护 `current_task_input`，下一轮 `_decide(current_task_input, ...)` 使用 hint。
  - 原始问题如需保留，可在 scratchpad 中通过上一步摘要提供，不新增复杂结构。
- reflect 失败时：
  - `fallback_used=True`
  - driver 标记为 `fallback` 或 `heuristic`
  - 继续用 threshold 判断，不崩溃。
- 工具异常路径也应构造最小 digest / scratchpad，并避免完整原文 trace。
- token / timeout / max_steps 预算检查保持硬约束。

### 验收标准

- 多步测试中第一步 reflect 返回 `sufficient=false` + `next_query_hint="缩小后的问题"`，第二步工具收到新 query。
- 第二轮 policy 的 scratchpad 中包含第一步 `observation_digest`。
- digest 长度不超过配置上限。
- reflect 抛异常时 outcome `fallback_used=True`，trace 有 fallback driver，循环不崩。
- token_budget、timeout、max_steps 旧测试继续通过。

### 验证命令

```bash
conda run -n autoGLM pytest tests/test_agentic_loop.py tests/test_react_reflect.py
```

### Checkpoint 4

多步闭环和降级通过后，再接 QA 默认构建配置。

---

## Phase 5 — QA 默认接线与集成回归

### 目标

让 QA 默认 `BoundedReActLoop` 使用新增 reflect 配置，并用 QA 测试验证 LLM reflect 序列可驱动收敛。

### 涉及文件

- `app/nodes/qa.py`
- `tests/test_qa_node.py`
- `tests/test_core_config_logging.py`

### 实施要点

- `_build_react_loop()` 传入：
  - `use_llm_judge=self.settings.react_use_llm_judge`
  - `sufficient_score_threshold=self.settings.react_sufficient_score_threshold`
  - `observation_digest_chars=self.settings.react_observation_digest_chars`
- `_build_react_policy()` 构建 `LLMReActPolicy` 时传入：
  - `model=self.settings.react_policy_model or self.settings.llm_cheap_model or self.settings.llm_model`
  - `reflect_model=self.settings.react_reflect_model or self.settings.react_policy_model or self.settings.llm_cheap_model or self.settings.llm_model`
- 不改 QA 会话 history 注入链路。
- 在 `tests/test_qa_node.py` 使用 FakeLLM / fake policy 验证：
  - reflect false 后继续。
  - reflect true 后 `react_main_converged.reason=sufficient`。
  - reflect reason 不进入最终 QA 输出。

### 验收标准

- QA 默认 loop 构造读取新增配置。
- 无真实 LLM 配置时仍安全降级 heuristic。
- `react_reflect_step` 可在 QA trace 中观测。
- QA 原有 history、basis、风险提示测试不回归。

### 验证命令

```bash
conda run -n autoGLM pytest tests/test_qa_node.py tests/test_core_config_logging.py
```

### Checkpoint 5

QA 接线通过后进入总体验收。

---

## Phase 6 — 总体验收与提交准备

### 目标

运行 SPEC 要求的目标测试、全量测试和编译检查，确认无触网、无真实 LLM、无敏感 trace、无无关改动。

### 涉及文件

- `app/core/config.py`
- `app/prompts/react_policy.py`
- `app/orchestrator/react_policy.py`
- `app/orchestrator/react_loop.py`
- `app/nodes/qa.py`
- `tests/test_react_reflect.py`
- `tests/test_react_policy.py`
- `tests/test_agentic_loop.py`
- `tests/test_qa_node.py`
- `tests/test_core_config_logging.py`
- `tasks/plan.md`
- `tasks/todo.md`

### 实施要点

- 先跑目标测试，修复与本需求相关失败。
- 再跑全量 pytest，确认旧流程不回归。
- 最后跑 compileall。
- 检查 diff，确认未夹带无关改动。
- 按项目规范：完成可独立验证阶段后立即 commit；提交前只 stage 相关文件。

### 验收标准

- 目标测试通过。
- 全量测试通过。
- compileall 通过。
- 默认测试未调用真实 LLM / 外部服务。
- `grep` 确认主循环不再通过 `decision.sufficient` 收敛。
- trace 中无完整 observation 正文、完整 query、完整 reflect reason 或密钥。

### 验证命令

```bash
conda run -n autoGLM pytest tests/test_react_reflect.py tests/test_react_policy.py tests/test_agentic_loop.py tests/test_qa_node.py tests/test_core_config_logging.py
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests scripts
```

## 风险与控制

- **风险：Act 与 Reflect 仍隐性耦合。** 控制：单测覆盖 `decision.sufficient=True` 但 reflect false 时不收敛。
- **风险：有 evidence 即停回归。** 控制：阈值测试覆盖 evidence 非空但 top_score 低于阈值不收敛。
- **风险：observation 正文进入 trace。** 控制：trace 只记录长度 / count / score；测试搜索敏感正文不出现。
- **风险：reflect prompt 被 observation 注入影响。** 控制：prompt 使用 `<data>` 并声明数据区指令无效。
- **风险：多一次 LLM 调用导致无 key 环境失败。** 控制：无真实配置走 heuristic；测试使用 FakeLLM。
- **风险：hint 回灌覆盖原始任务导致上下文丢失。** 控制：最小实现只影响下一步 Act 输入，scratchpad 保留上步 observation digest。
- **风险：新增配置范围过窄。** 控制：配置命名使用通用 `react_*`，不新增 `qa_*` 单节点配置。

## 总体验证计划

```bash
conda run -n autoGLM pytest tests/test_core_config_logging.py tests/test_react_policy.py tests/test_react_reflect.py
conda run -n autoGLM pytest tests/test_agentic_loop.py
conda run -n autoGLM pytest tests/test_qa_node.py
conda run -n autoGLM pytest tests/test_react_reflect.py tests/test_react_policy.py tests/test_agentic_loop.py tests/test_qa_node.py tests/test_core_config_logging.py
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests scripts
```
