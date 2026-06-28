# R4.1 检索最小片规格说明

## 1. Objective

### 目标

R4.1 的目标是把 QA 当前硬编码的 `LocalRetrievalTool` 空文档关键词匹配，升级为“可替换 Retriever 接口 + Qdrant 向量召回 + 法规 / 范文 / 术语本地入库 + provenance 回链”的最小可用检索能力，修复 QA 没有支撑知识时无法可靠回答的问题。

完成标准：

- `app/tools/retrieval.py` 提供稳定的 `Retriever` 协议：`search(query, top_k) -> list[RetrievalResult]`。
- `RetrievalResult` 向后兼容现有字段，并新增 `similarity` 与扩展 provenance：`doc_type`、`locator`。
- `QdrantRetriever` 支持本地 Qdrant 向量召回，并能按 `doc_type` / `locator` 等 payload 过滤。
- `LocalRetrievalTool` 继续可用，作为测试和降级后端。
- `build_retriever(settings)` 能按 `PAGENT_RETRIEVAL_BACKEND` 选择 `local` 或 `qdrant`，并在配置缺失或后端不可用时优雅降级。
- `QANode` 默认通过工厂构建 retriever，不再硬编码空文档 `LocalRetrievalTool()`。
- QA evidence 透传 `source`、`document_id`、`doc_type`、`locator`、`score`、`similarity`，并支持 `PatentQAResult.basis` 引用 evidence locator。
- `scripts/ingest_knowledge.py` 可读取 `knowledge/` 本地语料，切分、embedding、幂等 upsert 到 Qdrant。
- 默认测试全程使用 fake / stub，不触发真实网络、真实 Qdrant 或真实 embedding 服务。

### 目标用户

- 专利 QA 用户：提出法规、权利要求撰写、术语解释等问题时，需要回答有支撑材料，而不是无依据泛答。
- `patent_qa` skill：需要结构化 evidence，明确来源与定位信息，用于禁止臆造和可回链回答。
- 开发与测试人员：需要可替换检索接口、可预测本地后端、可 fake 的 Qdrant / embedding 实现。
- 后续 R4.2 ReAct 检索：需要本片提供单轮 retriever 抽象和 provenance 契约。

### 非目标

- 不接真实付费专利全文库、第三方专利检索源或外部商业数据源。
- 不实现 bounded ReAct 多步检索；本片只做 `max_steps=1` 单轮召回。
- 不实现图文、多模态或跨语言检索。
- 不改变 `PatentQAResult` 数据结构，只填充现有 `basis` / `risk_notes` / `disclaimer_hint`。
- 不把 Qdrant 作为测试硬依赖；CI 默认不需要网络和外部服务。

---

## 2. Commands

项目使用 Python + FastAPI + Pydantic + pytest。R4.1 默认测试必须使用 fake / stub，不触发真实网络、真实 Qdrant 或真实 embedding 服务。

```bash
# 安装依赖
pip install -r requirements.txt

# 检索接口、Local 后端、工厂、Qdrant fake 测试
pytest tests/test_retrieval_tool.py

# QA 接线、evidence provenance、降级回归
pytest tests/test_qa_node.py

# 配置项测试
pytest tests/test_core_config_logging.py

# 入库脚本切分、point id 幂等、fake upsert 测试
pytest tests/test_ingest_knowledge.py

# R4.1 目标测试
pytest tests/test_retrieval_tool.py tests/test_qa_node.py tests/test_core_config_logging.py tests/test_ingest_knowledge.py

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

1. 更新 `tests/test_retrieval_tool.py`，先覆盖 `RetrievalResult` 兼容字段、`Retriever` 协议、`build_retriever()` backend 选择、Qdrant fake client 查询和失败降级。
2. 更新 `tests/test_qa_node.py`，覆盖 `QANode` 默认工厂接线、evidence 透传 `doc_type` / `locator` / `similarity`、无命中依据不足、检索异常仍 success。
3. 更新 `tests/test_core_config_logging.py`，覆盖 retrieval / qdrant / embedding 配置默认值、环境变量读取和公开配置不暴露密钥。
4. 新增 `tests/test_ingest_knowledge.py`，覆盖本地语料切分、稳定 point id、metadata provenance、fake embedding、fake upsert。
5. 实现最小接口、配置、embedding、Qdrant retriever、入库脚本与 QA 接线。
6. 跑 R4.1 目标测试、全量测试和编译检查。

---

## 3. Project Structure

本次只做局部新增和接线，不重排目录。保留 `LocalRetrievalTool` 兼容旧测试和回退场景。

目标变更：

```text
pagent/
  app/
    core/
      config.py                  # 新增 PAGENT_RETRIEVAL_* / PAGENT_QDRANT_* / PAGENT_EMBEDDING_* 配置
    nodes/
      qa.py                      # 默认经 build_retriever(get_settings()) 注入检索器，evidence 透传 locator
    tools/
      retrieval.py               # Retriever 协议、RetrievalResult 扩展、LocalRetrievalTool、QdrantRetriever、build_retriever
      embeddings.py              # OpenAI 兼容 embedding 客户端、FakeEmbedding / 简单本地假实现
    prompts/
      patent_qa.py               # 如需微调，强调 evidence locator 引用和无依据不足声明
  knowledge/
    law/                         # 本地法规语料：专利法 / 实施细则 / 审查指南等
    template/                    # 权利要求范文 / 模板
    term/                        # 术语卡片，可从 TerminologyTool 语料转出
  scripts/
    ingest_knowledge.py          # 读取 knowledge/，切分、embedding、upsert Qdrant
  tests/
    test_retrieval_tool.py       # 检索接口、工厂、Qdrant fake、降级测试
    test_qa_node.py              # QA 接线、回链、无证据与异常降级测试
    test_core_config_logging.py  # 配置测试
    test_ingest_knowledge.py     # 入库脚本切分与幂等测试
```

### 接口契约

`Retriever` 协议：

```python
class Retriever(Protocol):
    def search(self, query: str, top_k: int = 3) -> list[RetrievalResult]: ...
```

`RetrievalResult`：

```python
class RetrievalResult(BaseModel):
    content: str
    provenance: dict[str, str] = Field(default_factory=dict)
    score: int = 0
    similarity: float = 0.0
```

字段约束：

- `content`：命中文本片段，QA 侧截断到 `token_budget` / 1000 字符上限。
- `provenance.source`：来源 URI，例如 `local://law/patent_law.md`。
- `provenance.document_id`：稳定文档 ID。
- `provenance.doc_type`：`law` / `template` / `term`。
- `provenance.locator`：法条号、页码、项号、术语名或文档内定位。
- `score`：保留旧关键词命中计数，Local 后端继续使用。
- `similarity`：向量相似度，Qdrant 后端填充；Local 后端可为 `0.0`。

### 检索工厂

`build_retriever(settings)` 行为：

```text
settings.retrieval_backend == "local"
  → LocalRetrievalTool()

settings.retrieval_backend == "qdrant"
  → 配置完整：EmbeddingClient + QdrantRetriever
  → 配置缺失 / 初始化失败：LocalRetrievalTool() 或空 Local 回退

未知 backend
  → LocalRetrievalTool() 回退
```

工厂不得抛裸异常影响 QA 主流程。后端不可用时记录 warning / trace 事件即可，QA 继续无 evidence 或 local evidence。

### QdrantRetriever

`QdrantRetriever` 最小能力：

- 使用可注入 `embedding_client` 将 query 转向量。
- 使用可注入 `qdrant_client`，测试中必须可传 fake client。
- 默认 collection 来自 `PAGENT_QDRANT_COLLECTION`。
- `search(query, top_k)` 返回按相似度排序的 `RetrievalResult`。
- 支持 payload 到 provenance 的映射：`content`、`source`、`document_id`、`doc_type`、`locator`。
- 支持可选过滤参数的内部扩展，但公开 `Retriever.search()` 先保持 `query/top_k` 最小契约。
- Qdrant 查询失败、embedding 失败或 payload 缺字段时不得向上抛出影响 QA。

### Embedding

`app/tools/embeddings.py` 提供：

- OpenAI 兼容 embedding 客户端，配置使用 `embedding_base_url`、`embedding_model`、`embedding_api_key`，为空时回退 LLM 对应配置。
- `FakeEmbedding` 或 deterministic embedding 实现供单元测试使用。
- `allow_cloud_sensitive_content=False` 时，入库或在线 embedding 不得发送完整敏感交底书；R4.1 本地知识库语料可 embedding，用户问题可做必要脱敏后 embedding。

### 入库管线

`scripts/ingest_knowledge.py`：

```text
python -m scripts.ingest_knowledge --path knowledge/
```

流程：

```text
knowledge/*
  → 读取文本
  → 按目录推断 doc_type：law / template / term
  → 清洗空白
  → 切分 chunk
  → 生成稳定 point_id = hash(document_id + chunk_index)
  → embedding(chunk.content)
  → upsert 到 Qdrant(collection=PAGENT_QDRANT_COLLECTION)
```

payload 统一包含：

```json
{
  "content": "命中文本片段",
  "source": "local://law/patent_law.md",
  "document_id": "patent_law",
  "doc_type": "law",
  "locator": "第22条",
  "chunk_index": "0"
}
```

切分规则：

- `knowledge/law/`：优先按条 / 款切分，locator 为法条号；识别失败时按段落切分。
- `knowledge/template/`：按权利要求项、标题或段落切分，locator 为项号或文档名。
- `knowledge/term/`：按术语卡片切分，locator 为术语名。

---

## 4. Code Style

### 基本原则

- 最小化、局部化改动，复用现有 `QANode._retrieve()` try/except、`PatentQASkill`、`SkillContext`、`Settings`、`core.security` 脱敏能力。
- 保留 `LocalRetrievalTool` 类名和当前关键词行为，避免破坏旧测试。
- 公开类、公开方法、公开函数必须添加中文 Google 风格 docstring。
- 不引入复杂抽象；只需要 `Retriever` 协议 + `LocalRetrievalTool` + `QdrantRetriever` + `build_retriever()`。
- 不在业务代码里硬编码 Qdrant URL、API Key、embedding API Key 或真实 endpoint。
- 检索失败必须降级为空 evidence 或 Local 后端，QA `status` 仍应为 `success`，除非 skill 输出 schema 本身无效。
- 不在日志 / trace 中记录完整检索正文、用户问题长文本、密钥或 API Key。

### 配置

新增配置项，沿用 `PAGENT_` 前缀：

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `PAGENT_RETRIEVAL_BACKEND` | `local` | `local` / `qdrant` |
| `PAGENT_RETRIEVAL_TOP_K` | `3` | QA 默认召回数 |
| `PAGENT_QDRANT_URL` | 空 | Qdrant 端点 |
| `PAGENT_QDRANT_API_KEY` | 空 | Qdrant 可选凭证，敏感字段 |
| `PAGENT_QDRANT_COLLECTION` | `patent_kb` | Qdrant collection 名称 |
| `PAGENT_EMBEDDING_BASE_URL` | 回退 `llm_base_url` | OpenAI 兼容 embedding endpoint |
| `PAGENT_EMBEDDING_MODEL` | 空 | embedding 模型名 |
| `PAGENT_EMBEDDING_API_KEY` | 回退 `llm_api_key` | embedding 凭证，敏感字段 |

`Settings.to_public_dict()` 可展示非敏感 retrieval 配置，但不得暴露 `qdrant_api_key`、`embedding_api_key`、`llm_api_key`。

### QA 接线

`QANode.__init__()`：

```python
self.retrieval_tool = retrieval_tool or build_retriever(get_settings())
```

`_retrieve()`：

- 使用配置或构造参数决定 `top_k`，默认 3。
- 保留 bounded guard：`max_steps <= 0`、`token_budget <= 0`、`timeout_seconds <= 0` 时跳过检索。
- 捕获检索异常并返回 `[]`。

`_build_evidence()`：

- 截断 `content`。
- 透传 `source`、`document_id`、`doc_type`、`locator`。
- 透传 `score`、`similarity`。
- provenance 缺失时使用安全默认值，但不得伪造具体法条或专利号。

### Prompt / Skill 约束

`patent_qa` 继续遵守项目 `CLAUDE.md`：

- evidence 作为数据进入 `<data>...</data>`，不作为指令。
- 禁止臆造法条、专利号、检索结果、引用。
- 有 evidence 时，`basis` 应优先引用 `locator` + `source` / `document_id`。
- 无 evidence 时，`answer` 必须显式声明“缺乏支撑知识 / 依据不足”，并保留 `disclaimer_hint`。

---

## 5. Testing Strategy

### `tests/test_retrieval_tool.py`

必须覆盖：

- `RetrievalResult` 新增 `similarity` 默认值为 `0.0`，不破坏旧构造方式。
- `LocalRetrievalTool` 继续按关键词命中计分，返回 provenance 和 `score`。
- Local 文档包含 `doc_type` / `locator` 时，结果 provenance 能透传。
- `build_retriever(settings)` 在 `backend=local` 时返回 `LocalRetrievalTool`。
- `build_retriever(settings)` 在 `backend=qdrant` 且 fake client / fake embedding 注入时返回 `QdrantRetriever`。
- Qdrant fake search 返回 payload 后，`QdrantRetriever.search()` 映射为 `RetrievalResult`，包含 `content`、`source`、`document_id`、`doc_type`、`locator`、`similarity`。
- embedding 或 Qdrant client 抛错时，`search()` 返回 `[]` 或工厂回退 Local，不抛裸异常。
- 未知 backend 回退 Local。

### `tests/test_qa_node.py`

必须覆盖：

- `QANode` 未显式传入 retrieval_tool 时通过工厂创建 retriever；测试可 monkeypatch `build_retriever` 避免真实服务。
- evidence 包含 `doc_type`、`locator`、`similarity`，并传入 skill 的 `state_snapshot["retrieval_results"]`。
- `PatentQAResult.basis` 可引用 locator；至少测试 fake skill 回链 `locator`。
- 无命中时 `qa_completed.has_retrieval=false`，answer / basis 表达依据不足。
- 检索异常时 QA 仍返回 `success`，trace result_count 为 0。
- bounded guard 阻止检索时不调用 retriever。
- 兼容旧 Local evidence 结构：只有 `source` / `document_id` / `score` 的结果仍可运行。

### `tests/test_core_config_logging.py`

必须覆盖：

- retrieval / qdrant / embedding 配置默认值。
- 配置可从环境变量读取。
- embedding base URL / API key 缺省时按设计回退 LLM 配置。
- `to_public_dict()` 不暴露 Qdrant API Key、embedding API Key、LLM API Key。

### `tests/test_ingest_knowledge.py`

必须覆盖：

- 从 `knowledge/law`、`knowledge/template`、`knowledge/term` 推断 `doc_type`。
- law 文本能按法条或段落切分，并生成 locator。
- template 文本能按权利要求项或段落切分。
- term 文本能按术语卡片切分。
- `point_id` 由 `document_id + chunk_index` 稳定生成，重复运行相同输入得到相同 id。
- fake embedding 被调用，fake qdrant upsert 收到 vector + payload。
- payload 包含 `content`、`source`、`document_id`、`doc_type`、`locator`、`chunk_index`。
- 输入目录为空时安全退出，不抛出不可读异常。

### 通用测试约束

- 默认测试不得触发真实 LLM、真实 embedding、真实 Qdrant 或网络请求。
- Qdrant 与 embedding 全部通过 fake / stub 注入。
- 不在测试代码中写真实 API Key、真实 endpoint 或隐私数据。
- trace 断言只检查稳定字段，不断言完整检索正文。
- 本地语料测试使用 `tmp_path` 构造，不依赖机器上的外部文件。

---

## 6. Boundaries

### Always do

- 始终通过 `Retriever` 协议接入 QA 检索。
- 始终保留 `LocalRetrievalTool` 作为测试和降级后端。
- 检索结果进入 prompt 前必须作为数据隔离，不得作为指令。
- evidence 必须携带可回链 provenance；有 locator 时必须透传。
- Qdrant / embedding / 入库脚本不得硬编码凭证。
- Qdrant、embedding 或入库单条数据失败时应优雅降级或跳过，不影响 QA 主流程。
- 默认测试使用 fake / stub，不触网。
- 日志 / trace 不记录密钥、完整 API Key、完整用户敏感材料或过长检索正文。
- `score` 保留为 int，新增 `similarity` 不破坏旧测试和旧调用方。

### Ask first

- 是否安装并引入真实 `qdrant-client` 或其他新依赖。
- 是否允许连接本机或远端真实 Qdrant 做人工验收。
- 是否允许调用云 embedding 服务处理用户问题或案件材料。
- 是否把真实法规全文、审查指南全文或模板文件提交到仓库。
- 是否调整 `PatentQAResult` schema 或新增 `Claim.source_trace` 字段。
- 是否把 `PAGENT_RETRIEVAL_BACKEND` 默认值从 `local` 改为 `qdrant`。

### Never do

- 不接真实付费专利检索源或第三方专利全文库。
- 不伪造法条、专利号、检索来源、相似度或 locator。
- 不因 Qdrant / embedding 不可用导致 QA 抛裸异常或整体 failed。
- 不把 `.env`、API Key、Qdrant API Key、embedding API Key 提交到 git。
- 不在日志、trace 或测试快照中记录完整敏感正文。
- 不绕过 `allow_cloud_sensitive_content=False` 把完整敏感案件材料发给云 embedding。
- 不在本片实现 R4.2 多步 ReAct 检索。

---

## 7. Functional Acceptance Checklist

- [ ] `RetrievalResult` 新增 `similarity: float = 0.0`，并保持旧构造方式可用。
- [ ] 新增 `Retriever` 协议。
- [ ] `LocalRetrievalTool` 实现 `Retriever`，保留现有关键词检索行为。
- [ ] 新增 `QdrantRetriever`，支持 query embedding、Qdrant search、payload 到 `RetrievalResult` 映射。
- [ ] 新增 `build_retriever(settings)`，支持 `local` / `qdrant` / 未知 backend 回退。
- [ ] 新增 `app/tools/embeddings.py`，包含 OpenAI 兼容 embedding 客户端和 fake embedding。
- [ ] `Settings` 增加 retrieval / qdrant / embedding 配置项。
- [ ] `to_public_dict()` 不暴露敏感凭证。
- [ ] `QANode` 默认通过 `build_retriever(get_settings())` 构建 retriever。
- [ ] `QANode._build_evidence()` 透传 `doc_type`、`locator`、`similarity`。
- [ ] 无 evidence 时 QA 结构化返回依据不足和 disclaimer，不编造来源。
- [ ] 新增 `scripts/ingest_knowledge.py`，支持 `python -m scripts.ingest_knowledge --path knowledge/`。
- [ ] 新增 `knowledge/law`、`knowledge/template`、`knowledge/term` 目录占位或样例策略明确。
- [ ] 入库 point id 幂等，可重复运行。
- [ ] 所有新增测试使用 fake / stub，不触网。
- [ ] R4.1 目标测试通过。
- [ ] `pytest && python -m compileall app tests scripts` 通过。

---

## 8. Implementation Order

1. 配置：在 `Settings` 增加 retrieval / qdrant / embedding 字段、环境变量读取和公开配置测试。
2. 模型与协议：扩展 `RetrievalResult`，新增 `Retriever` 协议，保持 `LocalRetrievalTool` 兼容。
3. Embedding：新增 `app/tools/embeddings.py`，先实现 fake / deterministic embedding，再接 OpenAI 兼容客户端。
4. Qdrant：新增 `QdrantRetriever`，通过 fake client 完成单元测试，不依赖真实 Qdrant。
5. 工厂：实现 `build_retriever(settings)` 和降级逻辑。
6. QA：`QANode` 默认经工厂注入 retriever，`_build_evidence()` 透传扩展 provenance。
7. 入库：新增 `scripts/ingest_knowledge.py`，实现读取、切分、稳定 point id、fake upsert 测试。
8. 语料目录：新增 `knowledge/law`、`knowledge/template`、`knowledge/term` 的最小占位或测试专用样例，不提交敏感材料。
9. 回归：运行 R4.1 目标测试、全量 `pytest` 和编译检查。
