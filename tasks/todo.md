# R4.1 Todo

## Phase 0: 计划文档

- [x] 写入 `tasks/plan.md`
  - 文件范围：`tasks/plan.md`
  - 验收：包含 R4.1 背景、依赖图、垂直任务拆分、检查点、风险约束和验证命令。
  - 验证：人工检查。
  - 阻塞：无。
- [x] 写入 `tasks/todo.md`
  - 文件范围：`tasks/todo.md`
  - 验收：任务清单包含文件范围、验收标准、验证命令和阻塞关系。
  - 验证：人工检查。
  - 阻塞：无。

## Phase 1: 配置入口最小闭环

- [x] 增加 retrieval / qdrant / embedding 配置字段
  - 文件范围：`app/core/config.py`、`tests/test_core_config_logging.py`
  - 验收：`Settings` 含 `retrieval_backend`、`retrieval_top_k`、`qdrant_url`、`qdrant_api_key`、`qdrant_collection`、`embedding_base_url`、`embedding_model`、`embedding_api_key`；默认值与 SPEC 一致。
  - 验证：`pytest tests/test_core_config_logging.py`
  - 阻塞：Phase 0。
- [x] 读取 `PAGENT_RETRIEVAL_*` / `PAGENT_QDRANT_*` / `PAGENT_EMBEDDING_*` 环境变量
  - 文件范围：`app/core/config.py`、`tests/test_core_config_logging.py`
  - 验收：环境变量可覆盖默认值；embedding base URL / API key 的回退口径清晰。
  - 验证：`pytest tests/test_core_config_logging.py`
  - 阻塞：增加配置字段。
- [x] 更新公开配置输出
  - 文件范围：`app/core/config.py`、`tests/test_core_config_logging.py`
  - 验收：`to_public_dict()` 展示非敏感 retrieval / qdrant / embedding 配置，不暴露 `llm_api_key`、`qdrant_api_key`、`embedding_api_key` 或密钥值。
  - 验证：`pytest tests/test_core_config_logging.py`
  - 阻塞：环境变量读取。

## Phase 2: 检索契约与 Local 兼容

- [x] 扩展 `RetrievalResult`
  - 文件范围：`app/tools/retrieval.py`、`tests/test_retrieval_tool.py`
  - 验收：新增 `similarity: float = 0.0`；旧构造方式不变；docstring 说明 provenance 扩展字段。
  - 验证：`pytest tests/test_retrieval_tool.py`
  - 阻塞：Phase 1。
- [x] 新增 `Retriever` 协议
  - 文件范围：`app/tools/retrieval.py`、`tests/test_retrieval_tool.py`
  - 验收：协议包含 `search(query: str, top_k: int = 3) -> list[RetrievalResult]`；`LocalRetrievalTool` 满足协议。
  - 验证：`pytest tests/test_retrieval_tool.py`
  - 阻塞：扩展 `RetrievalResult`。
- [x] 保持并扩展 Local provenance
  - 文件范围：`app/tools/retrieval.py`、`tests/test_retrieval_tool.py`
  - 验收：Local 关键词检索行为不变；document 包含 `doc_type` / `locator` 时透传；无字段时旧测试仍通过。
  - 验证：`pytest tests/test_retrieval_tool.py`
  - 阻塞：新增 `Retriever` 协议。

## Phase 3: Embedding 客户端薄片

- [x] 新增 `EmbeddingClient` 协议和 `FakeEmbedding`
  - 文件范围：`app/tools/embeddings.py`、`tests/test_retrieval_tool.py`
  - 验收：`embed(text) -> list[float]`；fake 输出可预测并记录调用；有中文 docstring。
  - 验证：`pytest tests/test_retrieval_tool.py`
  - 阻塞：Phase 2。
- [x] 新增 OpenAI 兼容 embedding 客户端
  - 文件范围：`app/tools/embeddings.py`、`tests/test_retrieval_tool.py`
  - 验收：使用 embedding 配置并可回退 LLM 配置；fake HTTP 响应可解析 vector；缺配置或 HTTP 失败不泄漏 key。
  - 验证：`pytest tests/test_retrieval_tool.py`
  - 阻塞：`EmbeddingClient` 协议。
- [x] 接入基础脱敏边界
  - 文件范围：`app/tools/embeddings.py`、`tests/test_retrieval_tool.py`
  - 验收：在线 embed 前使用 `redact_sensitive_text()`；trace / 异常不记录完整敏感正文或 API Key。
  - 验证：`pytest tests/test_retrieval_tool.py`
  - 阻塞：OpenAI 兼容 embedding 客户端。

## Phase 4: Qdrant 单轮检索闭环

- [x] 新增 `QdrantRetriever`
  - 文件范围：`app/tools/retrieval.py`、`tests/test_retrieval_tool.py`
  - 验收：构造参数支持 `collection_name`、`embedding_client`、`qdrant_client`；`search(query, top_k)` 可调用 fake embedding 和 fake qdrant。
  - 验证：`pytest tests/test_retrieval_tool.py`
  - 阻塞：Phase 3。
- [x] 映射 Qdrant payload 到 `RetrievalResult`
  - 文件范围：`app/tools/retrieval.py`、`tests/test_retrieval_tool.py`
  - 验收：fake hit 映射出 `content`、`source`、`document_id`、`doc_type`、`locator`、`similarity`；top_k 传递正确。
  - 验证：`pytest tests/test_retrieval_tool.py`
  - 阻塞：新增 `QdrantRetriever`。
- [x] 实现 Qdrant / embedding 异常降级
  - 文件范围：`app/tools/retrieval.py`、`tests/test_retrieval_tool.py`
  - 验收：embedding 或 qdrant fake 抛错时 `search()` 返回 `[]`；不抛裸异常。
  - 验证：`pytest tests/test_retrieval_tool.py`
  - 阻塞：payload 映射。

## Phase 5: Retriever 工厂与降级

- [x] 新增 `build_retriever(settings)` local 分支
  - 文件范围：`app/tools/retrieval.py`、`tests/test_retrieval_tool.py`
  - 验收：`retrieval_backend=local` 返回 `LocalRetrievalTool`；默认配置不触发外部服务。
  - 验证：`pytest tests/test_retrieval_tool.py`
  - 阻塞：Phase 4。
- [x] 新增 qdrant 分支与 fake 注入测试点
  - 文件范围：`app/tools/retrieval.py`、`tests/test_retrieval_tool.py`
  - 验收：`retrieval_backend=qdrant` 且配置完整时可构建 `QdrantRetriever`；测试可 fake 初始化，不触网。
  - 验证：`pytest tests/test_retrieval_tool.py`
  - 阻塞：local 分支。
- [x] 实现未知 backend / 配置缺失回退
  - 文件范围：`app/tools/retrieval.py`、`tests/test_retrieval_tool.py`
  - 验收：未知 backend、qdrant 配置缺失或初始化失败时回退 `LocalRetrievalTool`；不泄漏 key。
  - 验证：`pytest tests/test_retrieval_tool.py`
  - 阻塞：qdrant 分支。

## Phase 6: QA 垂直接线与 provenance 回链

- [ ] `QANode` 默认经工厂构建 retriever
  - 文件范围：`app/nodes/qa.py`、`tests/test_qa_node.py`
  - 验收：未显式传入 `retrieval_tool` 时调用 `build_retriever(get_settings())`；测试可 monkeypatch 工厂；旧显式注入用法仍可用。
  - 验证：`pytest tests/test_qa_node.py`
  - 阻塞：Phase 5。
- [ ] `_retrieve()` 使用配置 top_k 并保留 bounded guard
  - 文件范围：`app/nodes/qa.py`、`tests/test_qa_node.py`
  - 验收：top_k 默认 3 或来自配置 / 构造参数；`max_steps <= 0`、`token_budget <= 0`、`timeout_seconds <= 0` 时不调用 retriever。
  - 验证：`pytest tests/test_qa_node.py`
  - 阻塞：工厂构建 retriever。
- [ ] `_build_evidence()` 透传扩展 provenance
  - 文件范围：`app/nodes/qa.py`、`tests/test_qa_node.py`
  - 验收：evidence 包含 `source`、`document_id`、`doc_type`、`locator`、`score`、`similarity`；缺字段时安全默认，不伪造具体法条。
  - 验证：`pytest tests/test_qa_node.py`
  - 阻塞：`_retrieve()` top_k。
- [ ] 更新 QA 回链与降级测试
  - 文件范围：`tests/test_qa_node.py`、必要时 `app/prompts/patent_qa.py`
  - 验收：fake skill 可用 locator 写入 basis；无命中时依据不足；检索异常时 QA `status == success` 且 `result_count == 0`；旧 Local evidence 结构兼容。
  - 验证：`pytest tests/test_qa_node.py`
  - 阻塞：evidence 透传。

## Phase 7: 本地知识入库脚本

- [ ] 新增 `knowledge/` 目录结构占位
  - 文件范围：`knowledge/law/.gitkeep`、`knowledge/template/.gitkeep`、`knowledge/term/.gitkeep`
  - 验收：目录存在；不提交真实法规全文、敏感模板或案件材料。
  - 验证：人工检查。
  - 阻塞：Phase 6。
- [ ] 新增入库脚本 CLI
  - 文件范围：`scripts/ingest_knowledge.py`、`tests/test_ingest_knowledge.py`
  - 验收：支持 `python -m scripts.ingest_knowledge --path knowledge/`；空目录安全退出。
  - 验证：`pytest tests/test_ingest_knowledge.py`
  - 阻塞：目录结构占位。
- [ ] 实现 law / template / term 切分和 metadata
  - 文件范围：`scripts/ingest_knowledge.py`、`tests/test_ingest_knowledge.py`
  - 验收：按目录推断 `doc_type`；law 优先法条 locator；template 优先权利要求项；term 优先术语名；payload 包含全部 provenance 字段。
  - 验证：`pytest tests/test_ingest_knowledge.py`
  - 阻塞：入库脚本 CLI。
- [ ] 实现稳定 point_id 与 fake upsert
  - 文件范围：`scripts/ingest_knowledge.py`、`tests/test_ingest_knowledge.py`
  - 验收：`point_id = hash(document_id + chunk_index)` 稳定；重复运行相同输入得到相同 id；fake embedding 和 fake qdrant upsert 收到 vector + payload。
  - 验证：`pytest tests/test_ingest_knowledge.py && python -m compileall scripts`
  - 阻塞：切分和 metadata。

## Phase 8: 回归验收

- [ ] 运行 R4.1 目标测试
  - 文件范围：R4.1 修改涉及的源码与测试。
  - 验收：retrieval、QA、配置、ingest 目标测试全部通过；默认不触发真实 embedding / Qdrant / 网络。
  - 验证：`pytest tests/test_retrieval_tool.py tests/test_qa_node.py tests/test_core_config_logging.py tests/test_ingest_knowledge.py`
  - 阻塞：Phase 7。
- [ ] 运行全量测试
  - 文件范围：全项目。
  - 验收：全量 pytest 通过。
  - 验证：`pytest`
  - 阻塞：R4.1 目标测试。
- [ ] 运行编译检查
  - 文件范围：`app`、`tests`、`scripts`。
  - 验收：Python 编译检查通过。
  - 验证：`python -m compileall app tests scripts`
  - 阻塞：全量测试。
- [ ] 执行最终验收命令并检查敏感文件
  - 文件范围：全项目。
  - 验收：`pytest && python -m compileall app tests scripts` 通过；未提交 `.env`、API Key、Qdrant 凭证、embedding 凭证、真实法规全文或敏感案件材料。
  - 验证：`pytest && python -m compileall app tests scripts`
  - 阻塞：编译检查。
