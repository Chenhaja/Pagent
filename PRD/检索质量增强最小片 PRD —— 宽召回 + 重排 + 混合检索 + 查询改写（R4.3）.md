<aside>
 🎯

**本页定位**:把 R4.3 的 ③混合检索 / ④重排 / ⑤宽召回(切分增强暂不做) / ⑥查询改写,落成对着现有代码可直接实施的工程规格。
 **基线已就绪**:最新提交 `164dc657`(ragas 评测 + golden set)已建立可量化基线,后续每一步都用同一套 ragas 脚本做 A/B。
 **实施顺序(按 ROI 重排,非编号顺序)**:先 ⑤宽召回 → ④重排 → ③混合检索 → ⑥查询改写。理由:宽召回是重排/融合的前置开关,重排是单步收益最高的补丁,混合检索改 schema 成本最大放第三,查询改写默认关、最后做。

</aside>

## 0. 现状对齐(基于真实代码)

- `Retriever` 协议:`search(query, top_k=3, as_of=None)`,**无 fetch_k**。
- `QdrantRetriever`:单轮稠密召回,`_QdrantHTTPClient.search` POST `/collections/{c}/points/search`,请求体 `vector / limit / with_payload / filter`,**未命名单稠密向量**。
- `ensure_collection`(在 `ingest_knowledge.py`):建集合用 `vectors: size+Cosine`,即未命名稠密向量;upsert point 为 `id / vector / payload`。
- `OpenAICompatibleEmbeddingClient.embed(text)`:单条文本、OpenAI 兼容 `/embeddings`,失败返回 `[]`。
- `QANode._retrieve`:`retrieval_tool.search(question, top_k=self.top_k)`,`max_steps=1`,所以**改动尽量收敛在 retrieval 层,QANode 不动**。
- 评测:`scripts/eval/ragas_eval.py` 用 `NonLLMContextRecall` + `NonLLMContextPrecisionWithReference`,golden set `test/eval/golden_qa.jsonl`(schema:question / expected_item / expected_section / expected_locators / intent),并自带 `item_hit` / `section_hit` 自查。
- 时效过滤(R4.2)`_build_qdrant_time_filter` / `_law_matches_time` 已实现,**新管线必须把这个 filter 透传下去复用**。

## 1. 总体组装(build_retriever 分层)

核心思路:把每个增强做成**可组合的包装器**,统一在 `build_retriever` 里按开关拼装,关闭时行为与现在完全一致(向后兼容)。约定一条铁律:**重排永远作用在合并后的候选池上,且是最后一层截断到 top_k**。

```python
# app/tools/retrieval.py（组装伪代码）
def build_retriever(settings=None, embedding_client=None, qdrant_client=None,
                    reranker=None, sparse_encoder=None, query_rewriter=None) -> Retriever:
    s = settings or get_settings()
    base = _build_base_retriever(s, embedding_client, qdrant_client, sparse_encoder)  # Qdrant(单稠密或混合) 或 Local 回退

    # ⑥ 查询改写：对每个改写式做宽召回，合并去重，得到候选池
    recaller = base
    if s.retrieval_use_query_rewrite:
        recaller = MultiQueryRetriever(base, query_rewriter or _build_rewriter(s), settings=s)

    # ④ 重排：在候选池(fetch_k)上重排，截断到 rerank_top_k
    if s.retrieval_use_rerank:
        return RerankingRetriever(recaller, reranker or _build_reranker(s), settings=s)
    return recaller
```

约定每个包装器都暴露两个方法,避免重排/改写互相打架:

- `recall(query, fetch_k, as_of) -> list[RetrievalResult]`:宽召回候选(不截断到 top_k)。
- `search(query, top_k, as_of) -> list[RetrievalResult]`:对外语义不变 = `recall` 后截断。

这样:开改写不开重排 → `MultiQueryRetriever.search` 合并去重后截 top_k;开重排 → `RerankingRetriever.search` 调内层 `recall(fetch_k)` 再精排截 top_k。两者独立可控。

## 2. ⑤ 宽召回(R4.3.5 的保留部分,切分增强不做)

**目标**:召回阶段先取更宽的 `fetch_k`(默认 30),给重排/融合留排序空间;不启用任何增强时退化为 `top_k`。

**协议改动(向后兼容,新增可选参数)**:

```python
class Retriever(Protocol):
    def search(self, query: str, top_k: int = 3, as_of: str | None = None,
               fetch_k: int | None = None) -> list[RetrievalResult]: ...
    # 可选：def recall(self, query, fetch_k, as_of=None) -> list[RetrievalResult]
```

**QdrantRetriever**:`limit = fetch_k or top_k`,其余不变;时间 filter 照旧透传。`LocalRetrievalTool` 同步加 `fetch_k` 形参(仅扩签名)。

**注意**:`QANode` 不用改——`fetch_k` 由 `RerankingRetriever`/`MultiQueryRetriever` 内部从 `settings.retrieval_fetch_k` 读取并向内层传。

## 3. ④ 重排(R4.3.4)

**协议**:

```python
class Reranker(Protocol):
    def rerank(self, query: str, results: list[RetrievalResult],
               top_k: int) -> list[RetrievalResult]: ...

class FakeReranker:  # 测试用：按传入顺序或注入分数返回，可断言被调用
    ...

class HTTPReranker:  # OpenAI 兼容 /rerank（SiliconFlow / TEI / bge-reranker 等）
    def rerank(self, query, results, top_k):
        # POST {base}/rerank  body: {"model":m,"query":q,"documents":[r.content...],"top_n":top_k}
        # resp: {"results":[{"index":i,"relevance_score":s}...]} → 按 index 取回 RetrievalResult，写回 similarity=s
        ...
```

**RerankingRetriever**:

```python
class RerankingRetriever:
    def __init__(self, inner, reranker, settings):
        self.inner, self.reranker, self.s = inner, reranker, settings
    def search(self, query, top_k=3, as_of=None, fetch_k=None):
        wide = self.inner.recall(query, fetch_k or self.s.retrieval_fetch_k, as_of)
        if not wide:
            return []
        ranked = self.reranker.rerank(query, wide, self.s.rerank_top_k or top_k)
        return ranked[:(self.s.rerank_top_k or top_k)]
```

**降级**:reranker 端点未配 / 调用异常 → 捕获后直接返回宽召回的前 `top_k`(绝不让重排把检索打挂)。鉴权走 `rerank_api_key`,文本送出前复用 `redact_sensitive_text`。

## 4. ③ 混合检索(R4.3.3,dense + sparse)

这是改动最大的一项,涉及**集合 schema 迁移 + ingest 双向量 + 融合查询**,务必用开关隔离、独立集合灰度。

**4.1 稀疏编码器抽象**

```python
class SparseEncoder(Protocol):
    def encode(self, text: str) -> dict:  # {"indices":[int...], "values":[float...]}
        ...

class LocalLexicalSparseEncoder:  # jieba 分词 → token 稳定 hash 为 index → tf/bm25 权重；无网依赖
    ...
class ServiceSparseEncoder:       # 调 bge-m3 等服务取 lexical_weights
    ...
class FakeSparseEncoder:          # 测试用固定稀疏向量
    ...
```

**4.2 集合 schema(命名向量 + 稀疏向量)**——需 Qdrant ≥ 1.10

```json
{
  "vectors": {"dense": {"size": 1024, "distance": "Cosine"}},
  "sparse_vectors": {"sparse": {}}
}
```

upsert point 结构同步改为命名向量:

```json
{"id": "...", "vector": {"dense": [], "sparse": {"indices": [], "values": []}}, "payload": {}}
```

**4.3 融合查询**:新增 `_QdrantHTTPClient.query_hybrid`,POST `/collections/{c}/points/query`:

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

> `filter` 复用 `_build_qdrant_time_filter` 的输出。

**4.4 ingest 改动**:`ensure_collection` 按 `retrieval_use_hybrid` 走两套 schema;`ingest_knowledge` 在写 point 时,稠密向量来自现有 embedding,稀疏向量来自 `SparseEncoder.encode(chunk.content)`,组装成命名向量。

**4.5 兼容/迁移**:现有集合是未命名稠密向量,**与命名向量不兼容**。开混合时用**新集合名**(如 `patent_kb_hybrid`)重建入库,验证通过再切 `PAGENT_QDRANT_COLLECTION`,避免污染基线。

## 5. ⑥ 查询改写(R4.3.6,默认关)

**协议**:

```python
class QueryRewriter(Protocol):
    def expand(self, query: str) -> list[str]:  # 返回 [原查询, 改写1, 改写2 ...]
        ...
```

两种模式(`PAGENT_QUERY_REWRITE_MODE`):

- **multi**:让 LLM 生成 N 个同义/法言法语改写式(如把口语问法改成“第X条/创造性/优先权”等术语表述)。
- **hyde**:让 LLM 先写一段“假设答案/假设法条”,用其向量去检索。

**MultiQueryRetriever**:

```python
class MultiQueryRetriever:
    def recall(self, query, fetch_k, as_of=None):
        queries = self.rewriter.expand(query)  # 失败/未配 → [query]，降级为单查询
        pool, seen = [], set()
        for q in queries:
            for r in self.inner.recall(q, fetch_k, as_of):
                key = (r.provenance.get("document_id"), r.provenance.get("locator"), r.content[:64])
                if key not in seen:
                    seen.add(key); pool.append(r)
        return pool
    def search(self, query, top_k=3, as_of=None, fetch_k=None):
        return self.recall(query, fetch_k or self.s.retrieval_fetch_k, as_of)[:top_k]
```

LLM 复用现有 `llm_*` 配置;`expand` 出错或未配模型时静默降级为 `[query]`。注意:开改写时,真正的排序质量靠后置重排兜底,所以**改写通常与重排搭配使用**。

## 6. 配置项(PAGENT_ 前缀)

| 配置                        | 默认           | 说明                        |
| --------------------------- | -------------- | --------------------------- |
| RETRIEVAL_FETCH_K           | 30             | 重排/融合前宽召回候选数     |
| RETRIEVAL_USE_RERANK        | false          | 是否启用重排                |
| RERANK_BASE_URL             | 空             | OpenAI 兼容 /rerank 端点    |
| RERANK_MODEL                | 空             | reranker 模型名             |
| RERANK_API_KEY              | 空             | reranker 鉴权(敏感,exclude) |
| RERANK_TOP_K                | 空(回退 top_k) | 重排后保留数                |
| RETRIEVAL_USE_HYBRID        | false          | 是否启用 dense+sparse 混合  |
| SPARSE_ENCODER              | local          | 稀疏编码器 local 或 service |
| SPARSE_BASE_URL             | 空             | service 模式稀疏端点        |
| SPARSE_MODEL                | 空             | service 模式稀疏模型名      |
| HYBRID_FUSION               | rrf            | 融合方式                    |
| RETRIEVAL_USE_QUERY_REWRITE | false          | 是否启用查询改写            |
| QUERY_REWRITE_MODE          | multi          | multi 或 hyde               |
| QUERY_REWRITE_COUNT         | 3              | 改写式/假设文档数量         |

全部默认关闭;关闭态下 `build_retriever` 行为与当前完全一致。新增敏感项用 `Field(exclude=True)`,并补进 `to_public_dict`(非敏感项)。

## 7. 实施顺序与逐步验收(同一套 ragas)

每步只改一个变量,跑 `python -m scripts.eval.ragas_eval`(必要时带 `--top-k`),对比 `NonLLMContextRecall` / `NonLLMContextPrecisionWithReference` 及自查的 `item_hit` / `section_hit`。

1. **宽召回**:加 `fetch_k`(协议 + QdrantRetriever),无回归。
2. **重排**:`Reranker` 协议 + `HTTPReranker` + `RerankingRetriever` + 开关;开/关各跑一次,确认 top_k=3 的 Recall/Precision 提升。
3. **混合检索**:`SparseEncoder` + 命名向量 schema + `query_hybrid` + ingest 双向量;**新集合**重灌,对比纯稠密。
4. **查询改写**:`QueryRewriter` + `MultiQueryRetriever`,与重排搭配评估增量收益,再决定是否默认开。

## 8. 风险与迁移注意

- **schema 迁移**:命名向量与现有未命名集合不兼容,必须新集合灰度,切换前别动 `patent_kb`。
- **延迟/成本**:重排与改写都加网络往返;以 ragas 数值确认收益是否值回延迟。
- **稀疏编码一致性**:ingest 与查询必须用同一 `SparseEncoder` 实现与同一 hash 词表,否则 indices 对不上。
- **降级优先**:reranker / rewriter / sparse 任一异常都要静默降级到“纯稠密 + 宽召回前 top_k”,绝不抛错打挂检索。
- **golden set 偏小**:指标看趋势而非绝对值;新增混合/改写后建议扩充术语类、条号类问法样本。

## 9. 测试清单(tests/)

- `FakeReranker` / `FakeSparseEncoder` / 桩 `QueryRewriter`,全程不触网。
- 开关矩阵:四个开关的关闭态必须复现当前行为(回归保护)。
- `RerankingRetriever`:验证调用 `recall(fetch_k)`、按重排分数排序、截断 top_k、异常降级。
- `MultiQueryRetriever`:验证 expand 失败降级为单查询、合并去重正确。
- 混合:对 `query_hybrid` 请求体做断言(prefetch 两路 + rrf + 透传 time filter)。

## 10. 后续片预告

R4.3 这四件套打磨稳定后,再进 **R7 Agentic 编排(ReAct 主循环 + 工具路由 + websearch)**——补语料缺失内容(最新案例/法律状态/官费),并复用 R4.2 时效性与出处规范。顺序仍是“先把检索内功做扎实,再上 ReAct”。