# R4.3 检索质量增强实施计划

## 背景

R4.3 的目标是先形成检索质量增强的可执行实施计划，而不是立即进入代码实现。当前仓库已有 `Retriever`、`QdrantRetriever`、`LocalRetrievalTool`、`build_retriever`、Qdrant 时间过滤、配置读取、敏感信息脱敏和 QA 主流程。R4.3 将围绕宽召回、重排、混合检索、查询改写建立逐步可验证的垂直切片，并保持所有增强能力默认关闭。

本阶段只替换 `tasks/plan.md` 与 `tasks/todo.md`，后续实现阶段再按任务清单逐项落地。

## 依赖图

```text
SPEC.md
  -> tasks/plan.md / tasks/todo.md
  -> 配置基线
      -> app/core/config.py: Settings / env / to_public_dict
      -> tests/test_core_config_logging.py
      -> tests/test_security_compliance.py
  -> 宽召回
      -> app/tools/retrieval.py: Retriever.search(fetch_k) / recall
      -> QdrantRetriever / LocalRetrievalTool
      -> tests/test_retrieval_tool.py
  -> 重排
      -> Reranker / HTTPReranker / FakeReranker
      -> RerankingRetriever
      -> redact_sensitive_text
      -> build_retriever 组合
      -> tests/test_retrieval_tool.py
  -> 混合检索
      -> SparseEncoder / LocalLexicalSparseEncoder / ServiceSparseEncoder / FakeSparseEncoder
      -> _QdrantHTTPClient.query_hybrid
      -> scripts/ingest_knowledge.py: hybrid schema / hybrid point
      -> tests/test_ingest_knowledge.py
      -> tests/test_retrieval_tool.py
  -> 查询改写
      -> QueryRewriter / MultiQueryRetriever
      -> build_retriever 组合
      -> tests/test_retrieval_tool.py
  -> 回归验证
      -> tests/test_qa_node.py 确认 QANode 不改
      -> python -m scripts.eval.ragas_eval
```

## 关键文件

- `app/core/config.py`：新增 R4.3 配置默认值、环境变量读取和公开配置输出。
- `app/tools/retrieval.py`：实现宽召回、重排、混合检索、查询改写与 `build_retriever` 装配。
- `scripts/ingest_knowledge.py`：在 hybrid 开启时支持 named dense + sparse schema 和双向量 point。
- `app/core/security.py`：复用 `redact_sensitive_text()` 处理 rerank 外发文本和外部错误日志。
- `app/nodes/qa.py`：不修改主流程，仅通过测试确认仍只调用 `retrieval_tool.search(question, top_k=self.top_k)`。
- `tests/test_retrieval_tool.py`：覆盖 R4.3 检索增强主体行为。
- `tests/test_ingest_knowledge.py`：覆盖 hybrid collection schema 与 upsert point。
- `tests/test_core_config_logging.py`：覆盖配置默认值、环境变量覆盖和公开配置。
- `tests/test_security_compliance.py`：覆盖敏感配置不公开、rerank 脱敏和外部错误日志脱敏。
- `tests/test_qa_node.py`：确认 QA 主流程不被 R4.3 改动。

## Phase 1 — 配置基线与安全边界

**修改文件**
- `app/core/config.py`
- `tests/test_core_config_logging.py`
- `tests/test_security_compliance.py`

**实施内容**
- 增加 SPEC 指定的 R4.3 配置：`retrieval_fetch_k`、`retrieval_use_rerank`、`rerank_*`、`retrieval_use_hybrid`、`sparse_*`、`hybrid_fusion`、`retrieval_use_query_rewrite`、`query_rewrite_*`。
- 所有增强能力默认关闭，关闭态保持当前检索行为。
- `rerank_api_key` 等敏感项使用 `Field(exclude=True)` 或等价机制排除，不进入 `to_public_dict()`、日志或 trace。
- 环境变量使用项目统一前缀 `PAGENT_`，字段名与配置项一一对应。
- 对非敏感参数补齐 `to_public_dict()` 输出，便于排查。

**Checkpoint**
```bash
pytest tests/test_core_config_logging.py tests/test_security_compliance.py
```

## Phase 2 — 宽召回最小闭环

**修改文件**
- `app/tools/retrieval.py`
- `tests/test_retrieval_tool.py`
- `tests/test_qa_node.py`（只验证，不改 QANode 主流程）

**实施内容**
- 扩展 `Retriever.search(..., fetch_k=None)`。
- 为 `QdrantRetriever` / `LocalRetrievalTool` 增加 `recall(query, fetch_k, as_of)`。
- `QdrantRetriever` 请求 `limit = fetch_k or top_k`。
- Local 检索按 `fetch_k or top_k` 取候选。
- `_build_qdrant_time_filter()` 与 `_law_matches_time()` 继续透传并生效，确保 `as_of` 与 Qdrant filter 不丢失。
- `QANode` 仍只调用 `retrieval_tool.search(question, top_k=self.top_k)`。

**Checkpoint**
```bash
pytest tests/test_retrieval_tool.py tests/test_qa_node.py
```

## Phase 3 — 重排闭环

**修改文件**
- `app/tools/retrieval.py`
- `tests/test_retrieval_tool.py`
- `tests/test_security_compliance.py`

**实施内容**
- 新增 `Reranker` 协议、`FakeReranker`、`HTTPReranker`。
- 新增 `RerankingRetriever`，基于宽召回候选池重排并截断为 `top_k`。
- reranker 调用失败、未配置或返回异常时，降级返回宽召回前 `top_k`。
- 外发 documents 前复用 `redact_sensitive_text()`，避免 API Key、token、隐私内容或过长原文进入外部请求与错误日志。
- 错误日志使用稳定英文 `event`，`message` 保持中文可读，异常保留堆栈但不泄露敏感原文。

**Checkpoint**
```bash
pytest tests/test_retrieval_tool.py tests/test_security_compliance.py
```

## Phase 4 — 混合检索闭环

**修改文件**
- `app/tools/retrieval.py`
- `scripts/ingest_knowledge.py`
- `tests/test_retrieval_tool.py`
- `tests/test_ingest_knowledge.py`

**实施内容**
- 新增 `SparseEncoder` 协议、`LocalLexicalSparseEncoder`、`ServiceSparseEncoder`、`FakeSparseEncoder`。
- `_QdrantHTTPClient` 增加 `query_hybrid()`，请求 `/points/query`，使用 dense + sparse prefetch 和 RRF。
- hybrid 查询必须继续透传 `as_of` 和 Qdrant time filter。
- `_QdrantHTTPUpsertClient.ensure_collection()` 按开关支持 named dense + sparse schema。
- `ingest_knowledge()` 在开启 hybrid 时写入 `{"dense": ..., "sparse": ...}` 命名向量。
- 默认 dense-only 路径不变，不能污染现有未命名稠密 Qdrant 集合。

**Checkpoint**
```bash
pytest tests/test_retrieval_tool.py tests/test_ingest_knowledge.py
```

## Phase 5 — 查询改写闭环

**修改文件**
- `app/tools/retrieval.py`
- `tests/test_retrieval_tool.py`

**实施内容**
- 新增 `QueryRewriter` 协议、fake 实现、HTTP 或 LLM 兼容实现。
- 新增 `MultiQueryRetriever`。
- expand 失败、未配置或返回空结果时降级为 `[query]`。
- 合并去重 key 使用 `(document_id, locator, content[:64])`。
- 与重排组合时，先改写合并，再重排。
- 查询改写不改变 `QANode` 调用方式。

**Checkpoint**
```bash
pytest tests/test_retrieval_tool.py
```

## Phase 6 — build_retriever 装配与组合测试

**修改文件**
- `app/tools/retrieval.py`
- `tests/test_retrieval_tool.py`
- `tests/test_qa_node.py`

**实施内容**
- 扩展 `build_retriever(settings=None, embedding_client=None, qdrant_client=None, reranker=None, sparse_encoder=None, query_rewriter=None)`。
- 装配顺序固定为：base/hybrid -> `MultiQueryRetriever` -> `RerankingRetriever`。
- 关闭态与当前行为一致。
- 支持通过 fake reranker、fake sparse encoder、fake query rewriter 做组合测试，不连接真实 Qdrant、rerank、LLM rewrite 或 sparse service。

**Checkpoint**
```bash
pytest tests/test_retrieval_tool.py tests/test_qa_node.py
```

## Phase 7 — 项目级验收

**验收命令**
```bash
pytest tests/test_retrieval_tool.py tests/test_ingest_knowledge.py tests/test_core_config_logging.py tests/test_security_compliance.py tests/test_qa_node.py
pytest
python -m compileall app tests scripts
python -m scripts.eval.ragas_eval
```

## 风险与边界

- 不改 `QANode._retrieve`。
- 不默认开启重排、混合检索或查询改写。
- 不覆盖现有未命名稠密 Qdrant 集合。
- 不连接真实 Qdrant、rerank、LLM rewrite、sparse service，除非用户后续明确要求。
- 不硬编码 API Key、token、endpoint。
- 不让增强能力异常打挂基础检索。
- 不新增文档之外的大范围重构。
- 配置项保持通用作用域，Node/模块自行决定是否继承或覆盖。
- 混合检索只在新集合或明确 hybrid schema 下启用，避免与既有 dense-only 集合互相污染。
