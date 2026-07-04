<aside>
 🎯

参考 Junr-01/PatentWriterBot 的「Leader + Subagent-as-Tool + SOP 驱动、按大纲生成」编排范式，在 Pagent 中作为全新功能开发**专利文书生成（patent_drafting）**能力：从技术交底书生成一份完整专利申请文件（摘要 / 权利要求书 / 说明书 / 附图说明）。**第一步先删除**原项目所有权利要求书生成相关代码（claim_generation DAG 及其节点 / skill / workflow / prompt / 测试），清干净后再作为全新功能开发。参考项目用 MCP 承载的能力中，**仅 markitdown 用 Pagent 已有的 `office_to_md` / `file_extract`（≈markitdown）承接；其余 MCP（google_patent_search / learn_skills / filesystem）全部作为新 native tool 重新实现**，不引入 MCP。

</aside>

## 1. Objective

### 1.1 目标

在 Pagent 现有分层架构（接入层 → 归一化 → 意图路由 → 编排层 → 节点 → 能力层 Skills/Tools）之上，**新增**一个 `patent_drafting` workflow：

- 以**一个受限 ReAct 的 Leader 节点**按 SOP（作业规程）编排若干**子代理工具（subagent-as-tool）**，**按大纲逐节生成**，产出完整专利文书。
- 编排形态、生成方式对齐参考项目：先解析要点 → 查新 → 生成大纲 → 依大纲逐节写作 → 合并成一份 Markdown 文书。**子代理产出以 Markdown 文本为主，降低结构化约束**（不强制严格 JSON schema）。
- **第一步先删除当前权利要求生成代码**（详见 §9.1）：删除 `claim_generation` 相关节点（`feature_extract` / `claim_plan` / `claim_generate` / `claim_check` / `claim_revise`）、`ClaimWritingSkill`、`claim_generation` / `claim_revision` workflow 及其 prompt/测试；删除后权利要求作为一个全新的 `claims_writer` 子代理从零重写。
- 参考项目 4 个 MCP 的处置：`markitdown` → 复用现有 `office_to_md` / `file_extract`；`google_patent_search` / `learn_skills` / `filesystem` → **各自新建 native tool 重新实现**（不引入 MCP，不引入外部 agent 框架）。

完成标准：

- **（前置）原权利要求生成代码已删除干净**：无悬空引用，`compileall` 与 `pytest` 收集不报错，`claim_generation` / `claim_revision` 意图不再可路由。
- 新增意图 `patent_drafting`，`intent_router` 能路由，`WorkflowRegistry` 有对应定义。
- Leader 节点在受限护栏（工具白名单 / 最大步数 / token 预算 / 超时）内，按 SOP 与大纲调用子代理工具，产出一份完整专利文书（Markdown）。
- 子代理**主要返回 Markdown 文本片段**（对齐参考项目），仅保留最小必要的元信息（如产物 key、是否完成），不做重 schema。
- 新建三个 native tool：`patent_search`、`skill_loader`、`draft_workspace`（分别对应 google_patent_search / learn_skills / filesystem）。
- 全流程无 MCP 依赖；`requirements.txt` 不新增 agent 框架。
- 权利要求 / 终稿合并保留 human-in-the-loop 挂点。
- 默认 `pytest` 离线通过；`conda run -n autoGLM pytest && conda run -n autoGLM python -m compileall app tests` 通过。

### 1.2 目标用户

- 发明人 / 代理人：上传技术交底书（走 R10 附件通道），一次性获得完整专利文书草稿。
- 开发与测试人员：可断言 SOP 编排、子代理工具调用顺序、回环上限、防注入、trace 脱敏。
- 后续开发者：复用子代理工具与 Leader 编排，扩展 OA 答复、说明书单独重写等文书类任务。

### 1.3 非目标

- 不引入 MCP、不引入外部 agent 框架（LangChain/LangGraph 等）。
- 不采用「保留/停用」方式处理旧权利要求代码——本期直接删除（见 §9.1），而非保留独立 DAG。
- 不做前端上传组件（沿用 R10 `POST /agent/attachments`）。
- 不做交底书里**照片/图片的视觉理解与原图嵌入**；附图仍以结构化文本 / Mermaid 描述产出（图片理解列入后续 PRD）。
- 不做 docx/pdf 终稿导出（先产出 Markdown 文书，导出列入后续）。
- 不改变 R10 既有对外响应结构，只允许兼容新增字段。

------

## 2. 背景与现状

### 2.1 Pagent 当前的权利要求生成（第一步删除）

`app/orchestrator/workflow_defs.py` 现有：

```python
"claim_generation": WorkflowDef(
    nodes=["normalize_input", "completeness_gate", "feature_extract",
           "claim_plan", "claim_generate", "claim_check"],
    start_node="normalize_input", max_loop_count=2,
)
```

- 该 pipeline 为确定性顺序执行的独立 DAG。
- **本 PRD 第一步删除该 pipeline 全部代码**（节点 / skill / workflow / prompt / 测试），不保留、不作为 fallback。删除完成后，权利要求撰写在本功能中**从零实现**为 `claims_writer` 子代理。

### 2.2 Pagent 可继续使用的底座

- 受限 ReAct 设施：`react_loop.py` / `react_policy.py` / `tool_registry.py`（QA 节点已用 bounded ReAct）——作为 Leader 与子代理编排的通用能力底座继续使用。
- 文档解析 tool：`office_to_md.py` / `file_extract.py`（R10 已有）——**唯一复用**的能力。
- R10 附件通道：`documents` 已注入 `state.documents`，正文一律作 `<data>` 证据。

### 2.3 参考项目 PatentWriterBot（已经下载到目录：D:\WorkArea\Agent\patent-ref\PatentWriterBot） 的范式

- Leader Agent（`create_agent` + SOP prompt）驱动 9 个子代理，**子代理包装成 `@tool`**：`input_parser / patent_searcher / outline_generator / abstract_writer / claims_writer / description_writer×2 / diagram_generator / markdown_merger`。
- **按大纲生成**：先出说明书大纲，再依大纲逐节写作，最后合并为 `complete_patent.md`。
- 每个子代理 `ainvoke` 后 `return result["messages"][-1].content`（**纯文本/Markdown 回传**）。
- 4 个 MCP：`filesystem`（沙箱中转文件）、`markitdown`（docx→md）、`google_patent_search`（SerpApi）、`learn_skills`（读技能文档）。
- 文件系统即记忆：子代理间只传**路径**，正文按需读。

------

## 3. 关键设计决策

采用参考项目「Leader + 子代理即工具 + SOP + 按大纲生成」的编排形态，同时守住 Pagent 少数几条不可退让的原则（bounded 编排、防注入、PAGENT_ 配置、TDD、trace 脱敏）。**输出结构化程度对齐参考项目——以 Markdown 文本为主，不强制严格 JSON schema。**

| 维度       | 参考项目 PatentWriterBot               | Pagent R11 采用                                              |
| ---------- | -------------------------------------- | ------------------------------------------------------------ |
| 编排者     | 自由 ReAct leader，全程模型自决        | **单个 `drafting_leader` 节点内的 bounded ReAct**：工具白名单 + 最大步数 + token/超时预算 + 全程 trace（唯一对形态的收紧） |
| 生成方式   | 按大纲逐节生成                         | **对齐：按大纲逐节生成**（outline → 各节 → 合并）            |
| 子代理     | LangChain `create_agent`  • `@tool`    | Pagent **薄封装为 `ReActTool`**，注册进 `ToolRegistry`（全新实现） |
| 子代理回传 | `messages[-1].content` 纯文本/Markdown | **对齐：以 Markdown 文本为主**，仅附最小元信息（产物 key / 是否完成），不做重 schema |
| 中转记忆   | filesystem MCP（传路径）               | **新建 `draft_workspace` native tool**（对齐「传路径、按需读」的文件中转语义，无 MCP） |
| 文档解析   | markitdown MCP                         | **复用 `office_to_md` / `file_extract`**（R10 已有，唯一复用） |
| 查新检索   | google_patent_search MCP               | **新建 `patent_search` native tool**（不复用 kb_retrieval，重新实现） |
| 技能加载   | learn_skills MCP 读 md                 | **新建 `skill_loader` native tool**（重新实现技能文档读取）  |
| 权利要求   | claims_writer 子代理                   | **全新 `claims_writer` 子代理**（不复用 claim_generation 代码） |
| 附件正文   | 直接进 prompt                          | 一律 `<data>` 证据，防注入（安全底线，非输出结构化）         |
| 关键节点   | 无强制人审                             | 权利要求 / 终稿合并保留 human-in-the-loop 挂点               |

> 一句话：**编排形态、按大纲生成、子代理回传 Markdown 文本——全面对齐参考项目；仅在「Leader 受限护栏 + 防注入 + PAGENT_ 配置 + TDD」这几条守住 Pagent 底线。除 markitdown 外的 MCP 能力全部作为 native tool 重新实现。**

------

## 4. 架构设计

```
POST /agent (intent=patent_drafting)
   │
[确定性前段]  normalize_input → completeness_gate
   │            （R10 附件 documents 已注入 state.documents）
   ▼
drafting_leader 节点（bounded ReAct + SOP + 按大纲生成）
   │  读 SOP(prompt) + 工具卡片(tool_cards) + draft_workspace 指针
   │  循环：Thought → Action(调子代理工具) → Observation(Markdown) → Reflect(充分?)
   ├─ tool: input_parser        （交底书→技术要点，Markdown 要点清单）
   ├─ tool: patent_search       （查新，调新建 patent_search native tool）
   ├─ tool: outline_generator   （说明书大纲，作为后续逐节写作依据）
   ├─ tool: abstract_writer     （摘要）
   ├─ tool: claims_writer       （权利要求书，全新实现）★人审挂点
   ├─ tool: description_writer  （具体实施方式，依大纲逐节，可分段）
   ├─ tool: diagram_generator   （附图说明 + Mermaid 结构描述）
   └─ tool: markdown_merger     （按大纲合并各节为 complete_patent.md）★人审挂点
   ▼
完整专利文书（Markdown）→ 可选 human-in-the-loop 修订 → 归档（memory gating）
```

能力层实现（**无 MCP**）：

```
markitdown MCP        → app/tools/office_to_md.py + file_extract.py    (复用, 已有)
google_patent_search  → app/tools/patent_search.py                     (新建 native tool)
learn_skills MCP      → app/tools/skill_loader.py                      (新建 native tool)
filesystem MCP        → app/tools/draft_workspace.py                   (新建 native tool)
leader SOP prompt     → app/prompts/patent_drafting_sop.py             (新增)
子代理 = ReActTool    → app/tools/subagents/*.py + tool_registry 注册    (新建薄封装)
```

------

## 5. Project Structure（目标）

```
app/
  nodes/
    drafting_leader.py           # 新增：bounded-ReAct Leader 节点，按 SOP+大纲编排子代理工具
  tools/
    patent_search.py             # 新增：native 专利检索 tool（替代 google_patent_search MCP）
    skill_loader.py              # 新增：native 技能文档加载 tool（替代 learn_skills MCP）
    draft_workspace.py           # 新增：native 文书中转/暂存 tool（替代 filesystem MCP）
    subagents/
      __init__.py                # 新增：注册所有子代理工具到 registry
      base.py                    # 新增：SubagentTool 基类（薄封装，回传 Markdown 文本）
      input_parser.py            # 新增：交底书→技术要点（Markdown 要点清单）
      patent_searcher.py         # 新增：查新（内部调 patent_search）
      outline_generator.py       # 新增：说明书大纲
      abstract_writer.py         # 新增：摘要
      claims_writer.py           # 新增：权利要求（全新实现，不复用 ClaimWritingSkill）
      description_writer.py      # 新增：具体实施方式（依大纲逐节，可分段）
      diagram_generator.py       # 新增：附图说明 + Mermaid 结构描述
      markdown_merger.py         # 新增：按大纲合并为完整文书
  prompts/
    patent_drafting_sop.py       # 新增：Leader SOP（六要素齐全）
    subagents/                   # 新增：各子代理 prompt（角色/大纲约束/样例）
  orchestrator/
    workflow_defs.py             # 改：新增 patent_drafting（不改动 claim_generation）
    tool_registry.py             # 改：新增 native tool + 子代理工具注册
  models/
    schemas.py                   # 改：WorkflowState 增文书草稿字段（Markdown 文本为主）
  api/
    schemas.py                   # 改：AgentRequest 兼容 intent=patent_drafting（无破坏）
tests/
  test_patent_drafting_workflow.py
  test_drafting_leader.py
  test_subagent_tools.py
  test_new_native_tools.py       # patent_search / skill_loader / draft_workspace
```

------

## 6. Workflow / SOP 契约

### 6.1 workflow 定义

`app/orchestrator/workflow_defs.py` 新增（不改动现有 `claim_generation`）：

```python
"patent_drafting": WorkflowDef(
    intent="patent_drafting",
    nodes=["normalize_input", "completeness_gate", "drafting_leader"],
    start_node="normalize_input",
    max_loop_count=1,   # 前段确定性；编排回环发生在 leader 内部，受 PAGENT_DRAFTING_MAX_STEPS 控制
),
```

### 6.2 SOP prompt（Leader，遵守 [CLAUDE.md](http://CLAUDE.md) 六要素）

`app/prompts/patent_drafting_sop.py`，须覆盖：任务目标 / 判定规则 / 角色 / 受众 / 样例 / 输出格式；带专利域约束（禁止臆造、不确定标注、规范术语）。核心约束：

```
# 任务目标
依据 <data> 中的技术交底书，按 SOP 与说明书大纲编排子代理工具，
逐节生成并合并为一份完整专利文书（Markdown：摘要/权利要求书/说明书/附图说明）。

# 判定规则（编排 SOP，对齐参考项目按大纲生成）
1. 先 input_parser 抽取技术要点；要点不足 → 标注不确定，不得臆造。
2. allow_network=true 时可 patent_searcher 查新；否则跳过并在文书标注"未查新"。
3. 必须先 outline_generator 出大纲，后续 abstract/claims/description/diagram 依大纲写作。
4. 各子代理产物通过 draft_workspace 暂存并回传指针；后续子代理按指针读取，不重复塞长正文。
5. 最后 markdown_merger 依大纲合并为完整文书；如明显缺节且未超步数 → 回相应子代理补写。
6. 命中 PAGENT_DRAFTING_MAX_STEPS / token / 超时 → 产出当前最佳并标注 incomplete。

# 角色：资深专利代理人 + 编排者
# 受众：终稿合并与人审律师
# 样例：<至少 1 组 交底要点→大纲→逐节调用序列→文书片段>
# 输出格式：Markdown 专利文书（不额外输出解释）
```

------

## 7. Subagent-as-Tool 契约（对齐参考项目，轻结构化）

### 7.1 统一接口

每个子代理实现 `run(tool_input: dict) -> str | dict`，注册为 `ToolSpec`，可被 `tool_cards()` 暴露给 Leader policy：

```python
class SubagentTool:  # app/tools/subagents/base.py
    name: str
    description: str          # 供 policy 决策
    def run(self, tool_input: dict[str, Any]) -> dict:
        # 返回 {"markdown": "<该节 Markdown 正文>", "artifact_key": "...", "done": true}
        # 对齐参考项目：正文即 Markdown 文本，元信息最小化
        ...
```

要求：

- **输入**：接收结构化引用（如 `{"read": ["input_points","outline"], "params": {...}}`），**不接收整段长正文**；正文由子代理经 `draft_workspace` 按指针读取（对齐参考项目「只传路径」）。
- **输出**：以 **Markdown 文本**为主，元信息只保留 `artifact_key` / `done`（可选 `note`）；**不强制严格 JSON schema、不要求逐字段 required**（对齐参考项目结构化程度）。
- **副作用**：产物经 `draft_workspace` 暂存，返回中带指针与简要说明。
- **失败**：安全失败返回错误说明，不抛裸异常（对齐 `ToolRegistry.run` 既有约定）。
- **护栏**：`patent_searcher` 等内部可 bounded，受 `PAGENT_DRAFTING_SUBAGENT_MAX_STEPS` 限制；外部检索受 `allow_network` + `agentic_external_tools_enabled` 门控。

### 7.2 子代理清单（对齐参考项目 9 子代理）

| 子代理工具           | 职责（按大纲推进）                                | 底层能力                                        |
| -------------------- | ------------------------------------------------- | ----------------------------------------------- |
| `input_parser`       | 交底书→技术要点/问题/效果/关键词（Markdown 清单） | LLM + `office_to_md`/`file_extract`（R10 复用） |
| `patent_searcher`    | 查新、定位区别特征                                | **新建 `patent_search` native tool**（门控）    |
| `outline_generator`  | 说明书大纲（后续逐节写作依据）                    | LLM                                             |
| `abstract_writer`    | 摘要                                              | LLM                                             |
| `claims_writer`      | 独权/从权 + 引用关系 ★人审                        | **全新 LLM 实现**（不复用 ClaimWritingSkill）   |
| `description_writer` | 具体实施方式（依大纲逐节，可分段）                | LLM                                             |
| `diagram_generator`  | 附图说明 + Mermaid 结构描述                       | LLM（低温）                                     |
| `markdown_merger`    | 按大纲合并各节为完整文书 ★人审                    | LLM + 拼装                                      |

------

## 8. Tool 映射契约（MCP → native）

| 参考项目 MCP         | 承担的功能               | Pagent 处置                                       | 状态             |
| -------------------- | ------------------------ | ------------------------------------------------- | ---------------- |
| markitdown           | docx/pptx→md             | `office_to_md.py` / `file_extract.py`             | ✅ 复用(R10 已有) |
| google_patent_search | 专利检索                 | **新建 `app/tools/patent_search.py`**（native）   | 🆕 重新实现       |
| learn_skills         | 读技能文档               | **新建 `app/tools/skill_loader.py`**（native）    | 🆕 重新实现       |
| filesystem           | 子代理间文件中转（记忆） | **新建 `app/tools/draft_workspace.py`**（native） | 🆕 重新实现       |

### 8.1 新建 native tool 契约

- **`patent_search`**：输入 `{query, top_k, lang?}`；输出命中列表（标题 / 摘要 / 号 / 链接 / 相关度）+ provenance。受 `allow_network` + `agentic_external_tools_enabled` + 自身开关门控；离线测试可 fake。检索源（本地库 / 联网 API）见 §16 待定。
- **`skill_loader`**：输入 `{skill_name}`；输出技能文档文本（程序记忆），供 Leader/子代理注入上下文。技能文档来源目录用 `PAGENT_SKILL_DIR` 配置，仅读、路径校验防越界。
- **`draft_workspace`**：文书中转/暂存。接口 `put(key, markdown) / get(key) / list()`；载体默认 `state`（内存）或临时目录（`PAGENT_DRAFT_WORKSPACE_DIR`），子代理间只传 `key`（对齐参考项目 filesystem 传路径语义），不落用户可见磁盘。
- 不新增 `mcp` / `langchain-mcp-adapters` 等依赖。

------

## 9. 权利要求撰写（先删除旧代码，再全新开发）

### 9.1 第一步：删除原权利要求书生成代码（先于新功能开发）

按下列清单删除，并确保删除后无悬空引用、`compileall` 与 `pytest` 收集均不报错：

- **节点**：`app/nodes/feature_extract.py`、`claim_plan.py`、`claim_generate.py`、`claim_check.py`、`claim_revise.py`。
- **技能**：`ClaimWritingSkill`（`app/skills/` 下权利要求相关 skill）。
- **Workflow**：`workflow_defs.py` 中 `claim_generation`、`claim_revision` 定义。
- **路由**：`intent_router.py` 中 `claim_generation` / `claim_revision` 意图分支与相关意图常量。
- **Prompt**：`app/prompts/` 下权利要求相关 prompt。
- **State**：`WorkflowState` 中仅服务旧 pipeline 的字段（如 `claim_plan`、`claims_draft`、`claim_versions`、`technical_features`）——确认新功能不依赖后删除（新功能改用 Markdown 字段承载）。
- **测试**：`tests/` 下针对上述节点 / workflow / skill 的用例与夹具。
- **注册表**：`tool_registry.py` / 节点注册处对已删对象的引用。

> 删除作为独立、可回滚的首个 commit（对齐 [CLAUDE.md](http://CLAUDE.md) 提交规范），与后续新增功能分开提交。

### 9.2 删除后：全新实现 claims_writer

- **全新实现**：`claims_writer` 子代理独立实现——读大纲与技术要点，直接由 LLM 生成独权/从权及引用关系（对齐参考项目 claims_writer 的按大纲文本生成方式），不引用任何已删除代码。
- **人审保留**：权利要求作为 human-in-the-loop 挂点；终稿由 `markdown_merger` 合并时再次挂点。

------

## 10. 配置契约（PAGENT_ 前缀，系统级）

| 配置项                        | 环境变量                             | 默认               | 说明                                 |
| ----------------------------- | ------------------------------------ | ------------------ | ------------------------------------ |
| `drafting_max_steps`          | `PAGENT_DRAFTING_MAX_STEPS`          | `24`               | Leader 最大编排步数                  |
| `drafting_token_budget`       | `PAGENT_DRAFTING_TOKEN_BUDGET`       | `120000`           | Leader 全流程 token 预算             |
| `drafting_timeout_s`          | `PAGENT_DRAFTING_TIMEOUT_S`          | `600`              | 全流程超时                           |
| `drafting_subagent_max_steps` | `PAGENT_DRAFTING_SUBAGENT_MAX_STEPS` | `6`                | 单个子代理内部 bounded 步数          |
| `drafting_require_prior_art`  | `PAGENT_DRAFTING_REQUIRE_PRIOR_ART`  | `false`            | 是否强制查新（联网时）               |
| `patent_search_top_k`         | `PAGENT_PATENT_SEARCH_TOP_K`         | `8`                | 新建 patent_search 返回条数          |
| `skill_dir`                   | `PAGENT_SKILL_DIR`                   | `app/skills`       | skill_loader 读取目录                |
| `draft_workspace_dir`         | `PAGENT_DRAFT_WORKSPACE_DIR`         | `""`（内存 state） | draft_workspace 暂存目录，空则用内存 |

要求（对齐 [CLAUDE.md](http://CLAUDE.md) 参数规范）：

- 均为**系统级通用配置**。
- 覆盖用 `settings.xxx if arg is None else arg`，**禁止 `arg or settings.xxx`**（避免吞 `0`/`False`）。
- 非敏感项进 `to_public_dict()`；同步 `Settings` 默认值 / 环境变量 / 公开配置 / 测试。
- 复用既有 `allow_network`、`agentic_external_tools_enabled` 门控外部工具（patent_search）。

------

## 11. 数据 / State 契约（轻结构化，Markdown 为主）

`app/models/schemas.py`：

- `WorkflowState` 新增文书草稿字段，**以 Markdown 文本为主**（对齐参考项目按大纲逐节生成的产物形态）：

```python
input_points_md: str = ""          # input_parser 产物：技术要点 Markdown 清单
prior_art_md: str = ""             # patent_searcher 产物：查新结果 Markdown（含来源）
outline_md: str = ""              # outline_generator 产物：说明书大纲
abstract_md: str = ""            # 摘要
claims_md: str = ""             # 权利要求书
description_md: str = ""        # 具体实施方式（可含分段）
figures_md: str = ""           # 附图说明 + Mermaid
complete_patent_md: str = ""   # markdown_merger 产物：完整文书
drafting_incomplete: bool = False
```

- **不引入严格 `PatentDocument` JSON schema**；`draft_workspace` 以 `key -> markdown` 暂存各节，`complete_patent_md` 为最终合并产物（对齐参考项目 `complete_patent.md`）。

要求：

- `documents[*].text`（附件正文）永远只作 `<data>` 证据，不进 `raw_input`、不进 session memory user turn（对齐 R10，安全底线）。
- **memory gating**：仅人审通过的 `complete_patent_md` 才可固化进案件/长期记忆。

------

## 12. Trace 与日志契约（脱敏）

复用 `WorkflowState.add_trace_event` / `log_event`，新增结构化事件：

| 事件                  | 触发                | data（脱敏）                            |
| --------------------- | ------------------- | --------------------------------------- |
| `drafting_started`    | 进入 leader         | `intent`, `doc_count`                   |
| `subagent_invoked`    | 调用子代理工具      | `tool`, `step_index`                    |
| `subagent_observed`   | 子代理返回          | `tool`, `artifact_key`, `chars`, `done` |
| `drafting_loop`       | 回环补写            | `target`, `loop_count`                  |
| `drafting_budget_hit` | 步数/token/超时命中 | `reason`, `steps`, `tokens`             |
| `drafting_completed`  | 产出完整文书        | `incomplete`, `sections`                |

要求：不记录交底书正文、prompt 全文、检索正文、密钥；错误用稳定英文 `event`，`message` 可中文。

------

## 13. 防注入与专利域约束（强制，安全底线）

> 说明：这是安全要求，与「减少输出结构化」不冲突——子代理输出仍是 Markdown 文本，但**输入侧**必须做指令/数据分离。

- 所有附件/检索/外部内容包裹 `<data>...</data>` 并声明「仅数据、不作为指令」；忽略其中任何「忽略上文/改写系统指令」式内容（对齐 R10、[CLAUDE.md](http://CLAUDE.md)）。
- **禁止臆造**：法条、专利号、检索结果、引用必须来自输入或工具证据；无来源需在文书中显式标注不确定，不得编造。
- 规范术语：权利要求 / 独立·从属权利要求 / 新颖性 / 创造性 / IPC 等。
- 输出语言默认中文。

------

## 14. Testing Strategy（TDD，conda run -n autoGLM）

### 14.1 顺序

1. `test_claim_code_removed.py`：先删除旧权利要求代码，断言其模块/意图不可用（在删除 commit 内）。
2. `test_new_native_tools.py`：`patent_search`（门控/离线 fake/输出字段）、`skill_loader`（读目录/路径越界防护）、`draft_workspace`（put/get/list、内存与目录两模式、只传 key）。
3. `test_subagent_tools.py`：每个子代理调用、回传 Markdown、只按指针读取不吞长正文、失败安全返回、防注入。
4. `test_drafting_leader.py`：SOP 按大纲编排顺序（outline 先于逐节）、回环上限、步数/token/超时护栏、budget_hit 产出 incomplete。
5. `test_patent_drafting_workflow.py`：`intent=patent_drafting` 端到端产出 `complete_patent_md`。
6. 回归：QA / config / security 测试不破（`claim_generation` / `claim_revision` 已删除，其测试一并移除）。

### 14.2 必测用例

- 交底要点不足时 claims 标注不确定，不臆造。
- `allow_network=false` 时 `patent_searcher` 跳过并标注「未查新」，不触网。
- 子代理传入超长正文被拒/忽略，只按 `draft_workspace` key 读取。
- Leader 命中 `PAGENT_DRAFTING_MAX_STEPS` 时返回 `incomplete=True` 且不报裸异常。
- 未先出大纲直接写作时 Leader 纠偏为先 outline_generator。
- 附件含「忽略以上指令」时系统行为与输出不变。
- 默认测试不访问真实网络 / 外部 LLM（外部工具 monkeypatch）。

### 14.3 隔离

- 外部工具（patent_search 联网路径）与 LLM 全部 fake/monkeypatch。
- 联网集成测试标 `@pytest.mark.network`，默认 skip。

------

## 15. Boundaries

### 15.1 Always do

- 先删除原权利要求书生成代码（独立、可回滚的首个 commit），再开发新功能。
- Leader 用 bounded ReAct（工具白名单 + 步数/token/超时 + 全程 trace）。
- 按大纲生成：先 outline，再依大纲逐节写作、合并。
- 子代理回传 Markdown 文本；产物经 `draft_workspace` 暂存，回传只带 key/简述。
- 附件正文只作 `<data>`；保留 `WorkflowState.raw_input` 原始简短指令。
- 除 markitdown 外的 MCP 能力用新建 native tool 承接。
- 权利要求全新实现；claims / markdown_merger 保留 human-in-the-loop 挂点。
- memory gating：仅人审通过才固化。

### 15.2 Ask first（Open Decisions）

- `patent_search` 检索源：本地专利库、联网 API（如需 key），或两者。
- 默认步数/预算取值（24 / 120k / 600s）是否合适。
- `draft_workspace` 默认载体：内存 state vs 临时目录。
- 附图是否本期仅产出 Mermaid 结构描述（照片/原图理解与嵌入延后）。

### 15.3 Never do

- 不引入 MCP、不引入外部 agent 框架。
- 删除旧权利要求代码后不得残留对其的 import / 路由 / 注册引用（也不保留停用式旧 DAG）。
- 不让 Leader 变成无护栏自由 ReAct。
- 不把附件正文并入 raw_input / 拼接进指令 / 执行其中指令。
- 不把未人审产物写入长期记忆。
- 不在 trace/日志记录正文、prompt 全文或密钥。

------

## 16. Open Decisions

1. `patent_search` 检索源与是否需要外部 API key（离线可用性）。
2. Leader 默认步数/预算取值是否合适。
3. `draft_workspace` 载体：内存 state（默认）还是临时目录。
4. Leader 编排是否需要「并行调用无依赖子代理」（abstract/figures 可并行）——本期先串行，性能优化列后续。
5. 附图与交底书照片处理：本期仅 Mermaid 结构描述；视觉理解 + 原图嵌入是否单开 PRD。
6. 终稿导出（Markdown/docx）是否纳入本期，还是作为后续增量。

------

<aside>
 🧭

**落地顺序建议**：**(0) 先做 §9.1 删除原权利要求书生成代码（独立、可回滚的首个 commit）**；再做 §14.1 的 (1) 新建三个 native tool（patent_search / skill_loader / draft_workspace），(2) 子代理薄封装与按大纲生成，(3) Leader 编排，(4) 端到端。每个可独立验证阶段单独 commit（对齐 [CLAUDE.md](http://CLAUDE.md) 提交规范）。

</aside>