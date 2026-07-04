# Pagent R11 专利文书生成规格说明

## 1. Objective

### 1.1 目标

在 Pagent 现有分层架构（接入层 → 归一化 → 意图路由 → 编排层 → 节点 → Skills/Tools）之上，新增 `patent_drafting` workflow，用于从技术交底书生成完整专利申请文件草稿（摘要 / 权利要求书 / 说明书 / 附图说明）。

核心目标：

- 先删除原 `claim_generation` / `claim_revision` 权利要求生成相关代码，确保无悬空引用、测试收集和编译通过。
- 新增 `patent_drafting` 意图与 workflow：`normalize_input → completeness_gate → drafting_leader`。
- 使用单个 `drafting_leader` 节点内的 bounded ReAct 编排，按 SOP 调用子代理工具。
- 对齐参考项目 PatentWriterBot 的范式：Leader + Subagent-as-Tool + SOP 驱动 + 按大纲逐节生成。
- 子代理产物以 Markdown 文本为主，通过 `draft_workspace` 暂存并用 key 传递，避免长正文反复进入 prompt。
- 新增 native tool 替代参考项目 MCP：`patent_search`、`skill_loader`、`draft_workspace`；不引入 MCP，不引入外部 agent 框架。
- 复用 R10 附件通道与现有 `office_to_md` / `file_extract` 作为文档解析能力。
- 权利要求与终稿合并保留 human-in-the-loop 挂点。

完成标准：

- 旧 `claim_generation` / `claim_revision` 节点、workflow、skill、prompt、测试和路由已删除，相关意图不再可路由。
- `intent_router` 能识别并路由 `patent_drafting`。
- `WorkflowRegistry` 注册 `patent_drafting` workflow。
- `drafting_leader` 在工具白名单、最大步数、token 预算和超时护栏内完成编排。
- 完整流程默认产出 `complete_patent_md`，包含摘要、权利要求书、说明书、附图说明。
- 子代理返回 Markdown 片段及最小元信息（`artifact_key` / `done` / 可选 `note`）。
- 新 native tool 离线可测，默认测试不访问真实网络和真实外部 LLM。
- `conda run -n autoGLM pytest` 与 `conda run -n autoGLM python -m compileall app tests` 通过。

### 1.2 目标用户

- 发明人 / 代理人：上传技术交底书后，一次性获得完整专利文书 Markdown 草稿。
- 开发与测试人员：可验证意图路由、SOP 编排、子代理调用顺序、预算护栏、防注入和 trace 脱敏。
- 后续开发者：可复用 Leader + Subagent-as-Tool 编排形态，扩展 OA 答复、说明书重写、权利要求优化等文书类任务。

### 1.3 非目标

- 不引入 MCP。
- 不引入 LangChain / LangGraph 等外部 agent 框架。
- 不保留旧权利要求 DAG 作为 fallback。
- 不做前端上传组件。
- 不做照片 / 图片视觉理解与原图嵌入。
- 不做 docx / pdf 终稿导出，本期只产出 Markdown。
- 不改变 R10 既有对外响应结构，只允许兼容新增字段。

---

## 2. Commands

项目使用 conda 环境 `autoGLM`。所有 Python / pytest / 脚本命令必须通过 `conda run -n autoGLM` 执行。

```bash
# 阶段 0：删除旧权利要求生成代码后验证
conda run -n autoGLM pytest tests/test_claim_code_removed.py
conda run -n autoGLM python -m compileall app tests

# 阶段 1：新 native tools
conda run -n autoGLM pytest tests/test_new_native_tools.py

# 阶段 2：子代理工具
conda run -n autoGLM pytest tests/test_subagent_tools.py

# 阶段 3：drafting leader 编排
conda run -n autoGLM pytest tests/test_drafting_leader.py

# 阶段 4：端到端 patent_drafting workflow
conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py

# 全量回归
conda run -n autoGLM pytest

# 编译检查
conda run -n autoGLM python -m compileall app tests
```

约束：

- 默认测试不触网、不调用真实外部 LLM。
- 联网集成测试必须标记 `@pytest.mark.network`，默认 skip。
- 不新增 MCP 或外部 agent 框架依赖。
- 如新增依赖，必须同步 `requirements.txt`。
- 不执行 `git push`、`git reset --hard`、强制推送等危险操作，除非用户明确确认。
- 每完成一个可独立验证阶段，应按项目规范单独提交。

---

## 3. Project Structure

目标结构：

```text
pagent/
  app/
    nodes/
      drafting_leader.py           # 新增：bounded ReAct Leader 节点
    tools/
      patent_search.py             # 新增：native 专利检索 tool
      skill_loader.py              # 新增：native 技能文档加载 tool
      draft_workspace.py           # 新增：native 文书中转暂存 tool
      subagents/
        __init__.py                # 新增：注册子代理工具
        base.py                    # 新增：SubagentTool 基类
        input_parser.py            # 新增：交底书解析为技术要点
        patent_searcher.py         # 新增：查新与区别特征梳理
        outline_generator.py       # 新增：说明书大纲生成
        abstract_writer.py         # 新增：摘要撰写
        claims_writer.py           # 新增：权利要求撰写，全新实现
        description_writer.py      # 新增：具体实施方式撰写
        diagram_generator.py       # 新增：附图说明与 Mermaid 描述
        markdown_merger.py         # 新增：合并完整文书
    prompts/
      patent_drafting_sop.py       # 新增：Leader SOP prompt
      subagents/                   # 新增：各子代理 prompt
    orchestrator/
      workflow_defs.py             # 修改：删除旧 workflow，新增 patent_drafting
      tool_registry.py             # 修改：注册 native tools 与子代理工具
    models/
      schemas.py                   # 修改：WorkflowState 新增文书 Markdown 字段
    api/
      schemas.py                   # 修改：兼容 intent=patent_drafting
  tests/
    test_claim_code_removed.py
    test_new_native_tools.py
    test_subagent_tools.py
    test_drafting_leader.py
    test_patent_drafting_workflow.py
  SPEC.md
```

### 3.1 删除旧权利要求生成代码

必须先删除：

- 节点：`app/nodes/feature_extract.py`、`claim_plan.py`、`claim_generate.py`、`claim_check.py`、`claim_revise.py`。
- Skill：`app/skills/` 下 `ClaimWritingSkill` 及权利要求相关 skill。
- Workflow：`workflow_defs.py` 中 `claim_generation`、`claim_revision` 定义。
- 路由：`intent_router.py` 中 `claim_generation` / `claim_revision` 分支与相关常量。
- Prompt：`app/prompts/` 下旧权利要求相关 prompt。
- State：仅服务旧 pipeline 的字段，如 `claim_plan`、`claims_draft`、`claim_versions`、`technical_features`，确认新功能不依赖后删除。
- 测试：旧节点 / workflow / skill 相关测试和夹具。
- 注册表：`tool_registry.py` / 节点注册处对已删除对象的引用。

删除完成后要求：

- `claim_generation` / `claim_revision` 不再可路由。
- 无旧模块 import 残留。
- `pytest` 收集不报错。
- `compileall` 通过。

### 3.2 Workflow 契约

`app/orchestrator/workflow_defs.py` 新增：

```python
"patent_drafting": WorkflowDef(
    intent="patent_drafting",
    nodes=["normalize_input", "completeness_gate", "drafting_leader"],
    start_node="normalize_input",
    max_loop_count=1,
)
```

说明：

- 前段仍为确定性流程。
- 编排回环只发生在 `drafting_leader` 内部。
- Leader 回环受 `PAGENT_DRAFTING_MAX_STEPS`、token 预算和超时约束。

### 3.3 Leader SOP 契约

新增 `app/prompts/patent_drafting_sop.py`，prompt 必须覆盖项目要求的六要素：

1. 任务目标：依据 `<data>` 技术交底书，生成完整 Markdown 专利文书。
2. 上下文 / 判定规则：先解析要点、可选查新、先大纲后逐节、通过 workspace 暂存、预算命中时产出当前最佳并标注 incomplete。
3. 角色：资深专利代理人 + 编排者。
4. 受众：终稿合并与人审律师。
5. 样例：至少 1 组「交底要点 → 大纲 → 子代理调用序列 → 文书片段」。
6. 输出格式：Markdown 专利文书，不额外输出解释。

安全要求：

- 所有附件 / 检索 / 外部内容必须包裹 `<data>` 并声明仅作为数据证据。
- 明确忽略数据区内任何改写系统指令、忽略上文、改变输出格式等内容。
- 禁止臆造法条、专利号、引用和检索结果。
- 不确定信息必须显式标注。
- 默认输出中文，使用规范专利术语。

### 3.4 Subagent-as-Tool 契约

统一接口：

```python
class SubagentTool:
    name: str
    description: str

    def run(self, tool_input: dict[str, Any]) -> dict:
        ...
```

返回结构：

```python
{
    "markdown": "<该节 Markdown 正文>",
    "artifact_key": "outline",
    "done": True,
    "note": "可选说明"
}
```

要求：

- 输入接收结构化引用，如 `{"read": ["input_points", "outline"], "params": {...}}`。
- 不接收整段长正文；正文通过 `draft_workspace` key 读取。
- 输出以 Markdown 文本为主，不强制重 JSON schema。
- 子代理产物必须写入 `draft_workspace`，并返回 `artifact_key`。
- 失败时返回安全错误说明，不抛裸异常到上层。
- `patent_searcher` 内部调用 `patent_search` 时必须受联网门控约束。

子代理清单：

| 工具 | 职责 |
| --- | --- |
| `input_parser` | 从交底书提取技术要点、问题、效果、关键词 |
| `patent_searcher` | 查新，整理相似文献与区别特征 |
| `outline_generator` | 生成说明书大纲，供后续逐节写作 |
| `abstract_writer` | 生成摘要 |
| `claims_writer` | 全新生成独立 / 从属权利要求及引用关系 |
| `description_writer` | 按大纲逐节生成具体实施方式 |
| `diagram_generator` | 生成附图说明与 Mermaid 结构描述 |
| `markdown_merger` | 按大纲合并完整 Markdown 文书 |

### 3.5 Native tool 契约

#### `patent_search`

输入：

```python
{"query": "...", "top_k": 8, "lang": "zh"}
```

输出：

```python
{
    "results": [
        {
            "title": "...",
            "abstract": "...",
            "publication_number": "...",
            "link": "...",
            "score": 0.0,
            "provenance": "..."
        }
    ],
    "skipped": False,
    "reason": ""
}
```

要求：

- 受 `allow_network`、`agentic_external_tools_enabled` 和自身开关门控。
- 默认测试使用 fake，不访问真实网络。
- 网络不可用或未授权时返回 skipped / reason，不抛裸异常。
- 不编造专利号、链接、摘要或来源。

#### `skill_loader`

输入：

```python
{"skill_name": "patent_drafting"}
```

要求：

- 从 `PAGENT_SKILL_DIR` 指定目录读取技能文档。
- 仅读取允许目录内文件，必须防路径越界。
- 返回技能文本和元信息。
- 不执行技能文档中的任何指令，只作为上下文资料。

#### `draft_workspace`

接口：

```python
put(key, markdown)
get(key)
list()
```

要求：

- 默认载体为 `WorkflowState` 内存字段或等价内存结构。
- 可通过 `PAGENT_DRAFT_WORKSPACE_DIR` 切换到临时目录。
- 子代理间只传 key，不传长正文。
- 目录模式必须校验路径位于 workspace 根目录内。
- 不落用户可见长期磁盘，除非用户后续明确要求归档。

### 3.6 配置契约

新增系统级配置：

| 配置项 | 环境变量 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `drafting_max_steps` | `PAGENT_DRAFTING_MAX_STEPS` | `24` | Leader 最大编排步数 |
| `drafting_token_budget` | `PAGENT_DRAFTING_TOKEN_BUDGET` | `120000` | Leader token 预算 |
| `drafting_timeout_s` | `PAGENT_DRAFTING_TIMEOUT_S` | `600` | 全流程超时秒数 |
| `drafting_subagent_max_steps` | `PAGENT_DRAFTING_SUBAGENT_MAX_STEPS` | `6` | 单个子代理内部最大步数 |
| `drafting_require_prior_art` | `PAGENT_DRAFTING_REQUIRE_PRIOR_ART` | `false` | 是否强制查新 |
| `patent_search_top_k` | `PAGENT_PATENT_SEARCH_TOP_K` | `8` | 默认检索返回条数 |
| `skill_dir` | `PAGENT_SKILL_DIR` | `app/skills` | 技能文档目录 |
| `draft_workspace_dir` | `PAGENT_DRAFT_WORKSPACE_DIR` | `""` | 空表示使用内存 workspace |

要求：

- 配置保持系统级通用作用域。
- 新增配置必须同步 `Settings` 默认值、环境变量读取、`to_public_dict()` 和测试。
- 非敏感配置可进入 `to_public_dict()`。
- 不使用 `arg or settings.xxx`，必须使用 `settings.xxx if arg is None else arg`。
- 不把 API Key、token、secret 写入公开配置、日志或 trace。

### 3.7 WorkflowState 契约

`app/models/schemas.py` 中 `WorkflowState` 新增：

```python
input_points_md: str = ""
prior_art_md: str = ""
outline_md: str = ""
abstract_md: str = ""
claims_md: str = ""
description_md: str = ""
figures_md: str = ""
complete_patent_md: str = ""
drafting_incomplete: bool = False
```

要求：

- 不引入严格 `PatentDocument` JSON schema。
- Markdown 为主要产物形态。
- `documents[*].text` 仍只作为 `<data>` 证据。
- 附件正文不得并入 `raw_input`。
- 未经人审通过的 `complete_patent_md` 不得写入长期记忆或案件归档。

### 3.8 Trace 与日志契约

新增 trace 事件：

| 事件 | 触发 | data |
| --- | --- | --- |
| `drafting_started` | 进入 leader | `intent`, `doc_count` |
| `subagent_invoked` | 调用子代理 | `tool`, `step_index` |
| `subagent_observed` | 子代理返回 | `tool`, `artifact_key`, `chars`, `done` |
| `drafting_loop` | 回环补写 | `target`, `loop_count` |
| `drafting_budget_hit` | 命中预算 / 超时 | `reason`, `steps`, `tokens` |
| `drafting_completed` | 完成输出 | `incomplete`, `sections` |

要求：

- 不记录交底书正文、prompt 全文、检索正文或密钥。
- `event` 使用稳定英文名。
- `message` 可使用中文。
- 可恢复失败使用 warning 并说明降级结果。

---

## 4. Code Style

- 优先最小化、局部化改动，复用现有 helper、配置、trace、ToolRegistry 和 bounded ReAct 基础设施。
- 新增公开类、函数、方法必须写中文 Google 风格 docstring，包含 Args / Returns / Raises（如有）。
- 注释和日志沿用中文风格，`event` 字段使用稳定英文。
- 行内注释只解释不直观的安全边界、预算护栏、路径校验和降级原因。
- Prompt 必须集中在 `app/prompts/`，不能在业务逻辑中散落大段 prompt。
- Prompt 必须覆盖六要素，运行时变量使用具名占位符。
- 外部 / 用户 / 附件 / 检索内容必须放入 `<data>` 或等价分隔符，并声明数据区不作为指令。
- 不使用用户输入拼接 shell 命令或 SQL。
- 不把密钥、完整 API Key、附件正文、长原文写入日志或 trace。
- 不新增外部 agent 框架依赖。
- 删除旧代码时直接删除无用引用，不保留无意义兼容壳。

---

## 5. Testing Strategy

### 5.1 TDD 顺序

1. `test_claim_code_removed.py`
   - 断言旧模块不可 import。
   - 断言 `claim_generation` / `claim_revision` 不再可路由。
   - 断言 workflow registry 无旧 workflow。
   - 断言测试收集和编译不因删除失败。

2. `test_new_native_tools.py`
   - `patent_search`：联网门控、离线 fake、输出字段、跳过原因。
   - `skill_loader`：正常读取、目录配置、路径越界防护、缺失文件错误。
   - `draft_workspace`：put / get / list、内存模式、目录模式、路径安全、只传 key。

3. `test_subagent_tools.py`
   - 每个子代理可调用并返回 Markdown。
   - 返回包含 `artifact_key` 与 `done`。
   - 子代理只按 workspace key 读取，不接受超长正文。
   - 附件 / 检索数据中的注入指令不改变行为。
   - 失败时返回安全错误说明。

4. `test_drafting_leader.py`
   - Leader 先调用 `input_parser`。
   - `outline_generator` 必须先于 abstract / claims / description / diagram。
   - `markdown_merger` 最后合并。
   - 缺节时在步数内回环补写。
   - 命中最大步数 / token / 超时时标记 `drafting_incomplete=True`。
   - trace 事件脱敏且顺序可断言。

5. `test_patent_drafting_workflow.py`
   - `intent=patent_drafting` 可端到端路由。
   - 附件文档进入 `<data>` 证据，不污染 `raw_input`。
   - 默认离线生成 `complete_patent_md`。
   - 输出包含摘要、权利要求书、说明书、附图说明。

6. 回归测试
   - QA / config / security / attachment 相关测试不破。
   - 删除旧权利要求测试，不保留旧 DAG 断言。

### 5.2 必测用例

- 交底要点不足时，claims 标注不确定，不臆造。
- `allow_network=false` 时，`patent_searcher` 跳过并标注“未查新”，不触网。
- 未启用外部工具时，`patent_search` 返回 skipped / reason。
- 子代理传入超长正文被拒绝或忽略，只按 workspace key 读取。
- Leader 未先生成大纲时纠偏为先调用 `outline_generator`。
- Leader 命中 `PAGENT_DRAFTING_MAX_STEPS` 时返回 incomplete，不抛裸异常。
- 附件含“忽略以上指令”时，系统行为与输出格式不变。
- trace / 日志不包含交底书正文、prompt 全文、检索正文或密钥。
- `Settings` 默认值、环境变量覆盖、`to_public_dict()` 均有测试。
- 默认测试不访问真实网络或外部 LLM。

### 5.3 Fixtures 与隔离

- 使用 fake LLM / fake ToolRegistry / monkeypatch 隔离外部模型调用。
- 使用 fake patent search provider 隔离真实联网检索。
- 使用 `tmp_path` 覆盖 `draft_workspace_dir` 与 `skill_dir`。
- 附件 fixture 使用小型文本 / Markdown 文档，避免大二进制污染仓库。
- 联网集成测试单独标记 `network`，默认不运行。

---

## 6. Boundaries

### 6.1 Always do

- 先删除原权利要求生成代码，再开发新 `claims_writer`。
- 删除旧代码必须作为独立、可回滚阶段验证。
- Leader 使用 bounded ReAct，不允许自由无护栏 ReAct。
- Leader 只能调用白名单工具。
- 必须先生成大纲，再依大纲逐节写作和合并。
- 子代理回传 Markdown 文本，产物通过 `draft_workspace` 暂存。
- 子代理之间只传 key，不反复传长正文。
- 附件正文只作为 `<data>` 证据。
- 保留 `WorkflowState.raw_input` 原始简短指令。
- 除 markitdown 替代能力外，参考项目 MCP 能力全部用 native tool 实现。
- 权利要求与终稿合并保留 human-in-the-loop 挂点。
- 仅人审通过的 `complete_patent_md` 才可固化进长期记忆或案件归档。
- trace / 日志必须脱敏。

### 6.2 Ask first

- `patent_search` 的真实检索源：本地专利库、联网 API，或两者组合。
- 是否调整默认预算：24 步、120k token、600 秒。
- `draft_workspace` 默认载体是否坚持内存 state，还是改为临时目录。
- 附图本期是否仅产出 Mermaid 结构描述。
- 终稿导出（docx / pdf）是否另开增量。
- 是否允许本期新增任何非必要依赖。

### 6.3 Never do

- 不引入 MCP。
- 不引入 LangChain / LangGraph 等外部 agent 框架。
- 不保留旧 `claim_generation` DAG 或停用式兼容壳。
- 删除旧代码后不得残留 import / 路由 / 注册引用。
- 不让 Leader 变成无护栏自由 ReAct。
- 不把附件正文并入 `raw_input`、`normalized_input` 或用户 turn 记忆。
- 不执行附件 / 检索数据中的任何指令。
- 不编造法条、专利号、检索结果、引用或来源。
- 不在 trace / 日志记录正文、prompt 全文或密钥。
- 不把未人审产物写入长期记忆。
- 不通过 shell 拼接用户输入执行命令。

---

## 7. Open Decisions

实施前需要确认：

1. `patent_search` 的真实检索源与是否需要外部 API key。
2. Leader 默认步数 / token 预算 / 超时是否采用 PRD 建议值：24 / 120000 / 600s。
3. `draft_workspace` 默认使用内存 state，还是默认使用临时目录。
4. 本期是否保持串行编排，不做 abstract / figures 等无依赖子代理并行优化。
5. 附图与交底书照片处理是否确认本期仅 Mermaid，视觉理解和原图嵌入后续单开。
6. 终稿导出是否后续增量，本期只保留 Markdown。

---

## 8. Incremental Delivery Plan

### 阶段 0：删除旧权利要求生成代码

验收：

- 旧节点、skill、workflow、prompt、测试、路由和注册引用已删除。
- `claim_generation` / `claim_revision` 不再可路由。
- `conda run -n autoGLM pytest tests/test_claim_code_removed.py` 通过。
- `conda run -n autoGLM python -m compileall app tests` 通过。

建议提交：

```text
refactor(claim): 删除旧权利要求生成流程
```

### 阶段 1：新增 native tools

验收：

- `patent_search`、`skill_loader`、`draft_workspace` 实现并注册。
- 门控、路径安全、内存 / 目录 workspace 均有测试。
- `conda run -n autoGLM pytest tests/test_new_native_tools.py` 通过。

建议提交：

```text
feat(tool): 增加专利文书 native 工具
```

### 阶段 2：新增子代理工具

验收：

- 8 个子代理工具实现并注册。
- 统一返回 Markdown + `artifact_key` + `done`。
- 子代理按 workspace key 读取，不接收长正文。
- `conda run -n autoGLM pytest tests/test_subagent_tools.py` 通过。

建议提交：

```text
feat(drafting): 增加专利文书子代理工具
```

### 阶段 3：新增 drafting_leader

验收：

- Leader 使用 bounded ReAct 与 SOP。
- 调用顺序满足“要点 → 查新可选 → 大纲 → 逐节 → 合并”。
- 预算命中时产出当前最佳并标记 incomplete。
- trace 事件脱敏。
- `conda run -n autoGLM pytest tests/test_drafting_leader.py` 通过。

建议提交：

```text
feat(drafting): 增加专利文书编排节点
```

### 阶段 4：接入 workflow 与端到端

验收：

- `intent_router`、`WorkflowRegistry`、`WorkflowState`、API schema 兼容接入。
- `intent=patent_drafting` 端到端产出 `complete_patent_md`。
- 全量测试和编译通过。

建议提交：

```text
feat(drafting): 接入专利文书生成流程
```
