# R4.6 FastEmbed 本地 Sparse 编码器实施计划

## 背景

R4.6 在 R4.3 已完成的混合检索骨架上扩展第三种 sparse 编码器 `fastembed`。当前代码已具备：

- `app/tools/retrieval.py`：`SparseEncoder` 协议、`LocalLexicalSparseEncoder`、`ServiceSparseEncoder`、`FakeSparseEncoder`、`QdrantRetriever` hybrid 分支、`_QdrantHTTPClient.query_hybrid()`、`_build_sparse_encoder()` 工厂。
- `scripts/ingest_knowledge.py`：hybrid collection schema、named dense + sparse point 写入、可注入 sparse encoder。
- `app/core/config.py`：`retrieval_use_hybrid`、`sparse_encoder`、`sparse_base_url`、`sparse_model`、`hybrid_fusion` 已存在并进入 `to_public_dict()`。
- `tests/test_retrieval_tool.py` / `tests/test_ingest_knowledge.py` / `tests/test_core_config_logging.py`：已覆盖 R4.3 hybrid 基线。

本阶段只实现 FastEmbed 本地 sparse 适配器与装配，不修改 `SparseEncoder` 协议、`RetrievalResult`、payload schema、RRF 融合逻辑、dense embedding、rerank、query rewrite 或 QA 主流程。

## 依赖图

```text
SPEC.md
  -> 适配器垂直切片
      -> app/tools/adapters/fastembed_sparse.py
      -> tests/test_sparse_encoders.py
      -> SparseEncoder 输出契约 {indices, values}
  -> 工厂装配垂直切片
      -> app/tools/retrieval.py:_build_sparse_encoder
      -> tests/test_retrieval_tool.py
      -> build_retriever -> QdrantRetriever.sparse_encoder
  -> 配置与依赖隔离垂直切片
      -> app/core/config.py:get_settings / to_public_dict
      -> tests/test_core_config_logging.py
      -> requirements.txt 可选依赖说明
  -> 查询降级垂直切片
      -> FastEmbedSparseEncoder.encode -> 空 sparse 向量
      -> QdrantRetriever.recall hybrid 分支
      -> tests/test_retrieval_tool.py
  -> 入库一致性垂直切片
      -> scripts/ingest_knowledge.py:ingest_knowledge / main
      -> app/tools/retrieval.py:_build_sparse_encoder
      -> tests/test_ingest_knowledge.py
  -> 项目级验收
      -> conda run -n autoGLM pytest tests/test_sparse_encoders.py tests/test_retrieval_tool.py
      -> conda run -n autoGLM pytest
      -> conda run -n autoGLM python -m compileall app tests scripts
```

## 关键文件

- `app/tools/adapters/fastembed_sparse.py`：新增 `FastEmbedSparseEncoder`，隔离 `fastembed` 延迟导入与输出转换。
- `app/tools/retrieval.py`：`_build_sparse_encoder()` 增加 `sparse_encoder == "fastembed"` 分支；避免顶层导入 `fastembed`。
- `scripts/ingest_knowledge.py`：hybrid 入库默认 sparse encoder 需与检索工厂一致；记录 sparse 配置用于重建索引判断。
- `app/core/config.py`：确认 `PAGENT_SPARSE_ENCODER=fastembed` 与 `PAGENT_SPARSE_MODEL` 环境变量读取、公开配置输出。
- `requirements.txt`：标注 `fastembed` 为可选依赖，不让默认安装/测试强依赖真实模型。
- `tests/test_sparse_encoders.py`：新增 FastEmbed 适配器测试，全部使用 fake / monkeypatch。
- `tests/test_retrieval_tool.py`：补工厂分发、hybrid 空 sparse 降级、默认路径不导入 fastembed。
- `tests/test_ingest_knowledge.py`：补 ingest 使用一致 sparse encoder 配置与配置记录测试。
- `tests/test_core_config_logging.py`：补 fastembed 环境变量覆盖与公开配置测试。

## 垂直切片计划

### Phase 1 — FastEmbed 适配器最小闭环

**目标**

新增本地 FastEmbed sparse 适配器，完成从 fake FastEmbed 输出到项目 sparse dict 的转换，并保证加载/编码失败时返回空向量。

**修改文件**

- `app/tools/adapters/fastembed_sparse.py`
- `tests/test_sparse_encoders.py`

**实施内容**

- 新增 `FastEmbedSparseEncoder` 公共类，提供中文 Google 风格 docstring。
- `__init__` 支持 `model_name: str | None = None` 与可选 fake model 注入参数，默认模型为 `Qdrant/bm25`。
- 未注入 fake model 时，在 `__init__` 内部延迟导入 `from fastembed import SparseTextEmbedding`。
- 捕获依赖缺失、模型加载失败和编码失败，统一降级为空向量。
- `encode(text)` 将 FastEmbed 输出转换为 `{"indices": list[int], "values": list[float]}`。
- 对常见 fake 输出形态做最小兼容：对象属性 `indices/values`、字典 `indices/values`、迭代器首个结果。

**验收标准**

- 不在 `app/tools/retrieval.py` 或其它默认路径顶层导入 `fastembed`。
- fake model 正常输出时，`encode()` 返回 int indices 与 float values。
- `model_name` 为空时使用 `Qdrant/bm25`。
- 模型加载异常时返回空向量。
- 编码异常时返回空向量。
- 测试不触网、不下载模型。

**Checkpoint**

```bash
conda run -n autoGLM pytest tests/test_sparse_encoders.py
```

### Phase 2 — 工厂装配与默认路径隔离

**目标**

让 `sparse_encoder="fastembed"` 通过 `_build_sparse_encoder()` 进入现有 `build_retriever -> QdrantRetriever -> query_hybrid` 链路，同时保持 `local` / `service` / dense-only 行为不变。

**修改文件**

- `app/tools/retrieval.py`
- `tests/test_retrieval_tool.py`

**实施内容**

- `_build_sparse_encoder(settings)` 增加分支：
  - `retrieval_use_hybrid=False` -> `None`。
  - `sparse_encoder == "service"` -> `ServiceSparseEncoder(settings)`。
  - `sparse_encoder == "fastembed"` -> 延迟导入并返回 `FastEmbedSparseEncoder(model_name=settings.sparse_model)`。
  - 其它值 -> `LocalLexicalSparseEncoder()`。
- 工厂测试通过 monkeypatch 替换 `FastEmbedSparseEncoder`，避免真实依赖。
- 验证 `build_retriever()` 注入 fake embedding / fake qdrant 后，fastembed sparse encoder 能挂到 `QdrantRetriever.sparse_encoder`。
- 验证 dense-only、local、service 路径不需要安装 fastembed。

**验收标准**

- `retrieval_use_hybrid=false` 仍返回 `None`。
- `sparse_encoder="local"` 或未知值仍走本地 hash sparse。
- `sparse_encoder="service"` 行为不变。
- `sparse_encoder="fastembed"` 返回 FastEmbed 适配器。
- 默认 `build_retriever(Settings())` 仍因 Qdrant/embedding 配置缺失回退 `LocalRetrievalTool`。

**Checkpoint**

```bash
conda run -n autoGLM pytest tests/test_sparse_encoders.py tests/test_retrieval_tool.py
```

### Phase 3 — 配置与可选依赖说明

**目标**

补齐 fastembed 配置验收与依赖隔离说明，不新增敏感字段，不把 fastembed 变成默认强依赖。

**修改文件**

- `app/core/config.py`（仅在测试发现缺口时最小调整）
- `tests/test_core_config_logging.py`
- `requirements.txt`

**实施内容**

- 补测试：`PAGENT_SPARSE_ENCODER=fastembed` 可读取为 `settings.sparse_encoder == "fastembed"`。
- 补测试：`PAGENT_SPARSE_MODEL=Qdrant/bm42-all-minilm-l6-v2-attentions` 可读取并进入 `to_public_dict()`。
- 确认 `to_public_dict()` 不新增敏感字段，不排除非敏感 sparse 配置。
- 在 `requirements.txt` 中以注释形式标注 `fastembed` 可选依赖；不默认安装模型、不提交权重。

**验收标准**

- 配置默认值保持 `sparse_encoder="local"`、`sparse_model=""`。
- 环境变量可切到 `fastembed`。
- `to_public_dict()` 可见 `sparse_encoder` 和 `sparse_model`。
- 默认测试环境未安装 fastembed 时不失败。

**Checkpoint**

```bash
conda run -n autoGLM pytest tests/test_core_config_logging.py tests/test_sparse_encoders.py
```

### Phase 4 — Hybrid 查询降级闭环

**目标**

证明 FastEmbed 编码失败时不打挂检索，并沿用现有 sparse 空向量 / Qdrant 异常安全路径。

**修改文件**

- `tests/test_retrieval_tool.py`
- `app/tools/retrieval.py`（仅在现有降级不满足 SPEC 时最小调整）

**实施内容**

- 补测试：FastEmbed fake encoder 返回空 sparse 向量时，`QdrantRetriever.search()` 不抛异常。
- 补测试：hybrid 请求仍携带 dense vector、sparse `{"indices": [], "values": []}`、`as_of` time filter 和 `limit=fetch_k`。
- 若现有 Qdrant fake 表明空 sparse 会导致 query_hybrid 异常，则保持当前 `except Exception: return []` 或调整为纯 dense fallback；优先不改 RRF 请求契约。

**验收标准**

- sparse 编码失败不会抛到 QA 主流程。
- hybrid 请求格式不因 R4.6 改变。
- `as_of` / 时效过滤仍透传。
- dense-only 路径不受影响。

**Checkpoint**

```bash
conda run -n autoGLM pytest tests/test_retrieval_tool.py
```

### Phase 5 — 入库一致性闭环

**目标**

确保 CLI 入库与 query 使用同一 sparse encoder 工厂配置，并在入库侧记录 sparse 配置，提醒切换 encoder / model 必须重建 collection。

**修改文件**

- `scripts/ingest_knowledge.py`
- `tests/test_ingest_knowledge.py`

**实施内容**

- 将 hybrid 入库默认 sparse encoder 从固定 `LocalLexicalSparseEncoder()` 改为与检索侧同源的 `_build_sparse_encoder(resolved_settings)`；仍保留显式 `sparse_encoder` 注入优先，便于测试。
- 避免循环 import 或重依赖顶层导入；若需要导入 `_build_sparse_encoder`，确认不会触发 `fastembed` 顶层导入。
- 在入库日志或 collection metadata/payload 可见位置记录 sparse 配置。优先选择低侵入日志或 `qdrant_client.ensure_collection(..., settings=resolved_settings)` 可测试记录；不改变业务 payload schema。
- 补测试：hybrid + `sparse_encoder="fastembed"` 时，未显式注入 sparse encoder 也会走工厂；用 monkeypatch fake 工厂避免真实 fastembed。

**验收标准**

- `ingest_knowledge(..., settings=Settings(retrieval_use_hybrid=True, sparse_encoder="fastembed"))` 使用与 query 同一工厂来源。
- 显式传入 `sparse_encoder=FakeSparseEncoder(...)` 时仍优先使用注入对象。
- hybrid point 格式仍为 `{"dense": [...], "sparse": {"indices": [...], "values": [...]}}`。
- 入库侧可观察当前 `sparse_encoder` / `sparse_model` 配置，用于判断是否需要重建 collection。

**Checkpoint**

```bash
conda run -n autoGLM pytest tests/test_ingest_knowledge.py tests/test_retrieval_tool.py
```

### Phase 6 — 项目级验收

**目标**

确认 R4.6 不破坏 R4.3 既有检索增强链路和默认测试路径。

**验收命令**

```bash
conda run -n autoGLM pytest tests/test_sparse_encoders.py tests/test_retrieval_tool.py
conda run -n autoGLM pytest tests/test_ingest_knowledge.py tests/test_core_config_logging.py
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests scripts
```

## 风险与边界

- 不真实安装 `fastembed`，除非用户明确要求。
- 不真实下载 BM25 / BM42 / SPLADE 模型。
- 不连接真实 Qdrant，不创建或重建真实 collection。
- 不修改 `query_hybrid` RRF 融合请求契约。
- 不修改 dense embedding、rerank、query rewrite、QA 主流程或 prompt。
- 不改变 `RetrievalResult`、payload schema 或现有 collection schema。
- 不混用不同 sparse encoder / sparse model 的索引；切换后必须重建 collection。
- 不新增 `qa_*` 等绑定单 Node 的配置项。
- 不硬编码 API Key、token、真实 endpoint 或本地私有模型路径。
