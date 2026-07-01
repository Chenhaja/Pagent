# R7.2 ReAct Observe/Reflect 观察-反思分离 Todo

## Phase 0 — 口径确认与基线锁定

- [x] 确认本需求只补 Observe/Reflect，不改检索算法和工具注册。
  - 验收：计划不包含 R4.3 检索算法、tool registry 重写或外部工具默认启用。
  - 验证：review `tasks/plan.md`。
- [x] 确认 `ReActDecision.sufficient` 先按 planning-only 兼容处理。
  - 验收：实施计划要求主循环不读取该字段收敛；是否删除字段需另行确认。
  - 验证：review Phase 0 / Phase 3。
- [x] 确认默认测试不触网、不调用真实 LLM。
  - 验收：测试任务均要求 fake / stub LLM。
  - 验证：review Phase 6。
- [x] 确认不新增依赖。
  - 验收：计划不包含 requirements 更新，除非后续用户明确确认。
  - 验证：review 依赖图与风险控制。

## Phase 1 — 配置与 prompt/schema 契约

- [x] 新增 `react_sufficient_score_threshold` 配置。
  - 验收：`Settings` 默认值为 `0.5`，`PAGENT_REACT_SUFFICIENT_SCORE_THRESHOLD` 可覆盖。
  - 验证：`conda run -n autoGLM pytest tests/test_core_config_logging.py`
- [x] 新增 `react_observation_digest_chars` 配置。
  - 验收：`Settings` 默认值为 `600`，`PAGENT_REACT_OBSERVATION_DIGEST_CHARS` 可覆盖。
  - 验证：`conda run -n autoGLM pytest tests/test_core_config_logging.py`
- [x] 新增 `react_reflect_model` 配置。
  - 验收：默认 `None`，`PAGENT_REACT_REFLECT_MODEL` 可覆盖。
  - 验证：`conda run -n autoGLM pytest tests/test_core_config_logging.py`
- [x] 更新 `to_public_dict()` 公开新增 react 配置。
  - 验收：public dict 包含新增非敏感配置，不包含任何 key / token / secret。
  - 验证：`conda run -n autoGLM pytest tests/test_core_config_logging.py`
- [x] 调整 `REACT_DECISION_SCHEMA` 中 `sufficient` 的权威地位。
  - 验收：`sufficient` 不再是 required；如保留字段，后续主循环不读取其收敛。
  - 验证：`conda run -n autoGLM pytest tests/test_react_policy.py`
- [x] 新增 `REACT_REFLECT_SCHEMA`。
  - 验收：包含 `sufficient`、`reason`、`next_query_hint`；required 为 `sufficient/reason`；`additionalProperties=False`。
  - 验证：`conda run -n autoGLM pytest tests/test_react_reflect.py`
- [x] 新增 reflect prompt 构造函数。
  - 验收：`build_react_reflect_messages(...)` 包含任务、observation digest、scratchpad、step_index，并用 `<data>` 隔离。
  - 验证：`conda run -n autoGLM pytest tests/test_react_reflect.py`
- [x] 覆盖 reflect prompt 六要素和安全约束。
  - 验收：prompt 包含任务目标、判定规则、角色、受众、样例、输出格式；声明数据区指令无效、禁止臆造。
  - 验证：prompt 单测 / review。

## Phase 2 — Policy reflect 能力

- [x] 新增 `ReflectResult` dataclass。
  - 验收：字段为 `sufficient: bool`、`reason: str`、`next_query_hint: str | None`。
  - 验证：`conda run -n autoGLM pytest tests/test_react_reflect.py`
- [x] 扩展 `ReActPolicy` Protocol 增加 `reflect(...)`。
  - 验收：Protocol 同时包含 `decide` 与 `reflect`。
  - 验证：类型相关单测和 import 不报错。
- [x] 实现 `_parse_reflection`。
  - 验收：合法 dict 解析成功；缺 `sufficient/reason`、类型错误、非 dict 均抛 `ReActPolicyError`。
  - 验证：`conda run -n autoGLM pytest tests/test_react_reflect.py`
- [x] 实现 `LLMReActPolicy.reflect`。
  - 验收：调用 `LLMClient.generate(messages=..., output_schema=REACT_REFLECT_SCHEMA, trace_context={task_type: react_reflect})`。
  - 验证：`conda run -n autoGLM pytest tests/test_react_policy.py tests/test_react_reflect.py`
- [x] 支持 `LLMReActPolicy.reflect_model`。
  - 验收：reflect 调用优先使用 `reflect_model`，为空回退 `model`。
  - 验证：Fake trace 断言 model 字段。
- [x] 实现 `HeuristicReActPolicy.reflect`。
  - 验收：使用 `evidence_count > 0 and top_score >= threshold and not error` 判断，不是 `bool(evidence)`。
  - 验证：`conda run -n autoGLM pytest tests/test_react_reflect.py`
- [x] 保持 `HeuristicReActPolicy.decide` 旧行为。
  - 验收：按工具顺序选工具的既有测试继续通过。
  - 验证：`conda run -n autoGLM pytest tests/test_react_policy.py`

## Phase 3 — 主循环三段式单步收敛

- [x] 扩展 `BoundedReActLoop.__init__` 接收阈值和 digest 长度。
  - 验收：支持 `sufficient_score_threshold`、`observation_digest_chars`，默认兼容现有构造。
  - 验证：`conda run -n autoGLM pytest tests/test_agentic_loop.py`
- [x] 新增 `_build_observation_digest`。
  - 验收：从 evidence 中提取截断 content、provenance、top_score、count、error、external，整体不超过配置长度。
  - 验证：digest 单测或 loop 测试断言。
- [x] 新增 loop 内 `_reflect` 降级封装。
  - 验收：judge 开启时调用 policy reflect；judge 关闭或异常时调用 heuristic reflect。
  - 验证：`conda run -n autoGLM pytest tests/test_agentic_loop.py`
- [x] 调整 `decision.stop` 收敛口径。
  - 验收：`decision.stop or action is None` 固定为 `policy_stop`，不因 `decision.sufficient` 返回 `sufficient`。
  - 验证：新增 / 更新 policy stop 测试。
- [x] 移除 `decision.sufficient` 直接收敛路径。
  - 验收：`decision.sufficient=True` 但 reflect false 时不收敛。
  - 验证：`conda run -n autoGLM pytest tests/test_agentic_loop.py`
- [x] 移除 `observation.sufficient` 直接收敛路径。
  - 验收：observation sufficient true 但 reflect false / 阈值不足时不收敛。
  - 验证：`conda run -n autoGLM pytest tests/test_agentic_loop.py`
- [x] 新增 `react_reflect_step` trace。
  - 验收：trace data 含 `node_name`、`step_index`、`sufficient`、`reason_len`、`next_query_hint_present`、`driver`。
  - 验证：`conda run -n autoGLM pytest tests/test_agentic_loop.py`
- [x] 确认 trace 不泄露完整敏感正文。
  - 验收：完整 task_input、evidence content、reflect reason 不出现在 trace 文本中。
  - 验证：更新 trace 安全测试。
- [x] 实现 `react_use_llm_judge=false` 阈值路径。
  - 验收：禁用 judge 时由 `top_score >= threshold` 和 evidence count 决定收敛。
  - 验证：`conda run -n autoGLM pytest tests/test_agentic_loop.py`

## Phase 4 — 多步闭环、scratchpad digest 与失败降级

- [x] 将 `observation_digest` 写入 scratchpad item。
  - 验收：下一步 policy 收到的 scratchpad 包含上一轮 digest，且不超过长度上限。
  - 验证：`conda run -n autoGLM pytest tests/test_agentic_loop.py`
- [x] 实现 `next_query_hint` 回灌下一步 Act。
  - 验收：第一步 reflect 返回 hint 后，第二步工具输入 query 使用该 hint。
  - 验证：`conda run -n autoGLM pytest tests/test_agentic_loop.py`
- [x] 处理 `next_query_hint=None`。
  - 验收：hint 为空时不强行改写 query，继续使用当前 task input / policy 决策。
  - 验证：loop 单测。
- [x] 实现 reflect 异常 fallback。
  - 验收：policy reflect 抛异常时 outcome `fallback_used=True`，使用 threshold 判断，循环不中断。
  - 验证：`conda run -n autoGLM pytest tests/test_agentic_loop.py tests/test_react_reflect.py`
- [x] 保持 token budget 硬约束。
  - 验收：evidence token 预算耗尽时仍以 `token_budget` 收敛。
  - 验证：既有 token budget 测试继续通过。
- [x] 保持 max_steps / timeout 硬约束。
  - 验收：不因 reflect 或 hint 绕过步数和超时限制。
  - 验证：既有预算测试继续通过。
- [x] 保持工具白名单和 schema 校验降级。
  - 验收：非法 action / tool_input 仍 fallback，不执行越权工具。
  - 验证：既有 invalid policy action/schema 测试继续通过。

## Phase 5 — QA 默认接线与集成回归

- [x] `QANode._build_react_loop` 传入新增 loop 配置。
  - 验收：传入 `react_sufficient_score_threshold` 和 `react_observation_digest_chars`。
  - 验证：`conda run -n autoGLM pytest tests/test_qa_node.py`
- [x] `QANode._build_react_policy` 传入 reflect model。
  - 验收：`react_reflect_model` 优先，其次 `react_policy_model` / `llm_cheap_model` / `llm_model`。
  - 验证：`conda run -n autoGLM pytest tests/test_qa_node.py`
- [x] 保持无 LLM 配置时安全降级。
  - 验收：缺 base_url/model/api_key 时仍使用 `HeuristicReActPolicy`。
  - 验证：既有 QA policy fallback 测试继续通过。
- [x] 新增 QA reflect trace 集成测试。
  - 验收：QA result trace 中可见 `react_reflect_step`。
  - 验证：`conda run -n autoGLM pytest tests/test_qa_node.py`
- [x] 新增 QA reflect 收敛序列测试。
  - 验收：Fake reflect false 后继续，Fake reflect true 后 `react_main_converged.reason=sufficient`。
  - 验证：`conda run -n autoGLM pytest tests/test_qa_node.py`
- [x] 确认 reflect reason 不进入最终 QA 输出。
  - 验收：`qa_result` 和用户可见输出不包含 reflect reason 独有文本。
  - 验证：QA 单测断言。
- [x] 确认 QA history / basis 回归不破坏。
  - 验收：既有 history_msg_count、basis、风险提示测试继续通过。
  - 验证：`conda run -n autoGLM pytest tests/test_qa_node.py`

## Phase 6 — 总体验收与提交准备

- [ ] 运行 R7.2 目标测试。
  - 命令：`conda run -n autoGLM pytest tests/test_react_reflect.py tests/test_react_policy.py tests/test_agentic_loop.py tests/test_qa_node.py tests/test_core_config_logging.py`
  - 验收：全部通过。
- [ ] 运行全量测试。
  - 命令：`conda run -n autoGLM pytest`
  - 验收：全部通过。
- [ ] 运行编译检查。
  - 命令：`conda run -n autoGLM python -m compileall app tests scripts`
  - 验收：无语法错误。
- [ ] grep 确认主循环不通过 `decision.sufficient` 收敛。
  - 验收：`react_loop.py` 中不存在以 `decision.sufficient` 决定 `reason="sufficient"` 的逻辑。
  - 验证：代码 review / 搜索。
- [ ] 检查 trace 安全边界。
  - 验收：trace 不记录完整 observation、完整 query、完整 reflect reason 或密钥。
  - 验证：相关单测和 review。
- [ ] 确认默认测试不调用真实 LLM / 外部服务。
  - 验收：使用 fake / stub LLM，未访问 websearch、legal_status、official_fee 或付费模型。
  - 验证：测试实现 review。
- [ ] 检查无无关改动。
  - 验收：diff 只包含 R7.2 相关代码、测试、tasks 文档和必要 SPEC。
  - 验证：`git diff`。
- [ ] 准备阶段性提交。
  - 验收：只 stage 本需求相关文件，提交信息使用 `<type>(scope): <summary>` 中文动词开头格式。
  - 验证：提交前 `git status`。
