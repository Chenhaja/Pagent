# R9 CoT 推理链采集与分析实施计划

## 背景

本计划基于根目录 `SPEC.md` 生成，用于落地 R9「CoT 推理链采集与分析」。目标是在不改变 ReAct 决策、反思、检索与收敛业务行为的前提下，将模型推理信号作为只读观测数据接入现有 R8 结构化日志体系，并提供离线 eval 分析能力。

当前代码基线：

- `app/core/logging.py` 已有 `JsonLineFormatter`、`PrettyFormatter`、`log_event()`、上下文注入、字段脱敏截断和 `llm_call` 日志基础。
- `app/core/log_context.py` 已有 request/session/trace/node/task 上下文字段。
- `app/core/security.py` 已有 `redact_sensitive_text()`，覆盖 `sk-...`、`Bearer ...`、`password=...`、`token=...`、`api_key=...` 并支持截断。
- `app/core/config.py` 已有 R8 日志配置、环境变量读取和 `to_public_dict()`，尚无 `cot_*` 配置。
- `app/tools/llm.py` 已有 `LLMResponse`、`FakeLLMClient`、`OpenAICompatibleClient`、`LLMTraceSink`、`LoggingLLMTraceSink`，尚无 `reasoning_text` 与 reasoning 元数据。
- `app/orchestrator/react_policy.py` 中 `LLMReActPolicy.decide()` / `reflect()` 当前只返回结构化 `ReActDecision` / `ReflectResult`，未暴露 LLM response 的原生 reasoning。
- `app/orchestrator/react_loop.py` 已在 scratchpad/trace 中只记录 thought/reason 长度，适合作为只读旁路采集点。
- `eval/` 目录当前不存在，需要新增离线分析模块。

本计划只拆解实现路径与验收任务；实现阶段再修改代码。

---

## 依赖图

```text
SPEC.md
  -> Safety boundary
      -> app/core/security.py                    # 复用脱敏截断
      -> app/core/logging.py                     # 主日志不得含正文
      -> tests/test_security_compliance.py

  -> CoT config contract
      -> app/core/config.py                      # cot_* 默认值、env、public dict
      -> tests/test_core_config_logging.py
      -> app/core/reasoning_sink.py              # max chars、sink path、local gate
      -> app/orchestrator/react_loop.py          # capture enabled/source/local 判断

  -> Reasoning sink contract
      -> app/core/reasoning_sink.py              # ReasoningRecord、Noop、Jsonl
      -> tests/test_reasoning_sink.py
      -> app/orchestrator/react_loop.py          # 旁路写入 sink

  -> LLM reasoning extraction contract
      -> app/tools/llm.py                        # LLMResponse.reasoning_text、trace 元数据
      -> tests/test_cot_capture.py
      -> app/orchestrator/react_policy.py        # 需要把 LLM response reasoning 暴露给 loop
      -> app/orchestrator/react_loop.py          # 采集 native_cot
      -> app/tools/llm.py::LoggingLLMTraceSink   # llm_call 增补 has_reasoning/reasoning_chars

  -> ReAct observation path
      -> app/orchestrator/react_policy.py        # policy/reflect 返回值或旁路元数据载体
      -> app/orchestrator/react_loop.py          # Act/Reflect 后采集 thought/reason/native_cot
      -> tests/test_agentic_loop.py
      -> tests/test_cot_capture.py

  -> Eval offline analysis
      -> eval/cot_analysis.py                    # 信号消费检测、归因报告
      -> tests 或 eval 测试样本                 # 不触网、不依赖真实模型

  -> Final verification
      -> targeted pytest
      -> full pytest
      -> compileall app tests scripts eval
```

---

## 关键设计决策

### 1. trace 契约变更检查点

`LLMResponse.trace` 会按 SPEC 新增可选无正文字段：

- `reasoning_chars: int`
- `has_reasoning: bool`

这是向后兼容增量字段，但属于 SPEC 标注的 Ask first 项。实现前需要用户明确确认可以落地该 trace 字段扩展。

### 2. 原生 reasoning 的传递方式

`LLMResponse.reasoning_text` 在 `app/tools/llm.py` 产生，但当前 `LLMReActPolicy.decide()` / `reflect()` 只返回 `ReActDecision` / `ReflectResult`。为了让 `react_loop.py` 采集 native CoT，有两种实现口径：

- 推荐：在 `react_policy.py` 内部用私有属性记录最近一次 `LLMResponse.reasoning_text` 与 trace 元数据，例如 `last_decision_reasoning` / `last_reflect_reasoning`。这不改变公开 dataclass 契约，改动小。
- 备选：新增包装返回类型，携带 decision/result 与 response 元数据。该方式更显式，但会扩大 `ReActPolicy` 协议变更面。

实施阶段优先采用推荐方案，除非 review 发现现有测试或架构更适合显式包装类型。

### 3. 只读旁路原则

推理正文只允许从 LLM response / thought / reason 流向 reasoning sink，不能反向进入：

- `task_input`
- `scratchpad`
- observation digest
- 后续 `decide` / `reflect` prompt
- `LLMResponse.trace`
- 主 stdout 日志
- 用户返回

### 4. 纵向切片原则

每个阶段交付一条可验证闭环，而不是只改一层：

1. 先做 reasoning sink：正文脱敏截断写入的最小安全闭环。
2. 再做 `cot_*` 配置：默认关闭、local gate、public dict 的控制闭环。
3. 再做 LLM extraction：真实 / fake LLM response 都能产生 reasoning 元数据。
4. 再做 ReAct 旁路：Act/Reflect 后采集三类信号，但不改变收敛。
5. 再做 eval：离线读取样本，做信号消费检测与 outcome 关联。
6. 最后做安全合规与全量验证。

---

## Phase 0 — 口径确认与基线锁定

### 目标

确认本轮只做观测/评估用途的 CoT 采集与分析，不改变在线控制路径。

### 实施要点

- 确认允许新增 `LLMResponse.trace.reasoning_chars` / `has_reasoning`。
- 不引入第三方依赖。
- 不修改 ReAct 收敛逻辑、检索算法、工具注册、会话记忆链路。
- 默认不采集推理正文。
- 生产环境强制不采集正文。
- 默认测试不触网、不调用真实 LLM。

### 验收标准

- `tasks/plan.md` / `tasks/todo.md` 明确边界。
- 用户确认 trace 可选字段扩展后，才进入实现阶段。

### 验证步骤

- 人工 review 本计划。
- 人工确认 Ask first 项。

### 检查点

- Checkpoint 0：确认 `LLMResponse.trace` 可新增无正文元数据字段。

---

## Phase 1 — Reasoning sink 安全写入闭环

### 目标

新增独立 reasoning sink，使推理正文在允许采集时能脱敏、截断并写入 JSONL；默认实现不写任何正文。

### 触达文件

- 新增 `app/core/reasoning_sink.py`
- 新增 `tests/test_reasoning_sink.py`
- 复用 `app/core/security.py`

### 实施任务

1. 定义 `ReasoningRecord`，字段包含 `request_id`、`node_name`、`task_type`、`step_index`、`source`、`text`、`outcome`。
2. 定义 `ReasoningTraceSink` 协议。
3. 实现 `NoopReasoningSink.write()`。
4. 实现 `JsonlReasoningSink.write()`。
5. 写入前调用 `redact_sensitive_text(text, max_length=cot_max_chars)`。
6. sink 内部捕获异常并吞掉。
7. 不写 stdout，不混入主日志。

### 验收标准

- JSONL sink 写入合法 JSON Lines。
- 正文已脱敏且按上限截断。
- Noop sink 不产生副作用。
- sink 异常不向外抛出。

### 验证步骤

```bash
conda run -n autoGLM pytest tests/test_reasoning_sink.py
```

### 检查点

- Checkpoint 1：可以独立验证“安全写正文到独立 sink”的最小能力。

---

## Phase 2 — CoT 配置控制闭环

### 目标

新增 `cot_*` 配置，控制正文采集开关、来源、截断长度、sink 路径和 local 环境限制。

### 触达文件

- `app/core/config.py`
- `tests/test_core_config_logging.py`

### 实施任务

1. `Settings` 新增：
   - `cot_capture_enabled: bool = False`
   - `cot_capture_sources: list[str] | str = ["native_cot", "thought", "reason"]` 或保持字符串并提供解析 helper
   - `cot_max_chars: int = 1200`
   - `cot_sink_path: str = "logs/reasoning.jsonl"`
   - `cot_require_local_env: bool = True`
2. 更新 `Settings` 中文 docstring。
3. `get_settings()` 读取：
   - `PAGENT_COT_CAPTURE_ENABLED`
   - `PAGENT_COT_CAPTURE_SOURCES`
   - `PAGENT_COT_MAX_CHARS`
   - `PAGENT_COT_SINK_PATH`
   - `PAGENT_COT_REQUIRE_LOCAL_ENV`
4. 新增来源列表解析，支持逗号分隔字符串。
5. 更新 `to_public_dict()`，加入非敏感 `cot_*` 配置。

### 验收标准

- 默认关闭正文采集。
- env 可覆盖每个配置项。
- `to_public_dict()` 包含 `cot_*` 且不暴露敏感字段。
- 配置项保持全局通用作用域。

### 验证步骤

```bash
conda run -n autoGLM pytest tests/test_core_config_logging.py
```

### 检查点

- Checkpoint 2：可以从配置层证明默认安全、local gate 可控。

---

## Phase 3 — LLM reasoning 提取与 trace 元数据闭环

### 目标

让真实 OpenAI 兼容 client 与 Fake client 都能携带可选 `reasoning_text`，并在 trace / llm_call 中只暴露无正文元数据。

### 触达文件

- `app/tools/llm.py`
- `tests/test_llm_tool.py`
- `tests/test_cot_capture.py`

### 实施任务

1. `LLMResponse` 新增 `reasoning_text: str | None = None`。
2. `FakeLLMClient` 支持构造时注入 `reasoning_text`。
3. Fake trace 增加 `has_reasoning` / `reasoning_chars`。
4. `OpenAICompatibleClient.generate()` 从 response payload 提取：
   - `choices[0].message.reasoning_content`
   - `choices[0].message.reasoning`
   - 如有 streaming/delta 测试样本，再兼容 delta 聚合结构
5. `OpenAICompatibleClient` 成功和错误响应都保证 trace 含 reasoning 元数据默认值。
6. `LoggingLLMTraceSink` 继续通过 `_DROPPED_TRACE_FIELDS` 排除正文，允许输出新增元数据。
7. 测试断言 trace 不含 `reasoning_text` 正文。

### 验收标准

- 有 reasoning 字段时 `LLMResponse.reasoning_text` 被提取。
- 无 reasoning 字段时为 `None` 且不报错。
- trace 只含 `has_reasoning` / `reasoning_chars`。
- `llm_call` 日志能显示新增元数据且不含正文。
- 默认测试不触网。

### 验证步骤

```bash
conda run -n autoGLM pytest tests/test_llm_tool.py tests/test_cot_capture.py
```

### 检查点

- Checkpoint 3：可以独立验证“模型响应 → 进程内 reasoning_text → 无正文 trace 元数据”。

---

## Phase 4 — ReAct 旁路采集闭环

### 目标

在 ReAct Act / Reflect 后采集 `native_cot`、`thought`、`reason` 三类信号，写 `cot_captured` 元数据事件，并在开关允许时写独立 sink；不改变主循环行为。

### 触达文件

- `app/orchestrator/react_policy.py`
- `app/orchestrator/react_loop.py`
- `app/core/reasoning_sink.py`
- `tests/test_agentic_loop.py`
- `tests/test_cot_capture.py`

### 实施任务

1. 在 `LLMReActPolicy` 中保留最近一次 decide/reflect 的 `reasoning_text` 和 reasoning 元数据，供 loop 只读读取。
2. `BoundedReActLoop.__init__()` 接收可选 `settings` / `reasoning_sink` / cot 覆盖参数，默认继承配置；覆盖逻辑使用 `settings.xxx if arg is None else arg`。
3. 新增私有 helper 判断当前是否允许写正文：
   - `cot_capture_enabled=True`
   - `source in cot_capture_sources`
   - 若 `cot_require_local_env=True`，则 `environment == "local"`
4. 新增私有 helper `_capture_reasoning_signal(...)`：
   - 始终输出 `cot_captured` 元数据事件。
   - 仅允许时写 sink 正文。
   - 捕获异常并吞掉。
5. Act 后采集：
   - policy native CoT（如存在）
   - `decision.thought`
6. Reflect 后采集：
   - reflect native CoT（如存在）
   - `reflection.reason`
7. `react_step` 增补 `has_reasoning`、`reasoning_chars` 元数据。
8. 保持 scratchpad 仍只记录 `thought_len`、`reason_len` 等摘要。

### 验收标准

- 默认配置只输出元数据，不写正文。
- local + 开关开启时写脱敏、截断正文。
- prod + `cot_require_local_env=True` 强制不写正文。
- 采集失败不影响最终 outcome。
- 推理正文不进入 scratchpad、task_input、后续 prompt。
- 原有 ReAct 收敛结果不变。

### 验证步骤

```bash
conda run -n autoGLM pytest tests/test_cot_capture.py tests/test_agentic_loop.py
```

### 检查点

- Checkpoint 4：可以跑通“ReAct 一步 → cot_captured 元数据 → 可选独立 sink 正文”的完整在线观测路径。

---

## Phase 5 — 安全合规与不回灌证明闭环

### 目标

用测试证明 CoT / thought / reason 正文不会出现在主日志、用户输出、trace、scratchpad 或后续 prompt 中。

### 触达文件

- `tests/test_security_compliance.py`
- `tests/test_agentic_loop.py`
- `tests/test_cot_capture.py`

### 实施任务

1. 构造包含敏感信息的 reasoning 文本样本。
2. 断言 reasoning sink 写入文本已脱敏。
3. 捕获主日志，断言不包含 reasoning 正文。
4. 捕获 LLM trace，断言不包含 reasoning 正文。
5. 使用测试 policy / fake client 记录后续 prompt 输入，断言不包含上一步 reasoning 正文。
6. 断言 scratchpad 不包含 reasoning 正文。
7. 断言用户侧 outcome 不包含 reasoning 正文。

### 验收标准

- 主 stdout 日志无 CoT / thought / reason 正文。
- 用户返回无 CoT / reason 正文。
- trace 无正文。
- scratchpad 与后续 prompt 无正文。
- sink 正文脱敏且截断。

### 验证步骤

```bash
conda run -n autoGLM pytest tests/test_security_compliance.py tests/test_agentic_loop.py tests/test_cot_capture.py
```

### 检查点

- Checkpoint 5：完成 R9 最重要安全边界证明。

---

## Phase 6 — Eval 离线分析闭环

### 目标

新增 `eval/cot_analysis.py`，支持对 reasoning sink 样本做信号消费检测和 outcome 关联分析。

### 触达文件

- 新增 `eval/cot_analysis.py`
- 新增或扩展 eval 相关测试文件

### 实施任务

1. 定义读取/标准化 `ReasoningRecord` JSONL 的函数。
2. 实现信号消费检测：
   - `next_query_hint` 子串/关键词命中
   - 预算指令命中
   - 未选工具命中
3. 实现 outcome 关联汇总：
   - source 维度样本数
   - signal 命中率
   - sufficient 分布
   - converged_reason / steps_used 关联摘要
4. 输出结构化 dict，便于 JSON 或表格展示。
5. 缺失字段、空文本、未知 source 安全兜底。
6. 测试使用注入样本，不依赖真实模型。

### 验收标准

- 能正确识别注入样本中的 hint / 预算 / 未选工具引用。
- 能输出包含命中率与 outcome 关联字段的结构化结果。
- 不修改 prompt，不进入在线路径。

### 验证步骤

```bash
conda run -n autoGLM pytest tests/test_cot_capture.py
conda run -n autoGLM python -m compileall eval
```

如新增专门测试文件，则运行：

```bash
conda run -n autoGLM pytest tests/test_cot_analysis.py
```

### 检查点

- Checkpoint 6：离线分析可独立运行，且不会影响在线链路。

---

## Phase 7 — 全量验证与分阶段提交

### 目标

完成目标测试、全量测试和编译检查，并按项目规范分小步提交。

### 实施任务

1. 运行 reasoning 目标测试。
2. 运行配置、ReAct、安全合规测试。
3. 运行全量 pytest。
4. 运行 compileall。
5. 检查 git diff，确保无无关改动、无密钥、无临时产物。
6. 按阶段提交，不 push。

### 验收标准

- 所有目标测试通过。
- 全量 pytest 通过。
- compileall 通过。
- 每个 commit 都是可独立验证的小功能。

### 验证步骤

```bash
conda run -n autoGLM pytest tests/test_reasoning_sink.py tests/test_cot_capture.py
conda run -n autoGLM pytest tests/test_core_config_logging.py tests/test_agentic_loop.py tests/test_security_compliance.py
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests scripts eval
```

### 检查点

- Checkpoint 7：进入最终 review / commit 阶段。

---

## 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| CoT 正文泄漏到主日志或 prompt | 主日志字段白名单化元数据；测试 grep 正文；scratchpad 只存长度 |
| `LLMReActPolicy` 难以把 reasoning 传回 loop | 优先使用私有 last-reasoning 属性，避免扩大 dataclass 契约 |
| trace 字段扩展影响下游 | 仅新增可选无正文字段；实现前人工确认 |
| sink 写入失败影响主流程 | sink 和采集 helper 全部吞掉异常 |
| prod 误采集正文 | `cot_require_local_env=True` 默认强制 local gate；测试覆盖 prod 场景 |
| eval 被误用于在线控制 | eval 模块不被在线代码 import；计划和测试明确不回灌 |

---

## 人工 review 清单

- [ ] 是否确认允许 `LLMResponse.trace` 新增 `reasoning_chars` / `has_reasoning`？
- [ ] 是否接受 `LLMReActPolicy` 用私有 last-reasoning 属性向 loop 暴露原生 CoT？
- [ ] 是否确认 `cot_sink_path=logs/reasoning.jsonl` 作为默认本地路径？
- [ ] 是否确认 eval 输出先做结构化 dict / JSON，不做 CLI 或可视化？
- [ ] 是否确认本轮不新增第三方依赖、不引入异步 sink？
