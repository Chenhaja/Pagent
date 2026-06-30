# R4.6 FastEmbed 本地 Sparse 编码器规格说明

## 1. Objective

### 目标

R4.6 的目标是在 R4.3 已有混合检索骨架上新增第三种 sparse 编码实现 `fastembed`：在本进程内通过 Qdrant FastEmbed 生成 BM25 / BM42 / SPLADE sparse 向量，降低外部 sparse 服务运维成本，并显著改善现有本地 hash 词频方案对中文与 IDF 缺失的质量短板。

完成标准：

- `sparse_encoder="fastembed"` 且 `retrieval_use_hybrid=true` 时，`_build_sparse_encoder()` 返回 `FastEmbedSparseEncoder`。
- `FastEmbedSparseEncoder` 实现现有 `SparseEncoder.encode(text) -> {"indices": [...], "values": [...]}` 协议，不修改 `SparseEncoder`、`RetrievalResult` 或 payload schema。
- `fastembed` 作为可选依赖，仅在选择 `fastembed` 编码器时延迟导入；默认 `local` 与 `service` 路径不触发导入、不新增运行时强依赖。
- FastEmbed 模型加载失败或编码异常时返回空 sparse 向量，并让混合检索链路退化为纯 dense，不打挂 QA。
- `sparse_model` 在 `fastembed` 模式下复用为 FastEmbed 模型名；为空时默认使用 `Qdrant/bm25`。
- ingest 与 query 使用同一 sparse encoder / sparse model 配置，避免索引空间错配。
- 单测使用 fake / monkeypatch，不真实下载模型、不触网。

### 目标用户

- 专利 QA 用户：需要更稳定命中法规、指南、模板、术语、条号和关键词证据。
- 知识库维护人员：需要在不维护外部 sparse 服务的情况下启用更高质量的混合检索。
- 开发与测试人员：需要可选依赖隔离、关闭态回归稳定、fake 模型可测的 sparse 扩展方案。

### 非目标

- 不修改 `query_hybrid` 的 RRF 融合逻辑。
- 不修改 dense embedding、rerank、query rewrite、QA 主流程或 prompt。
- 不引入 GPU 部署要求。
- 不在 CI 中真实下载 FastEmbed 模型或访问外网。
- 不做 BM25 / BM42 / SPLADE 的离线质量对比评测。
- 不迁移或覆盖已有 collection；切换 sparse encoder 必须重建 collection。

---

## 2. Commands

项目使用 conda 环境 `autoGLM`。所有 Python / pytest / 脚本命令必须通过 `conda run -n autoGLM` 执行，不能依赖 `conda activate` 的跨命令状态。

```bash
# FastEmbed sparse 编码器与工厂测试
conda run -n autoGLM pytest tests/test_sparse_encoders.py tests/test_retrieval_tool.py

# 入库一致性与 schema / point 结构测试
conda run -n autoGLM pytest tests/test_ingest_knowledge.py

# 全量测试
conda run -n autoGLM pytest

# 编译检查
conda run -n autoGLM python -m compileall app tests scripts
```

最终验收命令：

```bash
conda run -n autoGLM pytest tests/test_sparse_encoders.py tests/test_retrieval_tool.py
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests scripts
```

依赖说明：

```bash
# 默认环境不要求安装 fastembed；仅实际启用 fastembed 编码器时安装
conda run -n autoGLM pip install fastembed
```

约束：

- `requirements.txt` 需要记录 `fastembed` 的可选依赖说明，但默认测试不能因未安装 `fastembed` 失败。
- 测试必须通过 fake model / monkeypatch 验证适配器行为，不触发真实模型下载。
- 不连接真实 Qdrant、不创建真实 collection，除非用户明确要求。

---

## 3. Project Structure

R4.6 只扩展 sparse encoder 组件，不改检索协议、融合协议和 QA 主流程。

目标变更：

```text
pagent/
  app/
    core/
      config.py                         # 复用 sparse_encoder / sparse_model；补 fastembed 取值测试
    tools/
      retrieval.py                      # _build_sparse_encoder 增加 fastembed 分支
      adapters/
        fastembed_sparse.py             # FastEmbedSparseEncoder，延迟导入重依赖
  scripts/
    ingest_knowledge.py                 # 入库侧使用同一 sparse encoder 配置；记录配置一致性
  tests/
    test_sparse_encoders.py             # FastEmbed 适配器 fake model、降级、输出格式测试
    test_retrieval_tool.py              # 工厂分发、hybrid 降级、as_of 透传回归
    test_ingest_knowledge.py            # sparse 配置一致性 / metadata 或日志测试
  requirements.txt                      # 标注 fastembed 可选依赖
  SPEC.md                               # 本规格
```

### SparseEncoder 契约

沿用 R4.3 协议，不新增方法：

```python
class SparseEncoder(Protocol):
    def encode(self, text: str) -> dict: ...
```

返回格式固定为：

```json
{"indices": [12, 88, 1043], "values": [0.7, 0.4, 0.9]}
```

约束：

- `indices` 必须是 `int` 列表。
- `values` 必须是 `float` 列表。
- 两个列表长度必须一致。
- 空向量统一返回 `{"indices": [], "values": []}`。
- 编码异常不得抛出到 `QdrantRetriever` 或 QA 主流程。

### FastEmbedSparseEncoder 契约

新增 `FastEmbedSparseEncoder`，建议位于 `app/tools/adapters/fastembed_sparse.py`。

职责：

- 在 `__init__` 中延迟导入 `from fastembed import SparseTextEmbedding`。
- 使用 `SparseTextEmbedding(model_name=model_name or "Qdrant/bm25")` 初始化模型。
- `encode(text)` 调用 FastEmbed sparse embedding 接口，并转换为项目统一 sparse dict。
- 支持测试注入 fake embedding model 或 monkeypatch `SparseTextEmbedding`。
- 模型加载失败、依赖缺失、编码异常时记录 warning，并返回空向量。

约束：

- 不在 `retrieval.py` 顶层导入 `fastembed`。
- 不让缺失 `fastembed` 影响 `local` / `service` 编码器。
- 不在日志中记录完整 query / document 原文。
- 公共类和公共方法必须有中文 Google 风格 docstring。

### 工厂分发契约

`_build_sparse_encoder()` 分发规则：

```text
retrieval_use_hybrid=False -> None
sparse_encoder == "service" -> ServiceSparseEncoder
sparse_encoder == "fastembed" -> FastEmbedSparseEncoder
其它 / 缺省 -> LocalLexicalSparseEncoder
```

约束：

- `fastembed` 分支只在实际选择时导入适配器。
- `local` 与 `service` 分支行为不变。
- 未识别取值继续走现有兜底策略，不扩大错误面。
- `sparse_model` 为空且 `sparse_encoder="fastembed"` 时使用 `Qdrant/bm25`。

### 配置契约

复用现有字段，尽量不新增配置：

| 配置字段 | 环境变量 | 默认值 / 现状 | R4.6 约定 |
| --- | --- | --- | --- |
| `retrieval_use_hybrid` | `PAGENT_RETRIEVAL_USE_HYBRID` | `false` | 不变，混合检索总开关 |
| `sparse_encoder` | `PAGENT_SPARSE_ENCODER` | `local` | 新增合法值 `fastembed` |
| `sparse_model` | `PAGENT_SPARSE_MODEL` | `""` | `fastembed` 模式下为 FastEmbed 模型名；空时用 `Qdrant/bm25` |
| `hybrid_fusion` | `PAGENT_HYBRID_FUSION` | `rrf` | 不变 |

要求：

- 不新增敏感字段；`to_public_dict()` 无新增排除项。
- 若代码层修改默认值，必须同步默认值、环境变量读取、公开配置和测试。
- 配置名保持通用检索作用域，不新增 `qa_*` 或绑定单 Node 的字段。

### 入库一致性契约

- ingest 写入 sparse 向量时必须使用与 query 相同的 `sparse_encoder` 与 `sparse_model`。
- 切换 `local` / `service` / `fastembed` 或切换 `sparse_model` 后，必须重建 collection。
- 建议在入库日志或 collection metadata 中记录 sparse 配置：`sparse_encoder`、`sparse_model`、`retrieval_use_hybrid`。
- 不因 R4.6 修改 payload schema 或 `RetrievalResult`。

---

## 4. Code Style

### 基本原则

- 最小化、局部化改动，优先复用 R4.3 已有 `SparseEncoder`、`ServiceSparseEncoder`、`LocalLexicalSparseEncoder`、`QdrantRetriever` 与 ingest 组装逻辑。
- 重依赖隔离在适配器文件中，避免 `fastembed` import 污染默认路径。
- 公共函数、公共方法、公共类必须添加中文 Google 风格 docstring，包含 Args / Returns / Raises（如有）。
- 注释和日志沿用中文风格；`event` 如存在应使用稳定英文名。
- 可恢复异常使用 warning 并说明降级为空 sparse 向量或纯 dense。
- 不硬编码模型权重路径、真实 endpoint、API Key、token 或 secret。
- 不记录完整文本、敏感数据或过长文档正文。

### 错误处理与降级

- 未安装 `fastembed` 且未选择 `fastembed`：不得失败。
- 选择 `fastembed` 但未安装依赖：适配器初始化失败后编码结果为空向量，检索退化为 dense。
- 模型加载失败：返回空向量，不中断检索。
- 编码异常或 FastEmbed 返回格式异常：返回空向量。
- sparse 空向量时，沿用现有混合检索降级语义，不抛出到 QA。

### 外部调用安全

- FastEmbed 为本地推理，不外发文本。
- `service` sparse 既有外部调用路径不在 R4.6 中扩展。
- 不新增 API Key / token 配置。
- 不触网下载模型作为单元测试前置条件。

---

## 5. Testing Strategy

### FastEmbed 适配器测试

必须覆盖：

- 使用 fake model 注入或 monkeypatch `SparseTextEmbedding`，`encode("text")` 输出 `{"indices": [...], "values": [...]}`。
- FastEmbed 返回对象格式不同但可解析时，适配器能转换为项目统一 dict。
- `sparse_model` 为空时使用默认模型 `Qdrant/bm25`。
- 模型加载异常时 `encode` 返回空向量。
- 编码异常时 `encode` 返回空向量。
- 测试不安装真实模型、不下载权重、不访问网络。

### 工厂分发测试

必须覆盖：

- `retrieval_use_hybrid=false` 时 `_build_sparse_encoder()` 返回 `None`。
- `sparse_encoder="local"` 或未知值时保持现有本地 sparse 兜底。
- `sparse_encoder="service"` 时返回 `ServiceSparseEncoder`，行为不变。
- `sparse_encoder="fastembed"` 时返回 `FastEmbedSparseEncoder`。
- `local` / `service` 测试路径不需要安装 `fastembed`。

### 混合检索降级测试

必须覆盖：

- FastEmbed 编码失败返回空 sparse 后，`QdrantRetriever` 不报错。
- sparse 空向量时检索退化为纯 dense 或现有安全路径。
- `query_hybrid` 的 dense / sparse 请求格式不因 R4.6 改变。
- `as_of` / 时效过滤仍透传到检索请求。

### 入库一致性测试

必须覆盖：

- ingest 在 hybrid 模式下使用同一 `_build_sparse_encoder()` 或等价组装逻辑。
- hybrid point 中 sparse 向量格式仍为 `indices` / `values`。
- 入库日志或 metadata 可体现当前 `sparse_encoder` / `sparse_model`，用于识别是否需要重建 collection。
- 切换 encoder 的风险在测试或文档中有明确提示，不自动混用旧索引。

### 配置与依赖隔离测试

必须覆盖：

- `PAGENT_SPARSE_ENCODER=fastembed` 可被读取为配置值。
- `PAGENT_SPARSE_MODEL` 可覆盖 FastEmbed 模型名。
- `to_public_dict()` 中非敏感 sparse 配置可见，且无新增敏感字段。
- 未安装 `fastembed` 时，全量默认测试仍通过。

### 验收口径

- `conda run -n autoGLM pytest tests/test_sparse_encoders.py tests/test_retrieval_tool.py` 通过。
- `conda run -n autoGLM pytest` 通过。
- `conda run -n autoGLM python -m compileall app tests scripts` 通过。
- 测试不触网、不下载模型、不提交模型权重。

---

## 6. Boundaries

### Always do

- 始终保持 `fastembed` 为可选依赖。
- 始终延迟导入 `fastembed`，避免默认路径受影响。
- 始终复用现有 `SparseEncoder` 协议和 sparse 向量格式。
- 始终让模型加载 / 编码失败降级为空 sparse 向量。
- 始终保持 `local` / `service` sparse 编码器行为不变。
- 始终让 ingest 与 query 使用一致的 sparse encoder / sparse model。
- 始终提示切换 sparse encoder 或 sparse model 需要重建 collection。
- 始终用 fake / stub / monkeypatch 做单测，不触发真实模型下载。
- 始终使用 `conda run -n autoGLM` 执行 Python、pytest 和脚本命令。

### Ask first

- 是否安装 `fastembed` 或其它新依赖。
- 是否真实下载 BM25 / BM42 / SPLADE 模型。
- 是否连接真实 Qdrant 并创建 / 重建 collection。
- 是否切换生产或主 collection 到 fastembed sparse 索引。
- 是否修改 RRF 融合、dense embedding、rerank、query rewrite 或 QA 主流程。
- 是否提交大体积模型、语料或评测产物。

### Never do

- 不在模块顶层导入 `fastembed` 导致默认路径强依赖。
- 不让 `fastembed` 缺失影响 `local` / `service` 或纯 dense 检索。
- 不把增强能力异常抛到 QA 主流程。
- 不混用不同 sparse encoder / sparse model 生成的索引空间。
- 不硬编码 API Key、token、真实 endpoint 或本地私有模型路径。
- 不在 CI / 单测中访问外网或下载模型权重。
- 不改变 `RetrievalResult`、payload schema 或 `query_hybrid` RRF 请求契约。
- 不新增绑定单 Node 的 `qa_*` 检索配置。

---

## 7. Functional Acceptance Checklist

- [ ] 新增 `FastEmbedSparseEncoder`，实现 `SparseEncoder.encode` 协议。
- [ ] `FastEmbedSparseEncoder` 延迟导入 `SparseTextEmbedding`。
- [ ] `FastEmbedSparseEncoder` 支持 fake model 注入或 monkeypatch 测试。
- [ ] `sparse_model` 为空时默认使用 `Qdrant/bm25`。
- [ ] 模型加载失败返回空 sparse 向量。
- [ ] 编码异常返回空 sparse 向量。
- [ ] `_build_sparse_encoder()` 支持 `sparse_encoder="fastembed"`。
- [ ] `retrieval_use_hybrid=false` 时仍返回 `None`。
- [ ] `local` / `service` sparse 编码器行为不变。
- [ ] 未安装 `fastembed` 时默认测试路径不失败。
- [ ] hybrid query 的 sparse 向量格式保持 `indices` / `values`。
- [ ] sparse 空向量时检索安全退化为 dense。
- [ ] `as_of` / 时效过滤继续透传。
- [ ] ingest 与 query 复用同一 sparse encoder 配置。
- [ ] 入库日志或 metadata 记录 sparse encoder / sparse model 配置。
- [ ] `requirements.txt` 标注 `fastembed` 可选依赖。
- [ ] 配置测试覆盖 `PAGENT_SPARSE_ENCODER=fastembed` 与 `PAGENT_SPARSE_MODEL`。
- [ ] `to_public_dict()` 无敏感字段新增风险。
- [ ] `tests/test_sparse_encoders.py` 与 `tests/test_retrieval_tool.py` 通过。
- [ ] `conda run -n autoGLM pytest` 通过。
- [ ] `conda run -n autoGLM python -m compileall app tests scripts` 通过。

---

## 8. Implementation Order

1. 适配器：新增 `FastEmbedSparseEncoder`，完成延迟导入、默认模型、输出转换与失败降级。
2. 单测：用 fake model 覆盖正常输出、加载失败、编码失败和默认模型。
3. 工厂：在 `_build_sparse_encoder()` 中增加 `fastembed` 分支，保持 `local` / `service` 不变。
4. 配置：补充 `sparse_encoder="fastembed"` 与 `sparse_model` 覆盖测试；确认 `to_public_dict()` 无敏感新增。
5. 入库一致性：确保 ingest 使用同一 sparse encoder 配置，并记录 sparse 配置用于重建索引判断。
6. 依赖：在 `requirements.txt` 标注 `fastembed` 可选依赖，不让默认测试依赖安装。
7. 回归：运行目标测试、全量测试和 compileall。
