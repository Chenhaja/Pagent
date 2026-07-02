# R9 CoT 推理链采集与分析 Todo

## Phase 0 — 口径确认与基线锁定

- [ ] 确认允许扩展 `LLMResponse.trace`。
  - 验收：仅新增可选无正文字段 `reasoning_chars`、`has_reasoning`。
  - 验证：人工 review `tasks/plan.md` 的 Checkpoint 0。
- [ ] 确认本轮只做观测/评估用途。
  - 验收：不改变 ReAct 决策、反思、检索、收敛业务行为。
  - 验证：review 计划和后续 diff。
- [ ] 确认默认不采集推理正文。
  - 验收：`cot_capture_enabled=False` 为默认值。
  - 验证：配置测试。
- [ ] 确认生产环境强制不采集正文。
  - 验收：`cot_require_local_env=True` 且 `environment=prod` 时 sink 不写正文。
  - 验证：CoT 采集测试。
- [ ] 确认不新增第三方依赖。
  - 验收：`requirements.txt` 不变。
  - 验证：review diff。
- [ ] 确认默认测试不触网、不调用真实 LLM。
  - 验收：新增测试使用 fake/stub/caplog/tmp_path。
  - 验证：review 测试实现。

## Phase 1 — Reasoning sink 安全写入闭环

- [ ] 新增 `app/core/reasoning_sink.py`。
  - 验收：模块可 import。
  - 验证：`conda run -n autoGLM pytest tests/test_reasoning_sink.py`
- [ ] 定义 `ReasoningRecord`。
  - 验收：字段包含 `request_id`、`node_name`、`task_type`、`step_index`、`source`、`text`、`outcome`。
  - 验证：reasoning sink 单测。
- [ ] 定义 `ReasoningTraceSink` 协议。
  - 验收：包含 `write(record: ReasoningRecord) -> None`。
  - 验证：类型/单测 import。
- [ ] 实现 `NoopReasoningSink`。
  - 验收：`write()` 不产生文件、不抛异常。
  - 验证：单测。
- [ ] 实现 `JsonlReasoningSink`。
  - 验收：写入合法 JSON Lines；不写 stdout。
  - 验证：tmp_path 单测读取 JSONL。
- [ ] 写入前脱敏正文。
  - 验收：`sk-...`、`Bearer ...`、`password=...`、`token=...`、`api_key=...` 被替换。
  - 验证：单测。
- [ ] 写入前截断正文。
  - 验收：超过 `cot_max_chars` 的正文带稳定截断标记。
  - 验证：单测。
- [ ] sink 异常吞掉。
  - 验收：文件写入失败或序列化失败不影响调用方。
  - 验证：注入异常 sink / monkeypatch 单测。

## Phase 2 — CoT 配置控制闭环

- [ ] `Settings` 新增 `cot_capture_enabled`。
  - 验收：默认 `False`；`PAGENT_COT_CAPTURE_ENABLED=true/false` 可读取。
  - 验证：`conda run -n autoGLM pytest tests/test_core_config_logging.py`
- [ ] `Settings` 新增 `cot_capture_sources`。
  - 验收：默认包含 `native_cot`、`thought`、`reason`；env 逗号分隔可覆盖。
  - 验证：配置测试。
- [ ] `Settings` 新增 `cot_max_chars`。
  - 验收：默认 `1200`；`PAGENT_COT_MAX_CHARS` 可读取为整数。
  - 验证：配置测试。
- [ ] `Settings` 新增 `cot_sink_path`。
  - 验收：默认 `logs/reasoning.jsonl`；`PAGENT_COT_SINK_PATH` 可覆盖。
  - 验证：配置测试。
- [ ] `Settings` 新增 `cot_require_local_env`。
  - 验收：默认 `True`；`PAGENT_COT_REQUIRE_LOCAL_ENV=false` 可读取。
  - 验证：配置测试。
- [ ] 更新 `Settings` docstring。
  - 验收：新增 `cot_*` 配置均有中文说明。
  - 验证：review。
- [ ] 更新 `get_settings()`。
  - 验收：五个 `PAGENT_COT_*` 环境变量生效。
  - 验证：配置测试。
- [ ] 更新 `to_public_dict()`。
  - 验收：包含新增 `cot_*` 非敏感配置；不包含 key/token/secret/password。
  - 验证：配置测试。

## Phase 3 — LLM reasoning 提取与 trace 元数据闭环

- [ ] `LLMResponse` 新增 `reasoning_text`。
  - 验收：默认 `None`，已有调用方不传该字段仍兼容。
  - 验证：`conda run -n autoGLM pytest tests/test_llm_tool.py tests/test_cot_capture.py`
- [ ] `FakeLLMClient` 支持注入 `reasoning_text`。
  - 验收：测试可构造带原生 reasoning 的 fake response。
  - 验证：CoT 采集测试。
- [ ] Fake trace 增加 reasoning 元数据。
  - 验收：`has_reasoning`、`reasoning_chars` 正确；不含正文。
  - 验证：CoT 采集测试。
- [ ] `OpenAICompatibleClient` 提取 `message.reasoning_content`。
  - 验收：响应样本含该字段时进入 `LLMResponse.reasoning_text`。
  - 验证：LLM tool / CoT 测试。
- [ ] `OpenAICompatibleClient` 提取 `message.reasoning`。
  - 验收：响应样本含该字段时进入 `LLMResponse.reasoning_text`。
  - 验证：LLM tool / CoT 测试。
- [ ] 无 reasoning 字段时安全退回。
  - 验收：`reasoning_text is None` 且不报错。
  - 验证：LLM tool / CoT 测试。
- [ ] 成功响应 trace 增加 reasoning 元数据。
  - 验收：`has_reasoning` / `reasoning_chars` 正确，不含正文。
  - 验证：CoT 测试。
- [ ] 错误响应 trace 增加 reasoning 元数据默认值。
  - 验收：错误路径也包含 `has_reasoning=False`、`reasoning_chars=0`。
  - 验证：LLM tool 测试。
- [ ] `llm_call` 日志允许输出 reasoning 元数据。
  - 验收：`LoggingLLMTraceSink` 不丢弃 `has_reasoning`、`reasoning_chars`，仍丢弃正文类字段。
  - 验证：日志相关测试。

## Phase 4 — ReAct 旁路采集闭环

- [ ] 在 `LLMReActPolicy.decide()` 保存最近 decision reasoning。
  - 验收：loop 可只读获取 native CoT；不改变 `ReActDecision` 字段。
  - 验证：CoT 采集测试。
- [ ] 在 `LLMReActPolicy.reflect()` 保存最近 reflect reasoning。
  - 验收：loop 可只读获取 native CoT；不改变 `ReflectResult` 字段。
  - 验证：CoT 采集测试。
- [ ] `BoundedReActLoop` 支持注入 settings / reasoning sink。
  - 验收：默认继承全局配置；测试可注入 Noop/InMemory/Jsonl sink。
  - 验证：agentic loop / CoT 测试。
- [ ] 实现正文采集允许判断 helper。
  - 验收：同时满足 enabled、source 命中、local gate 才写正文。
  - 验证：CoT 采集测试。
- [ ] 实现 `_capture_reasoning_signal(...)`。
  - 验收：始终输出 `cot_captured` 元数据；允许时写 sink；异常吞掉。
  - 验证：CoT 采集测试。
- [ ] Act 后采集 `native_cot`。
  - 验收：LLM decision reasoning 存在时记录 source=`native_cot`。
  - 验证：CoT 采集测试。
- [ ] Act 后采集 `thought`。
  - 验收：`ReActDecision.thought` 记录元数据；允许时写 sink。
  - 验证：CoT 采集测试。
- [ ] Reflect 后采集 `native_cot`。
  - 验收：LLM reflect reasoning 存在时记录 source=`native_cot`。
  - 验证：CoT 采集测试。
- [ ] Reflect 后采集 `reason`。
  - 验收：`ReflectResult.reason` 记录元数据；允许时写 sink。
  - 验证：CoT 采集测试。
- [ ] `react_step` 增补 reasoning 元数据。
  - 验收：包含 `has_reasoning`、`reasoning_chars`，不含正文。
  - 验证：agentic loop 测试。
- [ ] 默认配置不写正文。
  - 验收：`cot_capture_enabled=False` 时无 reasoning JSONL。
  - 验证：CoT 采集测试。
- [ ] local 开关开启写正文。
  - 验收：`environment=local` 且 enabled 时写入脱敏截断正文。
  - 验证：CoT 采集测试。
- [ ] prod 强制不写正文。
  - 验收：`environment=prod` 且 `cot_require_local_env=True` 时 captured=false。
  - 验证：CoT 采集测试。
- [ ] sink 异常不影响 ReAct 结果。
  - 验收：异常 sink 下 outcome 与正常路径一致。
  - 验证：agentic loop 测试。

## Phase 5 — 安全合规与不回灌证明闭环

- [ ] 主日志不含推理正文。
  - 验收：caplog/stdout 中不出现注入的 CoT / thought / reason 正文。
  - 验证：`conda run -n autoGLM pytest tests/test_security_compliance.py`
- [ ] 用户返回不含推理正文。
  - 验收：`ReActOutcome` / API 可见返回不出现 CoT / reason 正文。
  - 验证：安全或 agentic 测试。
- [ ] `LLMResponse.trace` 不含推理正文。
  - 验收：trace 只有 `has_reasoning`、`reasoning_chars`。
  - 验证：CoT 采集测试。
- [ ] scratchpad 不含推理正文。
  - 验收：scratchpad 仍只保存 thought_len / observation 摘要等字段。
  - 验证：agentic loop 测试。
- [ ] 后续 prompt 不含上一步推理正文。
  - 验收：记录后续 `decide` / `reflect` 输入，grep 不到 reasoning 正文。
  - 验证：agentic loop 测试。
- [ ] reasoning sink 正文已脱敏。
  - 验收：敏感样本写入后只出现 `[REDACTED]` 或等价占位。
  - 验证：安全测试。
- [ ] reasoning sink 正文已截断。
  - 验收：长度不超过 `cot_max_chars` 加稳定截断标记开销。
  - 验证：安全测试。

## Phase 6 — Eval 离线分析闭环

- [ ] 新增 `eval/cot_analysis.py`。
  - 验收：模块可 import；不被在线路径依赖。
  - 验证：`conda run -n autoGLM python -m compileall eval`
- [ ] 实现 reasoning JSONL 读取/标准化。
  - 验收：能处理 ReasoningRecord JSONL 和缺失字段样本。
  - 验证：eval 测试。
- [ ] 实现 `next_query_hint` 命中检测。
  - 验收：注入样本正确判定引用/未引用。
  - 验证：eval 测试。
- [ ] 实现预算指令命中检测。
  - 验收：注入样本正确判定引用/未引用。
  - 验证：eval 测试。
- [ ] 实现未选工具命中检测。
  - 验收：注入样本正确识别被提到但未选中的工具。
  - 验证：eval 测试。
- [ ] 实现 outcome 关联汇总。
  - 验收：输出 source 维度样本数、命中率、sufficient 分布、steps/reason 摘要。
  - 验证：eval 测试。
- [ ] 输出结构化报告 dict。
  - 验收：结果可 JSON 序列化；不自动改 prompt。
  - 验证：eval 测试。
- [ ] 缺失字段安全兜底。
  - 验收：空文本、未知 source、缺 outcome 不崩溃。
  - 验证：eval 测试。

## Phase 7 — 全量验证与分阶段提交

- [ ] 运行 reasoning 目标测试。
  - 验收：reasoning sink 与 CoT 采集测试通过。
  - 验证：`conda run -n autoGLM pytest tests/test_reasoning_sink.py tests/test_cot_capture.py`
- [ ] 运行配置、ReAct、安全合规测试。
  - 验收：相关目标测试通过。
  - 验证：`conda run -n autoGLM pytest tests/test_core_config_logging.py tests/test_agentic_loop.py tests/test_security_compliance.py`
- [ ] 运行 eval 测试。
  - 验收：如新增 `tests/test_cot_analysis.py`，该测试通过。
  - 验证：`conda run -n autoGLM pytest tests/test_cot_analysis.py`
- [ ] 运行全量 pytest。
  - 验收：全量测试通过。
  - 验证：`conda run -n autoGLM pytest`
- [ ] 运行 compileall。
  - 验收：app/tests/scripts/eval 编译通过。
  - 验证：`conda run -n autoGLM python -m compileall app tests scripts eval`
- [ ] 检查无无关改动。
  - 验收：git diff 仅包含本轮相关文件；无密钥、临时文件、调试代码。
  - 验证：`git status` / `git diff`。
- [ ] 分阶段提交。
  - 验收：每个 commit 是可独立验证的小功能；不执行 `git push`。
  - 验证：git log / status。
