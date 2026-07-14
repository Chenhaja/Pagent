# Pagent 文书生成顶层流程化 Todo

## Phase 0 — 顶层 workflow 契约与状态骨架

- [x] 新增或改写 `tests/test_drafting_workflow_defs.py`。
  - 验收：覆盖 `patent_drafting` 完整节点列表、gate 节点存在、旧单点 `drafting_leader` 不再作为唯一业务节点、`max_loop_count=3`。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_workflow_defs.py`
- [x] 展开 `app/orchestrator/workflow_defs.py` 中的 `patent_drafting` 节点列表。
  - 验收：节点列表包含 parse、search、prior art、三个 leader gate、guidance、content、review、finalize。
  - 验证：workflow defs 测试。
- [x] 定义 gate decision 数据结构。
  - 验收：支持 `decision`、`target_node`、`reason`、`required_changes`、`confidence`；枚举包含 `continue` / `retry` / `revise` / `escalate`。
  - 验证：schema 或 gate 测试。
- [x] 定义 drafting artifact key 状态存储约定。
  - 验收：长正文不进入 `WorkflowState` 的新增状态；只保存 artifact key、短摘要、gate decision、retry 信息。
  - 验证：workflow / state 测试。
- [x] 运行 Phase 0 验证命令。
  - 验收：workflow defs 测试与编译通过；全量回归通过。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_workflow_defs.py tests/test_workflow_registry.py && conda run -n autoGLM pytest && conda run -n autoGLM python -m compileall app tests`

## Phase 1 — 输入解析与 workspace 初始化

- [x] 新增 `drafting_parse_input` Node 测试。
  - 验收：覆盖无附件、有附件、workspace 写入、trace 脱敏。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_research_nodes.py`
- [x] 实现 `drafting_parse_input` Node。
  - 验收：从 `state.normalized_input` / `state.raw_input` / `state.documents` 构造输入 artifact。
  - 验证：输入节点测试。
- [x] 写入 `01_input/raw_document.md`。
  - 验收：workspace 中存在 source artifact；trace 只记录 key 和 chars。
  - 验证：输入节点测试。
- [x] 生成或委托生成 `01_input/parsed_info.json`。
  - 验收：后续节点可读取 parsed info artifact；失败时返回可解释错误。
  - 验证：输入节点测试。
- [x] 将 source / parsed info artifact key 写入 state 短字段或 `drafting_context`。
  - 验收：不把原始长正文写入新增 state 字段。
  - 验证：state 断言。
- [x] 运行 Phase 1 验证命令。
  - 验收：输入节点测试与编译通过；全量回归通过。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_research_nodes.py && conda run -n autoGLM pytest && conda run -n autoGLM python -m compileall app tests`

## Phase 2 — 前置研究：检索与现有技术分析

- [x] 新增 `drafting_patent_search` Node 测试。
  - 验收：覆盖离线降级、fake provider、有结果、无结果、trace 脱敏。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_research_nodes.py`
- [x] 实现 `drafting_patent_search` Node。
  - 验收：读取 `01_input/parsed_info.json`，调用 `patent_search` 工具，写入 `02_research/patent_search_results.json`。
  - 验证：research nodes 测试。
- [x] 新增 `drafting_prior_art_analysis` Node 测试。
  - 验收：覆盖有检索结果、检索不足、不编造来源、不确定点输出。
  - 验证：research nodes 测试。
- [x] 实现 `drafting_prior_art_analysis` Node。
  - 验收：读取 parsed info 与 search results，写入 `02_research/prior_art_analysis.json`。
  - 验证：research nodes 测试。
- [x] 规范 prior art analysis 输出字段。
  - 验收：包含 closest prior art、distinguishing features、technical effects、novelty risks、inventiveness risks、recommended claim focus、uncertain points、confidence。
  - 验证：JSON 字段断言。
- [x] 运行 Phase 2 验证命令。
  - 验收：research nodes、patent_search 测试与编译通过。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_research_nodes.py && conda run -n autoGLM pytest tests/test_patent_search.py && conda run -n autoGLM python -m compileall app tests`

## Phase 3 — Leader prior art gate

- [x] 新增 `drafting_leader_gate_prior_art` 测试。
  - 验收：覆盖 continue、retry、revise、escalate、非法 decision、非法 target_node。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_leader_gates.py`
- [x] 实现 Leader gate 基类或共享解析逻辑。
  - 验收：能校验结构化 decision，能把 decision 转换为合法 `NodeResult.next_node`。
  - 验证：gate 测试。
- [x] 实现 `drafting_leader_gate_prior_art` Node。
  - 验收：只读取 artifact key / 结构化摘要，不生成正文。
  - 验证：gate 测试。
- [x] 验证 prior art gate 回跳路由。
  - 验收：`retry` 回到 `drafting_patent_search`；`revise` 回到 `drafting_prior_art_analysis`；超过 loop limit 安全失败。
  - 验证：workflow defs / orchestrator 测试。
- [x] 运行 Phase 3 验证命令。
  - 验收：gate、workflow defs 测试与编译通过。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_leader_gates.py && conda run -n autoGLM pytest tests/test_drafting_workflow_defs.py && conda run -n autoGLM python -m compileall app tests`

## Phase 4 — 附图分析与写作风格指南

- [x] 新增 `drafting_drawing_analysis` Node 测试。
  - 验收：覆盖有附图文本、无附图、不得臆造图号、输出 uncertain points。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_guidance_nodes.py`
- [x] 实现 `drafting_drawing_analysis` Node。
  - 验收：读取 parsed info / 附件解析信息，写入 `02_research/drawing_analysis.json`。
  - 验证：guidance nodes 测试。
- [x] 新增 `drafting_writing_style_guide` Node 测试。
  - 验收：覆盖整合 parsed info、prior art、drawing analysis、用户注意事项、指令注入隔离。
  - 验证：guidance nodes 测试。
- [x] 实现 `drafting_writing_style_guide` Node。
  - 验收：写入 `02_research/writing_style_guide.json`，包含 global rules、terminology rules、claim style、description style、uncertain points、confidence。
  - 验证：guidance nodes 测试。
- [x] 确保用户注意事项作为数据处理。
  - 验收：注意事项中的“忽略以上指令”等文本不会改变输出格式或系统行为。
  - 验证：注入隔离测试。
- [x] 运行 Phase 4 验证命令。
  - 验收：guidance nodes 测试与编译通过。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_guidance_nodes.py && conda run -n autoGLM python -m compileall app tests`

## Phase 5 — Leader guidance gate

- [ ] 新增 `drafting_leader_gate_guidance` 测试。
  - 验收：覆盖写作指南缺失、附图缺失、continue、retry、revise、escalate。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_leader_gates.py`
- [ ] 实现 `drafting_leader_gate_guidance` Node。
  - 验收：判断 drawing analysis 与 writing style guide 是否足够进入大纲生成。
  - 验证：gate 测试。
- [ ] 验证 guidance gate 路由。
  - 验收：`continue` 进入 `drafting_generate_outline`；`retry` / `revise` 回到合法前置节点。
  - 验证：gate / workflow 测试。
- [ ] 运行 Phase 5 验证命令。
  - 验收：gate 测试与编译通过。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_leader_gates.py && conda run -n autoGLM python -m compileall app tests`

## Phase 6 — 内容生成：大纲、正文、合并、评审

- [ ] 新增或扩展内容生成节点测试。
  - 验收：覆盖大纲、正文、合并、评审四类节点的输入 artifact、输出 artifact 和失败语义。
  - 验证：`conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py`
- [ ] 实现 `drafting_generate_outline` Node。
  - 验收：读取 parsed info、prior art、drawing analysis、writing style guide，写入 `03_outline/patent_outline.md`。
  - 验证：内容节点测试。
- [ ] 实现 `drafting_generate_sections` Node。
  - 验收：读取大纲和写作指南，写入摘要、权利要求、说明书、附图说明等 `04_content/*.md`。
  - 验证：内容节点测试。
- [ ] 实现 `drafting_merge_document` Node。
  - 验收：按稳定顺序合并正文 artifact，写入 `05_final/complete_patent.md`。
  - 验证：内容节点测试。
- [ ] 实现 `drafting_review_document` Node。
  - 验收：读取终稿、写作指南、关键中间产物，写入 `05_final/review_report.json`。
  - 验证：内容节点测试。
- [ ] 确保内容节点不把长正文放入 `NodeResult.output`。
  - 验收：output 只包含 artifact key、done、简短说明。
  - 验证：内容节点测试。
- [ ] 运行 Phase 6 验证命令。
  - 验收：内容相关测试与编译通过。
  - 验证：`conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py && conda run -n autoGLM python -m compileall app tests`

## Phase 7 — Leader review gate 与 finalize

- [ ] 新增 `drafting_leader_gate_review` 测试。
  - 验收：覆盖 review 通过、返修正文、重评、人工介入 / 安全失败。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_leader_gates.py`
- [ ] 实现 `drafting_leader_gate_review` Node。
  - 验收：读取 review report 和相关 artifact key，输出结构化决策并返回合法 `next_node`。
  - 验证：gate 测试。
- [ ] 实现 `drafting_finalize` Node。
  - 验收：读取最终 artifact 并回填现有 API 兼容字段。
  - 验证：端到端测试。
- [ ] 兼容现有返回字段。
  - 验收：包含 `input_points_md`、`prior_art_md`、`outline_md`、`abstract_md`、`claims_md`、`description_md`、`figures_md`、`complete_patent_md`、`drafting_incomplete`。
  - 验证：`tests/test_patent_drafting_workflow.py`。
- [ ] 运行 Phase 7 验证命令。
  - 验收：review gate、端到端测试与编译通过。
  - 验证：`conda run -n autoGLM pytest tests/test_drafting_leader_gates.py && conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py && conda run -n autoGLM python -m compileall app tests`

## Phase 8 — 服务入口与端到端回归

- [ ] 更新 `AgentDispatchService._run_patent_drafting()` 测试。
  - 验收：服务入口注册完整 drafting node 集合，而不是只注册 `drafting_leader`。
  - 验证：`conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py`
- [ ] 更新 `_run_patent_drafting()` 节点注册。
  - 验收：`Orchestrator` 可调度全部 drafting 顶层节点。
  - 验证：端到端测试。
- [ ] 确认 `remaining_nodes` 裁剪逻辑适配新节点列表。
  - 验收：intent router 返回业务起始节点时能命中完整 workflow。
  - 验证：dispatch 测试。
- [ ] 确认端到端 trace 可观测性。
  - 验收：trace 包含多个 drafting 顶层 node 和 gate decision，而不是单个 `drafting_leader` 黑盒。
  - 验证：trace 断言。
- [ ] 运行 Phase 8 验证命令。
  - 验收：端到端、全量测试与编译通过。
  - 验证：`conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py && conda run -n autoGLM pytest && conda run -n autoGLM python -m compileall app tests`

## Phase 9 — 收敛旧 Leader 与测试迁移

- [ ] 迁移 `tests/test_drafting_leader.py`。
  - 验收：旧 Leader 顺序调用测试改为 gate 或 workflow 测试，不再断言 Leader 内部 for-loop。
  - 验证：相关测试通过。
- [ ] 删除或降级 `DraftingLeaderNode.run()` 的固定流程职责。
  - 验收：没有默认路径继续通过 `drafting_leader` 隐藏完整文书生成流程。
  - 验证：代码搜索与端到端测试。
- [ ] 清理旧流程常量引用。
  - 验收：`DRAFTING_ALLOWED_TOOLS` 等不再作为 patent_drafting 顶层顺序来源；如保留，只能作为内容节点内部子代理清单。
  - 验证：代码 review / 搜索。
- [ ] 确认 `workflow_defs.py` 是顺序权威来源。
  - 验收：文书生成流程顺序只需查看 `WorkflowRegistry` 即可理解。
  - 验证：workflow defs 测试。
- [ ] 运行 Phase 9 验证命令。
  - 验收：全量测试与编译通过。
  - 验证：`conda run -n autoGLM pytest && conda run -n autoGLM python -m compileall app tests`
