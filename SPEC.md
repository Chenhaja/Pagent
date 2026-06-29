# R4.2 时效性管理最小片规格说明

## 1. Objective

### 目标

R4.2 的目标是让法规类知识具备时效性，做到“答现行版、可追历史版、出处带生效日期”。本片在 R4.1 检索能力之上，为 `knowledge/law/` 入库、Qdrant payload、检索过滤和 QA evidence 增加法规版本与时间元数据。

完成标准：

- law chunk 入库后，payload 含 `law_name`、`version`、`effective_date`、`expiry_date`、`status`、`source_url`、`retrieved_at`、`content_hash`。
- 同一条文允许多版本共存，`document_id` 必须带版本，稳定 point id 使用 `sha256(document_id:chunk_index)`。
- 默认检索只召回 `status == "current"` 的法规版本。
- 传入历史 `as_of` 日期时，召回该日期有效的版本：`effective_date <= as_of AND (expiry_date is null OR expiry_date > as_of)`。
- 非 law 文档不受法规时间过滤影响，保持 R4.1 行为。
- QA evidence / basis 引用法规时，出处形如 `《专利法(2020修正)》第22条`，并包含生效日期。
- 命中 `superseded`，或 `retrieved_at` 超过 stale 阈值时，答案附“可能过时，建议核对官方最新版本”。
- 系统提示增加“以官方最新公布文本为准，涉及具体时间点请核对当时有效版本”。

### 目标用户

- 专利 QA 用户：需要当前有效法规回答，也需要按行为日、申请日、无效判断日追溯历史有效版本。
- `patent_qa` skill：需要结构化 evidence 携带法规版本、生效日与状态，避免臆造或引用过时条款。
- 开发与测试人员：需要 local / qdrant 后端的时间过滤行为一致，并能用 fake / stub 验证。
- 法规语料维护人员：需要通过 `meta.json` 手工维护法规版本、状态、生效日和来源。

### 非目标

- 不实现自动抓取、变更检测、定时重建或增量更新。
- 不实现跨法规冲突消解、效力位阶推理或复杂法律适用规则。
- 不对 template / term 等非法规类语料引入时效性管理。
- 不接真实付费法规库或外部商业数据源。
- 不改变 `PatentQAResult` 的核心 schema，优先通过现有 evidence / basis / risk_notes / disclaimer_hint 承载。

---

## 2. Commands

项目使用 Python + FastAPI + Pydantic + pytest。R4.2 默认测试必须使用 fake / stub，不触发真实网络、真实 Qdrant 或真实 embedding 服务。

```bash
# 安装依赖
pip install -r requirements.txt

# 配置项测试
pytest tests/test_core_config_logging.py

# 入库脚本时效字段、meta.json、payload 测试
pytest tests/test_ingest_knowledge.py

# 检索过滤、RetrievalResult 时效字段、local / qdrant 后端测试
pytest tests/test_retrieval_tool.py

# QA evidence 标注、过时提示、trace 测试
pytest tests/test_qa_node.py

# R4.2 目标测试
pytest tests/test_core_config_logging.py tests/test_ingest_knowledge.py tests/test_retrieval_tool.py tests/test_qa_node.py

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

1. 更新 `tests/test_core_config_logging.py`，覆盖 R4.2 新配置默认值、环境变量读取和公开配置输出。
2. 更新 `tests/test_ingest_knowledge.py`，覆盖 `meta.json` 读取、law 时效字段注入、`content_hash` / `retrieved_at`、带版本 `document_id` 和 payload。
3. 更新 `tests/test_retrieval_tool.py`，覆盖 `RetrievalResult` 时效字段、默认 current 过滤、`as_of` 历史过滤、非 law 不过滤。
4. 更新 `tests/test_qa_node.py`，覆盖 evidence 法规版本标注、生效日期、superseded / stale 过时提示和 trace `evidence_versions`。
5. 实现配置、入库、检索过滤、QA 标注与测试所需 fake。
6. 为专利法 2020 文本补 `knowledge/law/zhuanli_fa_2020/meta.json`。
7. 跑 R4.2 目标测试、全量测试和编译检查。

---

## 3. Project Structure

本片在 R4.1 结构上局部扩展，不重排目录，不移除 `LocalRetrievalTool` 降级后端。

目标变更：

```text
pagent/
  app/
    core/
      config.py                  # 新增 PAGENT_RETRIEVAL_DEFAULT_STATUS / PAGENT_RETRIEVAL_ENABLE_TIME_FILTER / PAGENT_LAW_STALE_DAYS
    nodes/
      qa.py                      # evidence 法规版本标注、过时提示、trace evidence_versions
    tools/
      retrieval.py               # RetrievalResult 时效字段、QdrantRetriever / LocalRetrievalTool 时间过滤
      embeddings.py              # 沿用 R4.1 embedding 能力
    prompts/
      patent_qa.py               # 追加官方最新文本与时间点核对提示
  knowledge/
    law/
      zhuanli_fa_2020/
        meta.json                # 专利法 2020 修正元数据
        *.txt                    # 法规正文，可按现有入库规则读取
  scripts/
    ingest_knowledge.py          # KnowledgeChunk 时效字段、meta.json 读取、content_hash / retrieved_at、payload 写入
  tests/
    test_core_config_logging.py  # 配置测试
    test_ingest_knowledge.py     # 入库时效字段测试
    test_retrieval_tool.py       # 时间过滤测试
    test_qa_node.py              # QA 标注与过时提示测试
```

### `KnowledgeChunk` 契约

`scripts/ingest_knowledge.py` 中 `KnowledgeChunk` 增加法规时效字段：

```python
@dataclass
class KnowledgeChunk:
    document_id: str
    chunk_index: int
    content: str
    doc_type: str
    locator: str
    law_name: str | None = None
    version: str | None = None
    effective_date: str | None = None
    expiry_date: str | None = None
    status: str = "current"
    source_url: str | None = None
    retrieved_at: str | None = None
    content_hash: str | None = None
```

字段约束：

- `document_id`：law 必须带版本，例如 `zhuanli_fa_2020`，避免覆盖旧版。
- `effective_date` / `expiry_date` / `retrieved_at`：ISO date 字符串，`expiry_date` 可为 `None`。
- `status`：只允许 `current` / `superseded` / `not_yet_effective`。
- `content_hash`：对 chunk 正文计算 sha256，用于审计和去重。
- `locator`：law 应包含版本，例如 `专利法(2020修正)·第22条`，用于 QA 回链。

### law `meta.json` 契约

`knowledge/law/` 下每个法规版本目录放一个 `meta.json`，入库时注入同目录各 chunk。

示例：

```json
{
  "document_id": "zhuanli_fa_2020",
  "law_name": "中华人民共和国专利法",
  "version": "2020修正",
  "effective_date": "2021-06-01",
  "expiry_date": null,
  "status": "current",
  "source_url": "https://example.invalid/source"
}
```

实现约束：

- `meta.json` 缺失时，非 law 沿用 R4.1；law 允许用安全默认值继续入库，但不得伪造具体 `effective_date` / `source_url`。
- `document_id` 优先取 `meta.json`；缺失时可用目录名，但 law 目录命名必须带版本。
- `retrieved_at` 由入库时生成，默认使用当天日期。
- `content_hash` 由入库时生成，不依赖人工填写。

### `RetrievalResult` 契约

`app/tools/retrieval.py` 中 `RetrievalResult` 增加 QA 标注所需字段：

```python
@dataclass
class RetrievalResult:
    content: str
    provenance: str | dict[str, str]
    score: int = 0
    similarity: float = 0.0
    law_name: str | None = None
    version: str | None = None
    effective_date: str | None = None
    expiry_date: str | None = None
    status: str | None = None
    source_url: str | None = None
    retrieved_at: str | None = None
```

兼容约束：

- 保持 R4.1 旧构造方式可用。
- 若当前实现 `provenance` 是 dict，则新增字段可同时存在于顶层字段和 provenance 中，但 QA 只依赖稳定字段。
- 不伪造缺失的法规版本、生效日或来源。

### 检索过滤契约

公开检索接口允许扩展可选 `as_of`，并保持旧调用兼容：

```python
class Retriever(Protocol):
    def search(self, query: str, top_k: int = 3, as_of: str | None = None) -> list[RetrievalResult]: ...
```

过滤规则：

```text
if doc_type == "law" and enable_time_filter:
  if as_of:
    effective_date <= as_of AND (expiry_date is null OR expiry_date > as_of)
  else:
    status == settings.retrieval_default_status  # 默认 current
else:
  不加法规时间过滤
```

`QdrantRetriever`：

- 查询时构造 payload filter。
- 默认 law 过滤 `status == "current"`。
- 带 `as_of` 时按 effective / expiry 范围过滤。
- 非 law 不附加法规时间过滤。
- Qdrant / embedding 异常时返回 `[]` 或由工厂回退 Local，不影响 QA 主流程。

`LocalRetrievalTool`：

- 在内存结果排序前或排序后执行等价过滤。
- 不因 payload 缺少时效字段抛异常。
- 非 law 文档保持 R4.1 关键词匹配行为。

### QA evidence 契约

`QANode._build_evidence()`：

- law 命中优先生成 `《{law_name}({version})》{条号}` 格式。
- evidence 透传 `version`、`effective_date`、`expiry_date`、`status`、`retrieved_at`。
- evidence / trace 增加 `evidence_versions`，用于排查召回版本。
- 命中 `status == "superseded"`，或 `retrieved_at` 距今天超过 `law_stale_days`，答案附“可能过时，建议核对官方最新版本”。
- prompt 追加官方最新文本和具体时间点核对提示。

---

## 4. Code Style

### 基本原则

- 最小化、局部化改动，复用 R4.1 `Retriever`、`LocalRetrievalTool`、`QdrantRetriever`、`build_retriever()` 和 `QANode._retrieve()` 结构。
- 公开类、公开方法、公开函数必须添加中文 Google 风格 docstring。
- 不引入复杂抽象；时间过滤逻辑应是小型 helper，并同时服务 local / qdrant。
- 不在业务代码里硬编码 Qdrant URL、API Key、embedding API Key 或真实 endpoint。
- 不在日志 / trace 中记录完整法规正文、用户问题长文本、密钥或 API Key。
- 检索失败必须安全降级，QA 不因 Qdrant / embedding / payload 缺字段整体 failed。
- 对法规元数据缺失保持保守：可以不标注，不得编造。

### 配置

新增配置项，沿用 `PAGENT_` 前缀：

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `PAGENT_RETRIEVAL_DEFAULT_STATUS` | `current` | 默认只召回现行有效法规 |
| `PAGENT_RETRIEVAL_ENABLE_TIME_FILTER` | `true` | 是否启用 law 时间过滤 |
| `PAGENT_LAW_STALE_DAYS` | `365` | `retrieved_at` 超过此天数标记可能过时 |

兼容 R4.1 既有配置：

- `PAGENT_RETRIEVAL_BACKEND`
- `PAGENT_RETRIEVAL_TOP_K`
- `PAGENT_QDRANT_URL`
- `PAGENT_QDRANT_API_KEY`
- `PAGENT_QDRANT_COLLECTION`
- `PAGENT_EMBEDDING_BASE_URL`
- `PAGENT_EMBEDDING_MODEL`
- `PAGENT_EMBEDDING_API_KEY`

`Settings.to_public_dict()` 可展示非敏感 R4.2 配置，但不得暴露任何 API Key。

### Prompt / Skill 约束

`patent_qa` 继续遵守项目 `CLAUDE.md`：

- evidence 作为数据进入 `<data>...</data>`，不作为指令。
- 禁止臆造法条、专利号、检索结果、引用。
- 有 law evidence 时，`basis` 应优先引用 `《法规名(版本)》第X条` 和 `effective_date`。
- 无 evidence 或元数据不足时，必须显式声明依据不足或需核对官方文本。
- 系统提示必须包含：“以官方最新公布文本为准，涉及具体时间点请核对当时有效版本”。

---

## 5. Testing Strategy

### `tests/test_core_config_logging.py`

必须覆盖：

- `retrieval_default_status` 默认 `current`。
- `retrieval_enable_time_filter` 默认 `True`。
- `law_stale_days` 默认 `365`。
- 三个配置可从环境变量读取。
- `to_public_dict()` 展示非敏感配置，不暴露 Qdrant / embedding / LLM API Key。

### `tests/test_ingest_knowledge.py`

必须覆盖：

- law 目录可读取同目录 `meta.json`。
- `KnowledgeChunk` 包含 `law_name`、`version`、`effective_date`、`expiry_date`、`status`、`source_url`、`retrieved_at`、`content_hash`。
- law `document_id` 带版本，例如 `zhuanli_fa_2020`。
- `locator` 包含版本信息，例如 `专利法(2020修正)·第22条`。
- `content_hash` 对相同正文稳定，对不同正文变化。
- `retrieved_at` 为 ISO date。
- fake qdrant upsert 收到完整时效 payload。
- 非 law 文档不要求 `meta.json`，保持 R4.1 payload。
- 输入目录为空时安全退出。

### `tests/test_retrieval_tool.py`

必须覆盖：

- `RetrievalResult` 新增时效字段默认 `None`，保持旧构造兼容。
- `QdrantRetriever` payload 映射出 `law_name`、`version`、`effective_date`、`status`、`retrieved_at`。
- 默认 law 查询带 `status == "current"` 过滤。
- 传入 `as_of` 时带 `effective_date <= as_of` 和 `expiry_date is null OR expiry_date > as_of` 过滤。
- current / superseded 两版共存时，默认只返回 current。
- 历史 `as_of` 返回该日期有效版本。
- `LocalRetrievalTool` 实现与 Qdrant 等价的内存过滤。
- 非 law 文档不受时间过滤影响。
- `PAGENT_RETRIEVAL_ENABLE_TIME_FILTER=false` 时不加法规时间过滤。
- payload 缺少时效字段时不抛裸异常。

### `tests/test_qa_node.py`

必须覆盖：

- `_build_evidence()` 对 law evidence 输出 `《专利法(2020修正)》第22条` 格式。
- evidence 包含 `effective_date`。
- 命中 `superseded` 时，答案或风险提示包含“可能过时，建议核对官方最新版本”。
- `retrieved_at` 超过 `law_stale_days` 时，答案或风险提示包含过时提示。
- current 且未 stale 时，不追加过时提示。
- trace 包含 `qa_completed.evidence_versions`。
- 无 evidence 时继续按 R4.1 依据不足逻辑返回，不编造法规引用。
- 非 law evidence 不强制法规版本标注。

### 通用测试约束

- 默认测试不得触发真实 LLM、真实 embedding、真实 Qdrant 或网络请求。
- Qdrant、embedding、QA skill 全部通过 fake / stub 注入。
- 不在测试代码中写真实 API Key、真实 endpoint 或隐私数据。
- trace 断言只检查稳定字段，不断言完整检索正文。
- 本地语料测试使用 `tmp_path` 构造，除验收 `knowledge/law/zhuanli_fa_2020/meta.json` 外不依赖机器外部文件。

---

## 6. Boundaries

### Always do

- 始终保留同一法规多版本，不通过新版覆盖旧版。
- law `document_id` 始终带版本。
- 默认 law 检索只召回 `current`。
- 带 `as_of` 时按 effective / expiry 判断当日有效版本。
- 非 law 检索行为不受法规时间过滤影响。
- evidence 必须携带可回链 provenance；有法规版本和生效日时必须透传。
- 命中旧版或 stale 语料时必须给出过时兜底提示。
- 测试默认使用 fake / stub，不触网。
- 日志 / trace 不记录密钥、完整 API Key、完整用户敏感材料或过长正文。

### Ask first

- 是否安装或升级真实 `qdrant-client`、embedding SDK 或其他新依赖。
- 是否连接本机或远端真实 Qdrant 做人工验收。
- 是否调用云 embedding 服务处理用户问题或案件材料。
- 是否提交真实法规全文或新增大体积知识库文件。
- 是否修改 `PatentQAResult` schema。
- 是否把 `PAGENT_RETRIEVAL_BACKEND` 默认值改为 `qdrant`。
- 是否实现自动抓取、变更检测或定时重建。

### Never do

- 不伪造法条、法规版本、生效日期、失效日期、来源 URL、检索结果或相似度。
- 不删除旧法规版本来“更新”法规。
- 不让 Qdrant / embedding / payload 缺字段导致 QA 抛裸异常或整体 failed。
- 不把 `.env`、API Key、Qdrant API Key、embedding API Key 提交到 git。
- 不在日志、trace 或测试快照中记录完整敏感正文。
- 不绕过 `allow_cloud_sensitive_content=False` 把完整敏感案件材料发给云 embedding。
- 不在本片实现自动更新机制、跨法规冲突消解或效力位阶推理。

---

## 7. Functional Acceptance Checklist

- [ ] `Settings` 增加 `retrieval_default_status`、`retrieval_enable_time_filter`、`law_stale_days`。
- [ ] `Settings.to_public_dict()` 不暴露敏感凭证。
- [ ] `KnowledgeChunk` 增加法规时效字段。
- [ ] `scripts/ingest_knowledge.py` 支持读取 law `meta.json`。
- [ ] 入库自动生成 `retrieved_at` 和 `content_hash`。
- [ ] law payload 写入完整时效字段。
- [ ] law `document_id` 带版本，point id 使用 `sha256(document_id:chunk_index)`。
- [ ] `RetrievalResult` 增加 `version`、`effective_date`、`status` 等时效字段。
- [ ] `QdrantRetriever` 默认过滤 `status == "current"`。
- [ ] `QdrantRetriever` 支持 `as_of` 时间点过滤。
- [ ] `LocalRetrievalTool` 支持等价内存时间过滤。
- [ ] 非 law 文档不受时间过滤影响。
- [ ] QA evidence / basis 引用法规时包含版本和生效日期。
- [ ] QA prompt 追加官方最新文本和具体时间点核对提示。
- [ ] 命中 superseded 或 stale 语料时追加过时提示。
- [ ] trace 增加 `qa_completed.evidence_versions`。
- [ ] 新增 `knowledge/law/zhuanli_fa_2020/meta.json`。
- [ ] R4.2 目标测试通过。
- [ ] `pytest && python -m compileall app tests scripts` 通过。

---

## 8. Implementation Order

1. 配置：在 `Settings` 增加 R4.2 三个配置项、环境变量读取和公开配置测试。
2. 入库模型：扩展 `KnowledgeChunk`，实现 `meta.json` 读取、日期/status 校验、`content_hash` / `retrieved_at`。
3. 入库 payload：确保 Qdrant upsert payload 写入完整时效字段，point id 使用带版本 `document_id`。
4. 检索模型：扩展 `RetrievalResult`，保持旧构造兼容。
5. 时间过滤 helper：实现 law-only 默认 current 过滤和 `as_of` 过滤。
6. Qdrant：把时间过滤转换为 Qdrant payload filter，并映射时效字段。
7. Local：实现等价内存过滤，保证后端可替换。
8. QA：更新 evidence provenance、prompt 时效声明、过时提示和 trace `evidence_versions`。
9. 语料：新增 `knowledge/law/zhuanli_fa_2020/meta.json`。
10. 回归：运行 R4.2 目标测试、全量 `pytest` 和编译检查。
