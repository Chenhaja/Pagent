# R7 Agentic 编排规格说明

## 1. Objective

### 目标

R7 的目标是在现有确定性 workflow 之外，引入一套受限的 Agentic 编排能力：以代码固定 workflow 边界，以 bounded ReAct 主循环负责局部工具路由、补料、观察与收敛，让 QA 等开放式任务可以在预算内选择 `kb_retrieval`、`websearch`、`legal_status`、`official_fee` 等白名单工具获取证据，并把证据回注给现有回答链路。

完成标准：

- 新增编排级 bounded ReAct 主循环，支持 reason → tool select → act → observe → judge → converge。
- ReAct 主循环必须受 `retrieval_max_steps`、`retrieval_token_budget`、`retrieval_timeout_seconds` 或等价通用预算配置封顶。
- 工具调用只能来自代码注册的白名单，LLM 不得直接调用任意函数、任意 URL 或改变全局 workflow 顺序。
- QA 不再维护独立 `_retrieve_loop`；QA 统一委派 R7 主循环，默认只开放 `kb_retrieval` 工具，需显式触发才允许外部工具。
- `kb_retrieval` 复用现有 `app/tools/retrieval.py` 检索能力和 R4.2 provenance / 时效字段，不重写检索四件套。
- `websearch`、`legal_status`、`official_fee` 产出的外部 evidence 必须带来源、抓取时间、时效状态或核对提示。
- 最终 QA 输出继续通过现有 `PatentQASkill` 生成结构化答案，`basis` 只能回链真实 evidence，不得伪造来源、法条、专利号或官费信息。
- 主循环收敛时必须写入 `react_main_step` / `react_main_converged` trace，且 trace 不记录完整 query、完整正文、密钥或敏感材料。
- 删除或收编 `QANode._retrieve_loop` 及其专属 trace / 配置 / 测试，避免两套多轮检索循环并存。

### 目标用户

- 普通发明人 / 专利代理业务用户：在知识库不足或强时效问题中获得带来源、带时效提示的辅助答案。
- 下游 workflow：可把 R7 主循环作为受控补料能力，而不是让 LLM 接管全局流程。
- 开发与测试人员：需要可断言的工具选择、预算收敛、trace、配置迁移和 QA 行为兼容。

### 非目标

- 不做开放式 AutoGPT；不允许无限循环、任意工具调用或任意联网。
- 不让 LLM 决定全局 workflow 顺序、节点跳转或业务流程边界。
- 不替代现有确定性 workflow；R7 只处理开放式补料与局部工具路由。
- 不重写 R4.3 检索四件套，不删除 `app/tools/retrieval.py`。
- 不在默认测试中触网、调用真实付费模型、真实搜索 API 或真实外部专利库。
- 不做前端，本轮仍以 API / service / node 为入口。
- 不新增外部 agent 框架；优先用项目内轻量模块实现。

---

## 2. Commands

项目使用 conda 环境 `autoGLM`。所有 Python / pytest / 脚本命令必须通过 `conda run -n autoGLM` 执行，不能依赖 `conda activate` 的跨命令状态。

```bash
# R7 主循环与工具路由核心测试
conda run -n autoGLM pytest tests/test_agentic_loop.py

# QA 收编回归测试
conda run -n autoGLM pytest tests/test_qa_node.py

# 配置迁移与公开配置测试
conda run -n autoGLM pytest tests/test_core_config_logging.py

# 检索工具回归测试
conda run -n autoGLM pytest tests/test_retrieval_tool.py

# 全量测试
conda run -n autoGLM pytest

# 编译检查
conda run -n autoGLM python -m compileall app tests scripts
```

最终验收命令：

```bash
conda run -n autoGLM pytest tests/test_agentic_loop.py tests/test_qa_node.py tests/test_core_config_logging.py
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests scripts
```

约束：

- 默认测试必须使用 fake / stub / monkeypatch，不触网、不调用真实付费模型或真实检索源。
- 如需新增依赖，必须先确认并同步 `requirements.txt`。
- 不运行会修改真实外部服务状态的命令，除非用户明确要求。
- 不使用破坏性 git / 文件命令清理旧实现；删除旧代码必须通过明确 diff 完成。

---

## 3. Project Structure

R7 应新增编排级 ReAct 主循环与工具注册层，并让 QA 节点从私有 `_retrieve_loop` 迁移到主循环。目标结构：

```text
pagent/
  app/
    core/
      config.py                         # 新增/迁移 R7 预算、工具开关、外部工具配置
    orchestrator/
      react_loop.py                     # 新增：bounded ReAct 主循环
      tool_registry.py                  # 新增：工具白名单、工具元数据、权限边界
      workflow_defs.py                  # 保持确定性 workflow，不让 LLM 改写
    nodes/
      qa.py                             # 删除 _retrieve_loop，委派 R7 主循环后构造 evidence
    tools/
      retrieval.py                      # 保留：kb_retrieval 底层能力
      websearch.py                      # 新增或预留：websearch 工具适配器
      legal_status.py                   # 新增或预留：法律状态查询工具适配器
      official_fee.py                   # 新增或预留：官费查询工具适配器
    prompts/
      react_router.py                   # 新增：工具选择 / 收敛判定 prompt，集中维护
      patent_qa.py                      # 保持最终回答 prompt
    skills/
      patent_qa.py                      # 保持最终结构化回答
    models/
      schemas.py                        # 可新增 ReActStep、ToolCall、Observation、ReActOutcome
  tests/
    test_agentic_loop.py                # 新增：主循环、预算、工具路由、收敛、trace
    test_agentic_tools.py               # 新增：工具契约、白名单、外部 evidence provenance
    test_qa_node.py                     # 更新：QA 委派主循环与结果兼容
    test_core_config_logging.py         # 更新：配置迁移与敏感字段排除
  SPEC.md                               # 本规格
```

### ReAct 主循环契约

建议在 `app/orchestrator/react_loop.py` 中提供轻量主循环单元，职责为：

1. 接收用户任务、上下文、可用工具白名单、预算参数与 trace sink。
2. 每轮由受控决策器选择下一步动作：继续调用某个白名单工具、收敛作答、或因预算停止。
3. 调用工具后把 observation 归一化为 evidence / metadata，不把工具原始大正文直接写入 trace。
4. 累积 evidence，并按工具类型注入去重策略：KB 结果按 `document_id`，外部结果按 source URL / locator / retrieved_at 等稳定字段。
5. 根据证据充分性、缺口类型、预算与超时判断收敛。
6. 返回 `ReActOutcome`：累积 evidence、工具调用摘要、收敛原因、步数、trace events。

收敛原因枚举：

```text
sufficient       # 证据充分
max_steps        # 达到最大步数
token_budget     # token / evidence 预算不足或耗尽
timeout          # 超过超时限制
tool_unavailable # 所需工具未启用或不可用
unsafe_request   # 请求涉及敏感材料外发或越权工具调用
```

### 工具注册契约

工具必须通过代码注册，不能由 LLM 自由发现：

| 工具名 | 默认可用场景 | 说明 |
| --- | --- | --- |
| `kb_retrieval` | QA 默认工具 | 调用现有 `build_retriever(settings).search(...)`，复用混合检索 / 重排 / 查询改写 / provenance。 |
| `websearch` | 显式补料场景 | 查询最新案例、公开资讯、强时效内容；必须带 URL、标题、retrieved_at、时效提示。 |
| `legal_status` | 法律状态缺口 | 查询专利法律状态；必须标注来源和查询时间，不能凭模型生成。 |
| `official_fee` | 官费缺口 | 查询官费或费用规则；必须标注来源、适用地区、查询时间和核对提示。 |

要求：

- 每个工具暴露统一 `run(input) -> ToolObservation` 或等价接口。
- 工具输入必须经过结构化 schema 校验，禁止把不可信输入拼接进 shell、SQL 或任意 URL。
- 工具输出必须归一化为 evidence，至少包含 `content`、`provenance`、`score/confidence`、`retrieved_at`（如适用）。
- 失败时返回可恢复 observation，不抛裸异常中断主循环。
- 外部工具默认关闭或 stub，只有配置启用且场景允许时才可调用。

### QA 收编契约

R7 采用“一个主循环”方案，删除 QA 私有多轮检索循环：

- `QANode.run()` 不再调用 `_retrieve_loop`。
- QA 默认调用 R7 主循环，工具白名单默认仅包含 `kb_retrieval`。
- 只有当输入或上游缺口检测明确需要强时效补料，且配置允许外部工具时，才加入 `websearch` / `legal_status` / `official_fee`。
- 删除或迁移以下 QA 私有循环 helper：`_retrieve`、`_retrieve_loop`、`_accumulate_results`、`_result_key`、`_is_evidence_sufficient`、`_top_score`、`_get_result_score`、`_estimate_evidence_tokens`、`_rewrite_query`、`_build_converged_trace`、`_build_convergence`。
- 保留 `_build_evidence`、法规时效告警、依据不足风险提示等最终回答相关逻辑，必要时改为消费 `ReActOutcome`。
- `qa_react_step` / `qa_react_converged` trace 迁移为 `react_main_step` / `react_main_converged`，可保留 `node_name="qa"` 便于定位。

### 配置契约

优先使用通用作用域配置，避免新增绑定单 Node 的 `qa_*` 字段。

建议配置：

| 配置字段 | 环境变量 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `retrieval_max_steps` | `PAGENT_RETRIEVAL_MAX_STEPS` | 现有默认 | 主循环最大工具步数，兼容现有检索预算。 |
| `retrieval_token_budget` | `PAGENT_RETRIEVAL_TOKEN_BUDGET` | 现有默认 | 主循环 evidence token 预算。 |
| `retrieval_timeout_seconds` | `PAGENT_RETRIEVAL_TIMEOUT_SECONDS` | 现有默认 | 主循环超时时间。 |
| `agentic_enabled` | `PAGENT_AGENTIC_ENABLED` | `True` | 是否启用 R7 主循环。 |
| `agentic_external_tools_enabled` | `PAGENT_AGENTIC_EXTERNAL_TOOLS_ENABLED` | `False` | 是否允许外部工具加入白名单。 |
| `agentic_default_tools` | `PAGENT_AGENTIC_DEFAULT_TOOLS` | `kb_retrieval` | 默认工具白名单。 |
| `websearch_enabled` | `PAGENT_WEBSEARCH_ENABLED` | `False` | 是否启用 websearch 工具。 |
| `legal_status_enabled` | `PAGENT_LEGAL_STATUS_ENABLED` | `False` | 是否启用法律状态查询工具。 |
| `official_fee_enabled` | `PAGENT_OFFICIAL_FEE_ENABLED` | `False` | 是否启用官费查询工具。 |

迁移要求：

- `retrieval_react_min_results`、`retrieval_react_min_score`、`retrieval_react_use_llm_judge` 属于旧 QA 私有循环判定配置；本轮应迁移到主循环策略配置或直接删除。
- 除非明确需要迁移窗口，不保留无意义兼容壳。
- 新增 / 删除配置必须同步 `Settings` 默认值、环境变量读取、`to_public_dict()`、测试和文档。
- 非敏感配置可进入 `to_public_dict()`；API Key、token、secret、password 等敏感字段必须排除。

### Trace 契约

每轮工具调用写入 `react_main_step`：

```json
{
  "node_name": "qa",
  "step_index": 0,
  "tool_name": "kb_retrieval",
  "input_len": 18,
  "observation_count": 3,
  "top_score": 0.67,
  "decision": "continue_or_converge",
  "external": false
}
```

主循环收敛时写入 `react_main_converged`：

```json
{
  "node_name": "qa",
  "reason": "sufficient",
  "steps_used": 1,
  "tool_calls": 1,
  "total_evidence": 3,
  "external_tools_used": []
}
```

约束：

- trace 不记录完整 query、完整工具返回正文、完整用户敏感材料、密钥或凭证。
- 外部工具 trace 只记录域名 / 来源类型 / retrieved_at / 结果数量等摘要字段。
- 继续保留 `qa_completed` trace，字段包括 `basis_count`、`has_retrieval`、`evidence_versions` 或等价信息。

---

## 4. Code Style

### 基本原则

- 最小化、局部化改动；优先复用现有 orchestrator、node、retrieval、patent QA skill、trace 结构。
- 不引入大型 agent 框架；主循环保持轻量、可测、可替换。
- 不重写检索工具；`kb_retrieval` 只是对现有 retrieval 能力的工具适配。
- 公共函数、公共方法、公共类必须添加中文 Google 风格 docstring，包含 Args / Returns / Raises（如有）。
- 私有简单 helper 可用一行中文概述；只在预算判断、工具门控、去重策略、安全降级等不直观处加行内注释。
- 日志 / trace 沿用稳定英文 event + 中文 message 风格。
- 不记录完整 query、检索正文、网页正文、密钥、凭证或过长文本。

### Prompt 规范

如新增工具选择、收敛判定或缺口判断 prompt，必须满足项目 prompt 规范：

- prompt 集中在 `app/prompts/`，不得内联散落在业务逻辑里。
- 覆盖任务目标、上下文 / 判定规则、角色、受众、样例、输出格式六要素。
- 外部 / 用户 / 检索 / websearch 内容必须包裹在 `<data>...</data>` 或三引号中，并声明数据区不作为指令。
- 默认要求仅输出 JSON，并明确字段类型、必填项、枚举值与 `additionalProperties: False`。
- 专利域约束必须明确：禁止臆造、不确定显式标注、使用规范术语。
- LLM 只能输出工具选择建议或收敛判断；最终工具白名单、外部工具权限和 workflow 边界由代码裁决。

### 错误处理与降级

- 工具异常、解析异常、决策异常不得以裸异常打断 QA；应记录可恢复 warning / trace 后基于已有 evidence 收敛。
- 预算为 `<= 0` 时不进入工具调用，直接走无检索 / 依据不足回答路径。
- 超时判断必须在循环中生效，不能只在循环结束后检查。
- token 预算不足时停止新增工具调用，收敛 reason 为 `token_budget`。
- 外部工具未启用或不可用时，收敛 reason 可为 `tool_unavailable`，最终回答需标注依据不足或需核对官方来源。
- 任何外部 evidence 缺少来源时不得进入 `basis`，只能作为不可引用背景或直接丢弃。

---

## 5. Testing Strategy

### ReAct 主循环测试

必须覆盖：

- 证据充分时只调用 1 步工具即收敛。
- 证据不足且仍有预算时继续选择工具并二次调用。
- 达到 `retrieval_max_steps` 后停止，收敛 reason 为 `max_steps`。
- token 预算耗尽时停止，收敛 reason 为 `token_budget`。
- 超时时停止，收敛 reason 为 `timeout`。
- 工具不可用时停止，收敛 reason 为 `tool_unavailable`。
- `max_steps <= 0` 或 token 预算 `<= 0` 时不调用任何工具。
- 循环步数、`steps_used`、trace 数量与实际工具调用次数一致。

### 工具路由与白名单测试

必须覆盖：

- 默认 QA 场景只允许 `kb_retrieval`。
- 外部工具开关关闭时，即使 LLM 选择 `websearch` / `legal_status` / `official_fee`，代码也拒绝调用。
- 未注册工具名被拒绝，不能动态 import 或任意调用。
- 工具输入通过 schema 校验；非法输入返回可恢复错误 observation。
- 工具异常不导致主循环裸异常。
- LLM 输出非法 JSON 或未知工具时回退安全路径。

### QA 收编测试

必须覆盖：

- `QANode.run()` 委派 R7 主循环，不再调用 `_retrieve_loop`。
- 默认单工具 `kb_retrieval` 行为与旧 QA 检索成功路径兼容。
- 依据不足时仍追加 `INSUFFICIENT_EVIDENCE_WARNING` 或等价风险提示。
- 法规过时 evidence 继续追加时效风险提示。
- `state.dialog_context["qa_retrieval_results"]` 存储主循环返回的归一化 evidence。
- 最终 `basis` 回链真实来源，不生成伪来源。
- 代码搜索 `_retrieve_loop` 无残留，或仅在迁移说明 / 测试 fixture 中出现。

### Evidence 与 provenance 测试

必须覆盖：

- KB evidence 保留 `document_id`、`source`、`locator`、`doc_type`、score / similarity。
- 法规 evidence 保留 `law_name`、`version`、`effective_date`、`expiry_date`、`status`、`retrieved_at`。
- websearch evidence 保留 URL / title / retrieved_at / source_type。
- legal status / official fee evidence 保留官方或可信来源、查询时间、适用范围和核对提示。
- 无来源 evidence 不进入最终 `basis`。
- 多轮 evidence 去重后保留高分或更可信来源。

### Trace 测试

必须覆盖：

- 每轮写入 `react_main_step`。
- `react_main_step` 包含 `node_name`、`step_index`、`tool_name`、`input_len`、`observation_count`、`external`。
- `react_main_step` 不包含完整 query、完整正文、密钥或敏感材料。
- 收敛时写入 `react_main_converged`。
- `react_main_converged` 包含 `reason`、`steps_used`、`tool_calls`、`total_evidence`、`external_tools_used`。
- 既有 `qa_completed` trace 保持可用。

### 配置测试

必须覆盖：

- 新增 agentic / tool 开关默认值正确，可被 `PAGENT_*` 环境变量覆盖。
- 非敏感配置进入 `to_public_dict()`。
- 敏感字段不进入 `to_public_dict()`、日志或 trace。
- 删除旧 `retrieval_react_*` 配置时，同步删除默认值、环境变量读取、公开配置和旧测试断言。
- 覆盖参数使用 `None` 继承全局配置，不吞掉 `0` / `False`。

### 验收口径

- `conda run -n autoGLM pytest tests/test_agentic_loop.py tests/test_qa_node.py tests/test_core_config_logging.py` 通过。
- `conda run -n autoGLM pytest` 通过。
- `conda run -n autoGLM python -m compileall app tests scripts` 通过。
- 默认测试不触网、不调用真实付费 LLM、不连接真实外部检索源。
- `grep -r "_retrieve_loop" app tests` 无生产代码残留；如 Windows 环境不用 grep，可用等价搜索工具确认。

---

## 6. Boundaries

### Always do

- 始终把全局 workflow 顺序留给确定性编排器。
- 始终通过代码白名单裁决工具可用性。
- 始终让 ReAct 主循环受步数、token 预算、超时封顶。
- 始终在证据不足、预算耗尽、工具不可用或超时时优雅收敛并作答。
- 始终保留 evidence provenance，最终 `basis` 只引用真实来源。
- 始终标注辅助初稿、非法律意见和必要的官方核对提示。
- 始终用 fake / stub / monkeypatch 做默认测试，不触网。
- 始终使用通用配置名，避免新增绑定单 Node 的 `qa_*` 配置。
- 始终使用 `conda run -n autoGLM` 执行 Python、pytest 和脚本命令。

### Ask first

- 是否接入真实 websearch、法律状态或官费查询服务。
- 是否允许外部工具默认启用。
- 是否允许向云模型发送完整敏感专利材料。
- 是否新增依赖或外部 SDK。
- 是否保留旧 `retrieval_react_*` 配置的兼容读取窗口。
- 是否提高 `max_steps`、token 预算或超时上限做人工验收。
- 是否修改全局 workflow 编排或让 LLM 参与节点路由。

### Never do

- 不让 LLM 改变全局 workflow 顺序或任意选择未注册工具。
- 不做无界、长程或跨会话无限 ReAct。
- 不伪造检索来源、网页来源、法条、专利号、法律状态或官费信息。
- 不在 trace / 日志记录完整敏感正文、完整 query、完整网页正文、完整检索正文或密钥。
- 不让预算耗尽、超时或工具失败导致裸异常中断 QA。
- 不在默认单测中触网、下载模型或调用真实付费服务。
- 不删除 `app/tools/retrieval.py` 或破坏 R4.3 检索四件套。
- 不保留两套并行多轮检索循环造成行为分叉。

---

## 7. Functional Acceptance Checklist

- [ ] 新增 `app/orchestrator/react_loop.py` 或等价 R7 主循环。
- [ ] 新增工具注册 / 白名单机制。
- [ ] `kb_retrieval` 工具复用现有 `app/tools/retrieval.py`。
- [ ] 预留或实现 `websearch`、`legal_status`、`official_fee` 工具适配器。
- [ ] 外部工具默认关闭或 stub，默认测试不触网。
- [ ] QA 委派 R7 主循环，不再调用 `_retrieve_loop`。
- [ ] 删除 QA 私有多轮检索 helper。
- [ ] 删除或迁移 `retrieval_react_*` 配置。
- [ ] 新增 agentic / tool 开关配置，并同步环境变量、`to_public_dict()` 和测试。
- [ ] 主循环支持 `sufficient`、`max_steps`、`token_budget`、`timeout`、`tool_unavailable`、`unsafe_request` 收敛原因。
- [ ] 主循环写入 `react_main_step` trace。
- [ ] 主循环写入 `react_main_converged` trace。
- [ ] trace 不记录完整 query、正文或敏感信息。
- [ ] evidence 保留 provenance 和 retrieved_at / 时效字段。
- [ ] 无来源 evidence 不进入最终 `basis`。
- [ ] 最终 QA `basis` 回链真实来源。
- [ ] 依据不足或外部工具不可用时输出风险提示。
- [ ] 法规过时提示保持可用。
- [ ] 默认测试不触网、不调用真实付费服务。
- [ ] `conda run -n autoGLM pytest` 通过。
- [ ] `conda run -n autoGLM python -m compileall app tests scripts` 通过。

---

## 8. Implementation Order

1. 测试先行：新增 `tests/test_agentic_loop.py`，覆盖预算、收敛、工具白名单、trace 和异常降级。
2. 主循环：新增 `app/orchestrator/react_loop.py`，实现 bounded ReAct 控制流和 `ReActOutcome`。
3. 工具注册：新增工具 registry，先接入 stub / fake 工具和 `kb_retrieval`。
4. 配置：新增 agentic / tool 开关配置，决定是否直接删除或短期兼容 `retrieval_react_*`。
5. QA 收编：修改 `app/nodes/qa.py`，删除 `_retrieve_loop` 及私有循环 helper，委派 R7 主循环。
6. Evidence：统一主循环 observation → QA evidence 转换，保留 provenance、时效和来源回链。
7. 外部工具：在默认关闭前提下接入或预留 `websearch`、`legal_status`、`official_fee` 适配器。
8. Prompt：如需要 LLM 工具选择 / 收敛判定，集中新增 `app/prompts/react_router.py`，严格 JSON 输出和指令 / 数据分离。
9. 回归：更新 `tests/test_qa_node.py`、`tests/test_core_config_logging.py`，删除或迁移 `tests/test_qa_react_loop.py`。
10. 验收：运行目标测试、全量 pytest 和 compileall，确认 `_retrieve_loop` 无生产代码残留。
