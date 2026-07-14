# Pagent 文书生成顶层流程化与 Leader 关口决策 PRD

## 1. Objective

### 1.1 背景

当前专利文书生成链路中的 Leader 本质上主要按固定流程顺序调用子代理，实际承担的是流程控制器职责，而不是少量高价值决策职责。这样会带来几个问题：

- 固定流程隐藏在 Leader 内部，节点边界不清晰。
- 子代理执行过程偏黑盒，难以单独测试、恢复、追踪和复用。
- patent_searcher、prior_art_analysis、专利附图分析、写作风格指南等前置产物散落在 prompt 或隐式流程中，缺少稳定中间产物契约。
- Leader 抽象价值不明确，容易变成“伪智能编排者”。

本 PRD 目标是将文书生成从“Leader 内部顺序调用子代理”重构为“顶层 Orchestrator 承载完整 patent_drafting 节点列表，Leader 只做关键关口决策”的架构。

### 1.2 目标

将专利文书生成流程显式建模为顶层 workflow 节点序列，使固定步骤由现有 `Orchestrator` 承担，Leader 仅在关键节点读取结构化状态并输出结构化决策。

核心目标：

- 将文书生成自代理 / 子流程显式拆为顶层 workflow Node，而不是隐藏在 Leader 内部。
- 复用现有 `app/orchestrator/workflow_defs.py` 与 `app/orchestrator/engine.py`，不新增平级 DAG 编排器。
- 将 `patent_searcher`、`prior_art_analysis`、专利附图分析、写作风格指南生成拆为可观测、可测试、可恢复的前置 Node。
- 将 Leader 降级为关口决策节点，只负责 `continue` / `retry` / `revise` / `escalate` 等少量结构化判断。
- 每个 Node 都有明确输入、输出、失败语义、workspace artifact 与测试验收。
- 长正文继续通过 `draft_workspace` artifact key 流转，`WorkflowState` 只保存短字段、路径和结构化摘要。
- 保持现有工具、prompt、workspace、配置和测试体系，避免引入外部 agent 框架。

完成标准：

- `patent_drafting` 的完整节点顺序可以在 `WorkflowRegistry` / workflow 定义中直接看到。
- 固定生成步骤由顶层 workflow 节点承载，不再由 Leader prompt 或 `DraftingLeaderNode.run()` 内部 for-loop 隐式串联全流程。
- Leader 只出现在关键 gate 节点，例如现有技术分析是否足够、写作风格指南是否足够、终稿审查是否通过。
- `patent_search`、`prior_art_analysis`、`drawing_analysis`、`writing_style_guide` 均形成独立中间产物。
- 每个中间产物都有稳定 artifact key、字段约束和失败降级规则。
- 默认测试不触网、不调用真实外部 LLM。
- `conda run -n autoGLM pytest` 与 `conda run -n autoGLM python -m compileall app tests` 通过。

### 1.3 目标用户

- 专利文书生成链路维护者：需要清楚看到每个阶段的输入、输出、失败原因和重试路径。
- 后续开发者 / agent：需要基于顶层 Node 边界扩展、替换或单测某个生成阶段。
- 产品 / 架构决策者：需要判断 Leader 在系统中的真实职责与价值。
- 发明人 / 代理人：间接受益于更稳定、可解释、可追踪的文书生成质量。

### 1.4 非目标

- 不新增与现有 `Orchestrator` 平级的第二套 DAG 编排器。
- 不立即重写所有生成逻辑。
- 不要求一次性替换现有全部 Leader 实现。
- 不让 Leader 参与每个阶段的正文生成或逐步调度。
- 不引入 LangChain / LangGraph / MCP 等外部编排框架。
- 不在默认测试中访问真实网络或真实外部 LLM。
- 不实现 docx / pdf 终稿导出。
- 不把未人审的完整专利文书写入长期记忆或案件归档。

---

## 2. Commands

项目使用 conda 环境 `autoGLM`。所有 Python / pytest / 脚本命令必须通过 `conda run -n autoGLM` 执行。

```bash
# workflow 定义与路由测试
conda run -n autoGLM pytest tests/test_drafting_workflow_defs.py

# Leader gate 决策测试
conda run -n autoGLM pytest tests/test_drafting_leader_gates.py

# patent_searcher 与 prior_art_analysis 节点测试
conda run -n autoGLM pytest tests/test_drafting_research_nodes.py

# 附图分析与写作风格指南节点测试
conda run -n autoGLM pytest tests/test_drafting_guidance_nodes.py

# 端到端专利文书生成回归
conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py

# 全量回归
conda run -n autoGLM pytest

# 编译检查
conda run -n autoGLM python -m compileall app tests
```

约束：

- 默认测试不得触网、不得调用真实外部 LLM。
- 真实检索集成测试必须显式标记并默认 skip。
- 如新增依赖，必须同步更新 `requirements.txt`。
- 不执行 `git push`、`git reset --hard`、强制推送等危险操作，除非用户明确确认。
- 每完成一个可独立验证阶段，按项目规范单独提交。

---

## 3. Project Structure

目标结构：

```text
pagent/
  app/
    orchestrator/
      workflow_defs.py             # 定义 patent_drafting 完整顶层节点列表与 max_loop_count
      engine.py                    # 复用现有顺序执行、next_node 跳转和 loop limit 能力
    nodes/
      drafting_state.py            # gate decision / drafting artifact key 数据结构
      drafting_leader_gate.py      # Leader 关口决策节点
      drafting_research.py         # patent_search / prior_art_analysis 节点
      drafting_guidance.py         # drawing_analysis / writing_style_guide 节点
      drafting_content.py          # outline / sections / merge / review / finalize 节点
    prompts/
      patent_drafting_leader.py    # Leader gate prompt 或现有 Leader prompt 的收敛版本
      drafting_gates.py            # 各 gate 的结构化决策 prompt
      subagents/
        patent_searcher_prompt.py
        prior_art_analysis_prompt.py
        drawing_analysis_prompt.py
        writing_style_guide_prompt.py
    tools/
      draft_workspace.py           # artifact 读写、list、merge
      patent_search.py             # 检索工具与离线降级
      subagents/                   # 现有子代理工具，可逐步迁移为 Node 适配层
    models/
      schemas.py                   # 如需集中放置决策和中间产物 schema
  tests/
    test_drafting_workflow_defs.py
    test_drafting_leader_gates.py
    test_drafting_research_nodes.py
    test_drafting_guidance_nodes.py
    test_patent_drafting_workflow.py
  SPEC.md
```

### 3.1 顶层 workflow 总体流程

`patent_drafting` 应直接在现有 `WorkflowRegistry` 中定义完整节点列表，而不是只定义为 `normalize_input -> drafting_leader`。

目标节点序列：

```python
WorkflowDef(
    intent="patent_drafting",
    nodes=[
        "normalize_input",
        "drafting_parse_input",
        "drafting_patent_search",
        "drafting_prior_art_analysis",
        "drafting_leader_gate_prior_art",
        "drafting_drawing_analysis",
        "drafting_writing_style_guide",
        "drafting_leader_gate_guidance",
        "drafting_generate_outline",
        "drafting_generate_sections",
        "drafting_merge_document",
        "drafting_review_document",
        "drafting_leader_gate_review",
        "drafting_finalize",
    ],
    start_node="normalize_input",
    max_loop_count=3,
)
```

可选失败 / 返修路径通过现有 `NodeResult.next_node` 表达：

```text
drafting_leader_gate_prior_art
  continue -> drafting_drawing_analysis
  retry    -> drafting_patent_search
  revise   -> drafting_prior_art_analysis
  escalate -> drafting_human_review 或 failed

drafting_leader_gate_guidance
  continue -> drafting_generate_outline
  retry    -> drafting_drawing_analysis 或 drafting_writing_style_guide
  revise   -> drafting_writing_style_guide
  escalate -> drafting_human_review 或 failed

drafting_leader_gate_review
  continue -> drafting_finalize
  revise   -> drafting_generate_sections
  retry    -> drafting_review_document
  escalate -> drafting_human_review 或 failed
```

要求：

- 不新增 `drafting_dag.py` 作为内部二级编排器。
- `workflow_defs.py` 是 patent_drafting 顺序的权威来源。
- `engine.py` 继续负责顶层节点执行、`next_node` 跳转和回环限制。
- 如需复杂路由，优先让 gate Node 返回合法 `next_node`，而不是在 Leader 内部调用下一步。

### 3.2 WorkflowState 契约

`WorkflowState` 只保存短字段、artifact key、结构化状态，不保存长正文。

示例：

```python
{
    "workspace_id": "temp_xxx",
    "input_key": "01_input/raw_document.md",
    "parsed_info_key": "01_input/parsed_info.json",
    "patent_search_key": "02_research/patent_search_results.json",
    "prior_art_analysis_key": "02_research/prior_art_analysis.json",
    "drawing_analysis_key": "02_research/drawing_analysis.json",
    "writing_style_guide_key": "02_research/writing_style_guide.json",
    "outline_key": "03_outline/patent_outline.md",
    "section_keys": ["04_content/abstract.md", "04_content/claims.md"],
    "review_key": "05_final/review_report.json",
    "final_key": "05_final/complete_patent.md",
    "last_gate_decision": {
        "decision": "continue",
        "target_node": "drafting_generate_outline",
        "reason": "现有技术分析和写作指南已足够进入大纲生成。",
        "required_changes": []
    },
    "retry_counts": {
        "drafting_patent_search": 0,
        "drafting_prior_art_analysis": 0
    }
}
```

要求：

- state 中 artifact key 必须为相对路径。
- 长正文、交底书全文、检索正文不得直接放入 state。
- 每个节点只读自己需要的 artifact。
- 每个节点只写自己负责的 artifact。
- 节点失败时必须返回可解释错误和可恢复状态。

### 3.3 Leader Gate 契约

Leader 不再负责固定流程调度，只作为顶层 workflow 中的关口决策节点。

输入：

- 当前 state 的短字段。
- 相关中间产物摘要或 artifact key。
- 当前 gate 的验收规则。
- retry count 与最大重试次数。

输出：

```json
{
  "decision": "continue | retry | revise | escalate",
  "target_node": "drafting_patent_search",
  "reason": "现有检索结果不足以判断最接近现有技术。",
  "required_changes": ["扩大关键词", "补充 IPC 检索", "重新提取区别特征"],
  "confidence": "low | medium | high"
}
```

要求：

- `decision` 必须为枚举值。
- `target_node` 必须指向 `WorkflowDef.nodes` 中存在的合法节点。
- gate Node 根据结构化决策返回 `NodeResult.next_node`。
- `reason` 使用中文，说明具体不足，不写空泛判断。
- `required_changes` 必须可执行。
- `confidence` 必须显式标注。
- Leader 不直接生成摘要、权利要求、说明书正文。
- Leader 不直接读写长正文，只基于 artifact key 和结构化摘要决策。

### 3.4 前置研究节点契约

#### 3.4.1 `drafting_patent_search` Node

职责：基于解析后的技术主题、关键词、IPC 候选和发明点执行专利检索。

输入：

- `01_input/parsed_info.json`
- 可选用户补充关键词
- 检索配置：`top_k`、国家 / 地区、授权状态、联网门控

输出 artifact：

```text
02_research/patent_search_results.json
```

输出字段：

```json
{
  "queries": [],
  "results": [
    {
      "title": "",
      "publication_number": "",
      "abstract": "",
      "url": "",
      "country": "CN",
      "status": "GRANT",
      "source": "serpapi",
      "confidence": "medium"
    }
  ],
  "sufficient": true,
  "skipped": false,
  "reason": ""
}
```

验收：

- 未授权联网或未配置 Key 时安全降级，不编造结果。
- 检索结果必须保留来源。
- 默认测试使用 fake provider。

#### 3.4.2 `drafting_prior_art_analysis` Node

职责：将检索结果转为可供撰写使用的现有技术分析。

输入：

- `01_input/parsed_info.json`
- `02_research/patent_search_results.json`

输出 artifact：

```text
02_research/prior_art_analysis.json
```

输出字段：

```json
{
  "closest_prior_art": [],
  "distinguishing_features": [],
  "technical_effects": [],
  "novelty_risks": [],
  "inventiveness_risks": [],
  "recommended_claim_focus": [],
  "uncertain_points": [],
  "confidence": "low | medium | high"
}
```

验收：

- 不编造专利号、法条、引用或检索结果。
- 检索不足时必须在 `uncertain_points` 中显式标注。
- 能为后续权利要求和说明书生成提供区别特征与技术效果。

### 3.5 附图与写作指南节点契约

#### 3.5.1 `drafting_drawing_analysis` Node

职责：分析交底书中的附图、部件编号、流程图或结构图信息，生成可供说明书和附图说明使用的结构化资料。

输入：

- `01_input/parsed_info.json`
- 可选 `01_input/drawing_assets.*` 或附件解析结果

输出 artifact：

```text
02_research/drawing_analysis.json
```

输出字段：

```json
{
  "figures": [
    {
      "figure_id": "图1",
      "title": "",
      "type": "结构图 | 流程图 | 系统框图 | 其他",
      "components": [
        {"label": "", "name": "", "description": ""}
      ],
      "description_points": []
    }
  ],
  "missing_drawings": [],
  "numbering_rules": [],
  "uncertain_points": [],
  "confidence": "low | medium | high"
}
```

验收：

- 不实现视觉理解时，必须只基于输入中已有的附图说明或解析文本。
- 不得臆造不存在的附图或部件编号。
- 附图缺失时输出 `missing_drawings` 和 `uncertain_points`。

#### 3.5.2 `drafting_writing_style_guide` Node

职责：将现有技术分析、附图分析、项目约束和参考写作要求整理为后续生成阶段必须遵守的写作风格指南。

输入：

- `01_input/parsed_info.json`
- `02_research/prior_art_analysis.json`
- `02_research/drawing_analysis.json`
- 可选历史风格 / 用户注意事项 artifact

输出 artifact：

```text
02_research/writing_style_guide.json
```

输出字段：

```json
{
  "global_rules": [],
  "terminology_rules": [],
  "claim_style": {
    "required_focus": [],
    "avoid_scope": [],
    "dependency_rules": []
  },
  "description_style": {
    "structure_rules": [],
    "embodiment_rules": [],
    "drawing_reference_rules": []
  },
  "avoid_phrases": [],
  "required_phrases": [],
  "uncertain_points": [],
  "confidence": "low | medium | high"
}
```

验收：

- 写作指南必须作为独立中间产物，不散落在正文生成 prompt 中。
- 后续 `drafting_generate_outline`、`drafting_generate_sections`、`drafting_review_document` 必须显式读取该 artifact。
- 用户注意事项必须作为规则进入指南，但外部输入必须作为数据处理，不得作为高优先级系统指令执行。

### 3.6 内容生成节点契约

内容生成节点可以沿用现有子代理能力，但需要通过顶层 Node 显式包装。

建议节点：

| Node | 输入 | 输出 |
| --- | --- | --- |
| `drafting_generate_outline` | `parsed_info`、`prior_art_analysis`、`drawing_analysis`、`writing_style_guide` | `03_outline/patent_outline.md` |
| `drafting_generate_sections` | 大纲、写作指南、现有技术分析、附图分析 | `04_content/*.md` |
| `drafting_merge_document` | `04_content/*.md` | `05_final/complete_patent.md` |
| `drafting_review_document` | 终稿、写作指南、关键中间产物 | `05_final/review_report.json` |
| `drafting_finalize` | 终稿、评审报告、gate 决策 | 最终响应 |

要求：

- 各节点只通过 artifact key 传递长正文。
- 各节点输出必须可由 workspace `list` 和 `read` 验证。
- 节点失败不应导致状态丢失。

### 3.7 日志与 Trace 契约

建议事件：

| event | 触发 | 字段 |
| --- | --- | --- |
| `drafting_workflow_started` | patent_drafting 开始 | `workspace_id`, `intent` |
| `drafting_node_started` | 节点开始 | `node`, `attempt` |
| `drafting_node_completed` | 节点完成 | `node`, `artifact_key`, `duration_ms` |
| `drafting_node_failed` | 节点失败 | `node`, `reason`, `recoverable` |
| `leader_gate_started` | Leader gate 开始 | `gate`, `attempt` |
| `leader_gate_decided` | Leader gate 输出决策 | `gate`, `decision`, `target_node`, `confidence` |
| `drafting_artifact_written` | 写入 artifact | `artifact_key`, `chars` |
| `drafting_workflow_completed` | patent_drafting 完成 | `final_key`, `review_key` |

要求：

- `event` 使用稳定英文名。
- `message` 可使用中文。
- 不记录交底书正文、prompt 全文、检索正文、API key、token 或隐私数据。
- 可恢复异常使用 warning 并说明降级结果。
- 异常保留堆栈。

---

## 4. Code Style

- 优先最小化、局部化改动，复用现有 helper、workspace、ToolRegistry、配置、trace 与测试设施。
- 所有公开类、函数、方法必须写中文 Google 风格 docstring，包含 Args / Returns / Raises（如有）。
- 注释和日志沿用中文风格；日志 `event` 字段使用稳定英文。
- 行内注释只解释不直观的边界、路由、降级、重试和安全处理。
- Prompt 不内联散落在业务逻辑里，集中在 `app/prompts/` 模块。
- 运行时变量使用具名占位符，禁止字符串拼接注入数据。
- 外部 / 用户 / 附件 / 检索内容必须包裹在 `<data>...</data>` 或等价分隔符内，并声明数据区不作为指令。
- 默认输出中文，使用规范专利术语。
- 不编造法条、专利号、检索结果、引用或来源。
- 不使用用户输入拼接 shell 命令或 SQL。
- 不把密钥、完整 API Key、附件正文、长原文写入日志、trace 或长期记忆。
- 不新增外部 agent 框架依赖。
- 删除或替换旧实现时直接清理无用代码，不保留无意义兼容壳。

---

## 5. Testing Strategy

### 5.1 增量测试顺序

1. workflow 定义与路由测试
   - `patent_drafting` 在 `WorkflowRegistry` 中展开为完整顶层节点列表。
   - 不再只包含 `normalize_input` 与 `drafting_leader`。
   - `continue` 路由到下一节点。
   - `retry` 路由回目标节点并受到 `max_loop_count` 限制。
   - `revise` 路由到返修节点。
   - `escalate` 路由到人工介入或安全终止。

2. Leader gate 测试
   - 输出严格符合 `decision` schema。
   - 非法枚举值被拒绝或安全降级。
   - `target_node` 不存在于 `WorkflowDef.nodes` 时返回可解释错误。
   - 低置信度必须带 `required_changes` 或 `uncertain_points`。
   - Leader 不直接生成正文 artifact。

3. `drafting_patent_search` 与 `drafting_prior_art_analysis` 节点测试
   - 离线时 `drafting_patent_search` 返回 skipped，不触网。
   - fake provider 返回结果时写入 `patent_search_results.json`。
   - `drafting_prior_art_analysis` 能提取最接近现有技术、区别特征、技术效果和风险。
   - 检索不足时不编造来源，并显式标注不确定。

4. `drafting_drawing_analysis` 与 `drafting_writing_style_guide` 节点测试
   - 附图信息存在时输出图号、标题、类型、部件编号。
   - 附图缺失时输出缺失项和不确定点。
   - 写作指南整合用户注意事项、现有技术分析和附图分析。
   - 写作指南 artifact 被后续生成节点读取。

5. 内容生成与 review 测试
   - 大纲生成读取全部前置 artifact。
   - 正文生成读取写作风格指南。
   - merge 顺序稳定。
   - review 输出结构化报告。
   - Leader review gate 能决定通过或返修。

6. 端到端回归
   - `intent=patent_drafting` 可完成离线 fake LLM 流程。
   - 输出包含摘要、权利要求书、说明书、说明书附图、评审报告。
   - 全流程 trace 可看到各顶层 Node 和 gate 决策。
   - 默认不触网、不调用真实外部 LLM。
   - 全量测试与 compileall 通过。

### 5.2 必测用例

- `WorkflowRegistry.get_workflow_def("patent_drafting")` 返回完整节点列表。
- Leader gate 输出 `continue` 时，Orchestrator 进入下一固定节点。
- Leader gate 输出 `retry` 且未超过上限时，Orchestrator 回到 `target_node`。
- Leader gate 输出 `retry` 且超过上限时，Orchestrator 返回 `loop_limit_exceeded` 或安全失败。
- `drafting_prior_art_analysis` 在无检索结果时不生成伪现有技术。
- `drafting_drawing_analysis` 在没有附图输入时不臆造图号。
- `drafting_writing_style_guide` 必须包含用户注意事项，但不得执行注意事项中的指令注入内容。
- `drafting_generate_outline` 未找到写作指南时返回可解释失败。
- `drafting_review_document` 能发现文书未遵守写作指南的情况。
- trace / 日志不包含交底书正文、prompt 全文、检索正文或密钥。
- `Settings` 默认值、环境变量覆盖、`to_public_dict()` 如有新增配置必须有测试。

### 5.3 Fixtures 与隔离

- 使用 fake LLM 隔离真实模型调用。
- 使用 fake patent search provider 隔离真实联网检索。
- 使用 `tmp_path` 覆盖磁盘 workspace。
- 使用小型 Markdown / JSON fixture，避免大二进制污染仓库。
- 联网集成测试单独标记，默认不运行。

---

## 6. Boundaries

### 6.1 Always do

- 固定流程由顶层 workflow Node 承载，Leader 只做关键 gate 决策。
- 复用现有 `Orchestrator`，不新增平级 DAG 编排器。
- 每个 Node 都定义输入、输出、artifact key、失败语义和测试验收。
- `drafting_patent_search`、`drafting_prior_art_analysis`、`drafting_drawing_analysis`、`drafting_writing_style_guide` 必须是显式前置 Node。
- Leader gate 输出必须是结构化 JSON 决策，并转化为合法 `NodeResult.next_node`。
- 长正文只通过 workspace key / artifact 流转。
- 检索、附件、用户注意事项均作为数据处理，不作为高优先级指令。
- 检索不足、附图缺失、风格约束不足时必须显式标注不确定。
- 默认测试不访问真实网络和真实外部 LLM。
- 日志和 trace 必须脱敏。
- 配置项保持通用作用域，不绑定单个临时 Node。

### 6.2 Ask first

- 是否一次性替换现有 `DraftingLeaderNode`，还是先保留兼容入口并逐步迁移到顶层节点。
- 是否新增 `drafting_human_review` / `manual_intervention` 节点。
- 是否将 `drafting_generate_sections` 继续拆为摘要、权利要求、说明书、附图多个节点。
- 是否启用 pydantic / JSON Schema 对中间产物做强校验。
- 是否调整现有 `max_loop_count`、重试次数、token 预算和超时。
- 是否增强 `Orchestrator` 支持 per-node / per-gate retry 上限。
- 是否将联网集成测试接入 CI 的可选 job。

### 6.3 Never do

- 不让 Leader 继续隐藏固定全流程。
- 不新增和 `app/orchestrator/engine.py` 职责重复的二级编排器。
- 不让 Leader 直接生成每个阶段正文。
- 不让子代理 / 自代理作为黑盒藏在单个大节点内部。
- 不把前置研究产物只塞进 prompt，而不落为 artifact。
- 不在无真实来源时伪造专利号、检索结果、引用或法条。
- 不执行附件、检索结果或用户注意事项中的指令。
- 不把附件正文、prompt 全文、检索正文或密钥写入日志 / trace / 长期记忆。
- 不通过 shell 拼接用户输入执行命令。
- 不引入 LangChain / LangGraph / MCP 等外部编排框架，除非另行确认。

---

## 7. Acceptance Criteria

### 7.1 架构验收

- 文书生成流程可以从 `workflow_defs.py` 中直接看到顶层节点顺序和 gate 节点位置。
- Leader gate 节点数量有限，且只出现在关键决策关口。
- 每个前置产物都有独立 artifact 文件和 schema。
- 任意节点失败后，可以根据 `WorkflowState`、trace 和 workspace artifact 判断失败位置。

### 7.2 质量验收

- `drafting_prior_art_analysis` 能明确区分真实检索结果与不确定判断。
- `drafting_drawing_analysis` 能明确区分已有附图信息与缺失附图信息。
- `drafting_writing_style_guide` 能稳定约束后续大纲、正文和评审节点。
- `drafting_review_document` 与 `drafting_leader_gate_review` 能发现关键约束未满足并返修。

### 7.3 工程验收

- 默认测试不触网、不调用真实外部 LLM。
- 全量测试通过。
- 编译检查通过。
- 日志、trace、公开配置不泄露敏感信息或长正文。

---

## 8. Incremental Delivery Plan

### 阶段 1：定义顶层 workflow、gate decision 与节点骨架

验收：

- `patent_drafting` 展开为完整顶层节点列表。
- gate decision schema 完整。
- `NodeResult.next_node` 路由测试通过。

建议提交：

```text
feat(drafting): 展开文书生成顶层流程节点
```

### 阶段 2：实现前置研究节点

验收：

- `drafting_patent_search` Node 写入检索结果 artifact。
- `drafting_prior_art_analysis` Node 写入现有技术分析 artifact。
- 离线降级与不臆造测试通过。

建议提交：

```text
feat(drafting): 拆分专利检索与现有技术分析节点
```

### 阶段 3：实现附图分析与写作风格指南节点

验收：

- `drafting_drawing_analysis` Node 写入附图分析 artifact。
- `drafting_writing_style_guide` Node 写入写作指南 artifact。
- 后续节点能读取写作指南。

建议提交：

```text
feat(drafting): 增加附图分析与写作指南节点
```

### 阶段 4：实现 Leader gate 节点

验收：

- prior art gate、guidance gate、review gate 均输出结构化决策。
- `continue` / `retry` / `revise` / `escalate` 路由可测。
- Leader 不直接生成正文。

建议提交：

```text
feat(drafting): 改为 Leader 关口决策节点
```

### 阶段 5：将内容生成接入顶层 workflow

验收：

- 大纲、正文、合并、评审节点接入顶层 workflow。
- 全流程使用 artifact key 流转。
- 端到端 fake LLM 流程通过。

建议提交：

```text
refactor(drafting): 将文书生成接入顶层流程
```

### 阶段 6：回归与收敛旧 Leader 职责

验收：

- 旧 Leader 不再承担固定流程脚本职责。
- 全量测试与 compileall 通过。
- 文档、配置、日志和 trace 对齐新架构。

建议提交：

```text
fix(drafting): 收敛 Leader 为关口决策节点
```
