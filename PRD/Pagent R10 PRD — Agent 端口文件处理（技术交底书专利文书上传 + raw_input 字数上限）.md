<aside>
 🎯

**一句话目标**：为统一 Agent 入口（`POST /agent`）新增"文件上传通道"，把**技术交底书 / 专利文书等长文**从"文字框（`raw_input`）"里剥离出来——`raw_input` 只承载简短指令并设**字数上限（暂定 ≤2000，小于最大输出 `llm_max_tokens=2048`）**；长文以文件形式上传、本地解析抽取文本后，作为 `<data>` 证据注入下游，避免后续改写 / 生成因输入过长导致**输出字数超范围或被截断**。

</aside>

本 PRD 对应仓库 `Chenhaja/Pagent`，承接现有 R4.x/R5.x/R7.x/R8/R9 分层骨架与 R 编号风格，聚焦**输入层（Agent 端口）**的能力补齐，不改动既有编排与业务节点的对外契约。

## 1. 背景与目标

当前统一入口 `POST /agent`（`app/api/routes.py` → `AgentDispatchService.dispatch`）接收 `AgentRequest.raw_input: str`，该字段**无长度限制**；dispatch 将 `raw_input` 依次带入 `normalize_input → query_rewrite → intent_router → 具体 workflow`（claim_generation / translation / claim_revision / qa）。`WorkflowState.raw_input` 约定**必须保留**用于审计与回退；`WorkflowState.invention_disclosure: dict` 已预留但目前**未被填充**。

存在的问题：

- 用户把整份**技术交底书**粘贴进 `raw_input` 文字框，长文与"要办什么"的指令混在一起。
- 长文一路带入改写 / 生成节点，上下文膨胀，输出被 `llm_max_tokens`（默认 2048）截断，表现为"**改写字数超出范围**"。
- 长正文进入 trace / 日志与云模型的风险也随之升高。

本阶段目标：

- **通道分离**：为 Agent 端口新增文件上传与解析能力，长文走文件通道，`raw_input` 只放简短指令。
- **字数上限**：为 `raw_input` 设可配置字数上限（默认 2000），且**小于最大输出 token**，超限时优雅拒绝并引导改用文件上传。
- **注入为数据**：文件抽取文本作为 `<data>` 证据注入，指令 / 数据分离、防注入，不并入 `raw_input`、不计入输出长度预算。
- **联网策略（取消"默认不触网"）**：文件解析优先走本地依赖，但系统**不再以"完全离线"为默认**；是否允许联网由配置 `allow_network`（`PAGENT_ALLOW_NETWORK`，默认 `true`）控制，为后续查新 / 检索等联网能力预留入口；`raw_input` 永远保留；输出仍标注为辅助初稿。

### 目标用户

- 发明人 / 代理人：需要上传技术交底书、说明书草稿、OA 通知书等文书，而非把整篇粘进文字框。
- 开发与测试人员：需要可断言"超限被拒""文件被解析并以 `<data>` 注入""长正文不入 trace"。

## 2. 现状盘点（基于当前代码）

| 模块                                     | 现状                                                         | 缺口                                |
| ---------------------------------------- | ------------------------------------------------------------ | ----------------------------------- |
| `app/api/schemas.py`                     | `AgentRequest{raw_input:str, claims_draft, session_id}`；`raw_input` 无长度约束 | 无字数上限；无文件 / 附件字段       |
| `app/api/routes.py`                      | 仅 `POST /agent`、`/claims/*`、`/translate`、`/health`       | 无文件上传端点；无超限统一错误      |
| `app/services/agent_dispatch_service.py` | `dispatch(raw_input, claims_draft, session_id)` 一路透传     | 不感知附件；无从文件构造证据 / 交底 |
| `app/models/schemas.py`                  | `WorkflowState.invention_disclosure` 已预留但未填充          | 无 attachments / documents 承载结构 |
| `app/core/config.py`                     | `PAGENT_` 前缀；`llm_max_tokens=2048`                        | 无输入字数上限 / 附件相关配置       |

## 3. 范围

### In scope（本轮）

- `raw_input` 可配置字数上限（默认 2000）+ 超限统一拒绝与引导文案。
- Agent 端口文件上传通道：上传端点 + 附件引用（`attachment_ids`）接入 `/agent`。
- 本地文件解析与抽取（`.txt` / `.md` 直读，`.docx` / `.pptx` 转**结构保留 Markdown**，`.pdf` 可选纯文本），与 patent-disclosure-skill 对齐；含大小 / 类型 / 数量护栏。
- 抽取文本以 `<data>` 证据形式注入 `WorkflowState`（落 `invention_disclosure` / 新增 documents），指令 / 数据分离。
- 相关 trace 事件 + 脱敏（仅长度 / 计数 / 类型）。
- 配套 TDD 测试与回归。

### Non-goals（本轮不做）

- 不做前端上传组件（仍以 API 为入口）。
- 不做 OCR / 扫描件图片识别、不做表格 / 图纸结构化还原。
- 不把附件正文自动写入长期会话记忆或永久知识库入库（留待后续）。
- 不改变既有 workflow 的走向与对外响应结构（仅新增字段）。
- 不引入外部 agent 框架（联网能力由 `allow_network` 配置控制，默认允许，不再默认离线）。

### 设计约束（为未来复用留缝）

附件解析与注入逻辑须与具体 workflow 解耦（写成可平移单元）；上限 / 大小 / 类型走 settings 不硬编码；trace 预留字段，便于未来接入知识库入库或多模态解析。

## 4. 详细需求

### R10.1 `raw_input` 字数上限（P0）

- 新增配置 `input_max_chars`（`PAGENT_INPUT_MAX_CHARS`，默认 `2000`），语义为 `raw_input` 允许的**最大字符数**。
- 约束关系：`input_max_chars` 应**小于**最大输出 token `llm_max_tokens`（默认 2048）。在 `config` 加载时对该关系做校验 / 告警（注意 token≠字符，此处按业务口径以字符近似封顶）。
- 校验位置：请求入口（`AgentRequest` 校验或 `normalize_input` 前置检查），对 `raw_input` 去空白后计长。
- 超限行为：**优雅拒绝**，返回 `requires_user_input` / `400`，`message` 明确引导"请将技术交底书等长文以**文件上传**，文字框仅填写简短指令"。

**验收标准**

- `len(raw_input.strip()) <= input_max_chars` 放行；超限返回统一错误 + 引导文案，不进入下游节点。
- 上限可通过 `PAGENT_INPUT_MAX_CHARS` 覆盖；默认 2000。
- 拒绝路径不记录 `raw_input` 原文，仅记录长度。

### R10.2 文件上传通道（P0）

- 新增端点 `POST /agent/attachments`（multipart/form-data），接收一个或多个文件，返回稳定 `attachment_id` 与元数据（文件名、类型、字节数、抽取字符数）。
- `AgentRequest` 新增可选字段 `attachment_ids: list[str] = []`，`/agent` 调用时通过该字段引用已上传附件。
- 护栏：单文件大小上限 `PAGENT_ATTACHMENT_MAX_BYTES`、单请求附件数上限 `PAGENT_ATTACHMENT_MAX_COUNT`、类型白名单 `PAGENT_ATTACHMENT_ALLOWED_TYPES`；超限 / 非白名单类型统一拒绝并给出可读原因。
- 存储：附件与抽取文本落**本地临时存储**（路径走 settings），不外传。

**验收标准**

- 上传合法文件返回 `attachment_id` 与元数据；非法类型 / 超大 / 超数量被拒并有明确错误。
- `/agent` 传入无效或过期 `attachment_id` 时优雅报错，不影响既有纯文本路径。

### R10.3 文件解析与文本抽取（P0，与 patent-disclosure-skill（已经下载到该目录D:\WorkArea\Agent\patent-ref\patent-disclosure-skill） 对齐）

- 抽取器按类型分派：`.txt` / `.md` 直读；**`.docx` / `.pptx` 转“结构保留的 Markdown”**（与 skill 一致）；`.pdf`（可选增量）走 pypdf/pdfminer 纯文本层（无 OCR）。

- 转换实现（本地库，移植而非 shell 调用）

  ：

  - `.docx` → Markdown 用 `mammoth.convert_to_markdown`，保留标题 / 列表 / 表格结构。
  - `.pptx` → Markdown 用 `python-pptx`：每页 `## 第 N 页`、表格转 md 表、备注转“备注”块；旧版 `.doc` / `.ppt` 不支持并告警。
  - 将 skill 的 CLI 脚本逻辑移植为**可导入函数** `tools/office_to_md.py`，不依赖 argparse / Bash / `CLAUDE_SKILL_DIR`；此单元同时供 R10 附件注入与未来交底书生成（项目扫描）复用。

- **媒体处理**：内嵌图片按 skill 同款策略抽取到 `{attachment_id}_media/`、Markdown 内相对引用；R10 阶段**仅把 media 清单记入元数据、不注入 `<data>`**（符合 Non-goals：不做图片 / 图纸识别），为 R11 预留。

- **`doc_type` 枚举**（与 skill / 交底书流程统一）：`invention_disclosure` / `specification` / `claims` / `office_action` / `prior_art` / `other`；默认 `other`，可由客户端指定。

- 抽取结果做轻量归一化（去控制字符、统一换行、折叠多余空白），并对**单附件抽取字符数**设上限 `PAGENT_ATTACHMENT_MAX_CHARS`，超出按需截断并标注 `truncated=true`。

- 解析失败 / 空内容优雅降级：记录原因，返回可读错误，不抛裸异常。

**验收标准**

- `.docx` / `.pptx` 稳定转为结构保留 Markdown（标题 / 表格 / 列表可辨）；`.txt` / `.md` 直读；不支持类型（含 `.doc` / `.ppt`）给出明确提示。
- 图片抽取到 `{attachment_id}_media/` 并在 Markdown 相对引用；media 清单进元数据、不进 `<data>`。
- 抽取字符数受上限约束，超限标注 `truncated`；解析异常不导致 500 崩溃。

### R10.4 注入策略：以 `<data>` 证据注入（P0）

- dispatch 感知 `attachment_ids`，将抽取文本组织为**结构化文档**写入 `WorkflowState`（落 `invention_disclosure` 结构化字段，或新增 `documents` 列表承载 `{attachment_id, filename, doc_type, text, truncated}`）。
- 下游节点（如 claim_generation / qa）在**指令 / 数据分离**前提下，把文档正文放入 `<data>` 块作为证据，**不并入 `raw_input`**，不参与"输出字数"预算。
- 防注入：附件正文一律视为**数据**而非指令；不执行文档内的任何指令式内容。

**验收标准**

- 附件文本以 `<data>` 形式进入 skill 上下文，`raw_input` 不被污染。
- 文档内含"忽略以上指令"等注入式文本时不改变系统行为（可断言）。
- `WorkflowState.raw_input` 始终保留原始简短指令。

### R10.5 可观测与 trace（P0）

每个关键步骤落脱敏 trace（仅长度 / 计数 / 类型 / 布尔 / 原因），不记录附件正文与 `raw_input` 原文：

| 事件名                  | 触发                   | data（脱敏）                        |
| ----------------------- | ---------------------- | ----------------------------------- |
| `input_length_rejected` | `raw_input` 超限       | `input_len` / `limit`               |
| `attachment_received`   | 上传成功               | `count` / `content_type` / `bytes`  |
| `attachment_rejected`   | 类型 / 大小 / 数量超限 | `reason` / `content_type` / `bytes` |
| `attachment_parsed`     | 抽取完成               | `chars` / `truncated` / `doc_type`  |
| `attachment_injected`   | 作为 `<data>` 注入     | `doc_count` / `total_chars`         |

## 5. 数据契约

`app/core/config.py`（`Settings` + `PAGENT_` 前缀，通用命名）新增：

- `input_max_chars`（`PAGENT_INPUT_MAX_CHARS`，默认 `2000`）
- `attachment_max_bytes`（`PAGENT_ATTACHMENT_MAX_BYTES`）
- `attachment_max_count`（`PAGENT_ATTACHMENT_MAX_COUNT`）
- `attachment_max_chars`（`PAGENT_ATTACHMENT_MAX_CHARS`）
- `attachment_allowed_types`（`PAGENT_ATTACHMENT_ALLOWED_TYPES`，逗号分隔；建议默认 `.txt,.md,.docx,.pptx`，`.pdf` 可选）
- `attachment_storage_dir`（`PAGENT_ATTACHMENT_STORAGE_DIR`）
- `allow_network`（`PAGENT_ALLOW_NETWORK`，默认 `true`）：是否允许联网；**默认允许**（取代此前"默认不触网"）。文件解析等本地能力不受影响；查新 / 检索等联网能力据此开关。
- 加载时校验 `input_max_chars < llm_max_tokens`（不满足则告警）。

`app/api/schemas.py`：

- `AgentRequest` 新增 `attachment_ids: list[str] = []`。
- 新增 `AttachmentUploadResponse{attachment_id, filename, content_type, bytes, chars, truncated, doc_type, format, media}`（`format` ∈ `markdown` / `text`；`media` 为抽取图片清单）。

`app/models/schemas.py`：

- `WorkflowState` 新增 `documents: list[dict] = []`（或复用 `invention_disclosure`），单文档 `{attachment_id, filename, doc_type, format, text, media, truncated}`。

## 6. 项目结构变更

```jsx
app/
  api/
    routes.py          # 新增 POST /agent/attachments；/agent 接受 attachment_ids
    schemas.py         # AgentRequest.attachment_ids；AttachmentUploadResponse
  services/
    attachment_service.py   # 新增:保存/校验/解析/抽取/组织文档（可平移单元）
    agent_dispatch_service.py  # dispatch 感知 attachment_ids，注入 documents
  core/
    config.py          # 新增 input/attachment 相关配置 + 关系校验
  models/
    schemas.py         # WorkflowState.documents（或填充 invention_disclosure）
  tools/
    file_extract.py    # 新增:按类型分派抽取（txt/md 直读；pdf 可选纯文本）
    office_to_md.py    # 新增:docx→md(mammoth)/pptx→md(python-pptx)+媒体抽取，移植自 patent-disclosure-skill，可复用于交底书生成
tests/
  test_input_limit.py        # 新增:raw_input 超限拒绝
  test_attachment_upload.py  # 新增:上传/类型/大小/数量护栏
  test_attachment_extract.py # 新增:抽取/截断/异常降级
  test_attachment_inject.py  # 新增:<data> 注入/防注入/raw_input 保留
```

## 7. 安全与可观测

- **指令 / 数据分离**：附件正文只作为 `<data>` 证据，永不作为指令执行；含注入式文本不改变系统行为。
- **脱敏**：trace / 日志不记录 `raw_input` 原文、附件正文与密钥，仅记录长度 / 计数 / 类型 / 布尔 / 原因。
- **本地优先**：文件解析走本地依赖；`allow_cloud_sensitive_content=False` 时不向云模型发送完整敏感材料。
- **护栏**：类型白名单、大小 / 数量 / 抽取字符上限；超限优雅拒绝，不崩溃。

## 8. 测试策略（TDD）

- [ ]  `raw_input` 长度 `<=` 上限放行；超限返回统一错误 + 引导文案，不进入下游。
- [ ]  `PAGENT_INPUT_MAX_CHARS` 可覆盖默认 2000；`input_max_chars < llm_max_tokens` 校验生效。
- [ ]  上传合法文件返回 `attachment_id` 与元数据；非法类型 / 超大 / 超数量被拒。
- [ ]  `.txt` / `.md` 直读；`.docx`(mammoth)/`.pptx`(python-pptx) 转结构保留 Markdown（标题 / 表格 / 列表可辨）；`.doc` / `.ppt` 明确不支持。
- [ ]  图片抽取到 `{attachment_id}_media/` 并在 Markdown 相对引用；media 清单进元数据、不进 `<data>`。
- [ ]  抽取字符数受上限约束并标注 `truncated`；解析异常优雅降级。
- [ ]  附件文本以 `<data>` 注入，`raw_input` 不被污染且始终保留。
- [ ]  文档内注入式文本（如"忽略以上指令"）不改变系统行为。
- [ ]  trace 只含长度 / 计数 / 类型，无正文。
- [ ]  测试用 fake、不依赖真实外部服务、不崩溃；`allow_network` 默认 `true`（可经配置关闭），不再以"默认不触网"为前提。

### 测试联网分层约定（离线默认 + 集成 opt-in）

把"不触网"绑定在**测试层**，而非产品 / 运行时默认；两者正交：

- **单元测试 / CI 默认离线**：所有单测用 fake / fixtures，永不真连外部（国知局 / WebSearch / 云 LLM）；保证可复现、快、不 flaky。此约定独立于运行时 `allow_network`。
- **联网集成测试显式 opt-in**：真连用例用 pytest mark `@pytest.mark.network` 标记，默认 `skip`；仅当置 `PAGENT_RUN_NETWORK_TESTS=1`（或显式 `pytest -m network`）时运行，用于验证真实抓取 / 限流 / 降级。
- **运行时 `allow_network`（`PAGENT_ALLOW_NETWORK`）** 只控制产品是否允许联网（默认 `true`，涉密部署可关），与测试是否触网无关。
- 验收：默认 `pytest` 全绿且不触网；`pytest -m network`（配合 env）才发起真实请求。

## 9. 边界

### Always do

- `raw_input` 设可配置字数上限且小于最大输出 token；超限优雅拒绝并引导上传文件。
- 附件正文以 `<data>` 证据注入，指令 / 数据分离、防注入。
- 保留 `raw_input` 原文；测试用 fake、不依赖真实外部服务（联网默认允许，由 `allow_network` 控制）。

### Ask first

- 是否本轮即支持 `.docx` / `.pptx` / `.pdf`（引入 mammoth / python-pptx / pypdf 等本地解析依赖）。
- 是否将附件正文纳入检索 / 长期知识库入库。
- 是否调整默认上限（2000 字 / 大小 / 数量）用于人工验收。

### Never do

- 不把附件正文并入 `raw_input` 或计入输出字数预算。
- 不执行附件内的指令式内容。
- 不在 trace / 日志记录完整正文或密钥。
- 不改变既有 workflow 对外响应结构（仅新增字段）。

## 10. 验收清单（Definition of Done）

- [ ]  `raw_input` 字数上限（默认 2000）落地，超限优雅拒绝 + 引导文案。
- [ ]  `POST /agent/attachments` 上传通道 + 护栏可用；`/agent` 支持 `attachment_ids`。
- [ ]  文件解析：txt/md 直读、docx/pptx→结构保留 Markdown（对齐 patent-disclosure-skill）、pdf 可选；media 清单 + 截断标注 + 异常降级。
- [ ]  抽取文本以 `<data>` 注入 `WorkflowState`，`raw_input` 保留且不被污染。
- [ ]  新增 `PAGENT_INPUT_*` / `PAGENT_ATTACHMENT_*` 配置与关系校验。
- [ ]  `input_length_rejected` / `attachment_*` trace 落地且脱敏。
- [ ]  新增 / 更新测试全部通过（测试用 fake，不依赖真实外部服务）。
- [ ]  `pytest && python -m compileall app tests` 通过。

## 11. 实施顺序（建议）

1. `config`：新增 `PAGENT_INPUT_*` / `PAGENT_ATTACHMENT_*` 配置 + `input_max_chars < llm_max_tokens` 校验。
2. 先写 `test_input_limit.py`，实现 `raw_input` 超限拒绝（入口 / normalize 前置）。
3. `tools/office_to_md.py`（docx/pptx→md，移植自 skill）+ `tools/file_extract.py` + `test_attachment_extract.py`：分派抽取（含结构保留 Markdown 与 media 清单）+ 截断 / 降级。
4. `services/attachment_service.py` + `POST /agent/attachments` + `test_attachment_upload.py`：保存 / 校验 / 元数据。
5. `AgentRequest.attachment_ids` + dispatch 注入 `documents` + `<data>` 组织 + `test_attachment_inject.py`（含防注入断言）。
6. 回归：修正相邻断言，跑全量 `pytest` + `compileall`。