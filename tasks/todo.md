# R4.2 Todo

## Phase 1: 配置切片

- [x] 增加法规时效配置字段
  - 文件范围：`app/core/config.py`、`tests/test_core_config_logging.py`
  - 验收：默认值为 `current` / `True` / `365`。
  - 验证：`pytest tests/test_core_config_logging.py`
- [x] 读取环境变量覆盖
  - 文件范围：`app/core/config.py`、`tests/test_core_config_logging.py`
  - 验收：`PAGENT_RETRIEVAL_DEFAULT_STATUS`、`PAGENT_RETRIEVAL_ENABLE_TIME_FILTER`、`PAGENT_LAW_STALE_DAYS` 可覆盖。
  - 验证：`pytest tests/test_core_config_logging.py`
- [x] 更新公开配置输出
  - 文件范围：`app/core/config.py`、`tests/test_core_config_logging.py`
  - 验收：public dict 包含新配置且不泄露 API Key。
  - 验证：`pytest tests/test_core_config_logging.py`

## Phase 2: 入库 metadata 与 payload 切片

- [x] 扩展 `KnowledgeChunk` 时效字段
  - 文件范围：`scripts/ingest_knowledge.py`
  - 验收：chunk 可承载法规名称、版本、生效/失效日期、状态、来源、检索日期、正文哈希。
  - 验证：`pytest tests/test_ingest_knowledge.py`
- [x] 读取 law 版本目录 `meta.json`
  - 文件范围：`scripts/ingest_knowledge.py`、`tests/test_ingest_knowledge.py`
  - 验收：跳过 `meta.json` 本身；document_id 优先取 metadata，缺失用版本目录名。
  - 验证：`pytest tests/test_ingest_knowledge.py`
- [x] 写入 Qdrant payload 时效字段
  - 文件范围：`scripts/ingest_knowledge.py`、`tests/test_ingest_knowledge.py`
  - 验收：law payload 含时效字段；非 law 行为兼容；`content_hash` 随正文稳定变化。
  - 验证：`pytest tests/test_ingest_knowledge.py`

## Phase 3: 检索模型与过滤 helper 切片

- [x] 扩展 `RetrievalResult` 和 `Retriever.search()` 协议
  - 文件范围：`app/tools/retrieval.py`、`tests/test_retrieval_tool.py`
  - 验收：旧构造和旧 `search(query, top_k)` 调用兼容；新字段默认 `None`。
  - 验证：`pytest tests/test_retrieval_tool.py`
- [x] 实现 law-only 时间过滤 helper
  - 文件范围：`app/tools/retrieval.py`、`tests/test_retrieval_tool.py`
  - 验收：关闭开关不过滤；非 law 不过滤；默认按 status；`as_of` 按有效期。
  - 验证：`pytest tests/test_retrieval_tool.py`
- [x] 实现 Qdrant 时间 filter helper
  - 文件范围：`app/tools/retrieval.py`、`tests/test_retrieval_tool.py`
  - 验收：filter 语义为“非 law OR 满足法规时间条件”。
  - 验证：`pytest tests/test_retrieval_tool.py`

## Phase 4: Local 与 Qdrant 后端过滤切片

- [x] Local 支持 `as_of` 与时效字段透传
  - 文件范围：`app/tools/retrieval.py`、`tests/test_retrieval_tool.py`
  - 验收：current/superseded 共存默认只返回 current；历史 as_of 返回当日有效版本。
  - 验证：`pytest tests/test_retrieval_tool.py`
- [x] Qdrant HTTP client 支持 `query_filter`
  - 文件范围：`app/tools/retrieval.py`、`tests/test_retrieval_tool.py`
  - 验收：HTTP search payload 按需加入 filter。
  - 验证：`pytest tests/test_retrieval_tool.py`
- [x] QdrantRetriever 映射时效字段并保持异常降级
  - 文件范围：`app/tools/retrieval.py`、`tests/test_retrieval_tool.py`
  - 验收：payload 映射到 `RetrievalResult` 顶层字段；embedding/Qdrant 异常返回 `[]`。
  - 验证：`pytest tests/test_retrieval_tool.py`

## Phase 5: QA evidence、过时提示与 trace 切片

- [x] `_build_evidence()` 透传法规时效字段
  - 文件范围：`app/nodes/qa.py`、`tests/test_qa_node.py`
  - 验收：law evidence 包含版本、状态、生效日、来源 URL、retrieved_at 等字段。
  - 验证：`pytest tests/test_qa_node.py`
- [x] 格式化 law citation
  - 文件范围：`app/nodes/qa.py`、`tests/test_qa_node.py`
  - 验收：元数据齐全时引用为 `《{law_name}({version})》第X条(生效日:...)`；缺元数据不伪造。
  - 验证：`pytest tests/test_qa_node.py`
- [x] 添加 superseded/stale 过时提示
  - 文件范围：`app/nodes/qa.py`、`tests/test_qa_node.py`
  - 验收：命中过时版本或 `retrieved_at` 超阈值时向 `risk_notes` 追加固定提示；current 且未 stale 不误报。
  - 验证：`pytest tests/test_qa_node.py`
- [x] trace 增加 `evidence_versions`
  - 文件范围：`app/nodes/qa.py`、`tests/test_qa_node.py`
  - 验收：trace 只记录短 metadata，不记录正文。
  - 验证：`pytest tests/test_qa_node.py`
- [x] 更新 QA prompt 时效约束
  - 文件范围：`app/prompts/patent_qa.py`
  - 验收：保留 `<data>` 数据隔离和禁止臆造约束，补充官方最新版本核对提示。
  - 验证：`pytest tests/test_qa_node.py`

## Phase 6: 任务文档与最终验收

- [x] 更新 `tasks/plan.md`
  - 文件范围：`tasks/plan.md`
  - 验收：包含 R4.2 实施计划、依赖图、checkpoint、风险与边界。
  - 验证：人工检查。
- [x] 更新 `tasks/todo.md`
  - 文件范围：`tasks/todo.md`
  - 验收：按 Phase 1–5 写 checklist 并更新状态。
  - 验证：人工检查。
- [x] 运行 R4.2 目标测试
  - 文件范围：R4.2 涉及源码与测试。
  - 验收：目标测试通过。
  - 验证：`pytest tests/test_core_config_logging.py tests/test_ingest_knowledge.py tests/test_retrieval_tool.py tests/test_qa_node.py`
- [x] 运行最终验收
  - 文件范围：全项目。
  - 验收：全量测试和编译检查通过。
  - 验证：`pytest && python -m compileall app tests scripts`
