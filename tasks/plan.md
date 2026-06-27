# 专利 Agent 可执行实施计划

## 1. 目标与范围

### MVP 目标

第一阶段目标不是直接实现完整专利 Agent，而是按 `SPEC.md` 建立后续可执行、可验证、可审计的工程路线。MVP 应优先形成三个纵向闭环：

1. 权利要求生成 API 闭环：输入技术方案，返回权利要求初稿、校验结果和下一步建议。
2. 翻译 adapter API 闭环：接收专利文本和术语上下文，调用外部翻译 agent adapter，返回译文、术语表和 trace。
3. 单条权利要求修改 API 闭环：根据用户意见定位目标权利要求，生成 patch，更新版本链并返回差异说明。

### 非目标

- 不在 MVP 内接入真实专利数据库。
- 不要求立即接入真实 LLM；单元测试优先使用 fake adapter / fixed response。
- 不重复实现翻译 agent，只定义外部翻译 agent adapter 边界。
- 不把全局 workflow 做成一个无边界 ReAct loop。
- 不实现前端、用户账号、长期案件记忆和权限系统，除非后续单独立项。

## 2. 目标目录结构

后续实施阶段建议逐步形成以下结构，本次计划阶段不创建这些业务文件：

```text
pagent/
  app/
    main.py
    api/
      routes/
        chat.py
        translate.py
        workflows.py
    core/
      config.py
      logging.py
      security.py
    orchestrator/
      engine.py
      workflow_defs.py
      state.py
      node_base.py
    nodes/
      normalize_input.py
      intent_router.py
      feature_extract.py
      claim_plan.py
      claim_generate.py
      claim_revise.py
      claim_check.py
      qa.py
      translate.py
      report_generate.py
    skills/
      claim_writing.py
      feature_extraction.py
      patent_qa.py
      patent_translation.py
      report_writing.py
    tools/
      llm.py
      retrieval.py
      terminology.py
      validators.py
      document.py
      translation_agent.py
    memory/
      session.py
      case_store.py
      wiki.py
    models/
      schemas.py
    services/
      chat_service.py
      workflow_service.py
      translate_service.py
  tests/
    unit/
    integration/
  tasks/
    plan.md
    todo.md
  SPEC.md
  requirements.txt
```

## 3. 架构约束

### 外层确定性编排

- workflow 由预定义 DAG / 状态机驱动。
- 意图识别只负责路由到预定义 workflow，不临时拼装任意流程。
- 编排层最小单位是 node，而不是 tool 或 skill。
- 每个 node 必须有明确输入、输出、状态推进和失败边界。

### Node / Tool / Skill 边界

| 层级 | 职责 | 禁止事项 |
| --- | --- | --- |
| Tool | 原子能力，如 LLM 调用、术语查询、规则校验、外部翻译 adapter | 不读写 workflow state，不做业务流程判断 |
| Skill | 方法包，包含 prompt 模板、few-shot、领域规则、输出 schema | 不持久化状态，不决定全局流程 |
| Node | 一次业务状态推进，装载 skill 并调用 tool | 不把多个独立业务阶段揉成不可审计的大步骤 |
| Orchestrator | 调度 node、维护 workflow 顺序、重试、回环、trace | 不让 LLM 自由决定全局步骤顺序 |

### 必须复用的能力

- `claim_generate` 与 `claim_revise` 共用 `claim_writing` skill、权利要求 schema、引用关系 validators、术语一致性 validators 和基础合规 validators。
- 技术特征抽取结果供权利要求生成、报告生成、问答解释和后续检索对比复用。
- 翻译只做外部翻译 agent adapter：本系统负责传参、术语上下文、结果接收、错误边界和 trace，不重复实现翻译 agent。
- 报告生成复用 `technical_features`、`claims_draft`、`validation_report` 和可选检索结果，不重复实现权利要求或特征分析逻辑。

### bounded ReAct 使用边界

允许在以下 node 内部局部使用 bounded ReAct：

- 专利问答中的多步资料检索。
- 现有技术检索与对比。
- 技术报告中的开放式分析。

护栏：限定工具集、最大步数、token 预算、超时、结构化输出 schema、trace 写入 state。权利要求主链路 MVP 优先使用确定性节点链和 fake LLM adapter，不依赖开放式 ReAct。

## 4. 核心数据模型

### WorkflowState

用于承载工作记忆和可审计状态：

- `raw_input`：用户原始输入，必须保留。
- `normalized_input`：轻量改写后的输入。
- `intent`：意图识别结果。
- `dialog_context`：会话上下文摘要。
- `invention_disclosure`：结构化技术交底。
- `technical_features`：技术特征清单。
- `claim_plan`：权利要求布局。
- `claims_draft`：当前权利要求草稿。
- `claim_versions`：权利要求版本链。
- `claim_patches`：修改 patch 列表。
- `validation_report`：校验报告。
- `user_feedback`：用户修改意见。
- `trace`：workflow 和 node 执行轨迹。

### NodeResult

所有 node 返回统一结构：

- `status`：`success` / `failed` / `requires_user_input`。
- `output`：结构化输出。
- `errors`：错误列表。
- `next_node`：显式下一节点或由 orchestrator 根据 workflow_def 推导。
- `requires_user_input`：是否需要追问或人审。
- `trace_events`：本节点产生的审计事件。

### SkillContext

调用 skill 时注入：

- `task_type`：任务类型，如 `claim_generate` / `claim_revise`。
- `state_snapshot`：必要状态快照，避免把完整敏感原文传给不需要的工具。
- `domain_rules`：专利撰写规则、术语规则。
- `output_schema`：结构化输出 schema。
- `examples`：少量示例。

### 权利要求相关 schema

- `Claim`：编号、类型、文本、引用编号、术语列表、来源 trace。
- `ClaimSet`：独立权利要求、从属权利要求、版本号、生成时间。
- `ClaimPatch`：目标编号、操作类型、修改前后文本、影响范围、风险说明。
- `ValidationReport`：引用关系、术语一致性、必要技术特征、清楚性、风险提示。

## 5. Workflow 设计

### 权利要求生成 workflow

```text
raw_input
  → normalize_input
  → intent_router
  → disclosure_check
  → feature_extract
  → claim_plan
  → claim_generate
  → claim_check
  → response_format
```

验收标准：

- 保留 `raw_input` 与 `normalized_input`。
- 每个节点输出都通过 Pydantic schema 校验。
- `claim_generate` 只消费结构化特征、布局和 `claim_writing` skill。
- `claim_check` 输出可读的校验报告和修改建议。

验证步骤：

- 使用 fake LLM response 跑通完整链路。
- 使用缺字段输入验证追问状态。
- 使用非法引用关系样例验证 validator 能返回错误。

### 翻译 adapter workflow

```text
text_input
  → detect_language_and_text_type
  → terminology_normalize
  → translate_adapter_node
  → receive_translation_result
  → response_format
```

验收标准：

- 翻译 tool 只调用外部 agent adapter 接口。
- 本系统不实现翻译推理链。
- 返回结果包含译文、术语表、错误边界和 trace。

验证步骤：

- 使用 fake translation adapter 返回固定译文。
- 模拟外部 adapter 超时、空响应、字段缺失。
- 检查日志和 trace 不记录过长原文或敏感信息。

### 单条权利要求修改 workflow

```text
user_feedback + claim_id
  → locate_claim_version
  → parse_revision_intent
  → claim_revise
  → apply_claim_patch
  → claim_check
  → response_format
```

验收标准：

- `claim_revise` 复用 `claim_writing` skill 和同一套权利要求 schema。
- 默认只修改目标权利要求。
- 如必须联动修改其他权利要求，必须返回原因和影响范围。
- 版本链保留修改前后文本和 patch。

验证步骤：

- 使用固定 claim set 修改单条从属权利要求。
- 验证引用关系、术语一致性和版本号更新。
- 验证目标 claim 不存在时返回明确错误。

## 6. 分阶段实施计划

### Phase 0：项目初始化与工程基线

**目标**：建立最小 Python/FastAPI 工程骨架、依赖文件和测试命令，使后续任务有稳定落点。

**任务**：

1. 创建 `requirements.txt`，列出 FastAPI、Pydantic、pytest 等最小依赖。
2. 创建 `app/`、`tests/` 基础目录。
3. 创建 `app/main.py` 健康检查入口。
4. 创建基础配置与日志初始化占位。
5. 建立 pytest 最小测试，验证工程可运行。

**验收标准**：

- `pytest` 可运行并通过最小测试。
- API 健康检查可返回固定状态。
- 不硬编码密钥、API key 或真实外部服务地址。

**验证步骤**：

- 运行 `pytest`。
- 启动 `uvicorn app.main:app --reload` 后访问健康检查接口。

### Phase 1：核心 schema 与 orchestrator 骨架

**目标**：先定义状态、节点结果、基础 orchestrator，使所有后续 node 都有统一协议。

**任务**：

1. 定义 `WorkflowState`、`NodeResult`、`SkillContext`。
2. 定义 `Claim`、`ClaimSet`、`ClaimPatch`、`ValidationReport`。
3. 定义 `Node` 抽象和最小 `run(state) -> NodeResult` 协议。
4. 实现轻量 orchestrator，可按 workflow_def 顺序执行 node。
5. 为 state 合并、node 失败、requires_user_input 写单元测试。

**验收标准**：

- schema 能表达 `SPEC.md` 的核心字段。
- orchestrator 不依赖真实 LLM。
- node 执行 trace 能写入 state。

**验证步骤**：

- 跑 schema 单元测试。
- 使用两个 fake node 验证顺序执行、失败中断和 trace 写入。

### Phase 2：工具层与 skill 层占位实现

**目标**：建立可替换的 adapter 边界，优先用 fake 实现保证测试稳定。

**任务**：

1. 创建 LLM tool adapter 接口和 fake implementation。
2. 创建外部翻译 agent adapter 接口和 fake implementation。
3. 创建 terminology tool 占位接口。
4. 创建 validators：引用关系、术语一致性、基础字段完整性。
5. 创建 `claim_writing` skill，占位输出必须符合权利要求 schema。
6. 创建 `feature_extraction`、`patent_translation`、`report_writing` skill 占位。

**验收标准**：

- 所有 tool 无状态，不读写 workflow state。
- skill 不负责流程编排。
- `claim_generate` 与 `claim_revise` 可以共用 `claim_writing` skill。
- 翻译能力只通过外部 adapter 暴露。

**验证步骤**：

- 使用 fake adapter 单元测试输出解析。
- 使用错误 fake response 验证 schema 校验失败路径。
- 验证 validators 可识别非法引用和术语不一致。

### Phase 3：基础 nodes 实现

**目标**：实现最小业务节点，形成可被 orchestrator 调度的纵向链路。

**任务**：

1. 实现 `normalize_input`：保留原文，生成轻量归一化文本。
2. 实现 `intent_router`：规则优先，路由到预定义 workflow。
3. 实现 `feature_extract`：调用 feature skill 和 fake LLM。
4. 实现 `claim_plan`：生成最小权利要求布局。
5. 实现 `claim_generate`：调用 `claim_writing` skill 生成初稿。
6. 实现 `claim_check`：调用 validators 输出 `ValidationReport`。
7. 实现 `translate` node：调用外部翻译 adapter。
8. 实现 `claim_revise` node：生成并应用结构化 patch。

**验收标准**：

- 每个 node 只推进一个明确业务状态。
- node 输出均为结构化结果。
- 失败时返回 `NodeResult.errors`，不吞异常。
- 修改链路默认只修改目标权利要求。

**验证步骤**：

- 分别运行每个 node 的单元测试。
- 使用 orchestrator 跑通权利要求生成、翻译、单条修改三条最小链路。

### Phase 4：Service 与 API 路由

**目标**：把 workflow 能力封装为服务和 HTTP API，形成可手动调用的闭环。

**任务**：

1. 实现 `workflow_service`：触发权利要求生成 workflow。
2. 实现 `translate_service`：触发翻译 adapter workflow。
3. 实现 claim revision service：触发单条权利要求修改 workflow。
4. 创建 `/workflows/claims` API。
5. 创建 `/translate` API。
6. 创建 `/workflows/claims/{workflow_id}/revise` 或等价修改 API。
7. 统一错误响应和面向普通发明人的提示文案。

**验收标准**：

- API 输入输出有 Pydantic schema。
- API 不直接调用 tool，必须通过 service / orchestrator。
- 返回内容明确提示“辅助初稿，不等同于专利代理师法律意见”。
- 不把完整敏感文本写入日志。

**验证步骤**：

- 使用 TestClient 跑 API 集成测试。
- 验证正常输入、缺字段输入、adapter 失败、校验失败。

### Phase 5：端到端主链路与质量门禁

**目标**：补齐 E2E 测试、质量门禁和风险边界，确保后续增强不会破坏 MVP 骨架。

**任务**：

1. 增加权利要求生成端到端测试。
2. 增加翻译 adapter 端到端测试。
3. 增加单条权利要求修改端到端测试。
4. 增加安全与合规测试：日志脱敏、长文本截断、未校验结果不入长期记忆。
5. 如引入 ruff / mypy，配置并接入本地验证命令。
6. 更新 README 或开发说明，记录本地运行和测试方式。

**验收标准**：

- 三条优先纵向切片均可通过 fake adapter 跑通。
- 所有测试不依赖真实 LLM、真实专利数据库或真实翻译 agent。
- 关键 workflow trace 可检查。
- 失败路径有可读错误和降级说明。

**验证步骤**：

- 运行 `pytest`。
- 如已配置，运行 `ruff check .` 与 `mypy app`。
- 手动调用三个 API，检查返回结构和风险提示。

## 7. 依赖图

```text
Phase 0 工程基线
  │
  └── Phase 1 schema + orchestrator
        │
        ├── Phase 2 tools / skills / validators
        │       │
        │       ├── Phase 3A 权利要求生成 nodes
        │       │       └── Phase 4A 权利要求生成 API
        │       │               └── Phase 5A 权利要求生成 E2E
        │       │
        │       ├── Phase 3B 翻译 adapter node
        │       │       └── Phase 4B 翻译 API
        │       │               └── Phase 5B 翻译 E2E
        │       │
        │       └── Phase 3C 单条修改 nodes
        │               └── Phase 4C 修改 API
        │                       └── Phase 5C 修改 E2E
        │
        └── 共享质量门禁：日志、安全、schema 校验、trace
```

## 8. Checkpoints

### Checkpoint 0：工程基线完成

- [ ] `pytest` 可运行。
- [ ] 健康检查 API 可运行。
- [ ] 项目没有真实外部服务依赖。

### Checkpoint 1：协议层完成

- [ ] 核心 schema 覆盖 `WorkflowState`、`NodeResult`、`SkillContext` 和权利要求相关模型。
- [ ] fake node 能通过 orchestrator 顺序执行。
- [ ] trace 写入可测试。

### Checkpoint 2：能力边界完成

- [ ] tool、skill、node 责任没有混淆。
- [ ] fake LLM 与 fake translation adapter 可替换。
- [ ] validators 可独立测试。

### Checkpoint 3：三条 node 链路完成

- [ ] 权利要求生成 node 链路跑通。
- [ ] 翻译 adapter node 链路跑通。
- [ ] 单条权利要求修改 node 链路跑通。

### Checkpoint 4：API 闭环完成

- [ ] 三条 API 可通过 TestClient 调用。
- [ ] 错误响应结构统一。
- [ ] 用户可见结果包含解释性提示和风险提示。

### Checkpoint 5：MVP 质量门禁完成

- [ ] 端到端测试覆盖三条纵向切片。
- [ ] 不依赖真实 LLM、真实专利数据库、真实翻译 agent。
- [ ] 日志不包含密钥、完整 API key、隐私数据或过长文本。

## 9. 风险与处理

| 风险 | 影响 | 处理策略 |
| --- | --- | --- |
| 过早接入真实 LLM 导致测试不稳定 | 高 | adapter 后置，单元测试使用 fake response |
| tool / skill / node 边界混淆 | 高 | 每个任务验收时检查状态读写位置和流程决策位置 |
| 翻译功能范围膨胀成重写翻译 agent | 中 | 只实现外部 adapter、错误边界和 trace |
| 权利要求生成与修改分叉成两套规则 | 高 | 强制共用 `claim_writing` skill、schema 和 validators |
| workflow 被实现成大 ReAct loop | 高 | 外层 workflow_def 固定，ReAct 仅允许在开放式 node 内部 |
| 日志泄露敏感文本 | 高 | 长文本截断、字段白名单、测试覆盖日志脱敏 |
| 只做横向基础设施，迟迟没有闭环 | 中 | 按三条纵向切片排序，每阶段都验证可运行路径 |

## 10. 最小交付定义

MVP 最小交付必须同时满足：

- 有 FastAPI 服务入口和测试基线。
- 有核心 schema、orchestrator、node 抽象和 trace。
- 权利要求生成 API 可用 fake LLM 跑通。
- 翻译 API 可用 fake external translation adapter 跑通。
- 单条权利要求修改 API 可用固定 claim set 跑通。
- 生成与修改共用 `claim_writing` skill、权利要求 schema 和 validators。
- 翻译不实现内部 agent，只做 adapter。
- 所有自动化测试不依赖真实 LLM、真实专利数据库或真实翻译 agent。
- 用户可见输出包含辅助性质和非法律意见提示。

## 11. 优先纵向切片

### Slice 1：权利要求生成 API 闭环

**路径**：API → service → orchestrator → normalize → intent_router → feature_extract → claim_plan → claim_generate → claim_check → response。

**优先原因**：这是专利 Agent MVP 的主价值链，能验证 schema、skill、validator、orchestrator 和 API 边界。

**验收标准**：

- 输入口语化技术方案后返回结构化权利要求初稿。
- 返回 `validation_report` 和下一步建议。
- trace 能看到每个 node 的执行结果。

**验证步骤**：

- 使用 fake LLM 固定输出跑通集成测试。
- 修改 fake 输出为缺字段，验证校验失败路径。

### Slice 2：翻译 adapter API 闭环

**路径**：API → service → terminology_normalize → translate node → external translation adapter → response。

**优先原因**：验证外部 agent adapter 边界，避免翻译能力侵入主系统。

**验收标准**：

- 返回译文、术语表和 trace。
- adapter 超时或失败时返回可读错误。
- 不要求真实翻译 agent 在线。

**验证步骤**：

- fake adapter 返回成功、超时、字段缺失三类结果。
- 检查 API 响应结构一致。

### Slice 3：单条权利要求修改 API 闭环

**路径**：API → service → locate_claim_version → parse_revision_intent → claim_revise → apply_claim_patch → claim_check → response。

**优先原因**：验证 claim writing 能力复用、版本链、patch 和引用关系校验。

**验收标准**：

- 只修改指定 claim，除非 validator 要求联动。
- 返回修改前后差异、风险提示和新版本号。
- 引用关系和术语一致性重新校验。

**验证步骤**：

- 使用固定 claim set 修改一条从属权利要求。
- 验证目标不存在、引用非法、术语不一致三类失败路径。
