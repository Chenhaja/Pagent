# 专利 Agent 实施任务清单

> 原则：优先形成纵向闭环，而不是只搭横向层。每个阶段完成后都要运行对应验证项；MVP 测试不得依赖真实 LLM、真实专利数据库或真实翻译 agent。

## Phase 0：项目初始化与工程基线

- [x] 创建最小 Python 项目结构：`app/`、`tests/`、`requirements.txt`。
  - 验收标准：目录和依赖文件存在，未创建无关业务模块。
  - 验证步骤：检查目录结构，确认依赖只包含 MVP 必需项。
- [x] 创建 FastAPI 入口和健康检查接口。
  - 验收标准：健康检查返回固定状态。
  - 验证步骤：启动本地服务后访问健康检查接口。
- [x] 创建基础配置和日志初始化占位。
  - 验收标准：不硬编码密钥、凭证或真实外部服务地址。
  - 验证步骤：检查配置默认值和日志字段。
- [x] 创建 pytest 最小测试。
  - 验收标准：测试能证明工程可运行。
  - 验证步骤：运行 `pytest`。
- [x] Phase 0 checkpoint。
  - 验收标准：工程基线可运行。
  - 验证步骤：`pytest` 通过，健康检查可调用。

## Phase 1：核心 schema 与 orchestrator 骨架

- [x] 定义 `WorkflowState`。
  - 验收标准：包含 `raw_input`、`normalized_input`、`intent`、`technical_features`、`claim_plan`、`claims_draft`、`claim_versions`、`claim_patches`、`validation_report`、`trace` 等核心字段。
  - 验证步骤：运行 schema 单元测试。
- [x] 定义 `NodeResult`。
  - 验收标准：包含 `status`、`output`、`errors`、`next_node`、`requires_user_input`、`trace_events`。
  - 验证步骤：测试 success、failed、requires_user_input 三类结果。
- [x] 定义 `SkillContext`。
  - 验收标准：可表达 `task_type`、`state_snapshot`、`domain_rules`、`output_schema`、`examples`。
  - 验证步骤：测试 skill 调用上下文序列化。
- [x] 定义权利要求相关模型：`Claim`、`ClaimSet`、`ClaimPatch`、`ValidationReport`。
  - 验收标准：可表达生成、修改、版本链和校验报告。
  - 验证步骤：测试正常样例和字段缺失样例。
- [x] 实现 node 抽象协议。
  - 验收标准：所有 node 统一使用 `run(state) -> NodeResult` 或等价协议。
  - 验证步骤：用 fake node 验证接口一致。
- [x] 实现轻量 orchestrator。
  - 验收标准：按 workflow_def 顺序执行 node，失败时中断或返回用户输入需求。
  - 验证步骤：用 fake node 测试顺序执行、失败中断、trace 写入。
- [x] Phase 1 checkpoint。
  - 验收标准：协议层可支撑后续所有 node。
  - 验证步骤：运行 schema 和 orchestrator 单元测试。

## Phase 2：工具层与 skill 层

- [x] 创建 LLM tool adapter 接口和 fake implementation。
  - 验收标准：业务代码不直接依赖真实 LLM。
  - 验证步骤：测试 fake response 可被解析，错误 response 可被捕获。
- [x] 创建外部翻译 agent adapter 接口和 fake implementation。
  - 验收标准：系统只定义 adapter，不实现翻译 agent 内部逻辑。
  - 验证步骤：测试成功、超时、字段缺失三类 adapter 结果。
- [x] 创建 terminology tool 占位接口。
  - 验收标准：只做术语查询 / 规范化边界，不读写 workflow state。
  - 验证步骤：用固定术语表测试命中和未命中。
- [x] 创建 validators：引用关系、术语一致性、基础字段完整性。
  - 验收标准：validators 无状态，可独立调用。
  - 验证步骤：测试非法引用、术语不一致和缺字段。
- [x] 创建 `claim_writing` skill 占位。
  - 验收标准：生成和修改都能复用同一 skill，输出符合权利要求 schema。
  - 验证步骤：分别用 `claim_generate` 和 `claim_revise` 上下文调用 fake 输出。
- [x] 创建 `feature_extraction` skill 占位。
  - 验收标准：输出结构化技术特征。
  - 验证步骤：用固定输入测试必要特征和附加特征字段。
- [x] 创建 `patent_translation` skill / adapter 上下文占位。
  - 验收标准：只组织术语上下文，不实现翻译推理。
  - 验证步骤：确认输出传给 external translation adapter。
- [x] 创建 `report_writing` skill 占位。
  - 验收标准：声明复用 `technical_features`、`claims_draft`、`validation_report`。
  - 验证步骤：测试缺少关键输入时返回明确错误。
- [x] Phase 2 checkpoint。
  - 验收标准：tool、skill、validator 边界清晰且可替换。
  - 验证步骤：运行工具层和 skill 层单元测试。

## Phase 3：业务 nodes

- [x] 实现 `normalize_input` node。
  - 验收标准：保留 `raw_input`，生成 `normalized_input`，不臆测技术内容。
  - 验证步骤：测试普通输入、多轮指代输入和空输入。
- [x] 实现 `intent_router` node。
  - 验收标准：路由到预定义 workflow，不动态拼装任意流程。
  - 验证步骤：测试权利要求生成、翻译、问答、未知意图。
- [x] 实现 `feature_extract` node。
  - 验收标准：调用 feature skill，写入 `technical_features`。
  - 验证步骤：用 fake LLM 跑单元测试。
- [x] 实现 `claim_plan` node。
  - 验收标准：生成最小权利要求布局，供后续 claim generation 使用。
  - 验证步骤：测试独权 / 从权布局输出。
- [x] 实现 `claim_generate` node。
  - 验收标准：调用 `claim_writing` skill，输出 `claims_draft`。
  - 验证步骤：测试正常生成和 schema 校验失败。
- [x] 实现 `claim_check` node。
  - 验收标准：调用 validators，输出 `validation_report`。
  - 验证步骤：测试合法 claim set、非法引用、术语不一致。
- [x] 实现 `translate` node。
  - 验收标准：调用外部翻译 adapter，返回译文、术语表、trace。
  - 验证步骤：测试成功、超时、空响应、字段缺失。
- [x] 实现 `claim_revise` node。
  - 验收标准：复用 `claim_writing` skill，默认只修改目标权利要求，输出结构化 patch。
  - 验证步骤：测试目标 claim 存在、不存在、需要联动修改三类情况。
- [x] Phase 3 checkpoint。
  - 验收标准：三条 node 链路都能通过 orchestrator 跑通。
  - 验证步骤：运行权利要求生成、翻译、单条修改链路测试。

## Phase 4：Service、显式 API 与 routing 边界

- [x] 实现 `workflow_service`。
  - 验收标准：封装权利要求生成 workflow，API 不直接调 node 或 tool。
  - 验证步骤：服务层单元测试覆盖成功和失败。
- [x] 实现 `translate_service`。
  - 验收标准：封装翻译 adapter workflow。
  - 验证步骤：服务层测试 adapter 成功和失败。
- [x] 实现 claim revision service。
  - 验收标准：封装单条权利要求修改 workflow 和版本链处理。
  - 验证步骤：测试 patch 应用和版本号更新。
- [x] 创建权利要求生成 API。
  - 验收标准：输入输出均有 Pydantic schema，返回初稿、校验报告、下一步建议。
  - 验证步骤：用 TestClient 跑成功、缺字段、校验失败。
- [x] 创建翻译 API。
  - 验收标准：返回译文、术语表、trace；不要求真实翻译 agent。
  - 验证步骤：用 TestClient 跑 adapter 成功和失败。
- [x] 创建单条权利要求修改 API。
  - 验收标准：返回修改后 claim、差异说明、风险提示、新版本号。
  - 验证步骤：用 TestClient 跑正常修改、目标不存在、引用非法。
- [x] 统一错误响应和用户提示。
  - 验收标准：面向普通发明人可理解，包含“辅助初稿，不等同于专利代理师法律意见”。
  - 验证步骤：检查三类 API 的错误和成功响应。
- [x] 补齐通用 dispatch / 统一 Agent 入口规格。
  - 验收标准：统一入口表达为 `normalize → intent_router → workflow selection → orchestrator → nodes`。
  - 验证步骤：检查 `SPEC.md` 与 `tasks/plan.md` 中统一 Agent 入口路径一致。
- [x] 明确显式业务 API 的 known intent 路径。
  - 验收标准：显式业务 API 复用 concrete workflow，不承担全局意图识别职责。
  - 验证步骤：搜索“显式业务 API”和“known intent”，确认边界一致。
- [ ] Phase 4 checkpoint。
  - 验收标准：显式业务 API 闭环状态清晰；通用 dispatch / Agent entry 规格清晰；routing 不下沉到 service/server。
  - 验证步骤：运行 API 集成测试，并检查文档中没有把 `intent_router` 放进具体业务 workflow 内部的主路径。

## Phase 5：端到端验证与质量门禁

- [ ] 增加权利要求生成 E2E 测试。
  - 验收标准：口语化技术方案可生成 claim draft、validation report 和 trace。
  - 验证步骤：运行对应集成测试。
- [ ] 增加翻译 adapter E2E 测试。
  - 验收标准：fake external translation adapter 可完成闭环。
  - 验证步骤：运行翻译 API 集成测试。
- [ ] 增加单条权利要求修改 E2E 测试。
  - 验收标准：固定 claim set 可完成 patch、版本更新和重新校验。
  - 验证步骤：运行修改 API 集成测试。
- [ ] 增加安全与合规测试。
  - 验收标准：日志不包含密钥、完整 API key、隐私数据或过长文本；未经校验输出不进入长期记忆。
  - 验证步骤：运行日志脱敏和边界测试。
- [ ] 如引入 ruff / mypy，配置质量检查命令。
  - 验收标准：质量检查可本地运行，不阻塞尚未启用的目录。
  - 验证步骤：运行 `ruff check .` 和 `mypy app`。
- [ ] 记录本地运行和测试方式。
  - 验收标准：开发者能按说明启动服务、运行测试。
  - 验证步骤：按文档从零执行一次。
- [ ] Phase 5 checkpoint。
  - 验收标准：MVP 最小交付定义全部满足。
  - 验证步骤：运行完整测试和三条 API 手动检查。

## 当前文档修正阶段：Workflow routing 架构修正

- [x] 修正 `SPEC.md` 架构分层。
  - 验收标准：明确双入口、routing 层、workflow registry、orchestrator 和 nodes 的边界。
  - 验证步骤：搜索 `intent_router`、`意图识别`、`路由`，确认上下文指向 workflow selection。
- [x] 修正 `tasks/plan.md` workflow 路径和 vertical slices。
  - 验收标准：计划中的 workflow 和 slice 都体现 normalize / known intent 或 recognized intent → routing → orchestrator → nodes。
  - 验证步骤：逐个检查权利要求生成、翻译、局部修改三条路径。
- [x] 修正 `tasks/todo.md` Phase 状态与 stale slice。
  - 验收标准：文档修正任务与后续代码实现任务分开，不再出现 Phase 已完成但 Slice 全部未开始的冲突。
  - 验证步骤：检查 Phase 4、Phase 5、纵向闭环状态汇总。
- [x] 三文档术语一致性检查。
  - 验收标准：三份文档对 routing 归属、service/API 边界、当前阶段范围保持一致。
  - 验证步骤：搜索 `intent_router`、`workflow_def`、`orchestrator`、`service`、`显式业务 API`、`统一 Agent 入口`。

## 纵向闭环状态汇总

### Slice 1：共同编排骨架闭环

- [x] 定义最小 schema、`WorkflowState`、`NodeResult`、`SkillContext`。
- [x] 实现 orchestrator 按 workflow_def 顺序执行 node。
- [x] 实现 normalize 与 intent_router node。
- [x] 补齐 workflow registry / workflow_defs 集中注册规格和后续实现。
- [x] 补齐统一 Agent 入口：`normalize → intent_router → workflow selection → orchestrator → nodes`。
- [x] 验证显式业务 API 与统一入口命中同一 concrete workflow。

### Slice 2：权利要求生成完整路径

- [x] 定义权利要求生成所需 schema。
- [x] 实现 fake feature extraction 和 fake claim writing 输出。
- [x] 实现 feature_extract、claim_plan、claim_generate、claim_check nodes。
- [x] 实现 claim generation service 和 API。
- [x] 验证输入口语化技术方案后返回权利要求初稿、校验报告、下一步建议和 trace。
- [x] 验证 fake LLM 输出缺字段时返回结构化错误。
- [x] 按修正后的 routing 架构验证显式 API 以 known intent 选择 `claim_generation` workflow。

### Slice 3：翻译 adapter 完整路径

- [x] 定义翻译请求、翻译结果和 adapter 错误 schema。
- [x] 实现 fake external translation adapter。
- [x] 实现 terminology_normalize / translate node 所需能力。
- [x] 实现 translate service 和 API。
- [x] 验证成功返回译文、术语表和 trace。
- [x] 验证超时、空响应、字段缺失的错误边界。
- [x] 按修正后的 routing 架构验证显式 `/translate` 以 known intent 选择 `translation` workflow。

### Slice 4：单条权利要求修改完整路径

- [x] 准备固定 claim set 测试数据。
- [x] 实现 locate_claim_version、parse_revision_intent、claim_revise、apply_claim_patch、claim_check 链路。
- [x] 复用 `claim_writing` skill、权利要求 schema 和 validators。
- [x] 实现 revision service。
- [x] 实现 revision API。
- [x] 验证只修改目标 claim，返回差异说明、风险提示和新版本号。
- [x] 验证目标不存在、引用非法、术语不一致三类失败路径。
