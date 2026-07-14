# Pagent 文书生成顶层流程化实施计划

## 目标与范围

本计划基于根目录 `SPEC.md`，用于将专利文书生成从 `drafting_leader` 内部固定 for-loop 改为由现有顶层 `Orchestrator` 承载完整 `patent_drafting` 节点列表，Leader 只作为关键 gate Node 做结构化决策。

本轮只生成 `tasks/plan.md` 与 `tasks/todo.md`，不修改实现代码、不运行测试、不提交 git。

核心范围：

- 在 `WorkflowRegistry` 中展开 `patent_drafting` 顶层节点列表。
- 复用 `app/orchestrator/engine.py` 的顺序执行、`NodeResult.next_node` 跳转和 `max_loop_count` 回环限制。
- 将当前 `DraftingLeaderNode.run()` 中的 9 环节隐式编排拆为普通 Node。
- 将 `patent_search`、`prior_art_analysis`、`drawing_analysis`、`writing_style_guide` 作为显式前置 Node。
- 增加 Leader gate Node：prior art gate、guidance gate、review gate。
- 长正文继续通过 `draft_workspace` artifact key 流转，`WorkflowState` 只保存短字段、artifact key 和结构化决策。
- 默认测试不触网、不调用真实外部 LLM。

当前只读探索结论：

- `app/orchestrator/workflow_defs.py` 当前 `patent_drafting` 仍是 `['normalize_input', 'drafting_leader']`。
- `app/orchestrator/engine.py` 已支持顺序执行、合法 `next_node` 跳转、向前回跳计数和 `loop_limit_exceeded`，可直接作为顶层流程承载层。
- `app/services/agent_dispatch_service.py` 当前 `_run_patent_drafting()` 只注册 `drafting_leader` 一个节点，需要改为注册完整 drafting 节点集合。
- `app/nodes/drafting_leader.py` 当前在 `run()` 内按 `DRAFTING_ALLOWED_TOOLS` for-loop 调用子代理，正是需要拆出的隐式编排。
- `app/models/schemas.py` 当前 `WorkflowState` 主要保存 Markdown 结果字段，尚未显式保存 drafting artifact key、gate decision、retry 结构化状态。
- 现有 `tests/test_drafting_leader.py` 和 `tests/test_patent_drafting_workflow.py` 仍以旧 Leader 编排为核心，需要逐步迁移到顶层 workflow 与 gate Node 测试。

---

## 依赖图

```text
P0 顶层 workflow 契约与状态骨架
  ├─> P1 输入解析与 workspace 初始化切片
  │     ├─> P2 前置研究切片
  │     │     ├─> P3 prior art gate 切片
  │     │     │     └─> P4 附图与写作指南切片
  │     │     │           ├─> P5 guidance gate 切片
  │     │     │           │     └─> P6 内容生成切片
  │     │     │           │           ├─> P7 review gate 与 finalize 切片
  │     │     │           │           │     └─> P8 服务入口与端到端回归
  │     │     │           │           └─> P8 服务入口与端到端回归
  │     │     └─> P8 服务入口与端到端回归
  │     └─> P8 服务入口与端到端回归
  └─> P9 收敛旧 Leader 与测试迁移
```

说明：

- P0 是所有后续任务的基础：节点名称、state 字段和 workflow 列表必须先稳定。
- P1 负责把输入资料写入 workspace，后续所有 Node 只通过 artifact key 读取。
- P2/P4 是前置产物生产链，阻塞内容生成。
- P3/P5/P7 是 Leader 价值所在：只做 gate 判断，不直接生成正文。
- P6/P7 完成从前置指南到终稿的完整可运行路径。
- P8 把完整节点集合接回 `AgentDispatchService`，形成端到端可验收路径。
- P9 在新路径稳定后再移除或降级旧 `DraftingLeaderNode`，避免中途大爆炸式替换。

---

## 垂直切片计划

### P0 — 顶层 workflow 契约与状态骨架

#### 目标

先把 `patent_drafting` 的顶层节点列表、gate decision schema、artifact key 状态约定固定下来，不实现复杂生成逻辑。

#### 覆盖范围

- `app/orchestrator/workflow_defs.py`
- `app/models/schemas.py` 或 `app/nodes/drafting_state.py`
- `tests/test_drafting_workflow_defs.py`

#### 实施要点

- 将 `patent_drafting` 从 `normalize_input -> drafting_leader` 展开为 SPEC 中的完整节点列表。
- 保持 `start_node='normalize_input'`。
- 设置 `max_loop_count=3`，用于 gate 回跳的短期统一上限。
- 增加 gate decision 数据结构：`decision`、`target_node`、`reason`、`required_changes`、`confidence`。
- 增加 drafting artifact key 状态约定，优先使用 `WorkflowState` 的短字段或单独 `drafting_context` 字典，避免把长正文塞入 state。
- 不新增 `drafting_dag.py` 或任何与 `engine.py` 平级的二级编排器。

#### 验收标准

- `WorkflowRegistry.get_workflow_def('patent_drafting')` 返回完整节点列表。
- 节点列表包含三个 Leader gate 节点。
- 节点列表不再包含旧的单点 `drafting_leader` 作为唯一业务节点。
- gate decision schema 能表达 `continue` / `retry` / `revise` / `escalate`。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_drafting_workflow_defs.py
conda run -n autoGLM python -m compileall app tests
```

#### 检查点

- 确认是否采用 `WorkflowState.drafting_context` 字典，还是新增显式字段。
- 确认短期使用统一 `max_loop_count=3`，per-gate retry 暂不做。

---

### P1 — 输入解析与 workspace 初始化切片

#### 目标

把当前 `DraftingLeaderNode._build_source_content()` 和 source artifact 写入能力拆成 `drafting_parse_input` Node，形成所有后续 Node 的入口 artifact。

#### 覆盖范围

- `app/nodes/drafting_research.py` 或独立 `app/nodes/drafting_input.py`
- `app/tools/draft_workspace.py`
- `tests/test_drafting_research_nodes.py` 或 `tests/test_drafting_input_node.py`

#### 实施要点

- `drafting_parse_input` 从 `state.normalized_input` / `state.raw_input` / `state.documents` 拼接输入数据。
- 写入 `01_input/raw_document.md`。
- 调用现有 `input_parser` 子代理或最小适配逻辑生成 `01_input/parsed_info.json`。
- 将相关 artifact key 写入 state 短字段或 `drafting_context`。
- trace 只记录 artifact key、字符数和状态，不记录原文。

#### 验收标准

- 无附件时能写入用户输入。
- 有附件时能合并附件文本。
- `01_input/raw_document.md` 与 `01_input/parsed_info.json` 存在。
- trace 不泄露用户原文和附件正文。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_drafting_research_nodes.py
conda run -n autoGLM python -m compileall app tests
```

#### 检查点

- 确认 `parsed_info.json` 短期是否继续沿用现有 `input_parser` 子代理输出，还是在本阶段引入强 schema。

---

### P2 — 前置研究切片：检索与现有技术分析

#### 目标

完成从 parsed info 到检索结果、现有技术分析的完整垂直路径。

#### 覆盖范围

- `app/nodes/drafting_research.py`
- `app/tools/patent_search.py`
- `app/tools/subagents/` 中的 `patent_searcher` 适配能力
- `tests/test_drafting_research_nodes.py`

#### 实施要点

- `drafting_patent_search` 读取 `01_input/parsed_info.json`。
- 调用 `patent_search` 工具，默认 fake provider / 离线降级。
- 写入 `02_research/patent_search_results.json`。
- `drafting_prior_art_analysis` 读取 parsed info 和 search results。
- 调用现有子代理能力或 fake LLM 适配层生成结构化 `02_research/prior_art_analysis.json`。
- 检索不足时不编造现有技术，在 `uncertain_points` 中显式标注。

#### 验收标准

- 离线 / 未授权联网时 `patent_search_results.json` 标记 `skipped=true` 或 `sufficient=false`。
- fake provider 有结果时保留来源、专利号、标题、摘要等字段。
- `prior_art_analysis.json` 包含最接近现有技术、区别特征、技术效果、风险、不确定点和置信度。
- 不在日志 / trace 中记录检索正文长内容或密钥。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_drafting_research_nodes.py
conda run -n autoGLM pytest tests/test_patent_search.py
conda run -n autoGLM python -m compileall app tests
```

#### 检查点

- 确认 prior art analysis 是否由新的 Node prompt 生成，还是短期复用 `patent_searcher` 子代理并改输出 artifact。

---

### P3 — Leader prior art gate 切片

#### 目标

让 Leader 第一次作为顶层 gate Node 工作：只判断现有技术分析是否足够支撑继续。

#### 覆盖范围

- `app/nodes/drafting_leader_gate.py`
- `app/prompts/drafting_gates.py`
- `tests/test_drafting_leader_gates.py`
- `tests/test_drafting_workflow_defs.py`

#### 实施要点

- 实现 `drafting_leader_gate_prior_art`。
- 输入只包含 artifact key、结构化摘要、retry count 和验收规则。
- 输出结构化 gate decision。
- `continue` 不设置 `next_node` 或设置到 `drafting_drawing_analysis`。
- `retry` 返回 `NodeResult.next_node='drafting_patent_search'`。
- `revise` 返回 `NodeResult.next_node='drafting_prior_art_analysis'`。
- `escalate` 短期返回 `requires_user_input` 或 failed；如新增 human review 需先确认。

#### 验收标准

- gate 输出非法枚举时安全失败。
- `target_node` 不在当前 workflow 中时安全失败。
- `retry` / `revise` 能被现有 `Orchestrator` 路由回前置节点。
- 超过 `max_loop_count` 时由 `engine.py` 返回 `loop_limit_exceeded`。
- Leader 不读写正文 artifact，不生成正文内容。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_drafting_leader_gates.py
conda run -n autoGLM pytest tests/test_drafting_workflow_defs.py
conda run -n autoGLM python -m compileall app tests
```

#### 检查点

- 确认 `escalate` 短期处理方式：`requires_user_input` 优先，暂不新增 human review Node。

---

### P4 — 附图分析与写作风格指南切片

#### 目标

把专利附图分析和写作风格指南从 prompt 上下文中拆为稳定前置 artifact。

#### 覆盖范围

- `app/nodes/drafting_guidance.py`
- `app/prompts/subagents/drawing_analysis_prompt.py`
- `app/prompts/subagents/writing_style_guide_prompt.py`
- `tests/test_drafting_guidance_nodes.py`

#### 实施要点

- `drafting_drawing_analysis` 读取 `parsed_info.json` 和可用附件解析信息。
- 只基于输入已有附图说明或解析文本生成 `02_research/drawing_analysis.json`。
- 无附图时输出 `missing_drawings` 与 `uncertain_points`，不得臆造图号。
- `drafting_writing_style_guide` 读取 parsed info、prior art analysis、drawing analysis 和用户注意事项。
- 写入 `02_research/writing_style_guide.json`。
- 用户注意事项作为数据进入规则，不作为高优先级指令执行。

#### 验收标准

- 有附图信息时输出图号、标题、类型、部件编号。
- 无附图信息时明确缺失，不臆造。
- 写作指南包含 global rules、术语规则、claim style、description style、不确定点和置信度。
- 后续内容节点可通过 artifact key 读取写作指南。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_drafting_guidance_nodes.py
conda run -n autoGLM python -m compileall app tests
```

#### 检查点

- 确认是否需要视觉理解；按 SPEC 默认不做视觉理解，只处理已有文本。

---

### P5 — Leader guidance gate 切片

#### 目标

让 Leader 判断附图分析和写作指南是否足够进入大纲 / 正文生成。

#### 覆盖范围

- `app/nodes/drafting_leader_gate.py`
- `app/prompts/drafting_gates.py`
- `tests/test_drafting_leader_gates.py`

#### 实施要点

- 实现 `drafting_leader_gate_guidance`。
- 输入包括 `drawing_analysis_key`、`writing_style_guide_key`、摘要字段、uncertain points、retry 信息。
- `continue` 进入 `drafting_generate_outline`。
- `retry` 可回到 `drafting_drawing_analysis` 或 `drafting_writing_style_guide`。
- `revise` 优先回到 `drafting_writing_style_guide`。
- 低置信度时必须给出 required changes。

#### 验收标准

- 写作指南缺失时不允许 continue。
- 附图信息缺失但已显式标注时，可以根据规则 continue 或 requires_user_input。
- 返回的 `target_node` 必须合法。
- trace 只记录决策、目标节点、置信度和原因摘要。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_drafting_leader_gates.py
conda run -n autoGLM python -m compileall app tests
```

#### 检查点

- 确认附图缺失是否阻塞继续，还是只作为 review 风险提示。

---

### P6 — 内容生成切片：大纲、正文、合并、评审

#### 目标

把现有子代理能力包装为顶层内容生成 Node，形成从写作指南到评审报告的完整路径。

#### 覆盖范围

- `app/nodes/drafting_content.py`
- `app/tools/subagents/`
- `app/tools/draft_workspace.py`
- `tests/test_drafting_content_nodes.py` 或并入 `tests/test_patent_drafting_workflow.py`

#### 实施要点

- `drafting_generate_outline` 读取 parsed info、prior art analysis、drawing analysis、writing style guide，写入 `03_outline/patent_outline.md`。
- `drafting_generate_sections` 读取大纲和前置指南，生成摘要、权利要求、说明书、附图说明等 `04_content/*.md`。
- `drafting_merge_document` 使用 workspace merge 或 merger 子代理写入 `05_final/complete_patent.md`。
- `drafting_review_document` 读取终稿和约束 artifact，写入 `05_final/review_report.json`。
- 每个 Node 都返回短 output，不把长正文塞入 result output。

#### 验收标准

- 大纲生成缺少写作指南时返回可解释失败。
- 正文生成必须读取 `writing_style_guide.json`。
- 合并顺序稳定。
- review 能发现终稿未遵守写作指南的情况。
- 所有长正文只在 workspace 中流转。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py
conda run -n autoGLM python -m compileall app tests
```

#### 检查点

- 确认 `drafting_generate_sections` 是否继续作为一个 Node，还是拆为摘要 / 权利要求 / 说明书 / 附图多个 Node。按 SPEC 当前先保留一个 Node。

---

### P7 — Leader review gate 与 finalize 切片

#### 目标

让 Leader 只在终稿评审后判断通过、返修、重评或人工介入，并由 finalize 汇总服务结果。

#### 覆盖范围

- `app/nodes/drafting_leader_gate.py`
- `app/nodes/drafting_content.py`
- `tests/test_drafting_leader_gates.py`
- `tests/test_patent_drafting_workflow.py`

#### 实施要点

- 实现 `drafting_leader_gate_review`。
- 输入包括 `complete_patent.md` key、`review_report.json` key、写作指南摘要和 retry 信息。
- `continue` 进入 `drafting_finalize`。
- `revise` 回到 `drafting_generate_sections`。
- `retry` 回到 `drafting_review_document`。
- `drafting_finalize` 读取最终 artifact，回填现有 API 兼容字段：`input_points_md`、`prior_art_md`、`outline_md`、`abstract_md`、`claims_md`、`description_md`、`figures_md`、`complete_patent_md`、`drafting_incomplete`。

#### 验收标准

- review gate 能对未满足写作指南的终稿返修。
- finalize 保持现有 `AgentDispatchService` 返回结构兼容。
- 旧端到端测试中的关键字段仍能返回。
- trace 可看到 review gate 决策。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_drafting_leader_gates.py
conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py
conda run -n autoGLM python -m compileall app tests
```

#### 检查点

- 确认 `drafting_incomplete` 的判定口径：任一必需 artifact 缺失或 gate escalate 即 True。

---

### P8 — 服务入口与端到端回归切片

#### 目标

将完整顶层节点集合注册到 `AgentDispatchService._run_patent_drafting()`，完成真实入口回归。

#### 覆盖范围

- `app/services/agent_dispatch_service.py`
- `app/orchestrator/workflow_defs.py`
- `tests/test_patent_drafting_workflow.py`

#### 实施要点

- `_run_patent_drafting()` 不再只注册 `drafting_leader`。
- 注册全部 drafting Node：parse、search、analysis、gates、guidance、content、finalize。
- 保持 `remaining_nodes` 裁剪逻辑可用。
- 确保 intent router 返回的起始节点能命中新 workflow。
- 默认 fake LLM / fake provider 流程可跑通。

#### 验收标准

- `AgentDispatchService().dispatch('请生成专利文书')` 返回 success。
- 返回结构兼容现有 API 字段。
- trace 包含多个顶层 drafting node，而不是单个 `drafting_leader` 黑盒。
- 默认不触网、不调用真实外部 LLM。

#### 验证命令

```bash
conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests
```

#### 检查点

- 确认是否保留旧 `drafting_leader` 作为兼容 fallback。若保留，不能再作为默认 patent_drafting 路径。

---

### P9 — 收敛旧 Leader 与测试迁移

#### 目标

新顶层 workflow 稳定后，清理旧 Leader 的固定流程职责，避免两套流程并存。

#### 覆盖范围

- `app/nodes/drafting_leader.py`
- `tests/test_drafting_leader.py`
- 相关 prompt / constants / registry 引用

#### 实施要点

- 删除或降级旧 `DraftingLeaderNode.run()` 内部 9 环节 for-loop。
- 将旧测试迁移为 gate Node 测试或 workflow 测试。
- 删除不再使用的 `DRAFTING_ALLOWED_TOOLS` 流程顺序常量，或只保留为内容节点内部子代理清单。
- 确认没有代码路径继续把 `drafting_leader` 当作完整文书生成黑盒。

#### 验收标准

- `workflow_defs.py` 是 patent_drafting 顺序权威来源。
- Leader 相关代码只保留 gate 决策职责。
- 全量测试通过。
- compileall 通过。

#### 验证命令

```bash
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests
```

#### 检查点

- 清理前确认没有外部 API 或测试依赖旧 `drafting_leader` 节点名。

---

## 阶段检查点

### Checkpoint A — 顶层 workflow 可见

完成 P0 后检查：

- `patent_drafting` 完整节点列表已在 `workflow_defs.py` 可见。
- 没有新增二级 DAG 编排器。
- `engine.py` 的现有 `next_node` 路由足够支撑短期 gate 回跳。

### Checkpoint B — 前置产物可复用

完成 P1-P5 后检查：

- `parsed_info`、检索结果、现有技术分析、附图分析、写作指南均有独立 artifact。
- Leader prior art gate 和 guidance gate 只输出结构化决策。
- 后续内容生成无需读取 Leader 内部状态。

### Checkpoint C — 完整路径可跑通

完成 P6-P8 后检查：

- API 入口能返回完整文书字段。
- trace 能看到多个顶层 drafting node。
- 默认测试不触网、不调用真实外部 LLM。

### Checkpoint D — 旧职责收敛

完成 P9 后检查：

- 旧 `drafting_leader` 不再隐藏固定全流程。
- Leader 只保留关口决策职责。
- 全量测试与编译检查通过。

---

## 风险与应对

### 风险 1：`engine.py` 只有统一 `max_loop_count`

- 影响：无法为 prior art、guidance、review 设置不同 retry 上限。
- 应对：短期按 SPEC 使用统一 `max_loop_count=3`；如后续确需差异化，再单独增强 per-node retry。

### 风险 2：一次性拆旧 Leader 影响端到端稳定性

- 影响：所有 patent_drafting 测试同时失败，定位困难。
- 应对：按垂直切片逐步迁移，先让新节点路径跑通，再收敛旧 Leader。

### 风险 3：中间产物 schema 过早强约束

- 影响：fake LLM / 子代理输出适配成本过高。
- 应对：先以最小字段 + 明确不确定性落地，强 JSON Schema 校验作为可选增强。

### 风险 4：子代理工具与 Node 边界重复

- 影响：Node 和 subagent 都像“执行单元”，职责混乱。
- 应对：Node 是顶层 workflow 调度单元；subagent 是 Node 内部可替换执行机制。流程顺序只在 `workflow_defs.py` 中定义。
