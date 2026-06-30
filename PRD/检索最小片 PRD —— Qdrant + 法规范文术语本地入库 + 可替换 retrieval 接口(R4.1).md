<aside>
 🎯

一句话:把 QA 的 `LocalRetrievalTool`(空文档关键词匹配)升级为「**可替换 Retriever 接口 + Qdrant 向量召回 + 法规/范文/术语本地入库**」,**修好「QA 没有支撑知识无法回答」**。对齐 Requirements R4.1(补齐 retrieval 工具)与 D3(mock/本地 + 可替换接口,不接付费源)。

</aside>

## 1. 背景与问题

现状(已读代码确认):

- `app/nodes/qa.py` 通过 `LocalRetrievalTool().search(question, top_k=3)` 取证据,但 `LocalRetrievalTool.documents` **默认空** → 永远返回 `[]` → evidence 空 → `patent_qa` skill **无支撑材料** → 用户说的「没有支撑知识无法回答」。
- `app/tools/retrieval.py` 仅做 `query.split()` 关键词包含计数(`score: int`),无语义、无真实知识库。
- 没有 `Retriever` 抽象、没有 embedding、没有知识入库管线。

结论:本片补「**可替换检索接口 + 向量后端 + 本地知识入库 + provenance 回链**」,且保持降级安全。

## 2. 目标 / 非目标

**目标**

- G1 **可替换 Retriever 协议**:`search(query, top_k) -> list[RetrievalResult]`,与现有 `RetrievalResult` 兼容。
- G2 **QdrantRetriever 实现**:本地 Qdrant(docker / embedded),向量召回 + payload 过滤(按 `doc_type` / 法条号)。
- G3 **知识入库管线**:法规(专利法/审查指南)、范文/模板(权利要求范文)、术语表 → 切分 → embedding → 入 Qdrant,保留 provenance(`source`/`document_id`/法条号/页码)。
- G4 **工厂 `build_retriever(settings)`**:按 backend 选 Qdrant 或 Local(回退/测试),与 `build_llm_client` 对称;`QANode` 经工厂注入,不再硬编码 `LocalRetrievalTool`。
- G5 **provenance 回链**:命中证据来源透传到 `PatentQAResult.basis`(并为 `Claim.source_trace` 预留),满足「禁止臆造、可回链」([CLAUDE.md](http://CLAUDE.md) R5)。
- G6 **优雅降级**:Qdrant / embedding 不可用 → 回退 Local 或空证据,QA 仍出结构化答复并带 `disclaimer`,绝不抛裸异常(沿用 `qa._retrieve` 的 try/except)。

**非目标**

- 不接真实付费专利检索源 / 第三方专利全文库(D3)。
- 不实现 bounded ReAct 多步检索(R4.2,后续);本片 `max_steps=1` 单轮召回。
- 不做图文多模态检索。
- 不改 `PatentQAResult` 结构(只填充 `basis`/`risk_notes`)。

## 3. 范围

- 重构 `app/tools/retrieval.py`:抽出 `Retriever` Protocol;`LocalRetrievalTool` 实现该协议(保留作回退/测试);新增 `QdrantRetriever`;新增 `build_retriever(settings)`。
- 新增 `app/tools/embeddings.py`:OpenAI 兼容 embedding 客户端(复用 `base_url`/`api_key`),`FakeEmbedding` 供测试。
- 新增入库脚本 `scripts/ingest_knowledge.py` + 本地语料目录 `knowledge/`(`law/`、`template/`、`term/`)。
- 改 `app/nodes/qa.py`:`retrieval_tool` 默认走 `build_retriever()`;`_build_evidence` 透传扩展 provenance。
- 改 `app/core/config.py`:retrieval / embedding 配置项。
- `RetrievalResult` 扩展(见 §5 兼容方案)。

## 4. 架构 / 流程

```
[离线入库]  knowledge/*  → 清洗 → 切分 → embedding → upsert Qdrant(collection)
[在线问答]  qa → build_retriever(settings) → embed(query) → Qdrant search(top_k, filter)
               → RetrievalResult[] → _build_evidence → patent_qa skill(user_data 走 <data>)
               → PatentQAResult(basis 含 locator 回链)
```

## 5. 接口契约

`Retriever`(Protocol):`search(query: str, top_k: int = 3) -> list[RetrievalResult]`。

`RetrievalResult` 扩展(**向后兼容**):

| 字段         | 类型            | 说明                                                         |
| ------------ | --------------- | ------------------------------------------------------------ |
| `content`    | `str`           | 命中片段(QA 侧截断至 1000)                                   |
| `provenance` | `dict[str,str]` | `source`/`document_id`  • 新增 `doc_type`/`locator`(法条号·页码·项号) |
| `score`      | `int`           | **保留**兼容旧测试(关键词命中计数)                           |
| `similarity` | `float = 0.0`   | **新增**向量相似度;Local 后端可为 0                          |

- 兼容:新增字段给默认值,`qa._build_evidence` 现有对 `source`/`document_id` 的读取不受影响。

## 6. 知识来源与切分

| 来源                           | doc_type   | 切分粒度     | provenance.locator |
| ------------------------------ | ---------- | ------------ | ------------------ |
| 专利法 / 实施细则 / 审查指南   | `law`      | 按条 / 款    | 法条号             |
| 权利要求范文 / 模板            | `template` | 按权利要求项 | 项号 / 文档名      |
| 术语表(复用 `TerminologyTool`) | `term`     | 术语卡片     | 术语名             |

- 元数据统一:`source=local://...`、`document_id`、`doc_type`、`locator`。

## 7. 入库管线

- `scripts/ingest_knowledge.py`:读取 `knowledge/` → 清洗 → 切分 → embedding → `upsert` Qdrant(`collection=PAGENT_QDRANT_COLLECTION`)。
- **幂等**:`point_id` 由 `document_id + chunk_index` 生成稳定 id,可重跑。
- CLI:`python -m scripts.ingest_knowledge --path knowledge/`。

## 8. QA 接线与回链

- `qa.py`:`self.retrieval_tool = retrieval_tool or build_retriever(get_settings())`。
- `_build_evidence` 透传 `doc_type`/`locator`;skill 已把 `retrieval_results` 放入 `user_data`(指令/数据分离)。
- `PatentQAResult.basis` 要求引用 evidence 的 `locator`;**无证据时** `answer` 必须显式声明「缺乏支撑知识 / 依据不足」并走 `disclaimer_hint`,**不得编造**([CLAUDE.md](http://CLAUDE.md) R5 禁止臆造)。

## 9. 配置(`PAGENT_` 前缀)

| 配置                        | 默认                | 说明                               |
| --------------------------- | ------------------- | ---------------------------------- |
| `PAGENT_RETRIEVAL_BACKEND`  | `local`             | `qdrant`/`local`;部署后切 `qdrant` |
| `PAGENT_QDRANT_URL`         | 空                  | Qdrant 端点                        |
| `PAGENT_QDRANT_API_KEY`     | 空                  | 可选鉴权                           |
| `PAGENT_QDRANT_COLLECTION`  | `patent_kb`         | 集合名                             |
| `PAGENT_EMBEDDING_BASE_URL` | 回退 `llm_base_url` | embedding 端点                     |
| `PAGENT_EMBEDDING_MODEL`    | 空                  | embedding 模型                     |
| `PAGENT_EMBEDDING_API_KEY`  | 回退 `llm_api_key`  | 凭证(env only)                     |
| `PAGENT_RETRIEVAL_TOP_K`    | `3`                 | 召回数                             |

## 10. 安全与合规

- 检索内容入 prompt 走 `<data>` 分隔(已具备);query embedding 前过脱敏。
- `allow_cloud_sensitive_content=False` 时不把完整交底书发送给云 embedding。
- 凭证只走环境变量,不入日志 / trace。

## 11. 验收标准 / 测试

`tests/test_retrieval.py`、`tests/test_qa_node.py`:

- [ ]  `build_retriever`:`backend=local` → `LocalRetrievalTool`;`=qdrant` → `QdrantRetriever`(注入 fake client)。
- [ ]  入库后 QA:对法规类问题召回到对应法条,evidence 非空,`qa_completed.has_retrieval=true`。
- [ ]  回链:`basis` 含 `locator`;无命中 → `answer` 声明依据不足 + `disclaimer`,不编造。
- [ ]  降级:Qdrant 连接失败 → 回退空/local,QA `status` 仍 `success`。
- [ ]  兼容:`RetrievalResult` 新字段默认值不破坏既有 `qa._build_evidence` 与测试;单测全程用 Fake,不触网。

## 12. 风险与取舍

- **`score`(int)→ 相似度**:新增 `similarity: float`,保留 `score` 兼容旧测试。
- **本地 vs 云嵌入**:默认可配;敏感内容默认不出域。
- **Qdrant 运维**:docker 单容器即可;CI 用 fake/local 不依赖网络。
- **后端默认 `local`**:不破坏现状;入库 + 部署 Qdrant 后再切 `qdrant`。