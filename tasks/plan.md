# R4.2 时效性管理实施计划

## Context

R4.2 目标是让法规类知识具备时效性：默认回答现行法规，支持按时间点追溯历史版本，并在 QA 出处中标注法规版本与生效日期。当前代码已具备 R4.1 的本地/Qdrant 检索、入库脚本、QA evidence 链路和 fake/stub 测试基础，本计划在其上补齐法规版本元数据、时间过滤、过时提示和 trace 版本记录。

## Dependency graph

```text
配置 Slice
  ├─> 检索过滤 Slice
  └─> QA stale 阈值 Slice

入库 metadata Slice
  ├─> Qdrant payload 映射/过滤 Slice
  ├─> Local 内存过滤 Slice
  └─> QA evidence 标注 Slice

RetrievalResult / Retriever 协议 Slice
  ├─> Qdrant 后端 Slice
  ├─> Local 后端 Slice
  └─> QA _retrieve 兼容 Slice

Qdrant + Local 后端 Slice
  └─> QA 端到端 evidence / warning / trace Slice
```

## Phase 1 — 配置切片

**修改文件**
- `app/core/config.py`
- `tests/test_core_config_logging.py`

**实施内容**
- 在 `Settings` 增加 `retrieval_default_status`、`retrieval_enable_time_filter`、`law_stale_days`。
- 在 `get_settings()` 读取 `PAGENT_RETRIEVAL_DEFAULT_STATUS`、`PAGENT_RETRIEVAL_ENABLE_TIME_FILTER`、`PAGENT_LAW_STALE_DAYS`。
- 在 `to_public_dict()` 输出非敏感配置，继续排除 API Key。

**Checkpoint A**
```bash
pytest tests/test_core_config_logging.py
```

## Phase 2 — 入库 metadata 与 payload 切片

**修改文件**
- `scripts/ingest_knowledge.py`
- `tests/test_ingest_knowledge.py`
- `knowledge/law/zhuanli_fa_2020/meta.json`

**实施内容**
- 扩展 `KnowledgeChunk` 法规时效字段。
- `load_chunks()` 对 law 版本目录读取同目录 `meta.json`，跳过 `meta.json`。
- law `document_id` 优先取 `meta.json.document_id`，缺失时使用版本目录名。
- 自动生成 `retrieved_at` 和 `content_hash`。
- law `locator` 增加版本信息。
- 入库 payload 写入全部时效字段，非 law 保持 R4.1 行为。

**Checkpoint B**
```bash
pytest tests/test_ingest_knowledge.py
```

## Phase 3 — 检索模型与过滤 helper 切片

**修改文件**
- `app/tools/retrieval.py`
- `tests/test_retrieval_tool.py`

**实施内容**
- 扩展 `RetrievalResult` 法规时效字段，保持旧构造方式兼容。
- 扩展 `Retriever.search(query, top_k, as_of=None)`。
- 集中实现 law-only 时间过滤 helper。
- 过滤规则：关闭开关不过滤；非 law 不过滤；`as_of` 按有效期过滤；默认按 `status == retrieval_default_status`。
- 日期解析失败或字段缺失安全返回不匹配，不抛裸异常。

## Phase 4 — Local 与 Qdrant 后端过滤切片

**修改文件**
- `app/tools/retrieval.py`
- `tests/test_retrieval_tool.py`

**实施内容**
- `LocalRetrievalTool.search()` 支持 `as_of` 并应用 law-only 过滤。
- Local 结果透传新增时效字段。
- `_QdrantHTTPClient.search()` 支持 `query_filter`。
- `QdrantRetriever.search()` 构造“非 law OR 满足法规时间条件”的 filter。
- Qdrant/embedding 异常继续返回 `[]`。

**Checkpoint C**
```bash
pytest tests/test_retrieval_tool.py
```

## Phase 5 — QA evidence、过时提示与 trace 切片

**修改文件**
- `app/nodes/qa.py`
- `app/prompts/patent_qa.py`
- `tests/test_qa_node.py`

**实施内容**
- `_build_evidence()` 透传法规时效字段。
- law evidence 增加不伪造的 `citation`，含版本和生效日。
- skill 返回后 deterministic 后处理：命中 `superseded` 或 stale `retrieved_at` 时向 `risk_notes` 追加固定提示。
- `qa_completed` trace 增加 `evidence_versions`，只记录短 metadata，不记录正文。
- `PATENT_QA_SYSTEM_PROMPT` 补充官方最新文本和历史版本核对约束。

**Checkpoint D**
```bash
pytest tests/test_qa_node.py
```

## Phase 6 — 任务文档与最终验收

**修改文件**
- `tasks/plan.md`
- `tasks/todo.md`

**实施内容**
- 创建/更新 R4.2 计划与 todo。
- 按 checkpoint 更新完成状态。
- 运行目标测试和最终验收。

**Checkpoint E**
```bash
pytest tests/test_core_config_logging.py tests/test_ingest_knowledge.py tests/test_retrieval_tool.py tests/test_qa_node.py
```

**Checkpoint F**
```bash
pytest && python -m compileall app tests scripts
```

## 风险与边界

- 最小化、局部化改动，复用现有 `Settings`、`KnowledgeChunk`、`build_point_id()`、`RetrievalResult`、`LocalRetrievalTool`、`QdrantRetriever`、`QANode._build_evidence()` 模式。
- 测试只使用 fake/stub，不触真实 Qdrant、embedding、LLM 或网络。
- 非 law 文档不受法规时间过滤影响。
- 缺失法规元数据时不伪造版本、生效日、来源 URL。
- 日志/trace 不记录密钥、完整正文或敏感材料。
- 不实现自动抓取、变更检测、定时重建或上游 `as_of` 意图识别。
