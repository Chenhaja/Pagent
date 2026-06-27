# 专利 Agent 规格说明

## 1. Objective

### 目标

构建一个面向普通发明人的专利 Agent，帮助用户以较低门槛完成专利相关任务：

- 专利问答：解释专利概念、流程、撰写注意事项、审查相关问题。
- 专利翻译：支持专利文本、技术交底、权利要求等内容的中英互译或术语化翻译。
- 权利要求生成：从用户输入的技术方案 / 交底材料中生成初版权利要求书。
- 全流程工作流：围绕「输入技术方案 → 信息补全 → 特征抽取 → 权利要求生成 → 初步校验 → 用户确认」形成可扩展流程。

第一版 MVP 不追求专业代理师级别的精细度，重点是建立可运行、可扩展、可审计的架构骨架，后续逐步增强各节点能力。

### 目标用户

首要目标用户是普通发明人：

- 不熟悉专利撰写格式和法律术语。
- 可能只会用口语描述发明点。
- 需要 Agent 主动澄清缺失信息。
- 更重视易用性、解释性和初稿生成，而不是一次性生成可直接提交的终稿。

### 架构原则

采用「外层确定性编排 + 内层局部 bounded ReAct」：

- workflow 由预定义 DAG / 状态机驱动，不让模型自由决定全局流程顺序。
- 编排层最小单位是 node，而不是 tool 或 skill。
- node 负责一次业务状态推进。
- skill 负责某类专业任务的方法、模板、few-shot 和输出 schema。
- tool 负责原子能力，例如 LLM 调用、检索、翻译、校验、术语查询。
- 仅在检索、开放式分析、问答追问等节点内使用受限 ReAct。

---

## 2. Commands

> 当前为规格阶段，具体命令可随工程初始化后调整。

### 推荐开发命令

```bash
# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境（Git Bash / Unix shell）
source .venv/Scripts/activate

# 安装依赖
pip install -r requirements.txt

# 启动 API 服务
uvicorn app.main:app --reload

# 运行测试
pytest

# 运行格式检查（如引入 ruff）
ruff check .

# 运行类型检查（如引入 mypy）
mypy app
```

### 运行形态

MVP 推荐采用 Python 后端：

- FastAPI：提供 HTTP API。
- Pydantic：定义输入输出 schema、workflow state、node 输出。
- 可选 LangGraph / 自研轻量 orchestrator：管理节点编排、状态推进、重试、回环。
- LLM Provider Adapter：封装云模型调用，便于后续切换模型。
- RAG / 检索模块：后续接入专利法规、术语库、模板库和公开专利数据。

---

## 3. Project Structure

推荐目录结构：

```text
pagent/
  app/
    main.py                    # FastAPI 入口
    api/
      routes/
        chat.py                # 问答 / 对话接口
        translate.py           # 翻译接口
        workflows.py           # 工作流触发与查询接口
    core/
      config.py                # 配置加载
      logging.py               # 日志初始化
      security.py              # API key、鉴权、脱敏等边界逻辑
    orchestrator/
      engine.py                # workflow 调度引擎
      workflow_defs.py         # 预定义 workflow 模板
      state.py                 # 全局 state / blackboard
      node_base.py             # node 抽象
    nodes/
      normalize_input.py       # 轻量改写 / 指代消解 / 上下文补全
      intent_router.py         # 意图识别与 workflow 路由
      feature_extract.py       # 技术特征抽取
      claim_plan.py            # 权利要求布局规划
      claim_generate.py        # 权利要求生成
      claim_revise.py          # 单条 / 局部权利要求修订
      claim_check.py           # 初步合规校验
      qa.py                    # 专利问答节点
      translate.py             # 翻译接口适配节点
      report_generate.py       # 专利技术报告生成节点
    skills/
      claim_writing.py         # 权利要求撰写 skill
      feature_extraction.py    # 技术特征抽取 skill
      patent_qa.py             # 专利问答 skill
      patent_translation.py    # 专利翻译 skill
      report_writing.py        # 技术报告 skill
    tools/
      llm.py                   # LLM 原子调用
      retrieval.py             # 检索 / RAG
      terminology.py           # 术语库查询
      validators.py            # 规则校验器
      document.py              # 文档解析 / 导出
    memory/
      session.py               # 会话记忆
      case_store.py            # 案件记忆接口
      wiki.py                  # 长期 wiki 记忆接口（后续）
    models/
      schemas.py               # 通用 Pydantic schema
    services/
      chat_service.py
      workflow_service.py
      translate_service.py
  tests/
    unit/
    integration/
  SPEC.md
  requirements.txt
```

### 核心数据结构

MVP 至少需要定义：

- `WorkflowState`
  - `raw_input`
  - `normalized_input`
  - `intent`
  - `dialog_context`
  - `invention_disclosure`
  - `technical_features`
  - `claim_plan`
  - `claims_draft`
  - `claim_versions`
  - `claim_patches`
  - `validation_report`
  - `user_feedback`
  - `trace`

- `NodeResult`
  - `status`
  - `output`
  - `errors`
  - `next_node`
  - `requires_user_input`
  - `trace_events`

- `SkillContext`
  - `task_type`
  - `state_snapshot`
  - `domain_rules`
  - `output_schema`
  - `examples`

---

## 4. Code Style

### 基本原则

- 优先最小化、局部化改动。
- 复用现有 helper，不随意引入新抽象。
- 先保证清晰、可测试、可扩展，再逐步增强智能化能力。
- workflow 骨架必须确定性，不能把全局步骤顺序交给 LLM 自由决定。
- 对外部模型输出必须进行 schema 校验和必要的安全检查。

### Python 风格

- 使用类型标注。
- 使用 Pydantic 定义 API 和节点输出 schema。
- 公开函数、方法、类补充中文 Google 风格 docstring。
- 注释使用中文，只解释不直观的设计原因。
- 日志事件名使用稳定英文，`message` 可使用中文。
- 不在日志中记录密钥、完整原文、完整译文、隐私信息或过长文本。

### Node / Tool / Skill 边界

- Tool：无状态、原子能力，不包含业务流程判断。
- Node：读写 workflow state，负责一次明确的业务推进。
- Skill：方法包，不直接持久化状态，不负责流程编排。

### 复用原则

相近业务能力应优先复用同一套 skill、schema、tool 和校验器，通过不同 node 输入上下文区分任务目标，避免为“生成 / 修改 / 解释 / 报告”维护多套分叉规则。

- 权利要求生成与局部修改共用 `claim_writing` skill、权利要求 schema、术语表、引用关系校验器和合规检查器。生成节点负责从技术方案产出完整初稿；修改节点负责根据用户意见对指定权利要求生成结构化 patch，并检查对引用关系、术语一致性和保护范围的影响。
- 技术特征抽取应作为共享能力，供权利要求生成、技术报告生成、问答解释和后续检索对比复用。
- 问答、报告和权利要求生成可共用 RAG / 检索 tool、术语库 tool 和引用材料摘要能力；区别在于输出 schema 与面向用户的解释深度。
- 翻译能力在 MVP 中仅提供可接入接口和适配 node，具体翻译 agent 由外部实现承载；本系统只负责传参、术语上下文、结果接收、trace 和错误边界。
- 报告生成不重复实现权利要求或特征分析逻辑，应消费已有 `technical_features`、`claims_draft`、`validation_report` 和可选检索结果。

### ReAct 使用边界

允许在以下场景使用 bounded ReAct：

- 专利问答中的多步资料检索。
- 现有技术检索与对比。
- 技术报告中的开放式分析。

必须具备以下护栏：

- 限定工具集。
- 最大步数 / token 预算 / 超时。
- 结构化输出 schema。
- trace 落库或写入 state，便于审计。

---

## 5. Testing Strategy

### 单元测试

覆盖：

- workflow state 合并与更新。
- node 输入输出 schema 校验。
- intent router 的路由规则。
- claim checker 的规则校验。
- translation / QA / claim generation / claim revision service 的边界行为。
- 单条权利要求修改生成 patch 后，引用关系、术语一致性和版本链更新正确。

### 集成测试

覆盖 MVP 主链路：

1. 用户输入口语化技术方案。
2. 轻量改写生成 `normalized_input`。
3. 意图识别路由到权利要求生成 workflow。
4. 特征抽取生成结构化特征。
5. 权利要求生成节点生成初稿。
6. 校验节点输出 validation report。
7. API 返回用户可理解的结果和下一步建议。

### LLM 相关测试

- 不直接依赖真实 LLM 做所有单元测试。
- 将 LLM 调用封装在 tool adapter 后，单元测试使用固定 fake response。
- 对关键 prompt 输出进行 golden case 测试。
- 对模型输出解析失败、字段缺失、超时、内容为空等情况做降级测试。

### 安全与合规测试

- API key 不出现在日志中。
- 用户输入不会被拼接进 shell 命令或 SQL。
- 云模型调用前支持脱敏开关。
- 长文本日志截断。
- 模型输出不会直接绕过校验进入案件记忆或长期记忆。

---

## 6. Boundaries

### Always do

- 保留用户原始输入 `raw_input`，不要只保存改写后的内容。
- 对 LLM 输出做结构化校验。
- 对权利要求生成结果做基础规则校验。
- 将 workflow trace 写入 state，便于排查。
- 面向普通发明人输出解释性结果，避免只给专业术语。
- 明确提示：生成内容是辅助初稿，不等同于专利代理师法律意见。

### Ask first

- 是否调用外部云模型处理完整技术交底书或敏感案件材料。
- 是否将用户内容写入长期案件记忆或经验记忆。
- 是否导出、发送、提交任何面向外部系统的文件或请求。
- 是否启用联网检索或第三方专利数据库。

### Never do

- 不把整个专利 Agent 做成一个无边界的大 ReAct loop。
- 不让模型自由决定全局 workflow 顺序。
- 不在日志中记录密钥、完整 API Key、隐私数据或过长原文。
- 不把未经校验 / 未经用户确认的模型输出固化进长期记忆。
- 不声称生成结果可直接替代专利代理师意见。
- 不硬编码密钥、凭证或云模型 API key。

---

## MVP Workflow 草案

### A. 专利问答

```text
用户问题
  → 轻量改写
  → 意图识别：patent_qa
  → QA Node
  → 可选 RAG / bounded ReAct 检索
  → 结构化回答 + 风险提示 + 后续建议
```

### B. 专利翻译

```text
用户文本
  → 语言 / 文本类型识别
  → 术语规范化
  → 翻译接口适配 Node
  → 调用外部翻译 agent
  → 接收译文 / 错误 / 术语结果
  → 返回译文 + 关键术语表
```

MVP 不重复实现翻译 agent，只定义可接入接口、上下文传递、错误处理和 trace 记录。

### C. 权利要求生成

```text
技术方案输入
  → 轻量改写
  → 信息完整性检查
  → 必要时向用户追问
  → 技术特征抽取
  → 权利要求布局规划
  → 独立权利要求生成
  → 从属权利要求生成
  → 基础合规校验
  → 返回初稿 + 校验报告 + 修改建议
```

### D. 单条 / 局部权利要求修改

```text
用户修改意见 + 目标权利要求编号
  → 定位当前权利要求版本
  → 解析修改意图
  → 生成结构化 patch
  → 应用 patch 得到新版本
  → 检查引用关系 / 术语一致性 / 保护范围影响
  → 返回修改后的权利要求 + 差异说明 + 风险提示
```

局部修改优先只改目标权利要求；只有当引用关系、术语一致性或保护范围联动要求必须调整其它权利要求时，才生成关联 patch，并在返回结果中解释原因。

### E. 专利技术报告生成

```text
技术方案 / 权利要求 / 用户补充材料
  → 复用已有技术特征 / 权利要求 / 校验结果
  → 必要时补充特征抽取
  → 可选检索与对比
  → 报告结构规划
  → 报告生成
  → 一致性检查
  → 返回技术报告草稿
```

---

## Open Questions

- 是否需要前端界面，还是先提供 API / CLI？
- 第一版是否接入真实专利检索数据源？
- 翻译功能 MVP 只提供可接入接口，具体实现复用已有翻译 agent。
- 权利要求生成是否先聚焦中国专利格式？
- 案件记忆是否在 MVP 中落库，还是先只做 session state？
- 是否需要用户账号、案件隔离和权限系统？
