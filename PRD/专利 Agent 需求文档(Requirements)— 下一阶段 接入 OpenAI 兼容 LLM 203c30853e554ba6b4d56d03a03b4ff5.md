# 专利 Agent 需求文档(Requirements)— 下一阶段 / 接入 OpenAI 兼容 LLM

<aside>
🎯

本文件是 **Requirements(需求)**,只描述「要什么 / 为什么 / 验收标准」,**不规定实现细节**——具体技术方案留给后续 `SPEC.md`。本轮迭代的两条主线:① 把现有 Pagent 骨架的「智能闭环」补齐;② **正式从 Fake LLM 切换到真实的 OpenAI 兼容格式 LLM 调用**。

</aside>

## 1. 背景与现状

现有 Pagent 已经完成一套忠实于架构的**分层骨架**:Tool / Node / Skill 三层边界清晰、orchestrator 按预定义 `workflow_def` 确定性顺序执行、`WorkflowState` 作为黑板、validators 无状态、测试覆盖完整(TDD)。

但两个关键短板使它目前只是「骨架」而非「可用 Agent」:

- **LLM 仍是 `FakeLLMClient`**:所有 skill 返回写死的固定输出,`generate()` 完全忽略 prompt 与 output schema。系统还没有真正"思考"过。
- **智能闭环缺失**:没有校验回环、第二种改写、ReAct/检索、记忆、LLM Wiki、真实 Prompt 规范。

本需求文档面向**下一阶段迭代**,目标是补齐上述闭环,并以**真实 OpenAI 兼容 LLM** 驱动各 skill / node。

## 2. 目标(Goals)

- G1：定义统一的 **LLM 调用契约(OpenAI 兼容格式)**,让所有 skill / node 通过同一个 LLM 抽象调用真实模型,且可在 Fake / 真实模型之间无缝切换(测试不依赖真实模型)。
- G2：让现有三条主链(权利要求生成 / 翻译 / 权利要求修改)**真正闭环**:补齐校验回环、统一编排、信息完整性追问。
- G3：补齐 **专利问答(QA)** 这条目前断头的能力线,并暴露**统一 Agent 入口 API**。
- G4：把「记忆 + LLM Wiki」从零落地,**以 Notion 数据库作为 wiki 承载**。
- G5：建立**分层 Prompt 规范 + 指令/数据分离防注入 + 输出契约**,并让 skill 实质化。
- G6：强化**安全与可审计**(调用前脱敏、trace 落库、provenance 回链)。

## 3. 非目标(Non-Goals)

- 不在本轮追求专利代理师级别的精细度;生成结果仍定位为「辅助初稿」。
- 不实现翻译 agent 内部推理(仍只做可接入 adapter)。
- 不构建前端界面(API / CLI 优先)。
- 不接入真实付费专利检索数据库(检索层先以可替换接口 + 本地/mock 数据)。
- 不做账号体系 / 多租户权限(可作为更后续阶段)。

---

## 4. 核心需求:接入 OpenAI 兼容格式 LLM(本轮重点)

<aside>
⭐

这是本轮最优先、最明确的需求。所有"智能"能力都依赖它先就位。

</aside>

### R1.1 统一 LLM 抽象(Protocol)

- 定义一个 LLM 客户端抽象(protocol / 接口),`FakeLLMClient` 与真实 `OpenAICompatibleClient` 都实现它。
- 业务代码(skill / node)**只依赖抽象,不依赖具体实现**;通过依赖注入选择实现。
- 单元测试继续用 Fake 实现,**不得依赖真实模型 / 网络**。

### R1.2 OpenAI 兼容调用形态

- 采用 **OpenAI Chat Completions 兼容格式**:`messages`(system / user / assistant 角色)、`model`、`temperature`、`max_tokens`、`timeout` 等标准参数。
- **`base_url` 可配置**:必须支持指向任意 OpenAI 兼容端点(OpenAI 官方、Azure OpenAI、国内兼容网关、本地 vLLM / Ollama 兼容层等),而不是写死 [openai.com](http://openai.com)。
- **`model` 可配置**:模型名从配置读取,便于切换。
- API Key 等凭证**只从环境变量 / 配置读取,严禁硬编码**,且不得进入日志。

### R1.3 结构化输出(输出契约)

- 调用必须支持**结构化输出**:优先使用 OpenAI 的 `response_format`(JSON Schema / json_object)或 function/tool calling,让模型输出可直接映射到 Pydantic schema(`Claim` / `ClaimSet` / `技术特征` 等)。
- LLM 抽象应接收期望的 `output_schema`,并把模型返回**解析 + 校验**为对应 Pydantic 模型;解析失败要走结构化降级,而非抛裸异常。

### R1.4 健壮性与边界

- 支持 **超时、重试(指数退避)、限流处理**。
- 对以下情况均返回结构化错误并可被上层节点消费:超时、空响应、字段缺失、JSON 解析失败、模型拒答。
- **调用前可选脱敏开关**:是否把完整技术交底 / 敏感案件材料发送给云模型,需可配置且默认保守。

### R1.5 可观测与审计

- 每次 LLM 调用写入 trace:模型名、token 用量、耗时、是否命中降级(**不记录密钥、完整原文 / 译文、隐私信息**)。
- token 用量可累计,为后续「token 预算」护栏打基础。

### R1.6 多模型 / Provider 适配

- 通过 adapter 形态预留**按任务选择不同模型**的能力(如:特征抽取用便宜模型、权利要求生成用强模型),本轮至少保证「单模型可配 + 接口可扩展」。

**R1 验收标准**

- [ ]  存在统一 LLM 抽象,Fake 与 OpenAI 兼容实现可互换。
- [ ]  `base_url` / `model` / `api_key` / `temperature` / `timeout` 全部可配置,均不硬编码。
- [ ]  至少一个 skill(如 `claim_writing` 或 `feature_extraction`)走真实 OpenAI 兼容调用并返回符合 Pydantic schema 的结构化输出。
- [ ]  超时 / 限流 / 解析失败 / 空响应均有降级与结构化错误。
- [ ]  单元测试全程使用 Fake,不触网。
- [ ]  日志与 trace 不含密钥与完整敏感原文。

---

## 5. 其余功能需求

### R2 编排闭环(P0)

- **R2.1 校验回环**:`claim_check` 不通过时,orchestrator 能有界回流(重生成 / 触发修订 / 向用户追问),而非直线结束。需支持最大回环次数。
- **R2.2 统一编排**:dispatch 仅负责 normalize + 意图路由,选出 `workflow_def` 后**统一交给同一个 Orchestrator** 执行;消除「业务 service 各自持有 orchestrator」「同一请求重复 normalize」的双轨问题。
- **R2.3 信息完整性 gate**:权利要求生成在特征抽取前增加完整性检查节点,缺失时面向普通发明人追问。
- **R2.4 `next_node` 生效**:让 `NodeResult.next_node` 真正驱动局部跳转 / 澄清 / 异常分支。

**验收**:三条主链在校验失败、信息缺失时都能正确回环或追问;同一请求只 normalize 一次。

### R3 改写双层(P1)

- **R3.1 问题改写(基于对话历史)**:意图识别**前**,利用大模型**根据对话历史对当前问题进行改写**,把上下文信息(指代、省略、延续的话题)融入当前问题,产出一个**自包含、可独立理解**的改写结果(写入 `normalized_input`),供意图识别与后续节点使用;且**始终保留 `raw_input`**。
    - 必须**参考会话上下文**(`dialog_context` / 历史轮次),而非仅看单轮输入——替换当前“直接字符串拼接上一轮输入”的粗糙实现。
    - 典型场景:用户上一轮问“这个方案能不能申请专利”,本轮只说“那它的权利要求怎么写”,改写后应还原为“<上一轮方案>的权利要求怎么写”。
    - 边界:只做指代消解 / 上下文补全,**不臆测、不新增技术内容**;无可用历史时退化为对单轮输入的轻量规范化。
- **R3.2 任务内改写**:进入检索 / QA 节点后的 query 改写,与意图前改写分离。

### R4 ReAct + 检索(P1)

- **R4.1 检索 tool**:补齐 `retrieval` 工具(本轮可用可替换接口 + mock / 本地数据)。
- **R4.2 bounded ReAct**:在问答 / 现有技术检索 / 报告开放式分析节点内引入受限 ReAct,**必须带护栏**:限定工具集、最大步数、token 预算、超时、结构化输出、trace 落库。

### R5 QA 能力线 + 统一入口 API(P0/P1)

- **R5.1 QA 落点**:补齐 `qa` / `report` 的 node + workflow + registry 注册(当前 `qa` 意图断头)。
- **R5.2 统一 Agent 入口 API**:把 `AgentDispatchService` 暴露为一个 endpoint,实现「统一入口 → normalize → 意图路由 → workflow selection → orchestrator」。

### R6 记忆 + Notion LLM Wiki(P1)

<aside>
🧠

Notion 本身就是 wiki。案件页 / 用户画像页 / 审查员页可以直接用 **Notion 数据库**承载,agent 通过读写这些页面来维护 LLM Wiki——人和 agent 共用同一份记忆,天然可编辑、可追溯。

</aside>

- **R6.1 四类记忆**:会话记忆 / 案件记忆 / 用户画像 / 经验(wiki)记忆,先建立 `memory/` 抽象(SPEC 列了但目录目前不存在)。
- **R6.2 memory gating**:未经校验 / 未经用户确认的模型输出**不得**写入长期记忆。
- **R6.3 Notion 作为 wiki 承载**:案件 / 用户画像 / 审查员以 Notion 数据库页面承载;读写带 **provenance 回链**(填充目前空置的 `Claim.source_trace`)。

### R7 Prompt 规范 + Skill 实质化(P1)

- **R7.1 分层 Prompt**:system(角色/规则) / 任务模板 / few-shot / 输出契约分层组织。
- **R7.2 指令-数据分离防注入**:用户内容与系统指令严格分隔,防止交底材料里的"指令"被执行。
- **R7.3 Skill 实质化**:skill 真正构造 prompt + few-shot + 填充 `SkillContext.output_schema`,不再返回写死 fake 输出。

### R8 安全与可审计(P2)

- **R8.1**:补 `core/security.py`(鉴权、脱敏开关)。
- **R8.2**:trace 持久化落库(目前只活在内存 `WorkflowState`)。
- **R8.3**:文档/目录对齐(`api/routes`、`memory/` 等 SPEC 与实现漂移);视情况引入 ruff / mypy。

---

## 6. 约束与原则

- workflow 全局顺序必须确定性,**不交给 LLM 自由决定**;ReAct 仅在受限节点内、且带护栏。
- 对所有模型输出做 schema 校验;未经校验 / 未确认不得固化进长期记忆。
- 不硬编码密钥;日志不含密钥、完整原文 / 译文、隐私、过长文本。
- 始终保留 `raw_input`;面向普通发明人输出解释性结果并标注「辅助初稿,不等同于专利代理师法律意见」。

## 7. 优先级汇总

| 优先级 | 需求 |
| --- | --- |
| P0 | R1 LLM 接入 / R2 编排闭环 / R5 QA 落点 + 统一入口 API |
| P1 | R3 改写双层 / R4 ReAct+检索 / R6 记忆+Notion Wiki / R7 Prompt+Skill |
| P2 | R8 安全 / 可审计 / 目录对齐 |

## 8. 待确认问题(Open Questions)

- 默认接入哪个 OpenAI 兼容端点与模型(OpenAI 官方 / Azure / 国内网关 / 本地)?是否需要同时配置「强模型 + 便宜模型」两档?
- 结构化输出优先用 `response_format`(JSON Schema)还是 function/tool calling?
- 是否在本轮就接入真实检索数据,还是先 mock?
- 记忆落地是否本轮就直接用 Notion 数据库,还是先本地 store、Notion 作为第二步?
- 云模型脱敏默认级别如何设定(默认是否禁止发送完整交底书)?