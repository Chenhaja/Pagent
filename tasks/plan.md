# R7 Agentic 编排实施计划

## 背景

R7 将在现有确定性 workflow 之外新增一套受限 Agentic 编排能力：由代码固定 workflow 边界，由 bounded ReAct 主循环负责局部工具路由、补料、观察与收敛。QA 节点不再维护私有 `_retrieve_loop`，而是统一委派 R7 主循环；默认只开放 `kb_retrieval`，外部工具 `websearch` / `legal_status` / `official_fee` 需配置显式启用并带 provenance 与时效提示。

本计划只拆解实现路径，不生成业务代码。

## 依赖图

```text
SPEC.md
  -> app/core/config.py
      -> 新增 agentic / tool 开关配置
      -> 删除或迁移 retrieval_react_* 旧 QA 循环配置
      -> to_public_dict() 排除敏感字段、暴露非敏感字段
      -> tests/test_core_config_logging.py

  -> app/orchestrator/tool_registry.py
      -> ToolSpec / ToolInput / ToolObservation 契约
      -> 工具白名单与启用条件
      -> kb_retrieval / websearch / legal_status / official_fee 注册
      -> tests/test_agentic_tools.py

  -> app/orchestrator/react_loop.py
      -> ReActBudget / ReActOutcome / 收敛原因
      -> bounded reason -> act -> observe -> judge -> converge
      -> trace: react_main_step / react_main_converged
      -> tests/test_agentic_loop.py

  -> app/tools/retrieval.py
      -> 保留 R4.3 检索四件套
      -> 被 kb_retrieval 工具适配器复用
      -> tests/test_retrieval_tool.py

  -> app/tools/websearch.py / legal_status.py / official_fee.py
      -> 默认 stub 或关闭
      -> 外部 evidence provenance / retrieved_at / 核对提示
      -> tests/test_agentic_tools.py

  -> app/nodes/qa.py
      -> 删除 _retrieve_loop 及私有循环 helper
      -> 委派 R7 主循环
      -> 消费 ReActOutcome 构造 evidence
      -> 保留 PatentQASkill、法规过时提示、依据不足提示、qa_completed trace
      -> tests/test_qa_node.py

  -> tests/test_qa_react_loop.py
      -> 删除、迁移或改写为 tests/test_agentic_loop.py
```

## 垂直切片原则

每个任务都以“一个可运行路径”为单位拆分，而不是按横向层拆分：

- 先让主循环在 fake 工具下跑通并可观测。
- 再接入真实 KB 检索适配器，形成 QA 默认路径。
- 再把 QA 从私有 `_retrieve_loop` 收编到主循环。
- 最后接外部工具 stub / 开关 / provenance，保证默认不触网。

## Phase 0 — 决策与迁移口径确认

### 目标

在实现前确认两个会影响代码形态的决策，避免后续返工。

### 任务

1. 确认旧配置 `retrieval_react_min_results`、`retrieval_react_min_score`、`retrieval_react_use_llm_judge` 是直接删除，还是保留一个版本兼容读取。
2. 确认外部工具本轮只做 stub / 接口预留，还是接入真实服务。
3. 确认工具选择策略本轮是否先用 deterministic policy，LLM router prompt 仅预留。

### 验收标准

- 决策写入 plan/todo 或实现 PR 描述。
- 若选择真实外部服务，必须补充密钥配置、安全边界和默认测试 stub。

### Checkpoint 0

人工确认后进入 Phase 1。默认建议：直接删除旧 `retrieval_react_*`，外部工具只做 stub / 关闭，工具选择先 deterministic。

---

## Phase 1 — 主循环最小闭环（fake 工具）

### 目标

新增 R7 bounded ReAct 主循环，在不接 QA、不接真实检索的情况下，用 fake 工具证明预算、收敛、trace 与异常降级可测。

### 涉及文件

- `app/orchestrator/react_loop.py`
- `tests/test_agentic_loop.py`

### 实施要点

- 定义 `ReActBudget`、`ReActOutcome`、`ToolObservation` 或等价数据结构。
- 实现收敛原因：`sufficient`、`max_steps`、`token_budget`、`timeout`、`tool_unavailable`、`unsafe_request`。
- 主循环每轮只接收已注册工具名，不动态 import。
- trace 输出 `react_main_step` / `react_main_converged`，只记录摘要字段。
- 工具异常转为可恢复 observation，不裸抛。

### 验收标准

- 证据充分时 1 步收敛。
- 证据不足且有预算时继续下一轮。
- `max_steps<=0` 或 token 预算 `<=0` 不调用工具。
- 工具异常、未知工具、超时都优雅收敛。
- trace 不含完整 query / content。

### 验证命令

```bash
conda run -n autoGLM pytest tests/test_agentic_loop.py
```

### Checkpoint 1

主循环在 fake 工具下稳定后，才接入工具注册和 KB 检索。

---

## Phase 2 — 工具注册与 `kb_retrieval` 默认路径

### 目标

新增工具白名单机制，并把现有 `app/tools/retrieval.py` 包装为 `kb_retrieval` 工具；保持 R4.3 检索四件套不被重写。

### 涉及文件

- `app/orchestrator/tool_registry.py`
- `app/tools/retrieval.py`（只复用，尽量不改）
- `tests/test_agentic_tools.py`
- `tests/test_retrieval_tool.py`（回归）

### 实施要点

- 定义工具注册结构：工具名、是否外部、启用条件、输入 schema、run 接口。
- `kb_retrieval` 调用 `build_retriever(settings).search(query, top_k=...)`。
- observation 归一化为 evidence，保留 `document_id`、`source`、`locator`、`doc_type`、score / similarity、法规时效字段。
- 未注册工具、禁用工具、非法输入全部返回安全失败 observation。

### 验收标准

- 默认 QA 工具白名单只有 `kb_retrieval`。
- 未注册工具不能被调用。
- `kb_retrieval` 复用现有 retriever，测试中可 monkeypatch fake retriever。
- KB evidence provenance 字段完整。
- 默认测试不触网、不连接真实 Qdrant。

### 验证命令

```bash
conda run -n autoGLM pytest tests/test_agentic_tools.py tests/test_retrieval_tool.py
```

### Checkpoint 2

`kb_retrieval` 工具路径可测后，才将 QA 迁移到主循环。

---

## Phase 3 — 配置迁移与工具开关

### 目标

增加 R7 主循环与外部工具开关配置，清理或迁移旧 QA 私有循环配置。

### 涉及文件

- `app/core/config.py`
- `tests/test_core_config_logging.py`

### 实施要点

- 新增非敏感配置：`agentic_enabled`、`agentic_external_tools_enabled`、`agentic_default_tools`、`websearch_enabled`、`legal_status_enabled`、`official_fee_enabled`。
- 继续复用 `retrieval_max_steps`、`retrieval_token_budget`、`retrieval_timeout_seconds` 作为主循环预算。
- 删除或迁移 `retrieval_react_min_results`、`retrieval_react_min_score`、`retrieval_react_use_llm_judge`。
- 同步默认值、环境变量读取、`to_public_dict()`、测试。
- 不把 API Key、token、secret、password 放入公开配置。

### 验收标准

- 新配置默认值符合 SPEC。
- `PAGENT_*` 环境变量覆盖生效。
- 非敏感配置进入 `to_public_dict()`。
- 旧 `retrieval_react_*` 无生产配置残留，或兼容窗口行为有测试覆盖。

### 验证命令

```bash
conda run -n autoGLM pytest tests/test_core_config_logging.py
```

### Checkpoint 3

配置迁移稳定后，再改 QA，避免节点代码依赖不稳定字段。

---

## Phase 4 — QA 收编到 R7 主循环

### 目标

删除 QA 私有 `_retrieve_loop` 路径，让 `QANode.run()` 委派 R7 主循环，同时保留最终回答、风险提示、法规时效提示和 `qa_completed` trace。

### 涉及文件

- `app/nodes/qa.py`
- `tests/test_qa_node.py`
- `tests/test_qa_react_loop.py`（删除、迁移或改写）
- `tests/test_agentic_loop.py`

### 实施要点

- `QANode.__init__` 注入或构造 R7 主循环 / tool registry。
- `QANode.run()` 调用主循环并消费 `ReActOutcome.evidence`。
- 删除私有 helper：`_retrieve`、`_retrieve_loop`、`_accumulate_results`、`_result_key`、`_is_evidence_sufficient`、`_top_score`、`_get_result_score`、`_estimate_evidence_tokens`、`_rewrite_query`、`_build_converged_trace`、`_build_convergence`。
- 保留 `_build_evidence` 或改造为支持通用 evidence。
- `_apply_insufficient_evidence_warning` 改为消费主循环 convergence / outcome。
- trace 从 `qa_react_*` 迁移到 `react_main_*`，保留 `node_name="qa"`。

### 验收标准

- QA 默认只调用 `kb_retrieval`。
- `state.dialog_context["qa_retrieval_results"]` 写入主循环 evidence。
- 依据不足时仍有固定风险提示。
- 法规过时提示保持可用。
- `qa_completed` trace 保持可用。
- 生产代码不再出现 `_retrieve_loop`。

### 验证命令

```bash
conda run -n autoGLM pytest tests/test_qa_node.py tests/test_agentic_loop.py
```

### Checkpoint 4

QA 默认 KB 路径跑通后，再接外部工具 stub。

---

## Phase 5 — 外部工具 stub 与 provenance 规范

### 目标

在默认关闭 / 不触网前提下，预留 `websearch`、`legal_status`、`official_fee` 工具适配器和 provenance 规范。

### 涉及文件

- `app/tools/websearch.py`
- `app/tools/legal_status.py`
- `app/tools/official_fee.py`
- `app/orchestrator/tool_registry.py`
- `tests/test_agentic_tools.py`

### 实施要点

- 三个外部工具默认 disabled 或 stub。
- 启用条件由 `agentic_external_tools_enabled` 和对应工具开关共同决定。
- 输出 evidence 必须有来源、retrieved_at、适用范围 / 时效 / 核对提示。
- 无来源 evidence 不进入最终 `basis`。
- 外部工具失败返回 `tool_unavailable` 或安全 observation。

### 验收标准

- 外部工具默认不调用。
- 开关关闭时即使被选择也拒绝调用。
- stub 输出 provenance 字段完整。
- 无来源 observation 被丢弃或不可引用。
- 默认测试不触网。

### 验证命令

```bash
conda run -n autoGLM pytest tests/test_agentic_tools.py
```

### Checkpoint 5

外部工具契约稳定后，才考虑真实服务接入；真实服务接入需单独确认。

---

## Phase 6 — Prompt / LLM router 预留（可选）

### 目标

如需要 LLM 参与工具选择或收敛判断，集中新增 prompt，并让代码继续裁决白名单和权限。

### 涉及文件

- `app/prompts/react_router.py`
- `app/orchestrator/react_loop.py`
- `tests/test_agentic_loop.py`

### 实施要点

- prompt 覆盖六要素：任务目标、上下文/判定规则、角色、受众、样例、输出格式。
- 用户输入、检索结果、websearch 内容全部包裹在数据区，并声明不作为指令。
- 输出仅 JSON，枚举工具名、置信度、是否收敛、缺口说明。
- LLM 输出只作为建议；代码仍执行白名单、配置、预算和安全裁决。
- LLM 非法 JSON、未知工具或异常时回退 deterministic policy。

### 验收标准

- prompt 不内联在业务逻辑中。
- 非法 JSON / 未知工具测试通过。
- 关闭 LLM router 时不调用模型。
- 默认测试不调用真实 LLM。

### 验证命令

```bash
conda run -n autoGLM pytest tests/test_agentic_loop.py
```

### Checkpoint 6

如果 Phase 0 决定本轮不用 LLM router，则本阶段只保留为后续任务，不阻塞 R7 默认路径验收。

---

## Phase 7 — 回归、清理与验收

### 目标

完成测试迁移、旧循环清理和全量验收。

### 涉及文件

- `tests/test_qa_react_loop.py`
- `tests/test_agentic_loop.py`
- `tests/test_qa_node.py`
- `tests/test_core_config_logging.py`
- `tasks/plan.md`
- `tasks/todo.md`

### 实施要点

- 将 `tests/test_qa_react_loop.py` 的有效用例迁移到 `tests/test_agentic_loop.py` / `tests/test_qa_node.py`。
- 删除旧 `qa_react_step` / `qa_react_converged` 断言，改为 `react_main_*`。
- 用代码搜索确认 `_retrieve_loop` 无生产代码残留。
- 运行目标测试、全量测试、compileall。
- 更新 todo 勾选状态。

### 验收标准

- 目标测试通过。
- 全量测试通过。
- compileall 通过。
- 生产代码不保留两套多轮检索循环。
- 默认测试不触网、不调用真实付费服务。

### 验证命令

```bash
conda run -n autoGLM pytest tests/test_agentic_loop.py tests/test_qa_node.py tests/test_core_config_logging.py
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests scripts
```

## 风险与控制

- **风险：QA 行为回归。** 控制：先用 fake `kb_retrieval` 对齐旧成功路径，再迁移 QA。
- **风险：外部工具误触网。** 控制：默认关闭；测试只用 stub；工具注册层强制检查开关。
- **风险：LLM 越权选工具。** 控制：LLM 只给建议；代码白名单最终裁决。
- **风险：trace 泄露敏感正文。** 控制：测试断言 trace 不含完整 query/content。
- **风险：配置残留造成两套语义。** 控制：优先直接删除旧 `retrieval_react_*`，若兼容则明确窗口和测试。

## 总体验证计划

```bash
conda run -n autoGLM pytest tests/test_agentic_loop.py
conda run -n autoGLM pytest tests/test_agentic_tools.py tests/test_retrieval_tool.py
conda run -n autoGLM pytest tests/test_core_config_logging.py
conda run -n autoGLM pytest tests/test_qa_node.py tests/test_agentic_loop.py
conda run -n autoGLM pytest tests/test_agentic_loop.py tests/test_qa_node.py tests/test_core_config_logging.py
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests scripts
```
