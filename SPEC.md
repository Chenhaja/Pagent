# ReAct Observe/Reflect 观察-反思分离规格说明

## 1. Objective

### 目标

本规格目标是将 R7.1 已落地但仍偏启发式的 ReAct Observation / 充分性判断，升级为独立的 Observe/Reflect 阶段：在 `tool.run()` 执行后，基于本步 observation 正文摘要，由策略层判断证据是否充分、是否继续，以及下一步 query 如何调整。

完成标准：

- `BoundedReActLoop` 主循环恢复为 `Thought/Act → Observation → Reflect` 三段式。
- `policy.decide(...)` 只负责行动决策：`thought`、`action`、`tool_input`、`stop`。
- `tool.run(...)` 之后必须调用 `policy.reflect(...)`，输入包含本步 observation 正文摘要与 scratchpad。
- `ReflectResult` 输出 `{sufficient, reason, next_query_hint}`。
- `use_llm_judge=true` 时，充分性收敛以 reflect 结果为准。
- `use_llm_judge=false` 或 reflect 失败时，回退确定性阈值：`evidence 非空` 且 `top_score >= react_sufficient_score_threshold`。
- `ReActDecision.sufficient` 不再触发主循环收敛；可删除，或保留为非权威 planning-only 字段但循环不得读取。
- scratchpad item 必须包含截断后的 `observation_digest`，让后续 Act / Reflect 具备内容级上下文。
- `reflection.next_query_hint` 必须能回灌下一步 Act，形成 observation-driven query 改写闭环。
- 新增 trace 事件 `react_reflect_step`，记录充分性、reason 长度、是否存在 next query hint、driver 等非敏感字段。
- reflect 失败必须确定性降级，设置 `fallback_used=true`，循环不中断。
- 步数、token、超时、工具白名单、schema 校验、外部工具开关、指令-数据分离和脱敏仍由代码硬约束。

### 目标用户

- 专利 QA / agentic 检索用户：希望多步检索不是“有结果即停”，而是基于 observation 内容判断证据是否充分。
- ReAct orchestration 开发者：需要清晰区分 Act 和 Observe/Reflect 的职责，便于测试与维护。
- 测试与排障人员：可以通过 Fake LLM、trace 和 scratchpad 验证 reflect 是否介入、是否收敛、是否回灌 query。

### 非目标

- 不改 R4.3 检索算法与工具注册机制。
- 不改会话记忆注入 QA 回答链路。
- 不做并行多工具、多智能体或外部工具默认启用。
- 不新增长期记忆、跨会话检索或语义历史召回。
- 不把预算、白名单、脱敏、外部工具权限交给 LLM 决定。
- 不让 reflect 的 `reason` 原文进入用户输出或持久化存储。

---

## 2. Commands

项目使用 conda 环境 `autoGLM`。所有 Python、pytest、脚本命令必须通过 `conda run -n autoGLM` 执行，不能依赖 `conda activate` 的跨命令状态。

```bash
# ReAct policy / reflect schema 测试
conda run -n autoGLM pytest tests/test_react_policy.py tests/test_react_reflect.py

# agentic loop 三段式与收敛测试
conda run -n autoGLM pytest tests/test_agentic_loop.py

# QA 节点 agentic reflect 集成回归
conda run -n autoGLM pytest tests/test_qa_node.py

# 配置公开字段与环境变量测试
conda run -n autoGLM pytest tests/test_core_config_logging.py

# 本需求目标测试
conda run -n autoGLM pytest tests/test_react_reflect.py tests/test_react_policy.py tests/test_agentic_loop.py tests/test_qa_node.py tests/test_core_config_logging.py

# 全量测试
conda run -n autoGLM pytest

# 编译检查
conda run -n autoGLM python -m compileall app tests scripts
```

验收命令：

```bash
conda run -n autoGLM pytest tests/test_react_reflect.py tests/test_react_policy.py tests/test_agentic_loop.py tests/test_qa_node.py tests/test_core_config_logging.py
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests scripts
```

约束：

- 默认测试必须使用 fake / stub LLM，不调用真实付费模型。
- 默认测试不触网，不调用真实外部检索源。
- 不新增依赖；如确需新增，必须先确认并同步 `requirements.txt`。
- 不执行破坏性 git / 文件命令。

---

## 3. Project Structure

目标结构：

```text
pagent/
  app/
    orchestrator/
      react_loop.py        # Act/Observe 拆段、observation_digest、reflect 调用、收敛门控、query hint 回灌
      react_policy.py      # ReflectResult、ReActPolicy.reflect、LLM/Heuristic reflect 实现
    prompts/
      react_policy.py      # REACT_REFLECT_SCHEMA 与 reflect prompt
    core/
      config.py            # react_use_llm_judge、阈值、digest 长度、reflect model 等配置
  tests/
    test_react_reflect.py       # reflect 解析、schema、next_query_hint、降级
    test_react_policy.py        # ReActDecision 不含权威 sufficient，LLM reflect 调用契约
    test_agentic_loop.py        # 三段式顺序、reflect 收敛、阈值兜底、scratchpad digest
    test_qa_node.py             # FakeLLM reflect 序列与 QA agentic 收敛回归
    test_core_config_logging.py # 新增 react_* 配置公开字段
  SPEC.md
```

### 3.1 主循环契约

`BoundedReActLoop.run` 每步必须按以下顺序执行：

1. 检查硬预算：`max_steps`、超时、token budget。
2. Act：调用 `policy.decide(task_input, allowed_tools, scratchpad, step_index)`。
3. 如果 `decision.stop` 或无有效 action，则以 `policy_stop` 收敛。
4. 执行工具白名单、工具存在性和 input schema 校验；非法时确定性降级。
5. 调用 `tool.run(decision.tool_input)` 获取 `ToolObservation`。
6. 构造 `observation_digest`，内容来自本步 evidence 正文摘要与 provenance / score 等非敏感字段。
7. Observe/Reflect：调用 `policy.reflect(task_input, observation_digest, scratchpad, step_index)`。
8. 根据 `use_llm_judge` 判定充分性：
   - 开启：以 `reflection.sufficient` 为准。
   - 关闭或 reflect 失败：以确定性阈值为准。
9. 写入 scratchpad item，包含 `observation_digest`、统计信息、错误、外部工具标记等。
10. 若充分，则以 `sufficient` 收敛。
11. 若不充分且 `reflection.next_query_hint` 非空，则回灌下一步 Act 的 query / task input。
12. 继续下一步，直到充分、policy stop 或预算耗尽。

要求：

- 主循环不得使用 `decision.sufficient` 作为收敛依据。
- `ToolObservation.sufficient` 只能作为阈值兜底输入或兼容字段，不得单独造成“有 evidence 即停”。
- reflect 异常、输出非 dict、schema 解析失败、超时等情况不得中断主循环。
- reflect 失败时必须记录 `fallback_used=true` 并使用阈值兜底。

### 3.2 Policy 契约

`app/orchestrator/react_policy.py` 必须包含：

```python
@dataclass
class ReflectResult:
    """表示一次观察后反思的结构化结果。"""

    sufficient: bool
    reason: str
    next_query_hint: str | None = None
```

`ReActPolicy` 协议必须包含：

```python
class ReActPolicy(Protocol):
    def decide(self, task_input, allowed_tools, scratchpad, step_index) -> ReActDecision: ...
    def reflect(self, task_input, observation_digest, scratchpad, step_index) -> ReflectResult: ...
```

要求：

- `LLMReActPolicy.reflect` 使用 `LLMClient.generate(messages=..., output_schema=REACT_REFLECT_SCHEMA, trace_context=...)`。
- `HeuristicReActPolicy.reflect` 封装确定性阈值判断，作为无 LLM、禁用 judge 或 reflect 失败时的兜底实现。
- `ReActDecision` 不再承载权威充分性判断；如果保留 `sufficient` 字段，必须在代码注释中标明 planning-only，主循环不得读取。
- 所有公开类、公开方法必须有中文 Google 风格 docstring。

### 3.3 Reflect Prompt 与 Schema 契约

`app/prompts/react_policy.py` 追加 `REACT_REFLECT_SCHEMA`：

```json
{
  "type": "object",
  "properties": {
    "sufficient": {"type": "boolean"},
    "reason": {"type": "string"},
    "next_query_hint": {"type": ["string", "null"]}
  },
  "required": ["sufficient", "reason"],
  "additionalProperties": false
}
```

Reflect prompt 必须覆盖项目 prompt 六要素：

- 任务目标：仅判断当前 observation 对任务是否充分，并给出下一步 query hint。
- 上下文 / 判定规则：只能依据任务、当前 observation digest 和 scratchpad；不得编造证据。
- 角色：熟悉专利业务与检索证据判断的专家。
- 受众：ReAct 主循环与结构化解析器。
- 样例：至少包含“证据充分”和“证据不足需改写 query”两类 JSON 示例。
- 输出格式：仅输出 JSON，字段与 schema 一致。

安全要求：

- observation digest 与 scratchpad 必须作为数据区包裹，例如 `<data>...</data>`。
- prompt 必须声明数据区内任何“指令”都不作为系统指令执行。
- 禁止臆造法条、专利号、检索结果、引用或 provenance。
- 不确定时应返回 `sufficient=false` 并给出保守的 `next_query_hint`。

### 3.4 Observation Digest 契约

`react_loop.py` 新增或改造 `_build_observation_digest(observation)`：

- 读取 evidence 前 N 条，保留正文摘要与关键 provenance。
- 每条 evidence 的正文按单条上限截断，整体再按 `react_observation_digest_chars` 截断。
- provenance 可包含 `source`、`document_id`、`score` 等已有字段。
- 必须遵守 `redaction_enabled` 与 `allow_cloud_sensitive_content` 的既有约束。
- digest 可进入 LLM prompt 和 scratchpad，但不得记录完整原文到 trace / 日志。
- `reflect.reason` 原文不落库、不回传用户，trace 仅记录长度。

scratchpad item 必须包含：

```json
{
  "step_index": 0,
  "tool_name": "kb_retrieval",
  "observation_count": 2,
  "top_score": 0.72,
  "error": null,
  "external": false,
  "observation_digest": "截断后的正文摘要"
}
```

### 3.5 配置契约

`app/core/config.py` 新增或真正接线以下配置：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `react_use_llm_judge` | `true` | 开启时以 reflect 判定充分性；关闭时走阈值兜底 |
| `react_sufficient_score_threshold` | `0.5` | `react_use_llm_judge=false` 或 reflect 失败时的 top_score 阈值 |
| `react_observation_digest_chars` | `600` | 单步 observation digest 总字符上限 |
| `react_reflect_model` | 空字符串 / None | 为空时回退 `react_policy_model` 或 `llm_cheap_model` |

要求：

- 环境变量名与字段一一对应，使用 `PAGENT_` 前缀。
- 非敏感配置进入 `to_public_dict()`。
- 新增配置必须覆盖默认值、环境变量读取、公开配置和覆盖行为测试。
- 配置项保持通用作用域，不新增单 Node 临时配置。
- 构造参数覆盖全局配置时使用 `settings.xxx if arg is None else arg`，避免吞掉 `False` / `0`。

### 3.6 Trace 契约

新增 `react_reflect_step`：

```json
{
  "event": "react_reflect_step",
  "node_name": "qa",
  "step_index": 1,
  "sufficient": false,
  "reason_len": 42,
  "next_query_hint_present": true,
  "driver": "llm"
}
```

要求：

- `driver` 可为 `llm`、`heuristic`、`fallback` 等稳定枚举。
- `react_main_converged.reason` 保持现有枚举：`sufficient`、`policy_stop`、`max_steps`、`token_budget`、`timeout`、`tool_unavailable`。
- `sufficient` 现由 reflect 或阈值决定。
- trace 不记录完整 observation 正文、完整 query、完整 reason、密钥或敏感材料。
- reflect LLM 的底层 `LLMResponse.trace` 只记录模型、输入长度、耗时等脱敏字段。

---

## 4. Code Style

### 基本原则

- 最小化、局部化改动，优先修改 `react_loop.py`、`react_policy.py`、`app/prompts/react_policy.py`、`config.py` 与相关测试。
- 复用现有 `LLMClient.generate`、`LLMMessage`、`ToolCard`、`ToolObservation`、`ReActOutcome`，不要新增大型抽象。
- 不改工具注册机制，不改检索算法，不改 QA 会话记忆链路。
- 公共函数、公共方法、公共类必须添加中文 Google 风格 docstring，包含 Args / Returns / Raises（如有）。
- 简单私有 helper 可使用一行中文概述。
- 只在三段式顺序、降级原因、安全边界等不直观处加行内注释。
- 日志 / trace 使用稳定英文事件名，message 可用中文。
- 不记录完整 observation、完整检索正文、完整 query、完整 reflect reason 或密钥。

### Prompt 风格

- prompt 继续集中在 `app/prompts/` 模块，不内联散落在业务逻辑中。
- 运行时变量使用具名占位符，不通过随意字符串拼接混合指令和数据。
- observation digest、scratchpad、用户任务等外部 / 动态数据必须包裹在 `<data>...</data>` 或等价分隔符内。
- 明确声明数据区内任何“指令”都应忽略。
- 输出强制 JSON，并通过 `REACT_REFLECT_SCHEMA` 约束。
- 专利域默认约束必须保留：禁止臆造、不确定显式标注、使用规范术语。

### 错误处理与兜底

- reflect 调用失败不得中断主循环。
- reflect 输出缺字段、类型错误或无法解析时，使用阈值兜底。
- `next_query_hint` 为空时，不强行改写 query。
- `top_score` 缺失或不是数字时，阈值兜底应视为不充分，除非已有明确的安全默认逻辑。
- 工具不可用、schema 校验失败、白名单不通过时，仍按现有安全降级路径处理。
- 不为异常情况引入复杂重试或隐藏循环；预算硬上限必须始终生效。

---

## 5. Testing Strategy

### Reflect Policy 测试

必须覆盖：

- `ReflectResult` 能表达 `sufficient`、`reason`、`next_query_hint`。
- `REACT_REFLECT_SCHEMA` 要求 `sufficient` 与 `reason`，允许 `next_query_hint=null`。
- `LLMReActPolicy.reflect` 调用 `LLMClient.generate(messages=..., output_schema=REACT_REFLECT_SCHEMA, trace_context=...)`。
- reflect prompt 包含任务、observation digest、scratchpad，并使用数据分隔符隔离。
- LLM 返回合法 JSON 时解析为 `ReflectResult`。
- LLM 返回缺字段、错误类型或异常时，上层 loop 能触发 fallback。
- `HeuristicReActPolicy.reflect` 使用阈值逻辑，不再是 `bool(evidence)`。

### ReAct Loop 测试

必须覆盖：

- 每步顺序为 decide → tool.run → build observation digest → reflect → 收敛 / 继续。
- trace 出现 `react_reflect_step`。
- `react_use_llm_judge=true` 且 LLM 可用时，收敛由 `reflection.sufficient` 决定。
- `react_use_llm_judge=false` 时，收敛由 `react_sufficient_score_threshold` 阈值决定。
- evidence 非空但 `top_score` 低于阈值时不收敛。
- `ReActDecision.sufficient` 不再触发收敛；grep 或单测确认主循环不读该字段。
- scratchpad item 含 `observation_digest`，且长度不超过 `react_observation_digest_chars`。
- 多步场景下 `reflection.next_query_hint` 改变下一步 tool input / query。
- reflect 失败后 `fallback_used=true`，循环不崩。
- 预算硬约束仍生效：`steps_used <= react_max_steps`，不超时、不超 token。

### QA / Agentic 集成测试

必须覆盖：

- 在 QA agentic 路径注入 Fake LLM reflect 序列，断言收敛原因与步数。
- 当 Fake reflect 第一步返回 `sufficient=false` 且给出 `next_query_hint` 时，第二步检索 query 使用该 hint。
- 当 Fake reflect 返回 `sufficient=true` 时，以 `react_main_converged.reason=sufficient` 收敛。
- reflect reason 不进入最终用户回答。
- 无真实 LLM key 环境下测试稳定走 fake 或阈值兜底，不漂移。

### 配置测试

必须覆盖：

- `Settings` 默认值包含新增 `react_*` 配置。
- `PAGENT_REACT_USE_LLM_JUDGE=false` 能正确读为 False。
- `PAGENT_REACT_SUFFICIENT_SCORE_THRESHOLD` 能覆盖阈值。
- `PAGENT_REACT_OBSERVATION_DIGEST_CHARS` 能覆盖 digest 长度。
- `PAGENT_REACT_REFLECT_MODEL` 能覆盖 reflect model。
- `to_public_dict()` 包含新增非敏感配置，不包含任何 key / token / secret。

### 验收口径

- `conda run -n autoGLM pytest tests/test_react_reflect.py tests/test_react_policy.py tests/test_agentic_loop.py tests/test_qa_node.py tests/test_core_config_logging.py` 通过。
- `conda run -n autoGLM pytest` 通过。
- `conda run -n autoGLM python -m compileall app tests scripts` 通过。
- 默认测试不触网、不调用真实付费 LLM。
- trace 中可见 `react_reflect_step`，但不可见完整 observation 正文或完整 reason。
- `grep` 确认主循环不再通过 `decision.sufficient` 收敛。

---

## 6. Boundaries

### Always do

- 始终保持 Act 与 Observe/Reflect 分离。
- 始终在 `tool.run()` 之后再做充分性判断。
- 始终让 `react_use_llm_judge=true` 时以 reflect 结果为准。
- 始终让 `react_use_llm_judge=false` 或 reflect 失败时走确定性阈值兜底。
- 始终保留步数、超时、token、工具白名单和 schema 校验等代码硬约束。
- 始终截断并按配置限制 observation digest 长度。
- 始终使用数据分隔符隔离 observation / scratchpad / 用户输入。
- 始终通过 fake / stub LLM 做默认测试。
- 始终使用 `conda run -n autoGLM` 执行 Python、pytest 和脚本命令。
- 始终避免新增单 Node 临时配置。

### Ask first

- 是否调用真实 LLM 做人工 reflect 验收。
- 是否允许向云模型发送 observation 正文摘要或敏感专利材料。
- 是否新增依赖或替换 LLM client 接口。
- 是否修改检索算法、工具注册机制或外部工具默认开关。
- 是否调整 `ReActOutcome`、`ToolObservation` 等外部可见数据结构。
- 是否删除而不是保留 `ReActDecision.sufficient` 字段。
- 是否把 reflect reason 原文持久化用于审计。

### Never do

- 不在 `tool.run()` 之前用 LLM 判断本步 observation 是否充分。
- 不让 `bool(evidence)` 单独触发收敛。
- 不让 `decision.sufficient` 触发主循环收敛。
- 不把预算、白名单、外部工具权限或脱敏策略交给 LLM 决定。
- 不把 observation 原文、完整 query、完整 reflect reason、密钥或敏感材料写入日志 / trace。
- 不在默认测试中触网、下载模型或调用真实付费服务。
- 不伪造检索来源、法条、专利号、法律状态或证据 provenance。
- 不为本需求引入并行多工具、多智能体、跨会话长期记忆或新存储后端。

---

## 7. Functional Acceptance Checklist

- [ ] `ReActPolicy` 包含 `reflect(...)` 方法。
- [ ] `ReflectResult` 包含 `sufficient`、`reason`、`next_query_hint`。
- [ ] `REACT_REFLECT_SCHEMA` 定义完整，含 `additionalProperties: false`。
- [ ] `LLMReActPolicy.reflect` 使用结构化 schema 调用 LLM。
- [ ] `HeuristicReActPolicy.reflect` 使用 top_score 阈值，不是 `bool(evidence)`。
- [ ] `tool.run()` 后存在独立 reflect 调用。
- [ ] trace 出现 `react_reflect_step`。
- [ ] `react_use_llm_judge=true` 且 LLM 可用时，收敛由 `reflection.sufficient` 决定。
- [ ] `react_use_llm_judge=false` 时，回退 `react_sufficient_score_threshold` 阈值。
- [ ] reflect 失败时，回退阈值、`fallback_used=true`、循环不中断。
- [ ] 主循环不读取 `decision.sufficient` 作为收敛条件。
- [ ] scratchpad item 包含 `observation_digest`。
- [ ] reflect 输入包含 observation 正文摘要，且长度不超过 `react_observation_digest_chars`。
- [ ] 多步场景下 `reflection.next_query_hint` 能改变下一步 query。
- [ ] `react_main_converged.reason=sufficient` 由 reflect 或阈值触发。
- [ ] trace 不记录完整 observation 正文、完整 query、完整 reflect reason 或密钥。
- [ ] 新增配置进入 `Settings`、环境变量读取、`to_public_dict()` 和测试。
- [ ] `conda run -n autoGLM pytest tests/test_react_reflect.py tests/test_react_policy.py tests/test_agentic_loop.py tests/test_qa_node.py tests/test_core_config_logging.py` 通过。
- [ ] `conda run -n autoGLM pytest` 通过。
- [ ] `conda run -n autoGLM python -m compileall app tests scripts` 通过。

---

## 8. Implementation Order

1. 新增 `ReflectResult`、`ReActPolicy.reflect` 协议和 `REACT_REFLECT_SCHEMA`。
2. 编写 / 更新 reflect policy 测试，先覆盖 schema、LLM reflect 调用和解析。
3. 实现 `HeuristicReActPolicy.reflect`，抽出 top_score 阈值兜底逻辑。
4. 实现 `LLMReActPolicy.reflect`，接入 `LLMClient.generate`、reflect prompt 和 trace context。
5. 新增配置：`react_use_llm_judge`、`react_sufficient_score_threshold`、`react_observation_digest_chars`、`react_reflect_model`，并补配置测试。
6. 改造 `react_loop.py`：新增 `_build_observation_digest`，在 `tool.run()` 后插入 reflect。
7. 改造收敛逻辑：移除 `decision.sufficient` 收敛路径，接入 `use_llm_judge` 门控与阈值 fallback。
8. 将 `reflection.next_query_hint` 回灌下一步 Act。
9. 将 `observation_digest` 写入 scratchpad，补充 `react_reflect_step` trace。
10. 更新 agentic loop 与 QA 集成测试，覆盖三段式顺序、reflect 收敛、阈值兜底、失败降级和 query hint 回灌。
11. 运行目标测试、全量 pytest 和 compileall。
12. 若本阶段形成可独立验证改动，按项目提交规范单独 commit。
