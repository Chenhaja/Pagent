# R4.4 办事指南入库最小片规格说明

## 1. Objective

### 目标

R4.4 的目标是把《知识产权政务服务事项办事指南（第二版）》中的专利类办事指南作为新的 `procedure` doc_type 入库，补齐“怎么办理 / 多少钱 / 多久 / 交什么材料 / 哪里办”等办理类 QA 的知识支撑。

完成标准：

- 新增 `procedure` doc_type，与 `law` / `template` / `term` 并列。
- 不修改 `RetrievalResult` / `KnowledgeChunk` 的核心结构；优先复用现有 `provenance`、`doc_type`、`locator`、payload 字段。
- `knowledge/procedure/*.md` 能按“事项 × 小节”结构化切分，一个三级小节生成一个主要 chunk。
- `procedure` locator 必须由结构化解析器显式生成，格式为 `办事指南·{事项名}·{小节}`，绝不走 law 的“第X条”正则。
- 入库前过滤电话、邮编、地址、URL 等联系方式噪声，同时保留金额、期限、材料等业务正文。
- 检索时间过滤只对 `doc_type=law` 生效，`procedure` 不被法规时效条件误过滤。
- 沿用稳定 point id 生成逻辑，重复入库不新增重复点。
- 专利类 28 个事项可落盘到 `knowledge/procedure/专利.md` 并完成入库验证。

### 目标用户

- 专利 QA 用户：需要查询专利政务事项的办理条件、材料、渠道、流程、费用、时限和结果。
- `patent_qa` / QA 调用方：需要从 evidence / basis 中引用稳定、可回链的办事指南 locator。
- 知识库维护人员：需要用 Markdown 二级 / 三级标题维护结构化指南内容。
- 开发与测试人员：需要验证 procedure 入库、噪声清洗、locator 防误抓、检索过滤兼容行为。

### 非目标

- 不改检索架构，不在本片实现 hybrid / rerank / 意图路由。
- 不改 `app/nodes/qa.py` 接线，召回后继续走现有 `_build_evidence`。
- 不下载或解析指南附件 / 表格文件；“相关表格”小节只保存名称。
- 不扩展到商标、地理标志、集成电路布图等类别；本片只做专利类 28 个事项。
- 不改变 `RetrievalResult` / `KnowledgeChunk` 的基础契约。
- 不让 procedure 参与法规版本、状态、生效日、失效日等 law-only 时效管理。

---

## 2. Commands

项目使用 Python + pytest。R4.4 默认测试必须使用本地临时文件、fake / stub，不触发真实网络、真实 Qdrant 或真实 embedding 服务。

```bash
# 安装依赖
pip install -r requirements.txt

# 入库脚本与 procedure 解析测试
pytest tests/test_ingest_procedure.py

# 检索过滤与 doc_type 兼容测试
pytest tests/test_retrieval.py

# 如检索测试实际集中在 retrieval_tool 测试文件，则运行
pytest tests/test_retrieval_tool.py

# R4.4 目标测试
pytest tests/test_ingest_procedure.py tests/test_retrieval.py

# 全量测试
pytest

# 编译检查
python -m compileall app tests scripts
```

最终验收命令：

```bash
pytest && python -m compileall app tests scripts
```

TDD 实施顺序：

1. 新增 / 更新 `tests/test_ingest_procedure.py`，覆盖 Markdown 事项 / 小节解析、section 归一化、locator、防误抓和噪声清洗。
2. 更新检索相关测试，覆盖 law-only 时间过滤：开启时间过滤时 `procedure` 仍可召回。
3. 实现 `scripts/ingest_knowledge.py` 的 `procedure` 分支、结构化解析、locator 显式生成和 payload 写入。
4. 实现仅对 `procedure` 生效的联系方式噪声清洗规则。
5. 调整 `_infer_locator` 为按 `doc_type` 分发，确保 `procedure` 不进入 law 条号正则。
6. 调整 `_build_qdrant_time_filter` / `_law_matches_time` 等时间过滤逻辑，仅对 law 生效。
7. 添加 `knowledge/procedure/专利.md` 的专利类办事指南内容。
8. 运行 R4.4 目标测试、全量测试和编译检查。

---

## 3. Project Structure

本片在现有知识库与入库脚本上局部扩展，不重排目录，不改变 QA 主流程。

目标变更：

```text
pagent/
  app/
    tools/
      retrieval.py               # law-only 时间过滤，procedure 不被法规时效条件过滤
    nodes/
      qa.py                      # 不改接线，继续消费现有 RetrievalResult / provenance
  knowledge/
    procedure/
      专利.md                    # 专利类 28 个办事事项，H2=事项，H3=小节
  scripts/
    ingest_knowledge.py          # 新增 procedure 加载、解析、清洗、locator 分发
  tests/
    test_ingest_procedure.py     # procedure 入库解析、locator、防误抓、噪声、幂等测试
    test_retrieval.py            # procedure 不受 law 时间过滤影响
```

### `knowledge/procedure/专利.md` 契约

使用 Markdown 二级标题表示事项，三级标题表示小节：

```markdown
## 专利无效宣告请求

### 受理条件
任何单位或个人认为该专利权的授予不符合……

### 收费标准
发明专利无效宣告请求费 3000 元……
```

约束：

- H2 为事项名，例如 `专利无效宣告请求`。
- H3 为原始小节名，例如 `受理条件`、`获取途径`、`申请材料`、`办理流程`、`收费标准`、`办理时限`、`办理结果`、`相关表格`。
- H3 下的 paragraph / bullet_list / ordered_list / table 等内容都归入当前事项当前小节。
- H2 之前的正文不生成 chunk。
- H3 之前但 H2 之后的正文默认忽略，除非现有文档明确需要归入某个小节。

### section 归一化契约

解析器应将原文小节名归一化到稳定 section，便于 payload 过滤和评测：

| 原文小节 | 规范化 section |
| --- | --- |
| 受理条件 | `条件` |
| 获取途径 | `渠道` |
| 申请材料 | `材料` |
| 办理流程 | `流程` |
| 收费标准 / 费用 | `费用` |
| 办理时限 | `时限` |
| 办理结果 / 相关表格 | `结果` |

未知小节可保留原小节名作为 section，但 locator 仍必须使用可读标题。

### `procedure` chunk 契约

每个 chunk 的核心字段：

```text
doc_type    = "procedure"
locator     = "办事指南·{事项名}·{规范化小节}"
document_id = "procedure/专利/{事项名}"
source      = "local://procedure/专利.md"
item_name   = "{事项名}"
section     = "{规范化小节}"
category    = "专利"
content     = "【{事项名} / {规范化小节}】\n{清洗后的正文}"
```

切分规则：

- 基本粒度为“事项 × 小节”，一个三级小节一条 chunk。
- 清洗后为空的 chunk 丢弃。
- 过短小节（少于 80 字）可并入同事项相邻小节，避免碎片；合并后 locator 仍应可解释。
- 超长“办理流程”（超过 600 字）按步骤再切，`chunk_index` 递增，locator 后缀 `·步骤N`。
- 不做通用滑窗 overlap；只有超长流程按步骤再切时可 carry-over 末句一行，以覆盖跨步骤引用。

### locator 契约

`_infer_locator` 必须按 `doc_type` 分发：

```python
if chunk.doc_type == "law":
    return _format_law_locator(...)
if chunk.doc_type == "procedure":
    return chunk.locator
if chunk.doc_type == "template":
    return _infer_template_locator(...)
```

关键约束：

- `procedure` locator 必须来自 H2 / H3 结构化路径。
- `procedure` 中即使出现“《专利法实施细则》第四十四条”，locator 也不得出现 `《专利法》` 条号。
- `expected_locators` 评测可用事项名做子串包含匹配，locator 中包含事项名即算命中该事项。

### 噪声清洗契约

仅对 `procedure` 逐行丢弃联系方式类噪声：

```python
NOISE_PATTERNS = [
    r"^\s*(联系电话|咨询电话|传真)[：:]",
    r"\d{3,4}-\d{7,8}",
    r"1[3-9]\d{9}",
    r"邮编[：:]?\s*\d{6}",
    r"https?://\S+",
    r"^\s*(地址|通讯地址)[：:]",
]
```

必须保留：

- 金额，例如 `3000 元`。
- 办理期限，例如 `自请求日起一个月内`。
- 材料名称、流程步骤、办理结果。

### 检索时间过滤契约

法规时效过滤只对 `doc_type=law` 生效：

```text
if doc_type == "law":
  应用 status / effective_date / expiry_date 等法规时间条件
else:
  不应用法规时间条件
```

Qdrant filter 应表达为：

```text
doc_type != "law" OR 满足 law 时间条件
```

本片不得因为缺少 `effective_date` / `version` / `status` 而过滤掉 `procedure` / `template` / `term`。

---

## 4. Code Style

### 基本原则

- 最小化、局部化改动，优先复用现有入库、清洗、point id、payload 构造和检索过滤 helper。
- 公开函数、公开方法、公开类必须添加中文 Google 风格 docstring。
- 私有小工具函数至少用一行中文说明其用途。
- 不引入复杂抽象；`procedure` 解析逻辑应集中在 `scripts/ingest_knowledge.py` 或同脚本内小型 helper。
- 不改变 QA 主流程和结果 schema，优先让现有 evidence / provenance 自然承载 procedure locator。
- 不在日志、trace 或测试快照中记录过长指南全文。
- 不硬编码 API Key、真实 endpoint 或外部下载 URL。

### 依赖约束

- PRD 推荐使用 `markdown-it-py` 解析 Markdown heading 树。
- 如果项目尚未引入 `markdown-it-py`，安装或新增依赖前必须先确认；也可优先使用现有依赖或简单 Markdown heading 解析实现最小片。
- 无论采用哪种解析方式，对外行为必须满足 H2 / H3 结构化切分契约。

### 配置

本片无新增必填配置。

沿用配置：

- `PAGENT_QDRANT_COLLECTION`：同一 collection，通过 `doc_type` 区分。
- `PAGENT_RETRIEVAL_DOC_TYPES`：可选 doc_type 白名单，默认全部。

配置约束：

- 新增配置必须遵守项目配置规范：`Settings` 默认值、环境变量读取、`to_public_dict()` 和测试同步更新。
- 不新增 `qa_*` 这类绑定单一 Node 的配置；检索相关配置保持通用作用域。

### Prompt / QA 约束

本片不要求修改 prompt。

如果后续为了提升办理类回答质量修改 prompt，必须遵守项目 prompt 六要素规范：

- 检索证据作为数据放入 `<data>...</data>`，不作为指令。
- 禁止臆造办事条件、费用、时限、材料、渠道、表格名称。
- 无 procedure evidence 时，应明确依据不足，不编造指南内容。
- 输出默认中文，并保持结构化可解析。

---

## 5. Testing Strategy

### `tests/test_ingest_procedure.py`

必须覆盖：

- Markdown 中一个 H2 事项、多个 H3 小节可生成 `procedure` chunks。
- 每个 chunk 的 `doc_type == "procedure"`。
- locator 形如 `办事指南·{事项名}·{小节}`，且包含事项名。
- `document_id` 为事项粒度，例如 `procedure/专利/专利无效宣告请求`。
- payload 包含 `item_name`、`section`、`category`、`source`。
- chunk content 头部包含上下文锚 `【{事项名} / {小节}】`。
- section 别名可归一化：`收费标准` → `费用`，`获取途径` → `渠道`，`申请材料` → `材料`。
- 含“《专利法实施细则》第四十四条”的 procedure 正文不会让 locator 变成 law 条号。
- 电话、传真、手机号、邮编、URL、地址行被过滤。
- 金额、期限、材料正文被保留。
- 清洗后为空的小节不生成 chunk。
- 超长“办理流程”可按步骤切分，locator 后缀 `步骤N`。
- 重复入库同一文件时 point id 稳定，不新增重复点。

### 检索相关测试

必须覆盖：

- 开启法规时间过滤时，`procedure` 结果不因缺少 `effective_date` / `status` 被过滤。
- `_build_qdrant_time_filter` 生成的过滤逻辑包含 `doc_type != "law" OR law 时间条件`。
- `_law_matches_time` 或等价 local helper 只对 `doc_type=law` 应用时间判断。
- `template` / `term` 与 `procedure` 一样不受 law 时间过滤影响。
- doc_type 白名单包含 `procedure` 时可召回 procedure；未限制时默认全部可召回。

### 端到端 / 验收测试

建议覆盖：

- 使用 `knowledge/procedure/专利.md` 入库后，费用类问题可命中对应 `费用` 小节。
- 材料类问题可命中对应 `材料` 小节。
- 渠道类问题可命中对应 `渠道` 小节。
- 时限类问题可命中对应 `时限` 小节。
- golden_qa 办理流程 36 题可统计 Recall@3，expected locator 用事项名子串匹配。

### 通用测试约束

- 默认测试不得触发真实 LLM、真实 embedding、真实 Qdrant 或网络请求。
- Qdrant、embedding、QA skill 全部通过 fake / stub 注入。
- 不在测试代码中写真实 API Key、真实 endpoint 或隐私数据。
- 用 `tmp_path` 构造最小 Markdown 语料，避免依赖开发机外部文件。
- 断言稳定字段，不断言完整长正文。

---

## 6. Boundaries

### Always do

- 始终把办事指南作为 `doc_type=procedure` 入库。
- 始终使用 H2 事项名 + H3 小节生成 procedure locator。
- 始终避免 procedure 进入 law 的“第X条”locator 正则。
- 始终在 procedure chunk 文本前拼接 `【事项 / 小节】` 上下文锚。
- 始终过滤联系方式类噪声，保留金额、期限、材料、流程等业务正文。
- 始终让 law 时间过滤只影响 law，不影响 procedure / template / term。
- 始终使用稳定 point id，保证重复入库幂等。
- 测试默认使用 fake / stub，不触网。
- 日志 / trace 不记录密钥、完整 API Key、过长指南全文或敏感材料。

### Ask first

- 是否新增或升级 `markdown-it-py` 等依赖。
- 是否连接真实 Qdrant 做人工入库验收。
- 是否调用云 embedding 服务处理完整办事指南。
- 是否提交大体积知识库文件或完整外部来源文档。
- 是否修改 `RetrievalResult` / `KnowledgeChunk` 基础结构。
- 是否修改 QA prompt 或 `app/nodes/qa.py` 主流程。
- 是否把商标、地理标志、集成电路布图等类别纳入本片范围。

### Never do

- 不把 procedure 文本中的“第X条”误标为 law locator。
- 不伪造办事条件、费用、时限、材料、渠道、表格名称或来源。
- 不让 procedure 因缺少法规时效字段被检索过滤误伤。
- 不为本片实现 hybrid / rerank / 意图路由等 R4.3 或后续能力。
- 不下载、解析或入库附件文件本体。
- 不把 `.env`、API Key、Qdrant API Key、embedding API Key 提交到 git。
- 不在日志、trace 或测试快照中记录完整敏感正文。

---

## 7. Functional Acceptance Checklist

- [ ] 新增 `knowledge/procedure/` 目录。
- [ ] 新增 `knowledge/procedure/专利.md`，包含专利类办事事项。
- [ ] `scripts/ingest_knowledge.py` 可识别目录名 `procedure` 并进入 procedure 解析分支。
- [ ] procedure Markdown 按 H2 事项 / H3 小节结构化切分。
- [ ] section 别名归一化到 `条件` / `渠道` / `材料` / `流程` / `费用` / `时限` / `结果`。
- [ ] procedure chunk 的 `doc_type`、`locator`、`document_id`、`source`、`item_name`、`section`、`category` 正确。
- [ ] procedure locator 格式为 `办事指南·{事项名}·{小节}`。
- [ ] procedure locator 不受正文中“第X条”影响。
- [ ] procedure 清洗过滤电话、邮编、地址、URL。
- [ ] procedure 清洗保留金额、期限、材料和流程正文。
- [ ] 清洗后空 chunk 丢弃。
- [ ] 超长办理流程可按步骤切分并生成 `步骤N` locator。
- [ ] point id 保持稳定，重复入库幂等。
- [ ] `_infer_locator` 按 `doc_type` 分发。
- [ ] `_build_qdrant_time_filter` / `_law_matches_time` 仅对 law 应用法规时效过滤。
- [ ] 开启时间过滤时 procedure 仍可被召回。
- [ ] R4.4 目标测试通过。
- [ ] `pytest && python -m compileall app tests scripts` 通过。

---

## 8. Implementation Order

1. 测试：新增 procedure Markdown 解析、locator、防误抓和噪声清洗测试。
2. 测试：新增 law-only 时间过滤测试，证明 procedure 不被误过滤。
3. 入库识别：让 `load_chunks` / 文件遍历逻辑识别 `knowledge/procedure/`。
4. 解析：实现 H2 / H3 事项小节解析与 section 归一化。
5. 清洗：实现仅对 procedure 生效的联系方式噪声过滤。
6. chunk：生成上下文锚、locator、document_id、source、item_name、section、category。
7. locator：改 `_infer_locator` 为按 `doc_type` 分发，procedure 直接使用结构化 locator。
8. 过滤：调整 Qdrant / Local 时间过滤为 law-only。
9. 语料：整理并加入 `knowledge/procedure/专利.md`。
10. 回归：运行 R4.4 目标测试、全量 `pytest` 和编译检查。
