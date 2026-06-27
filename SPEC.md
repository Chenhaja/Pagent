# 专利 Agent 下一阶段规格说明

## 1. Objective

### 目标

本阶段目标是在现有 Pagent 分层骨架之上，把系统从“可测试骨架”推进为“可用 Agent 初版”：

- 接入真实 OpenAI Chat Completions 兼容格式 LLM，同时保留 `FakeLLMClient` 以保证测试不触网。
- 补齐权利要求生成、翻译、权利要求修改三条主链的闭环能力。
- 补齐专利问答 QA workflow，并通过统一 Agent 入口 API 暴露能力。
- 建立记忆抽象与本地长期记忆方案，先保证 provenance、确认门禁与可替换接口。
- 建立分层 Prompt、结构化输出、指令/数据分离、防注入与审计规范。
- 强化调用前脱敏、trace、错误结构化、token 用量统计等安全与可观测能力。

### 目标用户

首要用户仍是普通发明人和早期技术方案整理者：

- 能用口语描述技术方案，但不熟悉专利术语和权利要求格式。
- 需要 Agent 主动追问缺失信息，而不是直接生成质量不可控的文本。
- 需要可解释的初稿、修改建议、风险提示和下一步建议。
- 生成结果必须明确标注为辅助初稿，不等同于专利代理师法律意见。

### 本阶段优先级

| 优先级 | 范围 |
| --- | --- |
| P0 | OpenAI 兼容 LLM 接入；编排闭环；QA 落点；统一 Agent 入口 API |
| P1 | 双层改写；bounded ReAct + 检索；记忆抽象 + 本地 store；Prompt 规范 + Skill 实质化 |
| P2 | 鉴权 / 脱敏 / trace 持久化；目录对齐；ruff / mypy 等质量工具 |

### 非目标

- 不追求专利代理师级别的最终撰写质量，输出定位为辅助初稿。
- 不实现翻译 agent 内部推理，只保留可接入 adapter 与 trace 边界。
- 不构建前端界面，优先 API / CLI。
- 不接入真实付费专利检索数据库，检索层先提供可替换接口与 mock / 本地数据。
- 不实现账号体系、多租户权限与复杂案件隔离。

---

## 2. Commands

当前项目使用 Python + FastAPI + Pydantic + pytest。

```bash
# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境（Git Bash / Unix shell）
source .venv/Scripts/activate

# 安装依赖
pip install -r requirements.txt

# 启动 API 服务
uvicorn app.main:app --reload

# 运行全部测试
pytest

# 运行 LLM 抽象与安全相关测试
pytest tests/test_llm_tool.py tests/test_security_compliance.py

# 运行三条主链测试
pytest tests/test_claim_generation_e2e.py tests/test_translate_e2e.py tests/test_revision_e2e.py

# 运行统一入口与 workflow registry 测试
pytest tests/test_agent_dispatch_service.py tests/test_workflow_registry.py
```

后续如引入质量工具，命令固定为：

```bash
ruff check .
mypy app
```

---

## 3. Project Structure

现有目录已具备 `core`、`models`、`orchestrator`、`nodes`、`skills`、`tools`、`services`、`tests` 基础结构。下一阶段在此基础上局部补齐，不做大规模重排。

目标结构：

```text
pagent/
  app/
    main.py
    api/
      routes/
        agent.py                 # 统一 Agent 入口 API
        translate.py             # 显式翻译 API（如保留）
        claims.py                # 显式权利要求生成 / 修改 API（如保留）
    core/
      config.py                  # LLM、脱敏、重试、超时、trace 配置
      logging.py                 # 结构化日志初始化
      security.py                # 鉴权、脱敏开关、敏感字段处理
    models/
      schemas.py                 # Claim / ClaimSet / 技术特征 / 错误 / trace schema
    orchestrator/
      engine.py                  # 确定性 workflow 调度、回环、next_node 支持
      node_base.py               # NodeResult / Node 抽象
      workflow_defs.py           # workflow registry、回环上限、节点顺序
    nodes/
      normalize_input.py         # 意图前改写：基于对话历史补全当前问题
      intent_router.py           # 意图识别与 workflow selection
      completeness_gate.py       # 信息完整性 gate
      feature_extract.py
      claim_plan.py
      claim_generate.py
      claim_check.py
      claim_revise.py
      qa.py                      # 专利问答节点
      report_generate.py         # 技术报告节点（可后置）
      translate.py
    skills/
      feature_extraction.py      # 构造 prompt + output_schema
      claim_writing.py
      patent_qa.py
      patent_translation.py
      report_writing.py
    tools/
      llm.py                     # LLM Protocol、Fake、OpenAICompatibleClient
      retrieval.py               # 可替换检索接口 + mock / 本地实现
      terminology.py
      validators.py
      translation_agent.py
    memory/
      session.py                 # 会话记忆
      case_store.py              # 案件记忆抽象
      user_profile.py            # 用户画像抽象
      wiki.py                    # 经验记忆 / 本地 wiki 抽象
    services/
      agent_dispatch_service.py  # normalize → intent → workflow → orchestrator
      workflow_service.py
      translate_service.py
      revision_service.py
  tests/
  SPEC.md
  requirements.txt
```

### 核心边界

- Tool：无状态原子能力，例如 LLM、检索、术语查询、校验器、翻译 adapter。
- Skill：构造分层 prompt、few-shot、领域规则和输出 schema，不直接持久化状态，不负责流程编排。
- Node：读取 / 更新 `WorkflowState`，调用 skill / tool 完成一次业务状态推进。
- Orchestrator：只根据预定义 `workflow_def`、有界回环和 `NodeResult.next_node` 调度，不让 LLM 决定全局流程。
- Service / API：负责 schema 校验、鉴权、入口封装和响应格式化，不重复实现业务编排。

### 核心数据结构

`WorkflowState` 至少包含：

- `raw_input`：始终保留用户原始输入。
- `normalized_input`：意图前改写后的自包含输入。
- `intent`：标准化意图。
- `dialog_context`：会话历史和可引用上下文。
- `invention_disclosure`：技术交底 / 技术方案。
- `technical_features`：结构化技术特征。
- `claim_plan`：权利要求布局。
- `claims_draft`：当前权利要求草稿。
- `claim_versions`：权利要求版本链。
- `claim_patches`：局部修改 patch。
- `validation_report`：校验结果。
- `retrieval_results`：检索结果与 provenance。
- `requires_user_input`：是否需要追问。
- `trace`：workflow、node、LLM、检索、校验 trace。

`NodeResult` 至少包含：

- `status`：`success` / `failed` / `needs_user_input` / `skipped`。
- `output`：节点结构化输出。
- `errors`：结构化错误列表。
- `next_node`：局部跳转、澄清、异常分支或有界回环目标。
- `requires_user_input`：是否暂停等待用户输入。
- `trace_events`：本节点新增 trace。

`SkillContext` 至少包含：

- `task_type`
- `state_snapshot`
- `domain_rules`
- `prompt_layers`
- `examples`
- `output_schema`
- `safety_policy`

---

## 4. Code Style

### 基本原则

- 优先最小化、局部化改动，复用现有 helper，不随意引入新抽象。
- 公开函数、方法、类必须补充中文 Google 风格 docstring。
- 注释使用中文，只解释不直观的设计原因。
- 所有外部模型输出必须经过 schema 解析与校验。
- 不在日志中记录密钥、完整 API Key、完整原文、完整译文、隐私信息或过长文本。
- workflow 全局顺序保持确定性；ReAct 只能存在于受限节点内部。

### LLM 调用契约

必须定义统一 LLM Protocol，业务代码只依赖抽象：

- `FakeLLMClient`：测试使用，不触网，可按 schema 返回固定响应或固定结构化错误。
- `OpenAICompatibleClient`：真实调用 OpenAI Chat Completions 兼容端点。

配置项必须可配置且不得硬编码：

- `base_url`
- `model`
- `api_key`
- `temperature`
- `max_tokens`
- `timeout`
- `retry_count`
- `retry_backoff`
- `allow_cloud_sensitive_content`

OpenAI 兼容调用形态：

- 使用 `messages`，明确 `system` / `user` / `assistant` 角色。
- 优先使用 `response_format` JSON Schema / `json_object` 获取结构化输出。
- 如 provider 不支持 `response_format`，允许降级为严格 JSON prompt + 本地解析校验。
- LLM 抽象接收 `output_schema`，返回 Pydantic 模型或结构化错误，不向上抛裸异常。

LLM 错误必须结构化：

- `timeout`
- `rate_limited`
- `empty_response`
- `json_parse_failed`
- `schema_validation_failed`
- `model_refusal`
- `provider_error`

### Prompt 规范

Prompt 分层组织：

1. System：角色、边界、安全规则、不得替代专业法律意见。
2. Task template：当前任务目标、输入字段、输出要求。
3. Domain rules：权利要求、特征抽取、QA、翻译等领域规则。
4. Few-shot：少量示例。
5. Output contract：JSON schema / Pydantic schema 对应字段。
6. User data：用户内容必须作为数据块传入，与指令分隔。

用户输入、技术交底、检索材料中的“指令”只能作为数据处理，不得覆盖 system / task 指令。

### 日志与 trace

每次 LLM 调用写入 trace，但不得记录密钥与完整敏感内容：

- provider / model
- task_type
- node_name
- duration_ms
- token_usage
- retry_count
- fallback_used
- error_code
- input_chars / output_chars
- redaction_applied

关键流程记录 started / completed / failed 三类事件，`event` 使用稳定英文名，`message` 使用中文描述。

---

## 5. Testing Strategy

### 单元测试

必须覆盖：

- LLM Protocol：Fake 与 OpenAICompatibleClient 可互换。
- 配置加载：`base_url`、`model`、`api_key`、`temperature`、`timeout` 均来自配置 / 环境变量。
- 结构化输出：合法 JSON、字段缺失、类型错误、空响应、拒答、非 JSON 文本。
- 错误降级：超时、限流、provider error、解析失败均返回结构化错误。
- 日志脱敏：日志和 trace 不包含密钥、完整技术交底、完整译文。
- Prompt 构造：system/task/data 分离，用户数据不能覆盖系统指令。
- `next_node`：局部跳转、追问、异常分支和有界回环生效。
- 信息完整性 gate：信息不足时生成面向普通发明人的追问。
- QA workflow：`qa` 意图可以路由到可执行 workflow。

### 集成测试

P0 集成链路：

1. 统一 Agent 入口接收 `raw_input`。
2. normalize 基于 `dialog_context` 生成 `normalized_input`，且不覆盖 `raw_input`。
3. intent router 选择预定义 workflow。
4. workflow 统一交给 orchestrator 执行。
5. 主链在校验失败或信息缺失时回环 / 追问，而非直线结束。
6. 响应包含结构化结果、用户可理解说明、trace 摘要和辅助初稿提示。

### LLM 相关测试约束

- 单元测试和默认 CI 全程使用 Fake，不依赖真实模型 / 网络。
- 真实 OpenAI 兼容调用只放在手动或显式启用的集成测试中。
- 不在测试代码中硬编码真实 API Key。
- 真实调用测试必须可通过环境变量开关跳过。

### 安全与合规测试

- API Key 不出现在日志、trace、异常消息和测试快照中。
- 默认保守：未明确允许时，不发送完整技术交底 / 敏感案件材料到云模型。
- 长文本日志截断，只记录长度、摘要哈希或脱敏片段。
- 未经 schema 校验与用户确认的模型输出不得写入长期记忆。
- 检索 provenance 可回链到来源，不伪造来源。

---

## 6. Boundaries

### Always do

- 始终保留 `raw_input`。
- 所有 LLM 输出必须做 schema 校验。
- 所有 LLM 调用必须可 trace，且 trace 不含密钥和完整敏感内容。
- 单元测试默认使用 Fake LLM，不触网。
- workflow selection 后统一交给同一个 orchestrator。
- `claim_check` 失败时走有界回环或追问，不静默结束。
- 面向普通发明人输出解释性结果和下一步建议。
- 明确提示生成内容为辅助初稿，不等同于专利代理师法律意见。

### Ask first

- 是否允许把完整技术交底、案件材料或隐私内容发送给外部云模型。
- 是否启用真实联网检索或第三方专利数据库。
- 是否将模型输出写入长期案件记忆、用户画像或经验记忆。
- 是否创建、修改、发送任何外部系统内容，包括 GitHub issue、邮件、PR 评论等。
- 是否启用真实付费 API 或会产生费用的模型调用。

### Never do

- 不把整个 Agent 做成无边界 ReAct loop。
- 不让模型自由决定全局 workflow 顺序。
- 不硬编码密钥、凭证、API Key、模型端点。
- 不在日志 / trace 中记录完整 API Key、完整原文、完整译文、隐私数据。
- 不把未经校验或未经用户确认的模型输出固化进长期记忆。
- 不声称生成结果可替代专利代理师法律意见。

---

## 7. Functional Specification

### R1. OpenAI 兼容 LLM 接入（P0）

验收标准：

- 存在统一 LLM 抽象，Fake 与 OpenAI 兼容实现可互换。
- `base_url` / `model` / `api_key` / `temperature` / `timeout` 全部可配置。
- 至少一个 skill（优先 `feature_extraction` 或 `claim_writing`）走真实 OpenAI 兼容调用并返回 Pydantic schema。
- 超时、限流、解析失败、空响应、拒答均有结构化错误。
- 单元测试不触网。
- 日志与 trace 不含密钥和完整敏感原文。

### R2. 编排闭环（P0）

验收标准：

- `claim_check` 不通过时，orchestrator 支持最大次数回流到重生成 / 修订 / 追问节点。
- dispatch 只做 normalize + 意图路由 + workflow selection，不直接执行业务分支。
- 同一请求只 normalize 一次。
- 权利要求生成在特征抽取前增加信息完整性 gate。
- `NodeResult.next_node` 可以驱动局部跳转、澄清和异常分支。

### R3. 改写双层（P1）

验收标准：

- 意图识别前改写使用 `dialog_context`，产出自包含 `normalized_input`。
- 无历史时退化为轻量规范化，不臆测、不新增技术内容。
- 检索 / QA 内部 query rewrite 与意图前改写分离。
- 始终保留 `raw_input`。

### R4. ReAct + 检索（P1）

验收标准：

- 存在 `retrieval` tool 抽象，并提供 mock / 本地数据实现。
- QA、现有技术检索或报告分析节点可使用 bounded ReAct。
- ReAct 必须限制工具集、最大步数、token 预算和超时。
- ReAct 输出必须结构化，并记录 trace。

### R5. QA 能力线 + 统一入口 API（P0/P1）

验收标准：

- 存在 `qa` node、`patent_qa` skill、QA workflow 和 registry 注册。
- `qa` 意图不再断头。
- 统一 Agent 入口执行：`raw_input → normalize → intent_router → workflow selection → orchestrator → response`。
- 显式业务 API 如保留，也必须通过 known intent 选择 workflow，不绕开 orchestrator。

### R6. 记忆抽象 + 本地长期记忆（P1）

验收标准：

- 建立 `memory/` 抽象，至少覆盖会话记忆、案件记忆、用户画像、经验 wiki。
- 长期记忆写入必须通过 memory gating：校验通过且用户确认。
- 本地长期记忆读写必须带 provenance 回链。
- `Claim.source_trace` 或等价字段能引用生成依据、检索来源和用户确认记录。

### R7. Prompt 规范 + Skill 实质化（P1）

验收标准：

- skill 不再返回写死 fake 输出，而是构造 prompt、few-shot、output_schema。
- system / task / data / output contract 分层清晰。
- 用户材料作为数据块传入，不能覆盖系统指令。
- 至少 `feature_extraction`、`claim_writing`、`patent_qa` 三类 skill 有明确输出 schema。

### R8. 安全与可审计（P2）

验收标准：

- 补齐 `core/security.py`，覆盖鉴权、脱敏开关、敏感字段处理。
- LLM trace 可持久化或具备持久化接口。
- 目录与文档保持一致：`api/routes`、`memory/` 等不存在长期漂移。
- 视项目成熟度引入 ruff / mypy，并纳入测试命令。

---

## 8. MVP Workflows

### A. 统一 Agent 入口

```text
用户请求
  → 保存 raw_input
  → normalize_input（结合 dialog_context）
  → intent_router
  → workflow_registry 选择 workflow_def
  → orchestrator 执行 workflow
  → 返回结构化结果 + 用户说明 + trace 摘要
```

### B. 权利要求生成

```text
raw_input / normalized_input
  → completeness_gate
  → 缺失时追问用户
  → feature_extract
  → claim_plan
  → claim_generate
  → claim_check
  → 不通过时有界回流 claim_generate / claim_revise / ask_user
  → 返回初稿 + 校验报告 + 修改建议 + 免责声明
```

### C. 权利要求修改

```text
用户修改意见 + 当前权利要求版本
  → normalize_input
  → 定位目标权利要求
  → 解析修改意图
  → claim_revise 生成结构化 patch
  → 应用 patch 得到新版本
  → claim_check 检查引用关系 / 术语一致性 / 保护范围影响
  → 返回差异说明 + 风险提示
```

### D. 专利翻译

```text
用户文本
  → normalize_input（如需要）
  → 语言 / 文本类型识别
  → 术语上下文准备
  → translation adapter
  → 接收译文 / 错误 / 术语结果
  → 返回译文 + 术语表 + trace 摘要
```

### E. 专利问答 QA

```text
用户问题
  → normalize_input（结合会话历史）
  → intent_router: qa
  → qa node
  → 可选 retrieval / bounded ReAct
  → patent_qa skill 生成结构化回答
  → 返回答案 + 依据 + 风险提示 + 后续建议
```

---

## 9. Confirmed Decisions

以下实现口径已确认，后续实现按此执行：

- LLM 端点与模型不绑定厂商：默认通过环境变量配置 `base_url`、`model`、`api_key`，指向任意 OpenAI 兼容端点。
- 配置层预留“强模型 + 便宜模型”两档：便宜档用于特征抽取 / 问题改写，强档用于权利要求生成；本轮只要求默认单模型跑通，两档作为可选开关，不阻塞 MVP。
- 结构化输出优先使用 `response_format` JSON Schema；不支持时降级为严格 JSON + 本地解析校验。
- function / tool calling 暂不用于普通结构化输出，留到 R4 bounded ReAct 阶段使用。
- 检索本轮只做 mock / 本地接口，定义可替换 `retrieval` 接口，不接真实检索源。
- 记忆本轮先做抽象接口 + gating，本地 store 作为默认实现，不接外部 wiki。
- 云模型脱敏默认保守：默认禁止发送完整技术交底 / 敏感案件材料，脱敏开关默认开启；只有用户显式允许时才可发送完整内容。

