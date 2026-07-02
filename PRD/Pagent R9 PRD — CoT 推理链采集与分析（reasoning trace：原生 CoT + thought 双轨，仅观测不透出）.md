<aside>
 🧠

本 PRD 基于 GitHub 仓库 `Chenhaja/Pagent` 当前代码现状（截至最新提交 `d334186 feat(react): 在策略提示中加入步数预算`）编写，沿用项目已有 PRD / [SPEC.md](http://SPEC.md) 结构与 `PAGENT_` 配置规范。
 核心主张：把「模型推理过程」作为**开发/评估信号**采集到 R8 观测性管道，用于验证 prompt 信号是否被真正消费、归因哪些推理有效；**默认不面向终端用户透出**，且**绝不回灌控制逻辑**。

</aside>

## 1. 背景与问题

R7.1/R7.2 已落地 LLM 驱动的 ReAct 主循环与观察-反思分离，R8 落地了统一结构化日志（`event` + `request_id` 全链路 + `LoggingLLMTraceSink`）。最新提交又把步数预算加进策略提示。但目前**看不清模型「为什么这么决策」**：

| 环节         | 现状                                                         | 问题                                                   |
| ------------ | ------------------------------------------------------------ | ------------------------------------------------------ |
| 决策可解释性 | `ReActDecision.thought` 仅一句被 schema 约束的短摘要         | 信息量有限，无法还原模型真实考量与被否决的路径         |
| 反思可解释性 | `ReflectResult.reason` 仅 trace 摘要                         | 只知结论不知推理，难判断充分性判定是否可靠             |
| 信号消费验证 | `next_query_hint` 回灌、`[系统预算指令]` 已接线              | **无法验证**模型是否真的读了 hint / 预算指令，还是无视 |
| 推理模型能力 | 若切换到会输出 reasoning tokens 的模型，`LLMClient` 未采集 `reasoning_content` | 原生 CoT 被直接丢弃，白白浪费可用于调参的信号          |
| 有效性归因   | 只有 `react_main_converged.reason` / `steps_used`            | 无法把「推理策略」与「结果质量」关联，改 prompt 靠猜   |

> 一句话：我们有了「做了什么」（R8 结构化事件），但缺「为什么这么想、想得对不对」这一层，导致 prompt 迭代缺少证据。

## 2. 目标与非目标

**目标（本轮 P0）**

- 明确区分并采集两类推理信号：
  - **原生 CoT**：推理模型输出的 `reasoning_content`/`reasoning` tokens（或其摘要），由 `LLMClient` 统一提取。
  - **结构化自述**：已有的 `thought`（决策）与 `reason`（反思），作为轻量、稳定、始终可得的推理轨迹。
- 把推理信号采集到 **R8 观测性管道**：trace 只记**元数据（长度/是否存在）**，完整推理正文仅在开发开关下写入**独立的 reasoning sink**，脱敏后落库。
- 支持**信号消费检测**：在评估层判断推理文本是否引用了 `next_query_hint` / 预算指令 / 被否决的工具，量化 prompt 信号的到达率。
- 提供**有效性归因**：把每步推理与该步结果（`sufficient` / 是否推进 / 收敛原因 / 步数）关联，产出可分析的评估样本。
- **安全边界硬约束**：默认不透出用户；推理正文默认不采集（`PAGENT_COT_CAPTURE_ENABLED=false`）；采集时脱敏、截断；**绝不把推理内容回灌进 `decide` / `reflect` 的控制路径**。

**非目标**

- 不面向终端用户展示 CoT（用户侧仍以最终答案 + 必要的结构化轨迹为准）。
- 不改 ReAct 收敛逻辑、检索算法、工具注册、会话记忆链路的**业务行为**。
- 不引入 OTel / LangSmith 等外部观测 SDK（延续 R8 非目标，仅标准库 + 现有管道）。
- 不用 CoT 做在线控制（不据推理正文改变决策、不做 self-consistency 投票）。
- 不强制切换到推理模型；无 reasoning tokens 时优雅退回到 `thought`/`reason` 双轨。

------

## 3. 方案设计

### 3.1 两类推理信号与「双轨」定位

| 信号      | 来源                                                         | 稳定性                      | 用途                                                 |
| --------- | ------------------------------------------------------------ | --------------------------- | ---------------------------------------------------- |
| 原生 CoT  | 推理模型 `reasoning_content` tokens（OpenAI 兼容 delta/message 扩展字段） | 取决于模型，可能缺失/仅摘要 | 还原真实考量、发现被否决路径（**不忠实，仅作假设**） |
| `thought` | `REACT_DECISION_SCHEMA` 结构化字段                           | 始终可得、受 prompt 约束    | 轻量决策轨迹，稳定可解析                             |
| `reason`  | `REACT_REFLECT_SCHEMA` 结构化字段                            | 始终可得                    | 充分性判定依据                                       |

> 原则：**结构化自述是基线（永远采集元数据），原生 CoT 是增强（按开关采集正文）**。二者互补，不互相替代。

### 3.2 LLM 客户端提取原生 CoT（`app/tools/llm.py`）

- 在 `OpenAICompatibleClient` 解析响应时，额外读取 `reasoning_content`/`reasoning`（存在才读，缺失不报错）。

- `LLMResponse` 新增**可选**只读字段 `reasoning_text: str | None`（仅在进程内传递，**不默认落库**）。

- ```
  LLMResponse.trace
  ```

  增量新增

  （向后兼容）：

  ```
  reasoning_chars: int
  ```

  、

  ```
  has_reasoning: bool
  ```

  ；

  不新增任何含正文的 trace 字段

  。

  - ⚠️ 按 R8「Ask first：是否改动 `LLMResponse.trace` 字段契约」——此为**新增可选字段**，需你确认后再落地。

- `FakeLLMClient` 支持在决策序列里注入 `reasoning_text`，便于测试。

### 3.3 独立 reasoning sink（新增 `app/core/reasoning_sink.py`）

```python
class ReasoningTraceSink(Protocol):
    def write(self, record: ReasoningRecord) -> None: ...

@dataclass
class ReasoningRecord:
    request_id: str | None
    node_name: str | None
    task_type: str            # react_policy / react_reflect
    step_index: int
    source: str               # "native_cot" | "thought" | "reason"
    text: str                 # 脱敏 + 截断后的推理正文
    outcome: dict             # 该步结果快照（见 3.5）
```

- 默认实现 `NoopReasoningSink`；开关开启时用 `JsonlReasoningSink`（写独立文件，**不混入主 stdout 日志**，避免污染生产聊天/日志）。
- 写入前统一走现有 `redact_sensitive_text`，并按 `PAGENT_COT_MAX_CHARS` 截断。
- sink 异常必须吞掉，**绝不影响主流程**（延续 R8「日志系统永不抛异常」）。

### 3.4 主循环接线（`app/orchestrator/react_loop.py`）

- Act 后：若 `LLMResponse.reasoning_text` 存在且开关开，调用 sink 记 `source="native_cot"`；始终把 `thought` 以 `source="thought"` 记元数据。
- Reflect 后：同理记 `reason` / 该步 `native_cot`。
- **只读旁路**：sink 调用与决策/收敛完全解耦，推理正文**不写回** `task_input`、`scratchpad` 或任何后续 prompt。
- 新增/扩展 trace 事件（见 3.6），元数据随 R8 管道输出。

### 3.5 信号消费检测与有效性归因（`eval/` 扩展）

利用已有 `eval/` 目录新增离线分析（不进在线路径）：

- **信号到达率**：对 `native_cot`/`thought` 文本做关键词/子串匹配，判定是否引用了当步注入的 `next_query_hint`、`[系统预算指令]`、以及 `allowed_tools` 中未被选中的工具，输出命中率。
- **有效性归因**：把每条 `ReasoningRecord.outcome`（`sufficient` / `top_score` / 是否触发下一步 query 改写 / 最终 `converged.reason` / `steps_used`）与推理特征关联，产出「哪些推理模式更常导向有效停止 / 冗余步」。
- 产物为离线报告（JSON/表格），供人工看，**不自动改 prompt**。

### 3.6 Trace 事件（接 R8 §3.4 规范）

| event                | level     | 关键附加字段（无正文）                                       | 触发点           |
| -------------------- | --------- | ------------------------------------------------------------ | ---------------- |
| `cot_captured`       | INFO      | `task_type`, `step_index`, `source`, `reasoning_chars`, `has_reasoning`, `captured`(是否落 sink) | 每次采集推理信号 |
| `react_step`（扩展） | INFO      | 增补 `has_reasoning`, `reasoning_chars`                      | ReAct 每步       |
| `llm_call`（扩展）   | INFO/WARN | 增补 `reasoning_chars`, `has_reasoning`                      | 每次 LLM 调用    |

- 所有事件**只记规模/布尔/枚举**，正文只进独立 sink；`reason`/CoT 原文不进主日志、不回传用户。

### 3.7 配置（`app/core/config.py`，`PAGENT_` 前缀）

| 配置项                  | 默认                                | 说明                                                    |
| ----------------------- | ----------------------------------- | ------------------------------------------------------- |
| `cot_capture_enabled`   | `false`                             | 是否采集**推理正文**到 reasoning sink（元数据始终采集） |
| `cot_capture_sources`   | `["native_cot","thought","reason"]` | 采集哪些来源                                            |
| `cot_max_chars`         | `1200`                              | 单条推理正文截断上限                                    |
| `cot_sink_path`         | `logs/reasoning.jsonl`              | 独立 sink 路径（仅本地/开发）                           |
| `cot_require_local_env` | `true`                              | 仅在 `environment==local` 允许采集正文，生产强制关闭    |

- 环境变量一一对应（`PAGENT_COT_CAPTURE_ENABLED` 等），全部进 `to_public_dict()`，且不含敏感值。
- 覆盖用 `settings.xxx if arg is None else arg`，不得用 `or` 吞掉 `False`。

------

## 4. 数据契约

- `LLMResponse`：新增可选 `reasoning_text: str | None`（进程内，不默认落库）。
- `LLMResponse.trace`：**增量新增** `reasoning_chars`、`has_reasoning`（需确认）。
- `ReasoningRecord`：见 3.3，正文字段已脱敏截断。
- `ReActDecision` / `ReflectResult` / `ToolObservation` / `ReActOutcome`：**契约不变**（CoT 是旁路观测，不改现有数据流）。

------

## 5. 验收标准

- [ ]  推理模型返回 `reasoning_content` 时，`LLMResponse.reasoning_text` 被提取；无则为 `None` 且不报错。
- [ ]  `cot_capture_enabled=false`（默认）时：只出 `cot_captured` 元数据事件，**无正文落库**。
- [ ]  `cot_capture_enabled=true` 且 `environment=local` 时：reasoning sink 写入脱敏、截断（≤ `cot_max_chars`）的正文。
- [ ]  `environment=prod` 时即使显式开启，`cot_require_local_env=true` 也**强制不采集正文**。
- [ ]  主日志（stdout）与用户返回**永不出现** CoT/`reason` 正文（grep 断言）。
- [ ]  推理正文**不出现在**任何后续 prompt（`decide`/`reflect` 输入 grep 断言，证明不回灌）。
- [ ]  `eval` 信号检测可对注入样本正确判定 `next_query_hint` / 预算指令是否被引用。
- [ ]  sink 写入异常不影响 ReAct 结果（注入抛异常 sink 验证循环不崩）。
- [ ]  预算/白名单/脱敏等原有硬约束不变。

## 6. 测试计划

- 新增 `tests/test_reasoning_sink.py`：脱敏、截断、Noop/Jsonl 切换、异常吞掉。
- 新增 `tests/test_cot_capture.py`：`FakeLLMClient` 注入 `reasoning_text`，断言提取 + `cot_captured` 事件 + 开关行为 + 生产强制关闭。
- 更新 `tests/test_agentic_loop.py`：CoT 旁路不改收敛结果、正文不入 scratchpad/prompt。
- 更新 `tests/test_core_config_logging.py`：新增 `cot_*` 配置默认值 / 环境变量 / `to_public_dict()`。
- 更新 `tests/test_security_compliance.py`：reasoning 正文经脱敏、主日志无正文。
- 新增 `eval` 侧最小分析用例：信号到达率 / 有效性归因样本生成。

## 7. 项目结构变更

```
app/
  core/
    reasoning_sink.py   # 新增：ReasoningTraceSink / ReasoningRecord / Noop|Jsonl 实现
    config.py           # 新增 cot_* 配置 + 环境变量 + to_public_dict
  tools/
    llm.py              # 提取 reasoning_content；LLMResponse.reasoning_text + trace 增量字段
  orchestrator/
    react_loop.py       # Act/Reflect 后旁路采集（只读，不回灌）
eval/
  cot_analysis.py       # 新增：信号消费检测 + 有效性归因（离线）
tests/
  test_reasoning_sink.py  # 新增
  test_cot_capture.py     # 新增
```

## 8. 实施顺序

1. 盘点 `llm.py` 响应解析与 `trace` 现状、`security.py` 脱敏能力（复用，不重造）。
2. 新增 `reasoning_sink.py`（Noop/Jsonl + 脱敏截断），配套测试。
3. `config.py` 新增 `cot_*` 配置 + 环境变量 + `to_public_dict()`，补配置测试。
4. `llm.py` 提取 `reasoning_content` → `reasoning_text` + trace 增量字段（**先确认 trace 契约变更**）。
5. `react_loop.py` 旁路接线（Act/Reflect 后采集，严格只读）。
6. Trace 事件 `cot_captured` + 扩展 `react_step`/`llm_call`。
7. `eval/cot_analysis.py` 信号检测与归因。
8. 跑目标测试、全量 pytest、compileall（`conda run -n autoGLM`）。
9. 按项目规范分小步 commit，不 `git push`，等确认。

## 9. DoD

- [ ]  双轨采集落地：结构化自述元数据始终有，原生 CoT 正文按开关采集。
- [ ]  默认关闭、生产强制关闭、用户不透出、控制不回灌——四条边界均有测试。
- [ ]  `eval` 可量化 prompt 信号到达率并产出归因样本。
- [ ]  `pytest && python -m compileall app tests` 通过。

## 10. 风险与缓解

| 风险                                     | 缓解                                                         |
| ---------------------------------------- | ------------------------------------------------------------ |
| **CoT 不忠实**：自述推理未必反映真实计算 | 明确定位为「假设生成器」，结论以基于结果的评估为准；文档与报告显式标注不可作为唯一证据 |
| 推理正文含敏感/注入内容                  | 默认不采集；采集时脱敏 + 截断 + 仅 local；绝不回灌 prompt / 不透出用户 |
| 推理模型放大延迟与成本                   | 采集为旁路、可关；不做 self-consistency；沿用 cheap 档位与步数预算 |
| trace 契约变更影响下游                   | 仅新增可选字段、向后兼容；落地前按 R8「Ask first」确认       |
| 采集拖慢主流程 / sink 故障               | sink 异步/容错、异常吞掉；元数据轻量，正文写独立文件         |

------

> 说明：本 PRD 只覆盖「CoT 推理链采集与分析」，且严格限定为**观测/评估用途**。用户侧展示、在线控制回灌均为非目标。承接 R8 观测性管道与 R7.2 观察-反思数据契约。