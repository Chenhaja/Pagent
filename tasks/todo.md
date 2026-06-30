# R4.6 Todo

## 1. 建立 FastEmbed 适配器测试

- [ ] 目标：新增 `tests/test_sparse_encoders.py`，用 fake model / monkeypatch 锁定 FastEmbed 适配器输出、默认模型和失败降级行为。
- 依赖：`SPEC.md`、`tasks/plan.md`。
- 验收标准：覆盖 fake 正常输出、默认 `Qdrant/bm25`、模型加载异常、编码异常、输出格式 `indices` / `values`；测试不触网、不下载模型。
- 验证命令：`conda run -n autoGLM pytest tests/test_sparse_encoders.py`

## 2. 实现 FastEmbed 适配器

- [ ] 目标：新增 `app/tools/adapters/fastembed_sparse.py`，实现 `FastEmbedSparseEncoder`。
- 依赖：任务 1。
- 验收标准：公共类/方法有中文 Google 风格 docstring；`fastembed` 只在适配器初始化路径延迟导入；`encode()` 返回 `{"indices": list[int], "values": list[float]}`；加载/编码失败返回空向量。
- 验证命令：`conda run -n autoGLM pytest tests/test_sparse_encoders.py`

## 3. 建立工厂分发测试

- [ ] 目标：扩充 `tests/test_retrieval_tool.py`，锁定 `_build_sparse_encoder()` 对 `fastembed` 的分发和默认路径隔离。
- 依赖：任务 2。
- 验收标准：`retrieval_use_hybrid=false` 返回 `None`；`local` / 未知值走 `LocalLexicalSparseEncoder`；`service` 走 `ServiceSparseEncoder`；`fastembed` 走 `FastEmbedSparseEncoder`；local/service/dense-only 路径不要求安装 fastembed。
- 验证命令：`conda run -n autoGLM pytest tests/test_sparse_encoders.py tests/test_retrieval_tool.py`

## 4. 接入 `_build_sparse_encoder()` fastembed 分支

- [ ] 目标：在 `app/tools/retrieval.py` 为 `_build_sparse_encoder()` 增加 `sparse_encoder == "fastembed"` 分支。
- 依赖：任务 3。
- 验收标准：`build_retriever()` 在 hybrid + fastembed 配置下可装配 FastEmbed sparse encoder；`local` / `service` 行为不变；`retrieval.py` 不顶层导入 `fastembed`。
- 验证命令：`conda run -n autoGLM pytest tests/test_sparse_encoders.py tests/test_retrieval_tool.py`

## 5. 建立配置与公开配置测试

- [ ] 目标：扩充 `tests/test_core_config_logging.py`，验证 `PAGENT_SPARSE_ENCODER=fastembed` 与 `PAGENT_SPARSE_MODEL` 覆盖行为。
- 依赖：任务 4。
- 验收标准：环境变量可读到 `fastembed`；`sparse_model` 可读到 FastEmbed 模型名；`to_public_dict()` 包含非敏感 sparse 配置；无新增敏感字段暴露。
- 验证命令：`conda run -n autoGLM pytest tests/test_core_config_logging.py`

## 6. 标注 FastEmbed 可选依赖

- [ ] 目标：更新 `requirements.txt`，以注释形式标注 `fastembed` 为可选依赖。
- 依赖：任务 5。
- 验收标准：默认安装/测试不强制安装 fastembed；说明仅启用 `PAGENT_SPARSE_ENCODER=fastembed` 时需要安装；不提交模型权重。
- 验证命令：人工读取 `requirements.txt`；`conda run -n autoGLM pytest tests/test_sparse_encoders.py tests/test_core_config_logging.py`

## 7. 建立 hybrid 空 sparse 降级测试

- [ ] 目标：扩充 `tests/test_retrieval_tool.py`，证明 FastEmbed 编码失败或返回空 sparse 时检索不抛异常。
- 依赖：任务 4。
- 验收标准：hybrid 请求可携带 `{"indices": [], "values": []}`；`as_of` time filter 仍透传；Qdrant 异常时保持安全返回；dense-only 路径不受影响。
- 验证命令：`conda run -n autoGLM pytest tests/test_retrieval_tool.py`

## 8. 补齐 hybrid 查询降级实现

- [ ] 目标：如任务 7 暴露缺口，最小调整 `QdrantRetriever` 或相关逻辑以满足降级要求。
- 依赖：任务 7。
- 验收标准：sparse 编码失败不抛到 QA；hybrid 请求格式不变；`query_hybrid` RRF 契约不变；已有 hybrid 测试继续通过。
- 验证命令：`conda run -n autoGLM pytest tests/test_retrieval_tool.py`

## 9. 建立入库一致性测试

- [ ] 目标：扩充 `tests/test_ingest_knowledge.py`，锁定 ingest 默认 sparse encoder 与 query 工厂同源。
- 依赖：任务 4。
- 验收标准：hybrid + `sparse_encoder="fastembed"` 且未显式注入 sparse encoder 时，通过 monkeypatch fake 工厂确认 ingest 使用 `_build_sparse_encoder()`；显式注入 `FakeSparseEncoder` 时仍优先使用注入对象；point vector 格式不变。
- 验证命令：`conda run -n autoGLM pytest tests/test_ingest_knowledge.py`

## 10. 实现入库同源 sparse encoder 与配置记录

- [ ] 目标：调整 `scripts/ingest_knowledge.py`，hybrid 默认 sparse encoder 使用与检索侧同源的工厂，并记录 sparse 配置。
- 依赖：任务 9。
- 验收标准：默认 hybrid 入库不再固定使用 `LocalLexicalSparseEncoder()`；`sparse_encoder` 显式注入优先级不变；入库日志或可测试记录体现 `sparse_encoder` / `sparse_model`；不改变业务 payload schema。
- 验证命令：`conda run -n autoGLM pytest tests/test_ingest_knowledge.py tests/test_retrieval_tool.py`

## 11. 运行目标回归

- [ ] 目标：运行 R4.6 目标测试，确认适配器、工厂、配置和入库一致性闭环通过。
- 依赖：任务 10。
- 验收标准：目标测试全部通过；无真实网络、无模型下载、无 fastembed 强依赖。
- 验证命令：`conda run -n autoGLM pytest tests/test_sparse_encoders.py tests/test_retrieval_tool.py tests/test_ingest_knowledge.py tests/test_core_config_logging.py`

## 12. 运行项目级验收

- [ ] 目标：运行全量测试与编译检查。
- 依赖：任务 11。
- 验收标准：全量 `pytest` 通过；`compileall` 通过；未引入敏感信息、真实服务调用或模型权重。
- 验证命令：`conda run -n autoGLM pytest && conda run -n autoGLM python -m compileall app tests scripts`
