# 专利文书 workflow create_agent 拓扑改造计划

## 目标

将 patent drafting workflow 从旧的线性/gate/聚合节点流程，调整为显式业务节点链路：输入解析、检索、大纲、权利要求、说明书、附图、摘要、终稿合并、最终回填。

## 边界

- 用线性 workflow 顺序近似 SPEC 的 DAG，不改 orchestrator 内核。
- 旧节点类可先保留，但不再进入新 `patent_drafting` 主流程。
- `DraftingPatentSearchNode` 负责补齐 `02_research/prior_art_analysis.json` 兼容 artifact，避免 finalize 缺字段。
- 不改 QA workflow。
- 不改变最终 API 输出字段语义。
- 不新增依赖，除非另行确认。
- 默认测试必须离线可运行。
- 不执行 push、reset、force push。

## 目标拓扑

```text
normalize_input
→ drafting_parse_input
→ drafting_patent_search
→ drafting_generate_outline
→ drafting_claims_writer
→ drafting_description_writer
→ drafting_diagram_generator
→ drafting_abstract_writer
→ drafting_merge_document
→ drafting_finalize
```

## Artifact 目标

```text
DraftingParseInputNode
  writes: 01_input/raw_document.md, 01_input/parsed_info.json

DraftingPatentSearchNode
  reads:  01_input/parsed_info.json
  writes: 02_research/patent_search_results.json
          02_research/prior_art_analysis.json

DraftingGenerateOutlineNode
  reads:  01_input/parsed_info.json
          02_research/patent_search_results.json
          02_research/prior_art_analysis.json
  writes: 03_outline/patent_outline.md

DraftingClaimsWriterNode
  reads:  parsed/search/prior_art/outline
  writes: 04_content/claims.md

DraftingDescriptionWriterNode
  reads:  parsed/search/prior_art/outline/claims
  writes: 04_content/description_part1.md
          04_content/description_part2.md
          04_content/description.md

DraftingDiagramGeneratorNode
  reads:  parsed/outline/description
  writes: 04_content/figures.md

DraftingAbstractWriterNode
  reads:  claims/description
  writes: 04_content/abstract.md

DraftingMergeDocumentNode
  reads:  abstract/claims/description/figures
  writes: 05_final/complete_patent.md
          05_final/review_report.json

DraftingFinalizeNode
  reads:  DRAFTING_FINALIZE_FIELDS 中的 artifact
  writes: WorkflowState 兼容 API 字段
```

## 阶段计划

### Phase 0 — 执行文档

- 更新 `tasks/plan.md` 和 `tasks/todo.md`。
- 记录目标拓扑、边界、验收标准、验证命令和阶段检查点。

验收：文档存在且内容匹配本次拓扑改造。

验证：

```bash
git status
```

### Phase 1 — 通用 drafting create_agent runner

- 新增或扩展 `app/tools/subagents/drafting_agent.py`。
- 复用 input parser runner 模式：网络开关、延迟导入、受控 artifact tools、`WorkflowTraceAgentMiddleware`、fallback、短 observation。
- 支持节点传入 `node_name`、`stage`、`agent_name`、`prompt_name`、`system_prompt`、允许读取 artifact、输出 artifact、fallback builder。

验收：离线 fallback 可写 artifact；fake create_agent 可验证 middleware；工具读写受 allowlist 限制；不返回长正文。

验证：

```bash
conda run -n autoGLM pytest tests/test_input_parser_agent.py tests/test_workflow_trace_events.py
conda run -n autoGLM python -m compileall app tests
```

### Phase 2 — 改造 DraftingPatentSearchNode

- 默认使用 `PATENT_SEARCHER_PROMPT + create_agent runner`。
- 支持 fake runner / fake registry 注入。
- 写 `02_research/patent_search_results.json` 与 `02_research/prior_art_analysis.json`。
- 检索不足时显式 uncertain，不编造专利号、来源或证据。
- 汇总 middleware trace 到 `NodeResult.trace_events`。

验收：默认路径使用 runner；离线 fallback 可跑；prior_art artifact 不缺失；trace 不泄露长正文或敏感字段。

验证：

```bash
conda run -n autoGLM pytest tests/test_drafting_research_nodes.py
conda run -n autoGLM pytest tests/test_workflow_trace_events.py
conda run -n autoGLM python -m compileall app tests
```

### Phase 3 — 拆分内容生成节点

- 改造 `DraftingGenerateOutlineNode` 使用 `OUTLINE_GENERATOR_PROMPT + create_agent`。
- 新增 `DraftingClaimsWriterNode`。
- 新增 `DraftingDescriptionWriterNode`，内部串行 Part1 / Part2。
- 新增 `DraftingDiagramGeneratorNode`。
- 新增 `DraftingAbstractWriterNode`。
- `DraftingGenerateSectionsNode` 保留类定义，但从新 workflow 移除。

验收：显式内容节点都能离线生成目标 artifact；NodeResult.output 只返回短字段；不依赖旧 drawing/style guide 节点。

验证：

```bash
conda run -n autoGLM pytest tests/test_drafting_content_nodes.py tests/test_patent_drafting_workflow.py
conda run -n autoGLM pytest tests/test_workflow_trace_events.py
conda run -n autoGLM python -m compileall app tests
```

### Phase 4 — 改造 DraftingMergeDocumentNode

- 默认使用 `MARKDOWN_MERGER_PROMPT + create_agent`。
- 读取 abstract / claims / description / figures。
- 写 `05_final/complete_patent.md` 和可选 `05_final/review_report.json`。
- 保留确定性拼接 fallback。

验收：merge 默认 create_agent，fallback 离线可拼接完整文书；输出 complete_patent_key 稳定；不改变 finalize API 字段语义。

验证：

```bash
conda run -n autoGLM pytest tests/test_drafting_content_nodes.py tests/test_patent_drafting_workflow.py
conda run -n autoGLM pytest tests/test_workflow_trace_events.py
conda run -n autoGLM python -m compileall app tests
```

### Phase 5 — 更新 workflow 拓扑和服务注册

- 更新 `app/orchestrator/workflow_defs.py` 的 `patent_drafting` 节点顺序。
- 将 `max_loop_count` 调整为 `0`。
- 更新 `AgentDispatchService._run_patent_drafting()` 注册新节点。
- 不改 translation / QA workflow。

验收：workflow registry 返回新节点列表；主流程不包含旧 gate/guidance/sections/review；API 字段兼容。

验证：

```bash
conda run -n autoGLM pytest tests/test_drafting_workflow_defs.py tests/test_workflow_registry.py
conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py tests/test_agent_api.py
conda run -n autoGLM pytest tests/test_orchestrator_engine.py
conda run -n autoGLM python -m compileall app tests
```

### Phase 6 — trace、安全、离线回归

- 为新增 create_agent 节点补 trace 断言。
- 断言 trace 不包含 prompt 全文、长正文、本地路径、API key、token、secret、password。
- 断言默认离线 fallback 可运行。
- 检查 prompt 集中在 `app/prompts/subagents/`。

验收：安全合规测试通过；默认测试不触网；没有新增依赖。

验证：

```bash
conda run -n autoGLM pytest tests/test_input_parser_agent.py tests/test_workflow_trace_events.py
conda run -n autoGLM pytest tests/test_drafting_research_nodes.py tests/test_drafting_content_nodes.py
conda run -n autoGLM pytest tests/test_security_compliance.py
conda run -n autoGLM python -m compileall app tests
```

### Phase 7 — 全量回归与清理

- 清理未使用 imports。
- 确认旧节点类未被新 workflow 或服务注册误用。
- 确认 finalize 所需 artifact 都由新流程产出。
- 确认 QA workflow 无改动。
- 全量 pytest 和 compileall。
- 按项目规范分阶段提交；未经确认不 push。

验收：全量测试和编译通过；diff 只包含本需求相关改动。

验证：

```bash
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests
git status
git diff
```

## 最终验证汇总

```bash
conda run -n autoGLM pytest tests/test_drafting_research_nodes.py
conda run -n autoGLM pytest tests/test_drafting_content_nodes.py tests/test_patent_drafting_workflow.py
conda run -n autoGLM pytest tests/test_drafting_workflow_defs.py tests/test_workflow_registry.py
conda run -n autoGLM pytest tests/test_input_parser_agent.py tests/test_workflow_trace_events.py
conda run -n autoGLM pytest tests/test_security_compliance.py tests/test_orchestrator_engine.py
conda run -n autoGLM python -m compileall app tests
conda run -n autoGLM pytest
```
