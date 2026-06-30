# R4.3 Todo

## 1. 写入 R4.3 计划文档

- [x] 目标：生成 `tasks/plan.md`，说明 R4.3 检索质量增强的背景、依赖图、关键文件、实施阶段、checkpoint、风险边界和最终验收命令。
- 依赖：`SPEC.md`。
- 验收标准：`tasks/plan.md` 标题为 `R4.3 检索质量增强实施计划`；内容包含依赖图、阶段、checkpoint、风险边界和验收命令。
- 验证命令：人工读取 `tasks/plan.md`。

## 2. 写入 R4.3 任务清单

- [x] 目标：生成 `tasks/todo.md`，按依赖顺序列出可勾选任务。
- 依赖：任务 1。
- 验收标准：`tasks/todo.md` 标题为 `R4.3 Todo`；每项任务包含目标、依赖、验收标准、验证命令。
- 验证命令：人工读取 `tasks/todo.md`。

## 3. 建立配置测试

- [x] 目标：补充配置与安全测试，先锁定 R4.3 配置默认关闭、环境变量覆盖和敏感项不公开的预期行为。
- 依赖：任务 2。
- 验收标准：覆盖 `retrieval_fetch_k`、`retrieval_use_rerank`、`rerank_*`、`retrieval_use_hybrid`、`sparse_*`、`hybrid_fusion`、`retrieval_use_query_rewrite`、`query_rewrite_*`；验证默认关闭、env 覆盖、`rerank_api_key` 等敏感项不进入 `to_public_dict()`。
- 验证命令：`pytest tests/test_core_config_logging.py tests/test_security_compliance.py`

## 4. 实现配置基线

- [x] 目标：在 `app/core/config.py` 实现 R4.3 配置项、环境变量读取和公开配置输出。
- 依赖：任务 3。
- 验收标准：SPEC 配置项齐全；所有增强默认关闭；`to_public_dict()` 只包含非敏感项；敏感项不进入日志或 trace。
- 验证命令：`pytest tests/test_core_config_logging.py tests/test_security_compliance.py`

## 5. 建立宽召回测试

- [x] 目标：补充 `tests/test_retrieval_tool.py` 和 `tests/test_qa_node.py`，锁定宽召回接口与默认行为。
- 依赖：任务 4。
- 验收标准：覆盖 `fetch_k`、`recall`、Qdrant `limit = fetch_k or top_k`、Local 候选截断、`as_of` 和 Qdrant time filter 透传；确认 `QANode` 主流程不改。
- 验证命令：`pytest tests/test_retrieval_tool.py tests/test_qa_node.py`

## 6. 实现宽召回闭环

- [x] 目标：扩展 `Retriever.search(..., fetch_k=None)`，并为 Qdrant / Local 检索实现 `recall(query, fetch_k, as_of)`。
- 依赖：任务 5。
- 验收标准：默认行为不变；`fetch_k` 仅扩大候选池；时间过滤继续生效；`QANode` 仍只调用 `search(question, top_k=self.top_k)`。
- 验证命令：`pytest tests/test_retrieval_tool.py tests/test_qa_node.py`

## 7. 建立重排测试

- [x] 目标：补充重排相关单测和安全测试。
- 依赖：任务 6。
- 验收标准：覆盖 fake 排序、HTTP 请求体、异常降级、外发 documents 脱敏、外部错误日志脱敏。
- 验证命令：`pytest tests/test_retrieval_tool.py tests/test_security_compliance.py`

## 8. 实现重排闭环

- [x] 目标：新增 `Reranker` 协议、`FakeReranker`、`HTTPReranker` 与 `RerankingRetriever`。
- 依赖：任务 7。
- 验收标准：`RerankingRetriever` 在宽召回候选池上重排并截断为 `top_k`；reranker 失败时返回宽召回前 `top_k`；外发文本复用 `redact_sensitive_text()`。
- 验证命令：`pytest tests/test_retrieval_tool.py tests/test_security_compliance.py`

## 9. 建立混合检索测试

- [x] 目标：补充 hybrid schema、双向量 point 和 hybrid query 测试。
- 依赖：任务 6。
- 验收标准：覆盖 named dense + sparse schema、`{"dense": ..., "sparse": ...}` 双向量 point、`query_hybrid()` 请求体、dense + sparse prefetch、RRF、time filter 透传；默认 dense-only 路径不变。
- 验证命令：`pytest tests/test_retrieval_tool.py tests/test_ingest_knowledge.py`

## 10. 实现混合检索闭环

- [x] 目标：新增 sparse encoder 体系，扩展 Qdrant hybrid 查询与入库 schema / point 写入。
- 依赖：任务 9。
- 验收标准：默认 dense-only 不变；hybrid 开启时支持新集合使用 named dense + sparse schema；不污染现有未命名稠密集合；hybrid 查询继续透传 `as_of` 与 filter。
- 验证命令：`pytest tests/test_retrieval_tool.py tests/test_ingest_knowledge.py`

## 11. 建立查询改写测试

- [ ] 目标：补充 query rewrite 与 multi-query 合并测试。
- 依赖：任务 6。
- 验收标准：覆盖 expand 失败降级为 `[query]`、多查询结果合并、按 `(document_id, locator, content[:64])` 去重、与重排组合时先改写合并再重排。
- 验证命令：`pytest tests/test_retrieval_tool.py`

## 12. 实现查询改写闭环

- [ ] 目标：新增 `QueryRewriter` 协议、fake / HTTP 或 LLM 兼容实现与 `MultiQueryRetriever`。
- 依赖：任务 11。
- 验收标准：`MultiQueryRetriever` 可独立启用；未配置或失败时降级为原始 query；不改变 `QANode` 调用方式。
- 验证命令：`pytest tests/test_retrieval_tool.py`

## 13. 装配 build_retriever

- [ ] 目标：扩展 `build_retriever(settings=None, embedding_client=None, qdrant_client=None, reranker=None, sparse_encoder=None, query_rewriter=None)` 并完成组合装配。
- 依赖：任务 8、任务 10、任务 12。
- 验收标准：装配顺序为 base/hybrid -> multi-query -> rerank；关闭态与当前行为一致；组合测试可使用 fake 组件，不连接真实外部服务。
- 验证命令：`pytest tests/test_retrieval_tool.py tests/test_qa_node.py`

## 14. 运行项目级验收

- [ ] 目标：运行 R4.3 目标测试、全量回归、编译检查和 ragas 评估入口。
- 依赖：任务 13。
- 验收标准：目标测试通过；全量 `pytest` 通过；`compileall` 通过；`python -m scripts.eval.ragas_eval` 可运行；未引入真实网络依赖、真实 API Key 或敏感内容。
- 验证命令：`pytest tests/test_retrieval_tool.py tests/test_ingest_knowledge.py tests/test_core_config_logging.py tests/test_security_compliance.py tests/test_qa_node.py && pytest && python -m compileall app tests scripts && python -m scripts.eval.ragas_eval`
