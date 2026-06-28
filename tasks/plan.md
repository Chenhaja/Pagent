# R4.1 检索最小片执行计划

## Context

R4.1 要补齐 QA 的“可替换检索接口 → 向量召回 → 本地知识入库 → evidence provenance 回链”最小闭环。当前 `QANode` 在 `app/nodes/qa.py` 中硬编码 `LocalRetrievalTool()`，而 `LocalRetrievalTool.documents` 默认空，导致 QA 默认没有任何支撑知识；`RetrievalResult` 也只有 `content`、`provenance`、`score`，缺少向量相似度和更细 provenance。

本计划只实现单轮检索最小片：保留 `LocalRetrievalTool` 作为测试 / 降级后端，新增 `Retriever` 协议、OpenAI 兼容 embedding、`QdrantRetriever`、`build_retriever(settings)`、QA evidence 透传和本地入库脚本。不接付费专利源，不实现 R4.2 多步 ReAct，不让测试依赖真实网络或真实 Qdrant。

## 依赖图

```text
任务 0 计划文档落地
  ↓
任务 1 配置入口：PAGENT_RETRIEVAL_* / QDRANT_* / EMBEDDING_*
  ↓
任务 2 检索契约薄片：RetrievalResult 扩展 + Retriever 协议 + Local 兼容
  ↓
任务 3 Embedding 客户端：Fake + OpenAI 兼容接口 + 脱敏边界
  ↓
任务 4 Qdrant 单轮检索：fake client 驱动的 QdrantRetriever
  ↓
任务 5 Retriever 工厂与降级：local/qdrant/未知 backend
  ↓
任务 6 QA 垂直接线：默认工厂注入 + evidence provenance 回链
  ↓
任务 7 本地知识入库：knowledge/* 切分 + point_id 幂等 + fake upsert
  ↓
任务 8 回归与最终验收：目标测试 + 全量测试 + compileall
```

## 关键复用点

- `app/tools/retrieval.py`：保留 `LocalRetrievalTool` 类名和关键词行为，扩展为实现 `Retriever` 协议；新增 `QdrantRetriever` 和 `build_retriever()`。
- `app/nodes/qa.py`：复用 `_retrieve()` 的 bounded guard 与 try/except；只改默认检索器来源和 `_build_evidence()` 透传字段。
- `app/core/config.py`：沿用 `Settings`、`.env` 加载、`to_public_dict()` 敏感字段排除模式。
- `app/core/security.py`：复用 `redact_sensitive_text()`；在线 query embedding 前可先脱敏，日志 / trace 不写完整正文。
- `app/tools/llm.py`：Embedding 客户端可复用 OpenAI 兼容 HTTP 调用风格，但不耦合 Chat Completions。
- `app/prompts/patent_qa.py`：已有 `<data>` 数据隔离和禁止臆造约束；必要时只补强 locator 引用，不重写 prompt 架构。
- `tests/test_retrieval_tool.py` / `tests/test_qa_node.py`：优先扩展现有测试，保持旧断言兼容。

## 垂直任务

### 任务 0：落地 R4.1 计划文件

**修改文件**
- `tasks/plan.md`
- `tasks/todo.md`

**实施内容**
- 将本执行计划写入 `tasks/plan.md`。
- 将任务拆成可勾选清单写入 `tasks/todo.md`，包含文件范围、验收标准、验证命令和阻塞关系。

**验收标准**
- 两个文件存在且内容与 R4.1 `SPEC.md` 对齐。
- 任务按可验证垂直切片组织，每个阶段都能独立跑局部测试。

**验证**
- 人工检查 `tasks/plan.md`、`tasks/todo.md`。

**检查点 CP0**
- R4.1 后续实现范围、依赖和验收命令明确。

---

### 任务 1：配置入口最小闭环

**修改文件**
- `app/core/config.py`
- `tests/test_core_config_logging.py`

**实施内容**
- 在 `Settings` 增加：
  - `retrieval_backend: str = "local"`
  - `retrieval_top_k: int = 3`
  - `qdrant_url: str | None = None`
  - `qdrant_api_key: str | None = Field(default=None, exclude=True)`
  - `qdrant_collection: str = "patent_kb"`
  - `embedding_base_url: str | None = None`
  - `embedding_model: str = ""`
  - `embedding_api_key: str | None = Field(default=None, exclude=True)`
- 在 `get_settings()` 读取对应 `PAGENT_*` 环境变量。
- 明确 embedding 回退口径：调用侧使用 `embedding_base_url or llm_base_url`、`embedding_api_key or llm_api_key`。
- `Settings.to_public_dict()` 展示非敏感 retrieval / qdrant / embedding 配置，不暴露任何 key。
- 增加默认值、环境变量读取、公开配置不暴露敏感字段的测试。

**验收标准**
- 默认 backend 为 `local`，不改变现有运行行为。
- `PAGENT_RETRIEVAL_TOP_K` 默认 3，可被环境变量覆盖。
- qdrant / embedding API key 不出现在 `to_public_dict()`。
- 测试不触网。

**验证**
```bash
pytest tests/test_core_config_logging.py
```

**检查点 CP1**
- 后续 retriever / embedding / ingest 不需要硬编码配置。

---

### 任务 2：检索契约与 Local 兼容

**修改文件**
- `app/tools/retrieval.py`
- `tests/test_retrieval_tool.py`

**实施内容**
- 新增 `Retriever` 协议：`search(query: str, top_k: int = 3) -> list[RetrievalResult]`。
- 扩展 `RetrievalResult`：新增 `similarity: float = 0.0`。
- 更新 `RetrievalResult` docstring，说明 `provenance` 可含 `source`、`document_id`、`doc_type`、`locator`。
- 保持旧构造方式可用，现有 `RetrievalResult(content=..., provenance=..., score=...)` 不变。
- `LocalRetrievalTool` 继续关键词计分；当 document 中存在 `doc_type` / `locator` 时透传到 provenance。
- 增加 Local 兼容测试和新增字段默认值测试。

**验收标准**
- 旧 `tests/test_retrieval_tool.py` 仍通过。
- `RetrievalResult.similarity` 默认 `0.0`。
- Local 后端可透传 `doc_type` / `locator`，无字段时保持旧 provenance。
- 不引入外部依赖，不触网。

**验证**
```bash
pytest tests/test_retrieval_tool.py
```

**检查点 CP2**
- QA 仍可使用 Local 后端，且 retrieval 契约已稳定。

---

### 任务 3：Embedding 客户端薄片

**修改文件**
- `app/tools/embeddings.py`（新增）
- `tests/test_retrieval_tool.py` 或新增 embedding 相关测试放入该文件

**实施内容**
- 新增 `EmbeddingClient` 协议：`embed(text: str) -> list[float]`。
- 新增 `FakeEmbedding`：返回 deterministic vector，记录调用文本，供测试断言。
- 新增 OpenAI 兼容 embedding 客户端：
  - 使用 `settings.embedding_base_url or settings.llm_base_url`。
  - 使用 `settings.embedding_api_key or settings.llm_api_key`。
  - 使用 `settings.embedding_model`。
  - HTTP payload 走 `/embeddings` 风格或由 base URL 直接拼接最小实现；缺配置时返回结构化错误或抛内部异常供上层降级。
- 在线 embed 前使用 `redact_sensitive_text()` 做基础脱敏；trace 不写完整正文。
- 测试只用 fake urlopen / fake embedding，不触网。

**验收标准**
- `FakeEmbedding.embed()` 可预测且无网络。
- OpenAI 兼容客户端能用 fake HTTP 响应解析 vector。
- 缺配置或 HTTP 失败不会泄漏 key 到异常消息 / trace。
- 有中文 docstring。

**验证**
```bash
pytest tests/test_retrieval_tool.py
```

**检查点 CP3**
- QdrantRetriever 可依赖统一 embedding 协议实现向量召回。

---

### 任务 4：Qdrant 单轮检索闭环

**修改文件**
- `app/tools/retrieval.py`
- `tests/test_retrieval_tool.py`

**实施内容**
- 新增 `QdrantRetriever`：
  - 构造参数支持 `collection_name`、`embedding_client`、`qdrant_client`。
  - `search(query, top_k)` 调用 embedding，再调用 qdrant fake / real client 的 search/query 方法。
  - 将 Qdrant hit payload 映射为 `RetrievalResult`。
  - `hit.score` 或等价字段映射到 `similarity`。
  - payload 缺失时使用 `local://unknown` / `unknown` 等安全默认值，但不得伪造具体法条。
- 支持 fake client 的最小接口，避免测试依赖真实 `qdrant-client`。
- 捕获 embedding / qdrant 异常，返回 `[]`。

**验收标准**
- fake Qdrant hit 可返回 content、source、document_id、doc_type、locator、similarity。
- top_k 会传给 fake client。
- embedding 或 Qdrant 抛错时 `search()` 返回 `[]`。
- 不要求安装真实 Qdrant 依赖即可通过测试。

**验证**
```bash
pytest tests/test_retrieval_tool.py
```

**检查点 CP4**
- 单轮向量召回路径可在 fake 环境下端到端验证。

---

### 任务 5：Retriever 工厂与降级

**修改文件**
- `app/tools/retrieval.py`
- `tests/test_retrieval_tool.py`

**实施内容**
- 新增 `build_retriever(settings)`：
  - `backend=local` 返回 `LocalRetrievalTool()`。
  - `backend=qdrant` 且配置完整时返回 `QdrantRetriever`。
  - qdrant 配置缺失、初始化失败或未知 backend 时回退 `LocalRetrievalTool()`。
- 为测试提供可注入参数或 monkeypatch 点，避免真实初始化网络客户端。
- 不把 API key 写入日志或异常文本。

**验收标准**
- local / qdrant / unknown backend 三类分支均有测试。
- qdrant 缺配置回退 Local。
- 工厂不抛裸异常影响 QA 初始化。

**验证**
```bash
pytest tests/test_retrieval_tool.py
```

**检查点 CP5**
- 在线 QA 可以只依赖工厂，不关心底层后端选择。

---

### 任务 6：QA 垂直接线与 provenance 回链

**修改文件**
- `app/nodes/qa.py`
- `app/prompts/patent_qa.py`（仅必要时小幅补强）
- `tests/test_qa_node.py`

**实施内容**
- 将 `QANode.__init__()` 的 `retrieval_tool` 类型改为 `Retriever | None`，默认 `build_retriever(get_settings())`。
- `_retrieve()` 使用 `settings.retrieval_top_k` 或构造参数决定 top_k，保留 bounded guard 和异常降级。
- `_build_evidence()` 透传：
  - `provenance.source`
  - `provenance.document_id`
  - `provenance.doc_type`
  - `provenance.locator`
  - `score`
  - `similarity`
- 更新测试 fake skill，使有 locator 时 basis 可引用 locator。
- 无 evidence 时仍通过现有 skill / fake skill 输出依据不足，不编造来源。

**验收标准**
- 未显式传入 retrieval_tool 时，测试可 monkeypatch 工厂并证明被调用。
- evidence 包含新增 provenance 字段和 similarity。
- 旧 Local 结果仍兼容。
- retrieval 抛错时 QA `status == success`，`result_count == 0`。
- `qa_completed.has_retrieval` 与结果数量一致。

**验证**
```bash
pytest tests/test_qa_node.py
```

**检查点 CP6**
- 用户 QA 路径已具备“检索 evidence → skill → basis 回链”的最小闭环。

---

### 任务 7：本地知识入库脚本

**修改文件**
- `scripts/ingest_knowledge.py`（新增）
- `tests/test_ingest_knowledge.py`（新增）
- `knowledge/law/.gitkeep`、`knowledge/template/.gitkeep`、`knowledge/term/.gitkeep`（如目录不存在）

**实施内容**
- 新增 CLI：`python -m scripts.ingest_knowledge --path knowledge/`。
- 实现读取 `knowledge/law`、`knowledge/template`、`knowledge/term` 下文本文件。
- 按目录推断 `doc_type`。
- 实现最小切分：
  - law：优先识别 `第X条`，失败按段落。
  - template：优先按权利要求项 / 段落。
  - term：优先按术语卡片 / 段落。
- 生成稳定 `point_id = hash(document_id + chunk_index)`。
- payload 包含 `content`、`source`、`document_id`、`doc_type`、`locator`、`chunk_index`。
- 使用可注入 fake embedding 和 fake qdrant upsert；真实客户端构建走配置但测试不触发。
- 空目录安全退出。

**验收标准**
- 三类 doc_type 推断均有测试。
- 重复运行相同输入得到相同 point_id。
- fake upsert 收到 vector + payload。
- 不提交真实法规全文或敏感模板，只保留目录占位或测试临时文件。

**验证**
```bash
pytest tests/test_ingest_knowledge.py
python -m compileall scripts
```

**检查点 CP7**
- 离线语料入库路径可验证，且不依赖真实 Qdrant / embedding。

---

### 任务 8：回归与最终验收

**修改文件**
- R4.1 涉及的源码与测试

**实施内容**
- 运行 R4.1 目标测试。
- 运行全量测试。
- 运行编译检查。
- 检查未提交 `.env`、API Key、真实法规全文、Qdrant 凭证或本地数据库。

**验收标准**
- R4.1 目标测试通过。
- 全量 pytest 通过。
- `python -m compileall app tests scripts` 通过。
- 默认配置仍为 `local`，不要求外部服务。

**验证**
```bash
pytest tests/test_retrieval_tool.py tests/test_qa_node.py tests/test_core_config_logging.py tests/test_ingest_knowledge.py
pytest
python -m compileall app tests scripts
pytest && python -m compileall app tests scripts
```

**检查点 CP8**
- R4.1 可作为可回归的最小检索能力交付。

## 风险与控制

- **新增依赖风险**：真实 `qdrant-client` 是否加入 `requirements.txt` 需先确认；默认计划通过可注入 fake client 避免 CI 硬依赖。
- **外发敏感内容风险**：默认 `allow_cloud_sensitive_content=False`；在线 query embedding 前脱敏；不把完整交底书发给云 embedding。
- **来源臆造风险**：缺 locator 时只写 `unknown`，不得补造法条号；prompt 继续要求 basis 只能来自输入。
- **测试触网风险**：所有新增测试使用 fake embedding / fake qdrant / fake HTTP。
- **过度抽象风险**：只引入 `Retriever` 和 `EmbeddingClient` 两个协议，不新增多层 repository / adapter。
