# R4.3 检索质量增强规格说明

## 1. Objective

### 目标

R4.3 的目标是在不改 `QANode` 主流程的前提下，为现有检索层补齐四类可开关增强能力：宽召回、重排、混合检索和查询改写，提升专利 QA 的上下文召回质量与证据排序稳定性。

完成标准：

- `Retriever.search(...)` 向后兼容地支持 `fetch_k`，并可通过 `recall(query, fetch_k, as_of)` 暴露宽召回候选池。
- 默认关闭所有增强时，`build_retriever` 行为与当前纯稠密 Qdrant / Local 回退检索一致。
- 开启宽召回时，检索阶段可先取 `PAGENT_RETRIEVAL_FETCH_K` 个候选，为重排、融合和改写留排序空间。
- 开启重排时，`RerankingRetriever` 在合并后的候选池上调用 reranker，并最终截断到 `top_k` 或 `rerank_top_k`。
- 开启混合检索时，Qdrant 使用命名 dense 向量 + sparse 向量的新集合 schema，通过 RRF 融合 dense / sparse 两路召回。
- 开启查询改写时，`MultiQueryRetriever` 对多个改写式分别召回、合并去重，并可由后置重排统一排序。
- R4.2 的法规时效过滤继续透传到 Qdrant / Local 检索，不因 R4.3 包装器丢失。
- reranker、rewriter、sparse encoder 任一未配置或失败时，检索必须安全降级，不打挂 QA。
- 每个阶段都可用 `scripts.eval.ragas_eval` 与 golden set 做 A/B 对比。

### 目标用户

- 专利 QA 用户：需要更稳定地命中正确法规、办事指南、模板或术语上下文。
- QA 调用方：需要保持 `QANode` 调用契约不变，同时获得更好的 evidence 排序。
- 开发与测试人员：需要通过开关矩阵验证各增强能力的关闭态回归和开启态收益。
- 知识库维护人员：需要在不污染现有纯稠密集合的情况下灰度验证混合检索集合。

### 非目标

- 不修改 `QANode._retrieve` 调用方式，不扩展 ReAct 主循环。
- 不实现切分增强；R4.3 只保留宽召回，不做 chunk overlap / 重新切片策略。
- 不直接迁移或覆盖现有未命名稠密 Qdrant 集合；混合检索必须使用新集合灰度。
- 不默认开启重排、混合检索或查询改写。
- 不把 reranker / rewriter / sparse 服务异常暴露为 QA 失败。
- 不在本片扩充 websearch、Agentic 编排或外部案例检索。

---

## 2. Commands

项目使用 Python + pytest。R4.3 单元测试默认使用 fake / stub，不触发真实 rerank、embedding、sparse 或 Qdrant 网络请求。

```bash
# 安装依赖
pip install -r requirements.txt

# 检索层单元测试
pytest tests/test_retrieval.py

# 若检索工具测试实际拆分在独立文件
pytest tests/test_retrieval_tool.py

# 入库与 Qdrant schema / point 结构测试
pytest tests/test_ingest_knowledge.py

# R4.3 目标测试
pytest tests/test_retrieval.py tests/test_ingest_knowledge.py

# ragas 基线 / A-B 评测
python -m scripts.eval.ragas_eval
python -m scripts.eval.ragas_eval --top-k 3

# 全量测试
pytest

# 编译检查
python -m compileall app tests scripts
```

最终验收命令：

```bash
pytest && python -m compileall app tests scripts
```

阶段验收顺序：

1. 宽召回：扩展协议与 Qdrant / Local 签名，关闭态无回归。
2. 重排：新增 reranker 协议、HTTP 实现、包装器与开关，验证异常降级。
3. 混合检索：新增 sparse encoder、命名向量 schema、双向量 upsert 与 `query_hybrid` 请求体测试。
4. 查询改写：新增 rewriter 协议、multi / hyde 模式与去重逻辑，验证失败降级。
5. 每步运行 ragas A/B，对比 `NonLLMContextRecall`、`NonLLMContextPrecisionWithReference`、`item_hit`、`section_hit`。

---

## 3. Project Structure

本片应把增强能力收敛在 retrieval 层、配置层、入库脚本和测试中，不改 QA 主流程。

目标变更：

```text
pagent/
  app/
    core/
      config.py                 # 新增 R4.3 通用检索配置与公开配置输出
    tools/
      retrieval.py              # Retriever fetch_k / recall、包装器、Qdrant hybrid 查询
      redaction.py              # 复用 redact_sensitive_text 后再外发 rerank 文本
  scripts/
    ingest_knowledge.py         # 混合集合 schema、稠密+稀疏 point upsert
  tests/
    test_retrieval.py           # 宽召回、重排、混合查询、改写、开关矩阵
    test_ingest_knowledge.py    # 混合 schema 与双向量 upsert 测试
  scripts/eval/
    ragas_eval.py               # 不强制修改，作为阶段评测入口
```

### 检索组装契约

`build_retriever` 负责按开关组装能力，关闭态保持现状：

```python
def build_retriever(settings=None, embedding_client=None, qdrant_client=None,
                    reranker=None, sparse_encoder=None, query_rewriter=None) -> Retriever:
    s = settings or get_settings()
    base = _build_base_retriever(s, embedding_client, qdrant_client, sparse_encoder)

    recaller = base
    if s.retrieval_use_query_rewrite:
        recaller = MultiQueryRetriever(recaller, query_rewriter or _build_rewriter(s), settings=s)

    if s.retrieval_use_rerank:
        return RerankingRetriever(recaller, reranker or _build_reranker(s), settings=s)
    return recaller
```

关键约束：

- 重排永远在候选合并之后执行。
- 重排是最后一层截断到 `top_k` / `rerank_top_k`。
- `QANode` 仍只调用 `retrieval_tool.search(question, top_k=self.top_k)`。
- `fetch_k` 由包装器内部从配置读取并向内层透传。

### Retriever 契约

```python
class Retriever(Protocol):
    def search(self, query: str, top_k: int = 3, as_of: str | None = None,
               fetch_k: int | None = None) -> list[RetrievalResult]: ...
```

可选扩展：

```python
def recall(self, query: str, fetch_k: int, as_of: str | None = None) -> list[RetrievalResult]: ...
```

约束：

- `search` 对外语义不变：返回最多 `top_k` 条。
- `recall` 返回宽召回候选池，不按最终 `top_k` 截断。
- 未实现专门 `recall` 的检索器可用默认逻辑调用 `search(..., top_k=fetch_k, fetch_k=fetch_k)`。
- Qdrant 和 Local 检索都必须接受 `fetch_k` 形参，保持调用兼容。

### 宽召回契约

- `QdrantRetriever.search` 的 Qdrant `limit = fetch_k or top_k`。
- `LocalRetrievalTool.search` 同步扩签名；本地排序逻辑可按 `fetch_k or top_k` 截断。
- 不启用重排 / 改写 / 混合时，`fetch_k` 不应改变当前外部 `top_k` 结果语义。
- R4.2 的 `as_of` 时间过滤必须原样透传。

### 重排契约

```python
class Reranker(Protocol):
    def rerank(self, query: str, results: list[RetrievalResult],
               top_k: int) -> list[RetrievalResult]: ...
```

`HTTPReranker`：

- 调 OpenAI 兼容 `/rerank`。
- 请求体：`{"model": model, "query": query, "documents": [content...], "top_n": top_k}`。
- 响应：`{"results": [{"index": i, "relevance_score": s}, ...]}`。
- 按 `index` 取回原 `RetrievalResult`，并写回 `similarity = relevance_score`。
- 文本外发前必须复用 `redact_sensitive_text`。
- 端点、模型或 key 未配置时安全降级。

`RerankingRetriever`：

- 调用 `inner.recall(query, fetch_k or settings.retrieval_fetch_k, as_of)` 获取候选池。
- 候选为空时返回 `[]`。
- reranker 异常时返回宽召回前 `top_k` 条。
- 正常时返回 `ranked[:rerank_top_k or top_k]`。

### 混合检索契约

混合检索必须使用新 Qdrant 集合 schema，要求 Qdrant 支持 named vectors 与 sparse vectors。

集合 schema：

```json
{
  "vectors": {"dense": {"size": 1024, "distance": "Cosine"}},
  "sparse_vectors": {"sparse": {}}
}
```

upsert point：

```json
{
  "id": "...",
  "vector": {
    "dense": [],
    "sparse": {"indices": [], "values": []}
  },
  "payload": {}
}
```

融合查询：

```json
{
  "prefetch": [
    {"query": [], "using": "dense", "limit": 30},
    {"query": {"indices": [], "values": []}, "using": "sparse", "limit": 30}
  ],
  "query": {"fusion": "rrf"},
  "limit": 30,
  "with_payload": true,
  "filter": {}
}
```

约束：

- 未开启 `retrieval_use_hybrid` 时继续使用现有未命名稠密向量 schema 和 `/points/search`。
- 开启 `retrieval_use_hybrid` 时必须使用新集合名，例如 `patent_kb_hybrid`，避免污染现有 `patent_kb`。
- ingest 和 query 必须使用同一 sparse encoder 实现与同一 hash / 词表规则。
- `_build_qdrant_time_filter` 输出必须透传到 hybrid query 的 `filter`。

### SparseEncoder 契约

```python
class SparseEncoder(Protocol):
    def encode(self, text: str) -> dict: ...  # {"indices": [int...], "values": [float...]}
```

实现：

- `LocalLexicalSparseEncoder`：本地分词 / token 稳定 hash → index，计算 tf / bm25 类权重；无网络依赖。
- `ServiceSparseEncoder`：调用外部稀疏编码服务，例如 bge-m3 lexical weights。
- `FakeSparseEncoder`：测试用固定稀疏向量。

### 查询改写契约

```python
class QueryRewriter(Protocol):
    def expand(self, query: str) -> list[str]: ...
```

模式：

- `multi`：生成 N 个同义或法言法语改写式。
- `hyde`：生成假设答案 / 假设法条文本用于检索。

`MultiQueryRetriever`：

- `expand` 失败或模型未配置时降级为 `[query]`。
- 对每个 query 调用 `inner.recall(q, fetch_k, as_of)`。
- 以 `(document_id, locator, content[:64])` 作为去重 key。
- `search` 返回合并候选前 `top_k`，若后面有重排则由 `RerankingRetriever` 统一排序。

### 配置契约

新增配置均使用 `PAGENT_` 前缀，默认关闭增强能力：

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `RETRIEVAL_FETCH_K` | `30` | 重排 / 融合 / 改写前候选数 |
| `RETRIEVAL_USE_RERANK` | `false` | 是否启用重排 |
| `RERANK_BASE_URL` | 空 | OpenAI 兼容 `/rerank` 端点 |
| `RERANK_MODEL` | 空 | reranker 模型名 |
| `RERANK_API_KEY` | 空 | reranker 鉴权，敏感排除 |
| `RERANK_TOP_K` | 空 | 重排后保留数，空则回退调用方 `top_k` |
| `RETRIEVAL_USE_HYBRID` | `false` | 是否启用 dense + sparse 混合检索 |
| `SPARSE_ENCODER` | `local` | `local` 或 `service` |
| `SPARSE_BASE_URL` | 空 | service 模式稀疏端点 |
| `SPARSE_MODEL` | 空 | service 模式稀疏模型名 |
| `HYBRID_FUSION` | `rrf` | 融合方式 |
| `RETRIEVAL_USE_QUERY_REWRITE` | `false` | 是否启用查询改写 |
| `QUERY_REWRITE_MODE` | `multi` | `multi` 或 `hyde` |
| `QUERY_REWRITE_COUNT` | `3` | 改写式 / 假设文档数量 |

配置要求：

- 新增字段必须同步 `Settings` 默认值、环境变量读取、`to_public_dict()` 和配置测试。
- `rerank_api_key` 等敏感字段必须 `Field(exclude=True)`，不得进入公开配置、日志或 trace。
- 配置命名保持检索通用作用域，不新增 `qa_*` 这类单 Node 配置。

---

## 4. Code Style

### 基本原则

- 最小化、局部化改动，优先复用现有 Qdrant client、embedding client、时间过滤、payload 解析和脱敏 helper。
- 公开函数、公开方法、公开类必须添加中文 Google 风格 docstring。
- 私有小工具函数至少用一行中文概述用途。
- 关闭态必须复现当前行为，不引入无意义兼容壳或全局副作用。
- 包装器职责单一：宽召回、改写、重排、混合检索分层组合，不互相内嵌复杂逻辑。
- 不在日志中记录 API Key、完整外发文本、长文档正文或隐私数据。
- 可恢复异常使用 warning 并说明降级结果；不要让增强能力异常打挂主检索。

### 错误处理与降级

- embedding 返回空向量时保持现有安全返回行为。
- reranker 未配置或调用失败：返回宽召回前 `top_k`。
- rewriter 未配置或调用失败：使用原始 query。
- sparse encoder 失败：混合检索应降级到纯稠密检索或返回纯稠密候选，不能抛到 QA。
- Qdrant hybrid API 不可用时应给出清晰 warning，并按配置允许的最安全路径降级。

### 外部调用安全

- rerank / rewrite / sparse service 调用必须使用配置中的 base URL、model 和 key，不硬编码真实 endpoint。
- 外发 rerank 文档前必须脱敏。
- 不把用户 query、完整检索正文或服务响应长文本写入 INFO 日志。
- HTTP 超时、状态码错误和响应格式错误都按可恢复异常处理。

---

## 5. Testing Strategy

### 宽召回测试

必须覆盖：

- `Retriever.search` 接受 `fetch_k` 形参且默认调用兼容旧代码。
- `QdrantRetriever` 请求体 `limit = fetch_k or top_k`。
- `LocalRetrievalTool` 接受 `fetch_k`，并按 `fetch_k or top_k` 截断候选。
- `recall(query, fetch_k, as_of)` 返回宽候选池。
- `as_of` 时间过滤参数在宽召回中继续透传。
- 默认关闭增强时，`search(top_k=3)` 行为不变。

### 重排测试

必须覆盖：

- `RerankingRetriever.search` 调用 `inner.recall(fetch_k=settings.retrieval_fetch_k)`。
- `FakeReranker` 可按注入分数重排结果。
- 最终返回数量为 `rerank_top_k or top_k`。
- reranker 未配置或抛异常时降级为宽召回前 `top_k`。
- `HTTPReranker` 请求体包含 `model`、`query`、`documents`、`top_n`。
- `HTTPReranker` 按响应 `index` 映射回原结果，并写回 `similarity`。
- rerank 外发文本经过脱敏 helper。

### 混合检索测试

必须覆盖：

- `ensure_collection` 在 `retrieval_use_hybrid=false` 时保持现有未命名稠密 schema。
- `ensure_collection` 在 `retrieval_use_hybrid=true` 时生成 named dense + sparse schema。
- ingest hybrid point 的 `vector` 同时包含 `dense` 和 `sparse`。
- `_QdrantHTTPClient.query_hybrid` 请求体包含 dense / sparse 两路 `prefetch`、`fusion=rrf`、`limit`、`with_payload`。
- hybrid query 透传 `_build_qdrant_time_filter` 结果。
- `FakeSparseEncoder` 可稳定生成稀疏向量，测试不触网。
- sparse encoder 异常时检索安全降级。

### 查询改写测试

必须覆盖：

- `QueryRewriter.expand` 返回 `[原查询, 改写1, 改写2]` 后，`MultiQueryRetriever` 对每个 query 调用 inner recall。
- expand 抛异常或返回空时降级为 `[query]`。
- 合并去重 key 使用 `document_id`、`locator`、`content[:64]`。
- `MultiQueryRetriever.search` 在不开重排时按合并顺序截断到 `top_k`。
- 与 `RerankingRetriever` 组合时，重排作用在改写合并后的候选池上。

### 配置与开关矩阵测试

必须覆盖：

- 所有新增配置默认值正确，增强能力默认关闭。
- 非敏感配置进入 `to_public_dict()`。
- `rerank_api_key` 不进入 `to_public_dict()`。
- 开关关闭态复现当前行为。
- 单独开启宽召回、重排、混合、改写时各自只影响对应层。
- 组合开启改写 + 重排时，先改写合并，再重排截断。

### 评测验收

每个阶段建议记录：

- `NonLLMContextRecall`
- `NonLLMContextPrecisionWithReference`
- `item_hit`
- `section_hit`

验收口径：

- 关闭态指标不应低于当前基线。
- 宽召回应保持或提升 recall，不应显著降低 precision。
- 重排应提升 top_k=3 的 precision 或 section_hit。
- 混合检索重点观察术语类、条号类、精确关键词类问题。
- 查询改写默认关，只有在与重排搭配有稳定增益时才考虑后续默认开启。

---

## 6. Boundaries

### Always do

- 始终保持所有 R4.3 增强默认关闭。
- 始终让关闭态行为与当前检索保持一致。
- 始终把重排放在候选池合并之后，并作为最后一层截断。
- 始终透传 `as_of` 与 R4.2 时间过滤。
- 始终在外发 rerank 文本前脱敏。
- 始终让 reranker / rewriter / sparse encoder 异常安全降级。
- 始终使用新集合灰度混合检索，不污染现有未命名稠密集合。
- 始终让 ingest 与 query 使用一致的 sparse encoder。
- 测试默认使用 fake / stub，不触网。
- 新增配置必须同步默认值、环境变量、公开配置和测试。

### Ask first

- 是否安装或新增分词、BM25、稀疏编码相关依赖。
- 是否连接真实 Qdrant 创建 hybrid 集合。
- 是否调用真实 rerank、LLM rewrite、embedding 或 sparse 服务。
- 是否切换生产 / 主集合 `PAGENT_QDRANT_COLLECTION` 到 hybrid 集合。
- 是否修改 `QANode`、QA prompt 或对外回答 schema。
- 是否把查询改写或重排默认开启。
- 是否提交评测结果文件或大体积语料变更。

### Never do

- 不覆盖或迁移现有 `patent_kb` 未命名稠密集合。
- 不让增强能力异常导致 QA 检索失败。
- 不硬编码 API Key、真实 endpoint、token 或 secret。
- 不把敏感配置写入 `to_public_dict()`、日志、trace 或测试快照。
- 不在本片实现切分增强、websearch、ReAct 主循环或 Agentic 编排。
- 不新增 `qa_*` 这类绑定单一 Node 的检索配置。
- 不为了兼容混合检索而破坏当前纯稠密路径。

---

## 7. Functional Acceptance Checklist

- [ ] `Retriever.search` 支持可选 `fetch_k`。
- [ ] Qdrant / Local 检索器支持 `recall(query, fetch_k, as_of)` 或等价宽召回逻辑。
- [ ] `QdrantRetriever` 使用 `limit = fetch_k or top_k`。
- [ ] `build_retriever` 可按开关组装 base、`MultiQueryRetriever`、`RerankingRetriever`。
- [ ] 所有增强默认关闭，关闭态行为与当前一致。
- [ ] 新增 R4.3 配置项与 `to_public_dict()` 测试完成。
- [ ] `rerank_api_key` 等敏感字段被排除。
- [ ] 新增 `Reranker` 协议、`HTTPReranker` 和 `FakeReranker`。
- [ ] `RerankingRetriever` 调用宽召回、重排并最终截断。
- [ ] reranker 失败时安全降级。
- [ ] rerank 外发文本经过脱敏。
- [ ] 新增 `SparseEncoder` 协议、local / service / fake 实现。
- [ ] hybrid collection schema 使用 named dense + sparse vectors。
- [ ] hybrid ingest point 同时写入 dense 与 sparse 向量。
- [ ] `_QdrantHTTPClient.query_hybrid` 使用 `/points/query` 和 RRF 融合请求体。
- [ ] hybrid 查询透传 time filter。
- [ ] 现有未命名稠密集合路径不被破坏。
- [ ] 新增 `QueryRewriter` 协议与 multi / hyde 模式。
- [ ] `MultiQueryRetriever` 支持改写召回、合并去重和失败降级。
- [ ] 改写 + 重排组合顺序正确。
- [ ] 宽召回、重排、混合、改写测试通过。
- [ ] `pytest && python -m compileall app tests scripts` 通过。
- [ ] 每阶段可运行 `python -m scripts.eval.ragas_eval` 做 A/B 对比。

---

## 8. Implementation Order

1. 配置：新增 R4.3 检索配置字段、环境变量读取、公开配置和测试。
2. 宽召回：扩展 `Retriever` / Qdrant / Local 签名，新增 `recall` 语义和测试。
3. 组装：调整 `build_retriever`，确保关闭态完全复现当前行为。
4. 重排：实现 `Reranker`、`HTTPReranker`、`RerankingRetriever`、fake 与异常降级测试。
5. 混合 schema：调整 `ensure_collection`，按开关区分未命名稠密与 named dense + sparse。
6. 稀疏编码：实现 `SparseEncoder`、local / service / fake，并补充一致性测试。
7. 混合入库：ingest 写入 dense + sparse 命名向量，保持现有 payload 与 point id 稳定。
8. 混合查询：新增 `_QdrantHTTPClient.query_hybrid` 与 QdrantRetriever hybrid 分支。
9. 查询改写：实现 `QueryRewriter`、multi / hyde 模式、`MultiQueryRetriever` 与去重测试。
10. 组合回归：跑开关矩阵、全量测试、编译检查和 ragas A/B。
