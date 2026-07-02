# CoT 推理链采集与分析规格说明

## 1. Objective

### 目标

在不改变 ReAct 决策、反思、检索与收敛业务行为的前提下，将模型推理信号作为只读观测数据接入 R8 结构化日志体系，用于开发与离线评估阶段验证 prompt 信号是否被消费、归因推理模式与结果质量之间的关系。

完成标准：

- `app/tools/llm.py` 能从 OpenAI 兼容响应中提取可选 `reasoning_content` / `reasoning`，写入 `LLMResponse.reasoning_text`。
- `LLMResponse.trace` 仅新增无正文元数据字段：`reasoning_chars`、`has_reasoning`。
- 新增独立 reasoning sink：默认 `NoopReasoningSink`，开发开关开启时用 `JsonlReasoningSink` 写入脱敏、截断后的推理正文。
- ReAct 主循环在 Act / Reflect 后旁路采集 `native_cot`、`thought`、`reason` 三类信号。
- 主日志只记录 `cot_captured`、`react_step`、`llm_call` 等无正文元数据事件。
- 默认不采集推理正文；生产环境在 `cot_require_local_env=true` 时即使显式开启也强制不采集正文。
- 推理正文不进入用户返回、主 stdout 日志、scratchpad、task_input 或后续 prompt。
- `eval/` 增加离线分析能力，支持信号消费检测与有效性归因样本产出。
- 默认测试不触网、不调用真实模型。

### 目标用户

- 本地开发者：判断模型是否读取了 `next_query_hint`、预算指令、工具白名单等 prompt 信号。
- Prompt / 评估人员：离线分析哪些推理模式更可能导向有效停止、冗余步骤或失败收敛。
- 线上排障人员：通过无正文元数据确认推理信号是否存在、长度是否异常、是否被采集，但不接触 CoT 正文。

### 非目标

- 不向终端用户展示 CoT 或完整 `reason` 正文。
- 不用推理正文改写下一步决策、反思、检索 query 或收敛逻辑。
- 不引入 OpenTelemetry、LangSmith、外部日志 SDK、远程观测服务或新存储后端。
- 不强制切换到推理模型；无原生 reasoning tokens 时退回结构化 `thought` / `reason` 元数据。
- 不改变 `ReActDecision`、`ReflectResult`、`ToolObservation`、`ReActOutcome` 既有业务契约。

---

## 2. Commands

项目使用 conda 环境 `autoGLM`。所有 Python、pytest、脚本命令必须通过 `conda run -n autoGLM` 执行，不能依赖 `conda activate` 的跨命令状态。

```bash
# reasoning sink 与 CoT 采集目标测试
conda run -n autoGLM pytest tests/test_reasoning_sink.py tests/test_cot_capture.py

# 配置、ReAct 旁路、安全合规目标测试
conda run -n autoGLM pytest tests/test_core_config_logging.py tests/test_agentic_loop.py tests/test_security_compliance.py

# 全量测试
conda run -n autoGLM pytest

# 编译检查
conda run -n autoGLM python -m compileall app tests scripts eval
```

约束：

- 默认测试不触网、不调用真实 LLM。
- 不新增第三方依赖；如确需新增，必须先确认并同步 `requirements.txt`。
- 不执行破坏性 git / 文件命令。
- 不执行 `git push`、`git reset --hard`、强制推送等危险操作，除非用户明确确认。
- 每完成一个可独立验证的小阶段，按项目规范单独 commit。

---

## 3. Project Structure

目标结构：

```text
pagent/
  app/
    core/
      reasoning_sink.py   # 新增：ReasoningTraceSink / ReasoningRecord / NoopReasoningSink / JsonlReasoningSink
      config.py           # 新增 cot_* 配置、环境变量读取、to_public_dict
      logging.py          # 继续承载 R8 结构化日志事件输出
      security.py         # 复用 redact_sensitive_text 等脱敏能力
    tools/
      llm.py              # 提取 reasoning_content；LLMResponse.reasoning_text；trace 元数据字段
    orchestrator/
      react_loop.py       # Act / Reflect 后只读旁路采集推理信号
  eval/
    cot_analysis.py       # 新增：信号消费检测与有效性归因离线分析
  tests/
    test_reasoning_sink.py
    test_cot_capture.py
    test_agentic_loop.py
    test_core_config_logging.py
    test_security_compliance.py
  SPEC.md
```

### 3.1 推理信号契约

| 信号 | 来源 | 是否始终可得 | 用途 |
| --- | --- | --- | --- |
| `native_cot` | 推理模型返回的 `reasoning_content` / `reasoning` | 否 | 开发观测与离线归因假设 |
| `thought` | `REACT_DECISION_SCHEMA` 结构化字段 | 是 | 稳定决策轨迹 |
| `reason` | `REACT_REFLECT_SCHEMA` 结构化字段 | 是 | 充分性判定依据 |

要求：

- `thought` / `reason` 作为结构化自述基线，至少记录无正文元数据事件。
- `native_cot` 作为增强信号，缺失时不报错。
- 所有推理正文仅允许进入独立 reasoning sink，不进入主日志、用户输出或控制路径。
- CoT 不保证忠实，只能作为开发与评估阶段的分析信号，不能作为自动决策依据。

### 3.2 LLM 响应解析契约

`app/tools/llm.py` 中扩展 `LLMResponse`：

```python
@dataclass(frozen=True)
class LLMResponse:
    content: str
    trace: dict[str, object]
    reasoning_text: str | None = None
```

要求：

- 从 OpenAI 兼容响应中读取 `message.reasoning_content`、`message.reasoning`、delta 聚合后的 `reasoning_content` 或等价扩展字段。
- 字段不存在时 `reasoning_text=None`，不得抛异常。
- `LLMResponse.trace` 仅新增：
  - `reasoning_chars: int`
  - `has_reasoning: bool`
- `trace` 不新增任何推理正文字段。
- `FakeLLMClient` 支持在测试序列中注入 `reasoning_text`。
- 已有调用方在不关心 `reasoning_text` 时行为不变。

### 3.3 Reasoning sink 契约

新增 `app/core/reasoning_sink.py`：

```python
class ReasoningTraceSink(Protocol):
    """写入推理轨迹记录的协议。"""

    def write(self, record: ReasoningRecord) -> None: ...


@dataclass(frozen=True)
class ReasoningRecord:
    request_id: str | None
    node_name: str | None
    task_type: str
    step_index: int
    source: str
    text: str
    outcome: dict[str, object]
```

要求：

- `source` 仅允许：`native_cot`、`thought`、`reason`。
- `NoopReasoningSink.write(...)` 不做任何事。
- `JsonlReasoningSink.write(...)` 将单条记录写入独立 JSON Lines 文件。
- 写入前统一调用现有 `redact_sensitive_text` 或等价项目脱敏 helper。
- `text` 按 `cot_max_chars` 截断，截断标记稳定。
- sink 内部异常必须吞掉，不影响主流程。
- sink 不写 stdout，不混入主结构化日志。
- 不为 sink 引入后台线程、队列、重试或外部依赖。

### 3.4 配置契约

`app/core/config.py` 新增通用配置：

| 配置项 | 默认值 | 环境变量 | 说明 |
| --- | --- | --- | --- |
| `cot_capture_enabled` | `False` | `PAGENT_COT_CAPTURE_ENABLED` | 是否采集推理正文到 reasoning sink |
| `cot_capture_sources` | `["native_cot", "thought", "reason"]` | `PAGENT_COT_CAPTURE_SOURCES` | 允许采集正文的来源 |
| `cot_max_chars` | `1200` | `PAGENT_COT_MAX_CHARS` | 单条推理正文截断上限 |
| `cot_sink_path` | `logs/reasoning.jsonl` | `PAGENT_COT_SINK_PATH` | 本地独立 sink 文件路径 |
| `cot_require_local_env` | `True` | `PAGENT_COT_REQUIRE_LOCAL_ENV` | 是否仅允许 local 环境采集正文 |

要求：

- 新增非敏感配置全部进入 `to_public_dict()`。
- `cot_sink_path` 不包含密钥，允许进入公开配置用于排查。
- 环境变量使用项目统一 `PAGENT_` 前缀，并与字段一一对应。
- 覆盖配置时使用 `settings.xxx if arg is None else arg`，不得用 `or` 吞掉 `False`、`0` 或空列表等有效值。
- 配置保持全局通用作用域，不新增单 Node 临时配置。

### 3.5 ReAct 主循环接线契约

在 `app/orchestrator/react_loop.py` 中只读旁路采集：

- Act 后：
  - 若 `LLMResponse.reasoning_text` 存在，记录 `source="native_cot"`。
  - 对 `ReActDecision.thought` 记录 `source="thought"` 的元数据；开关允许时可写正文 sink。
- Reflect 后：
  - 若反思 LLM 返回 `reasoning_text`，记录 `source="native_cot"`。
  - 对 `ReflectResult.reason` 记录 `source="reason"` 的元数据；开关允许时可写正文 sink。

要求：

- 采集逻辑不得修改 `task_input`、`scratchpad`、工具 observation、下一步 prompt、决策对象或反思对象。
- 采集失败不得影响 ReAct 结果。
- outcome 只记录该步结果快照，例如：`sufficient`、`top_score`、`action`、`tool_name`、`converged_reason`、`steps_used` 等非正文信息。
- 不记录完整 query、prompt、检索正文或原始用户输入。

### 3.6 Trace 事件契约

主结构化日志新增 / 扩展无正文事件：

| event | level | 关键附加字段 | 触发点 |
| --- | --- | --- | --- |
| `cot_captured` | INFO | `task_type`, `step_index`, `source`, `reasoning_chars`, `has_reasoning`, `captured` | 每次采集推理信号 |
| `react_step` | INFO | 增补 `has_reasoning`, `reasoning_chars` | ReAct 每步 |
| `llm_call` | INFO/WARNING | 增补 `has_reasoning`, `reasoning_chars` | 每次 LLM 调用 |

要求：

- 主日志只记录规模、布尔、枚举、耗时、数量等元数据。
- `cot_captured.captured` 表示是否写入独立 reasoning sink 正文，不代表主日志含正文。
- `reason`、`thought`、`native_cot` 正文不得进入 `message` 或结构化 `fields`。
- 事件名稳定英文，`message` 使用中文。

### 3.7 Eval 离线分析契约

新增 `eval/cot_analysis.py`，只处理 reasoning sink 产物或测试样本，不进入在线路径。

能力：

- 信号消费检测：判断推理文本是否引用当步 `next_query_hint`、预算指令、未选工具名称等信号。
- 有效性归因：将推理记录的 `source`、文本特征、命中信号与 outcome 中的 `sufficient`、`steps_used`、`converged_reason` 等结果关联。
- 输出 JSON 或表格型结构化报告，供人工分析。

要求：

- 不自动修改 prompt。
- 不把分析结论回灌在线控制路径。
- 对缺失字段、空文本、未知 source 做安全兜底。
- 测试使用注入样本，不依赖真实模型输出。

---

## 4. Code Style

### 基本原则

- 最小化、局部化改动，优先集中在 `reasoning_sink.py`、`config.py`、`llm.py`、`react_loop.py`、`eval/cot_analysis.py` 与对应测试。
- 复用现有结构化日志、脱敏、配置读取、FakeLLMClient 测试能力，不重复造轮子。
- 不新增外部依赖，不引入远程服务、队列、后台线程或复杂采样系统。
- 公共函数、公共方法、公共类必须添加中文 Google 风格 docstring，包含 Args / Returns / Raises（如有）。
- 简单私有 helper 可使用一行中文概述。
- 注释和日志 `message` 沿用中文风格；结构化 `event` 使用稳定英文。
- 所有 prompt 相关改动必须遵守项目 Prompt 编写规范，运行时变量使用具名占位符，外部数据必须指令与数据分离。

### 安全与边界

- 推理正文默认不采集。
- 推理正文采集时必须先脱敏、再截断、再写入独立 sink。
- 生产环境在 `cot_require_local_env=true` 时强制不采集正文。
- 推理正文不允许进入主日志、用户响应、后续 prompt、scratchpad 或 trace 字段。
- sink、formatter、trace hook 失败不得影响主业务流程。
- 不为不可能发生的内部路径增加复杂兜底；只在系统边界做必要防护。

---

## 5. Testing Strategy

### Reasoning sink 测试

`tests/test_reasoning_sink.py` 必须覆盖：

- `NoopReasoningSink.write(...)` 不产生文件或异常。
- `JsonlReasoningSink.write(...)` 写入合法 JSON Lines。
- 写入前对 `sk-...`、`Bearer ...`、`password=...`、`token=...`、`api_key=...` 等敏感内容脱敏。
- `text` 超过 `cot_max_chars` 时被截断，并带稳定截断标记。
- sink 写入异常被吞掉，不向外抛出。
- `source`、`task_type`、`step_index`、`outcome` 等字段保留。

### CoT 采集测试

`tests/test_cot_capture.py` 必须覆盖：

- 推理模型返回 `reasoning_content` 时，`LLMResponse.reasoning_text` 被提取。
- 无原生 reasoning 字段时，`reasoning_text is None` 且不报错。
- `LLMResponse.trace` 包含 `reasoning_chars` 与 `has_reasoning`，不包含正文。
- `FakeLLMClient` 能注入 `reasoning_text`。
- `cot_capture_enabled=false` 默认只输出 `cot_captured` 元数据事件，不写 reasoning sink 正文。
- `cot_capture_enabled=true` 且 `environment=local` 时写入脱敏、截断后的正文。
- `environment=prod` 且 `cot_require_local_env=true` 时强制不写正文。
- `cot_capture_sources` 能限制被写入 sink 的来源。

### ReAct 旁路测试

`tests/test_agentic_loop.py` 必须补充：

- 接入 CoT 采集后，原有收敛结果、步骤数、工具调用行为不变。
- `native_cot`、`thought`、`reason` 采集失败不影响最终结果。
- 推理正文不进入 scratchpad。
- 推理正文不出现在后续 `decide` / `reflect` prompt 输入中。
- `react_step` 元数据包含 `has_reasoning`、`reasoning_chars`。

### 配置测试

`tests/test_core_config_logging.py` 必须补充：

- `Settings` 默认 `cot_capture_enabled=False`。
- `Settings` 默认 `cot_capture_sources=["native_cot", "thought", "reason"]`。
- `Settings` 默认 `cot_max_chars=1200`。
- `Settings` 默认 `cot_sink_path="logs/reasoning.jsonl"`。
- `Settings` 默认 `cot_require_local_env=True`。
- `PAGENT_COT_CAPTURE_ENABLED=true/false` 能正确读取为布尔值。
- `PAGENT_COT_CAPTURE_SOURCES` 能正确读取为来源列表。
- `PAGENT_COT_MAX_CHARS` 能正确读取为整数。
- `PAGENT_COT_SINK_PATH` 能正确读取为字符串路径。
- `PAGENT_COT_REQUIRE_LOCAL_ENV=false` 能正确读取为布尔值。
- `to_public_dict()` 包含新增 `cot_*` 非敏感配置。
- `to_public_dict()` 不包含 API key、token、secret、password。

### 安全合规测试

`tests/test_security_compliance.py` 必须补充：

- 主 stdout 日志不出现 `native_cot`、`thought`、`reason` 正文。
- 用户返回不出现 CoT / `reason` 正文。
- reasoning sink 正文已经脱敏。
- reasoning sink 正文长度不超过 `cot_max_chars` 加稳定截断标记开销。
- trace 字段不出现正文、API key、完整 prompt、完整 response。

### Eval 测试

`eval` 侧最小测试必须覆盖：

- 对注入样本正确判定是否引用 `next_query_hint`。
- 对注入样本正确判定是否引用预算指令。
- 对注入样本正确判定是否提到未选工具。
- 能输出包含命中率与 outcome 关联字段的结构化结果。
- 空文本、缺失字段、未知 source 不崩溃。

### 验收口径

- `conda run -n autoGLM pytest tests/test_reasoning_sink.py tests/test_cot_capture.py` 通过。
- `conda run -n autoGLM pytest tests/test_core_config_logging.py tests/test_agentic_loop.py tests/test_security_compliance.py` 通过。
- `conda run -n autoGLM pytest` 通过。
- `conda run -n autoGLM python -m compileall app tests scripts eval` 通过。
- 默认配置下不生成 reasoning 正文文件。
- local 开关开启时可生成脱敏、截断后的 `logs/reasoning.jsonl`。
- prod 环境强制不采集正文。
- 主日志与用户输出 grep 不到推理正文。

---

## 6. Boundaries

### Always do

- 始终把 CoT / thought / reason 作为只读观测信号。
- 始终只在主日志记录无正文元数据。
- 始终在写 reasoning sink 前脱敏并截断正文。
- 始终让 sink、日志、采集失败不影响主流程。
- 始终保持 `PAGENT_` 配置前缀和 `to_public_dict()` 同步。
- 始终使用 `settings.xxx if arg is None else arg` 处理构造参数覆盖。
- 始终使用 `conda run -n autoGLM` 执行 Python、pytest 和脚本命令。
- 始终用离线 eval 分析推理信号，不自动改 prompt 或在线策略。

### Ask first

- 是否修改 `LLMResponse.trace` 字段契约。本规格仅允许新增可选无正文字段 `reasoning_chars`、`has_reasoning`。
- 是否引入任何第三方依赖、观测 SDK、远程存储或日志服务。
- 是否把推理正文用于用户展示、在线控制、自动 prompt 改写或 self-consistency 投票。
- 是否记录完整 query、prompt、检索正文、LLM 输入输出或用户原文用于排障。
- 是否新增异步队列、后台线程、重试机制或采样丢弃策略。
- 是否改动 ReAct 收敛逻辑、检索算法、工具注册或会话记忆链路业务行为。

### Never do

- 不向终端用户透出 CoT 或完整 `reason` 正文。
- 不把推理正文写入主 stdout 日志、`LLMResponse.trace`、后续 prompt、scratchpad、task_input 或检索 query。
- 不用推理正文改变 `decide` / `reflect` / 收敛结果。
- 不在默认配置下采集推理正文。
- 不在生产环境绕过 `cot_require_local_env=true` 的强制关闭。
- 不记录密钥、凭证、完整 API Key、隐私数据或过长正文。
- 不让日志或 sink 异常打断业务流程。
- 不在默认测试中触网、调用真实 LLM 或下载模型。

---

## 7. Functional Acceptance Checklist

- [ ] 新增 `app/core/reasoning_sink.py`。
- [ ] 实现 `ReasoningRecord`、`ReasoningTraceSink`、`NoopReasoningSink`、`JsonlReasoningSink`。
- [ ] reasoning sink 写入前脱敏、截断。
- [ ] reasoning sink 异常不影响主流程。
- [ ] `Settings` 新增 `cot_capture_enabled`、`cot_capture_sources`、`cot_max_chars`、`cot_sink_path`、`cot_require_local_env`。
- [ ] 新增对应 `PAGENT_` 环境变量读取。
- [ ] 新增 `cot_*` 配置进入 `to_public_dict()`。
- [ ] `OpenAICompatibleClient` 提取 `reasoning_content` / `reasoning`。
- [ ] `LLMResponse` 新增可选 `reasoning_text`。
- [ ] `LLMResponse.trace` 新增 `reasoning_chars`、`has_reasoning`，且不含正文。
- [ ] `FakeLLMClient` 支持注入 `reasoning_text`。
- [ ] ReAct Act 后旁路采集 `native_cot` 与 `thought`。
- [ ] ReAct Reflect 后旁路采集 `native_cot` 与 `reason`。
- [ ] 主日志新增 `cot_captured` 无正文元数据事件。
- [ ] `react_step` / `llm_call` 增补 `has_reasoning`、`reasoning_chars`。
- [ ] 默认配置不写 reasoning 正文。
- [ ] local 开关开启时写独立 `logs/reasoning.jsonl`。
- [ ] prod 且 `cot_require_local_env=true` 时强制不写正文。
- [ ] 推理正文不进入用户返回、主日志、scratchpad、task_input 或后续 prompt。
- [ ] 新增 `eval/cot_analysis.py`。
- [ ] eval 支持 `next_query_hint` / 预算指令 / 未选工具的信号消费检测。
- [ ] eval 支持 outcome 关联与结构化报告输出。
- [ ] `tests/test_reasoning_sink.py` 通过。
- [ ] `tests/test_cot_capture.py` 通过。
- [ ] 相关配置、ReAct、安全测试通过。
- [ ] 全量 pytest 通过。
- [ ] compileall 通过。

---

## 8. Implementation Order

1. 盘点 `app/tools/llm.py` 响应解析、`LLMResponse.trace`、`FakeLLMClient` 与 `app/core/security.py` 脱敏能力。
2. 新增 `app/core/reasoning_sink.py`，实现 Noop / JSONL sink、脱敏、截断与异常吞掉，并补 `tests/test_reasoning_sink.py`。
3. 扩展 `app/core/config.py`，新增 `cot_*` 默认值、环境变量读取、`to_public_dict()`，并补配置测试。
4. 扩展 `app/tools/llm.py`，提取 `reasoning_content` / `reasoning` 到 `LLMResponse.reasoning_text`，新增 trace 元数据字段，并补 `tests/test_cot_capture.py`。
5. 扩展 `FakeLLMClient`，支持测试注入 `reasoning_text`。
6. 在 `app/orchestrator/react_loop.py` 接入只读旁路采集，输出 `cot_captured` 元数据事件。
7. 扩展 `react_step` / `llm_call` 元数据，确保无正文。
8. 新增 `eval/cot_analysis.py`，实现信号消费检测与有效性归因最小能力。
9. 补齐安全合规与不回灌测试，重点断言正文不进主日志、用户输出、scratchpad、后续 prompt。
10. 运行目标测试、全量 pytest 和 compileall。
11. 每完成一个可独立验证阶段，按项目提交规范单独 commit；不执行 `git push`，等待用户确认。
