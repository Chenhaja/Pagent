# Pagent R12 专利文书生成工具缺口修复规格说明

## 1. Objective

### 1.1 目标

在 R11 已接入 `patent_drafting` workflow 的基础上，修复专利文书生成链路中“已注册但未真正实现”的能力缺口，使专利文书生成从占位骨架升级为可由 Leader 编排、子代理真实调用 LLM、按项目工作区流转文件、按参考项目 Prompt 规范执行的完整实现。

核心目标：

- 增强 `draft_workspace`：从扁平 `{key}.md` 升级为项目工作区，支持 `temp_[uuid]/01_input ... 05_final` 标准目录、相对路径 key、`list` 与 `merge` 动作，并默认使用内存 key-store。
- 将子代理工具从“读源文件并加标题”的空壳改为真正的 subagent：每个子代理使用独立 role SOP prompt、可调用受限工具、产物写回 workspace，只返回 `{artifact_key, done}` 等短结果。
- 将 `patent_search` 从 stub 改为基于 SerpAPI 的真实检索工具：按关键词检索、优先 CN、GRANT、Top-K，并受联网门控控制，离线时安全降级。
- 将 `skill_loader` 从读取 Python 源码改为读取 Markdown 技能 / SOP 文档，与 `app/skills/*.py` 可执行 Skill 类解耦。
- 自研 TodoList 规划中间件与 `write_todos` 工具，给 Leader 与全部子代理提供独立 todo 状态和上下文注入。
- 按 R12 PRD §4 原文落地 Leader 与 9 个子代理 Prompt，仅允许做工具名等价替换，不自行改写语义。
- 将现有 8 个子代理定义调整为参考项目一致的 9 个环节：拆分 `description_writer_part1` 与 `description_writer_part2`。

完成标准：

- `draft_workspace` 支持 `write` / `read` / `list` / `merge`，支持项目目录结构，默认内存模式，`PAGENT_DRAFT_WORKSPACE_DIR` 非空时落盘，保留 key 白名单与防路径逃逸。
- `skill_loader` 只从 `PAGENT_SKILL_DIR` 指定的 Markdown 技能文档目录读取白名单文档，不读取 Python 源码。
- `patent_search` 在联网授权时使用 SerpAPI 作为真实检索后端；未配置 SerpAPI Key、未授权联网或后端不可用时返回可解释的 skipped / degraded 结果，不编造检索结果。
- Leader 与每个子代理均可使用独立 todo 列表，通过 `write_todos` 更新，当前 todo 状态会注入后续上下文。
- 子代理工具会调用 LLM，并按角色限制可用工具。
- Prompt 常量集中放入 `app/prompts/`，内容与 R12 PRD §4 保持语义一致。
- `description_writer_part1` / `description_writer_part2` 均存在并注册，完整执行顺序与 R12 PRD 一致。
- 默认测试不访问真实网络、不调用真实外部 LLM；真实检索集成测试需显式标记并默认跳过。
- `conda run -n autoGLM pytest` 与 `conda run -n autoGLM python -m compileall app tests` 通过。

### 1.2 目标用户

- 发明人 / 代理人：上传技术交底书后，获得完整专利申请文件 Markdown 草稿，包括摘要、权利要求书、说明书、说明书附图与评审报告。
- 专利文书生成链路维护者：可验证工具真实能力、子代理 prompt、工作区流转、todo 规划、检索降级与日志脱敏。
- 后续开发者：可基于 Leader + Subagent-as-Tool + 项目工作区模式扩展其他专利文书任务。

### 1.3 非目标

- 不引入 MCP。
- 不引入 LangChain / LangGraph 等外部 agent 框架。
- 不把 `parsed_info` 强制改为结构化 schema；默认继续保持参考项目的软约定，可选增强另开。
- 不实现 docx / pdf 终稿导出，本期仍以 Markdown 为主。
- 不实现图像视觉理解或原始图片嵌入。
- 不在默认测试中访问真实网络或真实外部 LLM。
- 不把未人审专利文书写入长期记忆或案件归档。

---

## 2. Commands

项目使用 conda 环境 `autoGLM`。所有 Python / pytest / 脚本命令必须通过 `conda run -n autoGLM` 执行。

```bash
# 单项：draft_workspace 工作区增强
conda run -n autoGLM pytest tests/test_draft_workspace.py

# 单项：skill_loader Markdown 技能文档加载
conda run -n autoGLM pytest tests/test_skill_loader.py

# 单项：patent_search 检索门控与降级
conda run -n autoGLM pytest tests/test_patent_search.py

# 单项：write_todos / TodoList 中间件
conda run -n autoGLM pytest tests/test_todo_middleware.py

# 单项：子代理工具与 prompt 注册
conda run -n autoGLM pytest tests/test_subagent_tools.py

# 单项：drafting leader 编排
conda run -n autoGLM pytest tests/test_drafting_leader.py

# 端到端专利文书生成回归
conda run -n autoGLM pytest tests/test_patent_drafting_workflow.py

# 全量回归
conda run -n autoGLM pytest

# 编译检查
conda run -n autoGLM python -m compileall app tests
```

约束：

- 默认测试不得触网、不得调用真实外部 LLM。
- 联网真实检索测试必须使用 `@pytest.mark.network` 或等价标记，默认 skip。
- 如新增依赖，必须同步更新 `requirements.txt`。
- 不执行 `git push`、`git reset --hard`、强制推送等危险操作，除非用户明确确认。
- 每完成一个可独立验证阶段，按项目规范单独提交。

---

## 3. Project Structure

目标结构：

```text
pagent/
  app/
    prompts/
      patent_drafting_leader.py          # R12 Leader Prompt 原文常量
      todo.py                 # write_todos sys_prompt / tool_prompt 原文常量
      subagents/
        input_parser_prompt.py
        patent_searcher_prompt.py
        outline_generator_prompt.py
        abstract_writer_prompt.py
        claims_writer_prompt.py
        description_writer_part1_prompt.py
        description_writer_part2_prompt.py
        diagram_generator_prompt.py
        markdown_merger_prompt.py
    tools/
      draft_workspace.py                 # 增强：项目工作区、list、merge、内存/磁盘模式
      patent_search.py                   # 增强：SerpAPI 检索后端 + 联网门控 + 离线降级
      skill_loader.py                    # 增强：读取 Markdown 技能文档，不读 Python 源码
      todo.py                 # 新增：write_todos 工具与 todo 状态维护
      subagents/
        __init__.py                      # 注册 9 个子代理定义
        base.py                          # 如需拆分：LLM 子代理通用执行逻辑
    skills_docs/                         # 新增或配置：Markdown 技能 / SOP 文档目录
      patent_drafting.md
      mermaid.md
    nodes/
      drafting_leader.py                 # 接入 workspace / todo / subagent 编排
    orchestrator/
      tool_registry.py                   # 注册增强后的 native tools 与子代理工具
    models/
      schemas.py                         # 如需：workspace / todo 状态字段
    config.py                            # 如需：新增配置项与 env 读取
  tests/
    test_draft_workspace.py
    test_skill_loader.py
    test_patent_search.py
    test_todo.py
    test_subagent_tools.py
    test_drafting_leader.py
    test_patent_drafting_workflow.py
  SPEC.md
```

### 3.1 `draft_workspace` 契约

#### 动作

- `write`：写入 artifact。
- `read`：读取 artifact。
- `list`：枚举 workspace 下目录和 artifact，供 Leader 审查缺失文件。
- `merge`：按顺序合并多个 artifact 为一个 artifact，供 `description_writer_part2` 与 `markdown_merger` 使用。

#### 项目工作区

每个专利项目必须具备以下逻辑目录结构：

```text
temp_[uuid]/
  01_input/
    raw_document.docx
    parsed_info.json
  02_research/
    prior_art_analysis.md
    abstract_writing_style.md
    claims_writing_style.md
    description_writing_style.md
  03_outline/
    patent_outline.md
  04_content/
    abstract.md
    claims.md
    description.md
    figures.md
  05_final/
    complete_patent.md
    summary_report.md
```

要求：

- artifact 使用相对路径 key，例如 `04_content/abstract.md`。
- 默认使用内存 key-store。
- `PAGENT_DRAFT_WORKSPACE_DIR` 非空时使用磁盘落盘。
- 保留 key 白名单校验、防路径逃逸、内容截断能力。
- 长正文只通过 workspace 读写；Leader 与子代理入参只传 key / 路径。
- `merge` 必须按输入顺序合并，输出写回指定 key。

### 3.2 `skill_loader` 契约

输入示例：

```python
{"skill_name": "patent_drafting"}
```

要求：

- 从 `PAGENT_SKILL_DIR` 指向的独立 Markdown 技能文档目录读取。
- 只允许读取白名单技能文档，例如 `patent_drafting`、`mermaid`。
- 不读取 `app/skills/*.py`，不把可执行 Skill 类源码作为技能内容。
- 防止路径穿越。
- 返回技能文档正文与元信息。
- 技能文档内容只作为上下文资料，不作为高优先级指令执行。

### 3.3 `patent_search` 契约

输入示例：

```python
{
  "query": "技术关键词",
  "top_k": 10,
  "country": "CN",
  "status": "GRANT"
}
```

输出示例：

```python
{
  "results": [
    {
      "title": "...",
      "publication_number": "...",
      "abstract": "...",
      "url": "...",
      "country": "CN",
      "status": "GRANT",
      "score": 0.0,
      "provenance": "..."
    }
  ],
  "sufficient": true,
  "skipped": false,
  "reason": ""
}
```

要求：

- 对齐参考项目 `google_patent_search` 用途：通过 SerpAPI 执行关键词检索、优先 CN、GRANT、Top-K。
- 受联网门控与 SerpAPI Key 配置控制；离线、未授权或未配置 Key 时返回 `skipped=True` / `sufficient=False` / `reason`。
- SerpAPI Key 必须从环境变量 / 配置读取，不得硬编码，不得进入日志、trace 或公开配置。
- 不编造专利号、链接、摘要、授权状态或来源。
- 默认测试使用 fake provider，不触网。

### 3.4 TodoList 中间件契约

#### `write_todos` 工具

输入为完整 todo 列表：

```python
{
  "todos": [
    {"text": "解析输入文档", "status": "pending"},
    {"text": "生成专利大纲", "status": "in_progress"},
    {"text": "合并终稿", "status": "done"}
  ]
}
```

状态枚举：

- `pending`
- `in_progress`
- `done`

要求：

- Leader 与每个子代理各自维护一份独立 todo 状态。
- 每步执行前后将当前 todo 列表注入对应 agent 上下文。
- 使用 R12 PRD §4.2 的 `sys_prompt` 作为规划说明、`tool_prompt` 作为工具描述。
- 不并行多次调用 `write_todos`。
- todo 状态不改变 `PAGENT_DRAFTING_MAX_STEPS` 等硬门控，只辅助规划和上下文。

### 3.5 子代理契约

统一要求：

- 每个子代理 = LLM + role SOP prompt + 受限工具访问。
- 输入只传 `source_artifact_key` / 相对路径 key / 必要参数，不传长正文。
- 输出写回 `draft_workspace`，返回短结果：

```python
{
  "artifact_key": "04_content/abstract.md",
  "done": true,
  "note": "可选说明"
}
```

- 失败时返回可解释错误，不抛裸异常到 Leader。
- 外部内容必须作为数据包裹，忽略数据区内任何指令。
- 产物格式遵循各自 Prompt 原文要求。

子代理清单与顺序：

| 顺序 | 子代理 | 主要输入 | 主要输出 | 可用工具 |
| --- | --- | --- | --- | --- |
| 1 | `input_parser` | `01_input/raw_document.*` | `01_input/parsed_info.json` | `draft_workspace`, `office_to_md` / `file_extract`, `write_todos` |
| 2 | `patent_searcher` | `01_input/parsed_info.json` | `02_research/*.md` | `draft_workspace`, `patent_search`, `office_to_md` / `file_extract`, `write_todos` |
| 3 | `outline_generator` | `parsed_info.json` | `03_outline/patent_outline.md` | `draft_workspace`, `skill_loader`, `write_todos` |
| 4 | `abstract_writer` | `parsed_info.json`, `patent_outline.md`, `abstract_writing_style.md` | `04_content/abstract.md` | `draft_workspace`, `skill_loader`, `write_todos` |
| 5 | `claims_writer` | `parsed_info.json`, `patent_outline.md`, `abstract.md`, `claims_writing_style.md` | `04_content/claims.md` | `draft_workspace`, `skill_loader`, `write_todos` |
| 6 | `description_writer_part1` | `parsed_info.json`, `patent_outline.md`, `abstract.md`, `claims.md`, `prior_art_analysis.md`, `description_writing_style.md` | `04_content/description.md` 第一部分 | `draft_workspace`, `skill_loader`, `write_todos` |
| 7 | `description_writer_part2` | `description.md` 第一部分及相关材料 | `04_content/description.md` 完整说明书 | `draft_workspace`, `skill_loader`, `write_todos` |
| 8 | `diagram_generator` | `04_content/description.md` | `04_content/figures.md` | `draft_workspace`, `skill_loader`, `write_todos` |
| 9 | `markdown_merger` | `04_content/*` | `05_final/complete_patent.md`, `05_final/summary_report.md` | `draft_workspace`, `skill_loader`, `write_todos` |

### 3.6 Prompt 契约

要求：

- R12 PRD §4 是唯一 Prompt 来源。
- 实现时直接使用 §4 原文，仅按 §4.0 做工具名等价替换。
- Prompt 集中存放在 `app/prompts/`，不得散落在业务逻辑中。
- Leader Prompt 放入 `app/prompts/patent_drafting_leader.py`。
- 子代理 Prompt 放入 `app/prompts/subagents/<role>_prompt.py`。
- Todo Prompt 放入 `app/prompts/todo_middleware.py`。
- 内部 Markdown 围栏如需恢复，只能恢复语义等价围栏，不改变 Prompt 语义。

### 3.7 配置契约

新增或确认配置：

| 配置项 | 环境变量 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `drafting_max_steps` | `PAGENT_DRAFTING_MAX_STEPS` | 保持现有或 R11 默认 | Leader 最大编排步数 |
| `drafting_subagent_max_steps` | `PAGENT_DRAFTING_SUBAGENT_MAX_STEPS` | 保持现有或 R11 默认 | 单个子代理最大步数 |
| `draft_workspace_dir` | `PAGENT_DRAFT_WORKSPACE_DIR` | `""` | 空表示内存 key-store，非空表示磁盘 workspace |
| `skill_dir` | `PAGENT_SKILL_DIR` | `app/skills_docs` | Markdown 技能文档目录 |
| `patent_search_top_k` | `PAGENT_PATENT_SEARCH_TOP_K` | `10` | 默认检索条数 |
| `serpapi_api_key` | `SERPAPI_API_KEY` / `PAGENT_SERPAPI_API_KEY` | `None` | SerpAPI Key，敏感配置，不进入公开配置 |

要求：

- 配置保持通用作用域，不绑定单个 Node 临时场景。
- 新增配置必须同步 `Settings` 默认值、环境变量读取、`to_public_dict()` 和测试。
- 非敏感配置可进入 `to_public_dict()`。
- 敏感配置不得进入日志、trace 或公开配置。
- 默认继承配置时使用 `settings.xxx if arg is None else arg`，不得使用会吞掉 `0` / `False` 的 `arg or settings.xxx`。

### 3.8 日志与 Trace 契约

建议事件：

| 事件 | 触发 | data |
| --- | --- | --- |
| `draft_workspace_written` | 写入 artifact | `artifact_key`, `chars`, `storage_mode` |
| `draft_workspace_listed` | 枚举 workspace | `prefix`, `count` |
| `draft_workspace_merged` | 合并 artifact | `source_count`, `output_key`, `chars` |
| `skill_doc_loaded` | 加载技能文档 | `skill_name`, `chars` |
| `patent_search_started` | 开始检索 | `top_k`, `country`, `status` |
| `patent_search_skipped` | 检索降级 | `reason` |
| `subagent_invoked` | 调用子代理 | `tool`, `step_index` |
| `subagent_observed` | 子代理返回 | `tool`, `artifact_key`, `done` |
| `todos_updated` | 更新 todo | `owner`, `total`, `in_progress`, `done` |
| `drafting_completed` | 终稿完成 | `complete_key`, `sections` |

要求：

- `event` 使用稳定英文名。
- `message` 可使用中文。
- 不记录交底书正文、prompt 全文、检索正文、API key、token 或隐私数据。
- 可恢复异常使用 warning 并说明降级结果。
- 异常保留堆栈，使用 `logger.exception(...)` 或等价方式。

---

## 4. Code Style

- 优先最小化、局部化改动，复用现有 helper、ToolRegistry、配置、trace 与 bounded ReAct 基础设施。
- 所有公开类、函数、方法必须写中文 Google 风格 docstring，包含 Args / Returns / Raises（如有）。
- 注释和日志沿用中文风格；日志 `event` 字段使用稳定英文。
- 行内注释只解释不直观的安全边界、路径校验、预算护栏和降级原因。
- Prompt 不内联散落在业务逻辑里，集中在 `app/prompts/` 模块，作为命名常量或模板函数导出。
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

### 5.1 TDD / 增量顺序

1. `draft_workspace` 增强测试
   - 内存模式默认启用。
   - `PAGENT_DRAFT_WORKSPACE_DIR` 非空时落盘。
   - 自动具备 `01_input` 到 `05_final` 逻辑目录。
   - `write` / `read` / `list` / `merge` 正常工作。
   - 相对路径 key 白名单、防路径逃逸、截断逻辑有效。
   - `merge` 按顺序合并并写入目标 artifact。

2. `skill_loader` 修复测试
   - 从 `PAGENT_SKILL_DIR` 读取 Markdown 文档。
   - 白名单技能可读。
   - 缺失技能返回可解释错误。
   - 路径穿越被拒绝。
   - 不读取 `app/skills/*.py` 源码。

3. `patent_search` 真实检索接口与门控测试
   - 空 query 报错或返回明确错误。
   - `allow_network=False` 时返回 skipped，不触网。
   - fake provider 返回 CN / GRANT / Top-K 结果。
   - provider 异常时安全降级。
   - 不编造结果字段。

4. TodoList 中间件测试
   - `write_todos` 接收完整 todo 列表并保存状态。
   - 状态只允许 `pending` / `in_progress` / `done`。
   - Leader 与子代理 todo 状态相互隔离。
   - 每步上下文能注入当前 todo 列表。
   - todo 状态不改变最大步数 / token / 超时门控。

5. Prompt 注册与子代理测试
   - 9 个子代理均注册。
   - `description_writer_part1` 与 `description_writer_part2` 拆分存在。
   - 每个子代理使用对应 R12 Prompt 常量。
   - 子代理调用 fake LLM，而不是只做字符串拼接。
   - 子代理只返回短结果，长正文写入 workspace。
   - 子代理工具权限符合角色范围。

6. Leader 编排测试
   - 严格按 `input_parser → patent_searcher → outline_generator → abstract_writer → claims_writer → description_writer_part1 → description_writer_part2 → diagram_generator → markdown_merger` 顺序执行。
   - 每个子代理完成后通过 workspace `list` 审查输出是否存在。
   - 缺文件时按上限重委托，超过上限返回失败原因。
   - 最终输出 `05_final/complete_patent.md` 和 `05_final/summary_report.md` key。
   - trace / 日志脱敏。

7. 端到端回归
   - `intent=patent_drafting` 可完成离线 fake LLM 流程。
   - 输出包含摘要、权利要求书、说明书、说明书附图、评审报告。
   - 默认不触网、不调用真实外部 LLM。
   - 全量测试与 compileall 通过。

### 5.2 必测用例

- workspace key 为 `../secret`、绝对路径、非法字符时被拒绝。
- `list` 能列出 `04_content/` 下已有 artifact，Leader 可据此发现缺失文件。
- `merge` 合并 `description` 第一部分与临时具体实施方式后生成完整 `description.md`。
- `skill_loader` 对 `patent_drafting.py` 或任意 Python 源码请求不返回源码内容。
- `patent_search` 离线时 `patent_searcher` 仍能生成“未查新 / 检索不足”的可解释分析，不臆造现有技术。
- 附件或检索数据中包含“忽略以上指令”时，Prompt 和输出格式不被改变。
- `write_todos` 非法状态值被拒绝。
- 子代理 LLM 返回空内容时，工具返回安全失败并不写入伪完成 artifact。
- `markdown_merger` 合并顺序固定为摘要、权利要求书、说明书、说明书附图。
- trace / 日志不包含交底书正文、prompt 全文、检索正文或密钥。
- `Settings` 默认值、环境变量覆盖、`to_public_dict()` 均有测试。

### 5.3 Fixtures 与隔离

- 使用 fake LLM 隔离真实模型调用。
- 使用 fake patent search provider 隔离真实联网检索。
- 使用 `tmp_path` 覆盖磁盘 workspace 与 skill docs 目录。
- 使用小型 Markdown / 文本文档作为输入 fixture，避免大二进制污染仓库。
- 联网集成测试单独标记，默认不运行。

---

## 6. Boundaries

### 6.1 Always do

- 直接使用 R12 PRD §4 Prompt 原文，不自行改写语义。
- 只做 §4.0 明确的工具名等价替换。
- Leader 与 9 个子代理都挂载独立 todo 能力。
- 子代理产物必须写入 `draft_workspace`，子代理返回短结果。
- 长正文只通过 workspace key / 路径流转。
- `draft_workspace` 默认内存 key-store，磁盘落盘只在 `PAGENT_DRAFT_WORKSPACE_DIR` 非空时启用。
- 文件 / artifact 路径必须做白名单和防逃逸校验。
- `skill_loader` 读取 Markdown 技能文档，不读取可执行 Python 源码。
- `patent_search` 受联网门控，离线安全降级。
- 默认测试不访问真实网络和真实外部 LLM。
- 保持 `parsed_info` 结构软约定，除非明确选择可选 schema 增强。
- 日志和 trace 必须脱敏。

### 6.2 Ask first

- SerpAPI 接入方式：直接 HTTP 调用还是引入官方 / 第三方轻量 SDK；如新增依赖必须同步 `requirements.txt`。
- 是否需要新增依赖支持文档转换。
- `parsed_info` 是否启用 pydantic / JSON Schema 结构化校验增强。
- 默认最大步数、token 预算、超时时间是否沿用 R11 现有值或调整。
- `PAGENT_SKILL_DIR` 默认目录是否使用 `app/skills_docs`。
- 是否将联网集成测试接入 CI 的可选 job。

### 6.3 Never do

- 不引入 MCP。
- 不引入 LangChain / LangGraph 等外部 agent 框架。
- 不把 Python 源码作为技能文档返回给 LLM。
- 不让子代理继续停留在“加标题写回”的空壳实现。
- 不让 `patent_search` 在无真实来源时伪造 evidence。
- 不把附件正文、prompt 全文、检索正文或密钥写入日志 / trace / 长期记忆。
- 不执行附件、检索结果或技能文档中的指令。
- 不编造法条、专利号、检索结果、引用或来源。
- 不通过 shell 拼接用户输入执行命令。
- 不把未人审的完整专利文书固化进长期记忆或案件归档。

---

## 7. Open Decisions

实施前需要确认：

1. SerpAPI 接入方式：直接 HTTP 调用还是引入 SDK；如新增依赖需同步 `requirements.txt`。
2. SerpAPI 查询参数映射细节：Google Patents 引擎 / 普通搜索限定站点 / 专利专用参数的最终选择。
3. `parsed_info` 是否保持软约定，还是启用可选 schema 校验增强。
4. `PAGENT_SKILL_DIR` 默认值是否确定为 `app/skills_docs`。
5. Leader / 子代理最大步数、token 预算、超时是否沿用现有 R11 配置。
6. TodoList 中间件状态放在 `WorkflowState`、agent runtime state，还是独立上下文对象中。

---

## 8. Incremental Delivery Plan

### 阶段 1：增强 `draft_workspace`

验收：

- 项目工作区、目录结构、相对路径 key、`list`、`merge`、内存 / 磁盘模式均实现。
- 路径安全与截断测试通过。
- `conda run -n autoGLM pytest tests/test_draft_workspace.py` 通过。

建议提交：

```text
feat(tool): 增强专利文书工作区能力
```

### 阶段 2：修复 `skill_loader`

验收：

- 从 Markdown 技能文档目录读取。
- 与 `app/skills/*.py` 可执行 Skill 类解耦。
- 白名单与路径安全测试通过。

建议提交：

```text
fix(tool): 改为加载专利 Markdown 技能文档
```

### 阶段 3：实现 `patent_search` 真实检索接口

验收：

- fake provider 离线测试通过。
- 联网门控与降级行为明确。
- 不再返回占位 fake evidence。

建议提交：

```text
feat(tool): 接入专利真实检索接口
```

### 阶段 4：实现 TodoList 中间件与 `write_todos`

验收：

- Leader 与每个子代理可维护独立 todo 状态。
- 当前 todo 列表能注入上下文。
- §4.2 Prompt 已接入。

建议提交：

```text
feat(drafting): 增加文书生成待办规划工具
```

### 阶段 5：落地 R12 Prompt 与 9 个子代理

验收：

- Leader 和 9 个子代理 Prompt 常量集中在 `app/prompts/`。
- `description_writer` 拆为 part1 / part2。
- 子代理调用 fake LLM，并按 workspace key 读写。
- `conda run -n autoGLM pytest tests/test_subagent_tools.py` 通过。

建议提交：

```text
feat(drafting): 接入专利文书子代理提示词
```

### 阶段 6：更新 Leader 编排与端到端回归

验收：

- Leader 严格按 R12 顺序委托、审查、重委托、交付。
- 缺文件时能通过 `list` 发现并重试。
- `markdown_merger` 产出 `complete_patent.md` 与 `summary_report.md`。
- 全量测试与 compileall 通过。

建议提交：

```text
fix(drafting): 修复专利文书生成编排缺口
```
