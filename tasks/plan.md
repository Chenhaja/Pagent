# 通用 LangChain Agent 与 Policy File Tools 实施计划

## 目标

基于 `SPEC.md`，把当前 `LangChainDraftingAgent` / `LangChainInputParserAgent` 收敛为一个通用 LangChain Agent runner，并配套通用 file tools 与 file policy。业务差异由 node/agent 参数表达：`node_name`、`agent_name`、prompt、`allowed_tools`、file policy、fallback 等。

## 当前代码观察

- 现有业务 Agent 类位于：
  - `app/tools/subagents/input_parser_agent.py`
  - `app/tools/subagents/drafting_agent.py`
- 现有调用点：
  - `app/nodes/drafting_research.py`：`DraftingParseInputNode`、`DraftingPatentSearchNode`
  - `app/nodes/drafting_content.py`：大纲、权利要求、说明书、附图、摘要、合并节点
- 现有工具构建问题：
  - input parser 通过 `_build_tools(source_key, attachments)` 内联构造 `read_source_artifact`、`write_parsed_info`、`file_extract`、`office_to_md`。
  - drafting 通过 `_build_tools()` 内联构造 `read_artifact`、`write_output_artifact`。
  - 权限逻辑散落在工具闭包中，尚未形成统一 policy 层。
- 可复用基础：
  - `DraftWorkspaceTool` 已提供 artifact read/write/list/merge 与基础安全 key 校验。
  - `WorkflowTraceAgentMiddleware` 已承接 create_agent middleware trace。
  - 现有测试已覆盖 fallback、middleware 传递、受限读写和不手写 wrapper trace。

## 依赖图

```text
SPEC.md
  -> file_policy.py
      -> file_tools.py
          -> agent_runner.py
              -> drafting_research.py 调用迁移
              -> drafting_content.py 调用迁移
                  -> 删除旧业务 Agent 类与导出
                      -> 测试迁移与安全回归
```

关键依赖：

1. `FileToolPolicy` 必须先存在，否则通用 file tools 无法在执行前校验路径。
2. 通用 file tools 必须先存在，否则 runner 无法用 `allowed_tools` 统一筛选工具。
3. 通用 runner 必须先完成，否则 node 无法脱离 `LangChainDraftingAgent` / `LangChainInputParserAgent`。
4. node 迁移完成后，才能删除旧业务 Agent 类。
5. 测试需随每个垂直切片同步迁移，避免最后一次性破坏大量调用点。

## 纵向切片原则

每个阶段都产出一条可验证路径，而不是只做一层抽象：

- 先让 policy 独立可测。
- 再让 file tool 通过 policy 读写 workspace。
- 再让 runner 把 wrapped tools 传给 `create_agent`。
- 再迁移一个真实 node 验证调用侧参数化。
- 最后批量迁移 drafting 内容节点并删除旧类。

## 阶段计划

### Phase 0 — 文档与基线确认

工作：

- 用本文件和 `tasks/todo.md` 固化实施顺序。
- 确认本阶段只做 read-only 规划，不实现代码。
- 记录最终验证命令和阶段检查点。

验收标准：

- `tasks/plan.md`、`tasks/todo.md` 与 `SPEC.md` 一致。
- 计划明确删除旧业务 Agent 类，不保留薄封装/命名工厂。

验证：

```bash
git status
```

检查点：用户审阅 plan/todo 后再进入实现。

---

### Phase 1 — 建立 FileToolPolicy 垂直切片

工作：

- 新增 `app/tools/subagents/file_policy.py`。
- 定义 `FileToolPolicy` / 相关结果或异常类型。
- 支持字段：`readRoots`、`writeRoots`、`allowGlobs`、`denyGlobs`。
- 路径统一转 POSIX 风格相对路径，拒绝空路径、绝对路径、`..`、逃逸 workspace 的路径。
- 判定顺序：normalize -> denyGlobs -> operation roots -> allowGlobs -> default deny。
- 写权限必须显式配置，不能由读权限推导。

验收标准：

- allow read/write 正常通过。
- 未显式允许读写时默认拒绝。
- `denyGlobs` 优先。
- `allowGlobs` 可细粒度收窄/补充。
- `../`、绝对路径、`.env`、`secrets/`、`*.pem`、`*.key` 被拒绝。

验证：

```bash
conda run -n autoGLM pytest tests/test_file_tool_policy.py
conda run -n autoGLM python -m compileall app tests
```

检查点：policy 语义稳定后再接入工具层。

---

### Phase 2 — 建立通用 file tools 垂直切片

工作：

- 新增 `app/tools/subagents/file_tools.py`。
- 基于 `DraftWorkspaceTool` 实现通用工具注册/构建能力。
- 至少实现当前迁移必需工具：
  - `read_file`：读取 policy 允许的 artifact。
  - `write_file`：写入 policy 允许的 artifact。
- 如成本低，可同时提供 `list_files`；`search_files` 可保留设计但不强行实现。
- 工具执行前调用 policy，而不是依赖 prompt 自律。
- 工具返回 JSON 字符串，错误受控，不泄露敏感路径细节。

验收标准：

- `read_file` 只能读取 policy 允许路径。
- `write_file` 只能写入 policy 允许路径。
- policy 拒绝时不调用 `DraftWorkspaceTool.run()` 访问真实文件系统/工作区。
- 工具名稳定，可被 runner 用 `allowed_tools` 筛选。

验证：

```bash
conda run -n autoGLM pytest tests/test_file_tool_policy.py tests/test_langchain_agent_runner.py
conda run -n autoGLM python -m compileall app tests
```

检查点：通用工具层通过后，再替换 runner `_build_tools`。

---

### Phase 3 — 建立通用 LangChainAgentRunner

工作：

- 新增 `app/tools/subagents/agent_runner.py`。
- 支持参数：
  - `node_name`
  - `stage`
  - `agent_name`
  - `prompt_name`
  - `system_prompt`
  - `allowed_tools`
  - `file_policy`
  - `output_artifact_key`
  - `fallback_builder`
  - `settings`
  - `workspace`
  - `workflow_trace_emitter`
- 复用现有网络开关、延迟导入 `create_agent` / `ChatOpenAI`、`WorkflowTraceAgentMiddleware`、fallback、短 observation 行为。
- 根据 `allowed_tools` 从通用工具注册表筛选工具，再传给 `create_agent`。
- 用户 prompt 中说明必须读取/写入的 artifact，但真实权限仍由 tool policy enforcing。

验收标准：

- LLM 不可用时离线 fallback 写入目标 artifact。
- fake `create_agent` 可捕获 tools，仅包含 `allowed_tools`。
- fake `create_agent` 可捕获 middleware，node/agent/stage 正确。
- policy 拒绝时 wrapped tool 不访问 workspace。
- observation 不返回长正文。

验证：

```bash
conda run -n autoGLM pytest tests/test_langchain_agent_runner.py tests/test_workflow_trace_events.py
conda run -n autoGLM python -m compileall app tests
```

检查点：runner 单独可用后，开始迁移真实 node。

---

### Phase 4 — 迁移 input parser 路径并删除专用 input parser Agent

工作：

- 将 `DraftingParseInputNode` 默认 runner 改为通用 `LangChainAgentRunner`。
- 通过 node 参数传入：
  - `node_name="drafting_parse_input"`
  - `agent_name="input_parser_agent"`
  - `prompt_name="INPUT_PARSER_PROMPT"`
  - `allowed_tools` 至少包含读取 source、写 parsed info 所需的通用 file tools。
  - file policy：读 `01_input/raw_document.md`，写 `01_input/parsed_info.json`。
- 保留 input parser 特有的 JSON 校验/fallback 逻辑，可放在 node 或 runner 的可注入验证步骤中，避免为了它保留业务 Agent 类。
- 处理 `file_extract` / `office_to_md`：若当前真实流程仍需要，作为后续专门受控 attachment tools 处理；本阶段不把任意本地路径纳入通用 file tools。
- 删除 `LangChainInputParserAgent` 类和直接测试依赖。

验收标准：

- `DraftingParseInputNode` 不再 import / 实例化 `LangChainInputParserAgent`。
- source artifact key 异常仍被拒绝。
- fallback 仍写合法 `01_input/parsed_info.json` JSON object。
- 写权限不能写到 parsed info 以外的 artifact。

验证：

```bash
conda run -n autoGLM pytest tests/test_input_parser_agent.py tests/test_drafting_research_nodes.py
conda run -n autoGLM pytest tests/test_workflow_trace_events.py
conda run -n autoGLM python -m compileall app tests
```

检查点：input parser 真实调用路径完成通用 runner 验证。

---

### Phase 5 — 迁移 drafting research/content 路径并删除 drafting Agent

工作：

- 将 `DraftingPatentSearchNode`、`DraftingGenerateOutlineNode`、`_SingleArtifactWriterNode`、`DraftingDescriptionWriterNode`、`DraftingMergeDocumentNode` 默认 runner 改为通用 `LangChainAgentRunner`。
- 为每个 node 构造明确 file policy：
  - read roots / allow globs 对应当前 `allowed_read_artifact_keys`。
  - write roots / allow globs 对应唯一输出 artifact 或 part artifact。
- 用 `allowed_tools=["read_file", "write_file"]` 替代 `allowed_read_artifact_keys + _build_tools`。
- 删除 `LangChainDraftingAgent` 类和直接测试依赖。

验收标准：

- `app/nodes/drafting_research.py`、`app/nodes/drafting_content.py` 不再 import / 实例化 `LangChainDraftingAgent`。
- 所有 drafting create_agent 节点仍能离线 fallback 产出目标 artifact。
- 每个 node 只能读取声明的输入 artifact、写声明的输出 artifact。
- trace middleware 行为保持。

验证：

```bash
conda run -n autoGLM pytest tests/test_drafting_agent.py tests/test_drafting_research_nodes.py tests/test_drafting_content_nodes.py
conda run -n autoGLM pytest tests/test_workflow_trace_events.py
conda run -n autoGLM python -m compileall app tests
```

检查点：旧业务 Agent 类删除前，确认所有调用点已迁移。

---

### Phase 6 — 清理导出、测试与安全回归

工作：

- 更新 `app/tools/subagents/__init__.py` 导出。
- 全仓搜索 `LangChainDraftingAgent` / `LangChainInputParserAgent`，确保只在历史文档或无关文本中出现；代码和测试不得依赖。
- 调整/新增测试：
  - `tests/test_file_tool_policy.py`
  - `tests/test_langchain_agent_runner.py`
  - 迁移后的 `tests/test_input_parser_agent.py`
  - 迁移后的 `tests/test_drafting_agent.py` 可重命名或改为 runner 测试。
- 安全回归确认 trace/log 不含敏感内容。

验收标准：

- 旧业务 Agent 类不可实例化使用。
- `allowed_tools` 未声明工具不会传给 `create_agent`。
- policy 拒绝优先，默认拒绝读写。
- 安全合规测试通过。

验证：

```bash
conda run -n autoGLM pytest tests/test_file_tool_policy.py tests/test_langchain_agent_runner.py
conda run -n autoGLM pytest tests/test_input_parser_agent.py tests/test_drafting_agent.py
conda run -n autoGLM pytest tests/test_security_compliance.py tests/test_workflow_trace_events.py
conda run -n autoGLM python -m compileall app tests
```

检查点：功能测试和安全测试均通过后再全量回归。

---

### Phase 7 — 全量回归与提交准备

工作：

- 运行全量测试与编译。
- 检查 diff，只包含 SPEC 对应改动。
- 按项目规范分阶段 commit；未经确认不 push。

验收标准：

- 全量测试通过。
- 编译通过。
- 工作区无无关改动、无临时文件、无密钥。

验证：

```bash
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests
git status
git diff
```

## 最终验证汇总

```bash
conda run -n autoGLM pytest tests/test_file_tool_policy.py tests/test_langchain_agent_runner.py
conda run -n autoGLM pytest tests/test_input_parser_agent.py tests/test_drafting_agent.py
conda run -n autoGLM pytest tests/test_drafting_research_nodes.py tests/test_drafting_content_nodes.py
conda run -n autoGLM pytest tests/test_workflow_trace_events.py tests/test_security_compliance.py
conda run -n autoGLM python -m compileall app tests
conda run -n autoGLM pytest
```
