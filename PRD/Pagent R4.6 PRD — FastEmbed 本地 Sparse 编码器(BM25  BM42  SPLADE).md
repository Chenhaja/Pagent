<aside>
 💡

**文档类型**:PRD · **阶段**:R4.6 混合检索 Sparse 编码器扩展(FastEmbed 本地适配) · **状态**:草稿待评审
 **承接**:R4.3(混合检索 dense+sparse / RRF 融合 / `SparseEncoder` 协议 / `_build_sparse_encoder` 工厂)
 **不破坏**:R4.3 已有 `local` / `service` 两种 sparse 实现、`query_hybrid` 链路、`RetrievalResult` 与 payload schema

</aside>

本 PRD 对应仓库 `Chenhaja/Pagent`,承接 R4.3 检索质量增强阶段,沿用既有分层骨架(Tool / Node / Skill)、`PAGENT_` 参数规范与 R 编号风格。

## 1. 背景与目标

### 1.1 背景

R4.3 已落地混合检索,sparse 向量当前有两条路(`config.sparse_encoder`):

- **`local`**:`LocalLexicalSparseEncoder` —— `text.split()` + sha256 hash 到 100 万维、raw TF。零依赖,但**对中文按空格切失效**、无 IDF,检索质量有限。
- **`service`**:`ServiceSparseEncoder` —— 调外部 `POST {sparse_base_url}/sparse-embeddings`。质量取决于服务端,但**需要自建并长期维护一个 sparse 推理服务**,运维成本高。

两条路是“质量低但零成本”与“质量高但要养服务”的两极,中间缺一档。

### 1.2 目标

新增第三种 sparse 实现 **`fastembed`**:在本进程内用 Qdrant 官方 FastEmbed 产出工业级 BM25/BM42/SPLADE sparse 向量,**免外部服务、免自建运维**,质量显著优于本地 hash 词频。同时把“组件可替换”做扎实,为后续再换 sparse 方案留好扩展位。

- **G1**:`sparse_encoder="fastembed"` 时,`_build_sparse_encoder()` 返回 FastEmbed 适配器,无缝接入现有 `query_hybrid` 链路。
- **G2**:`fastembed` 作为**可选依赖**,仅在选用时延迟导入;默认 `local` 路径与所有现有测试零影响、零新依赖。
- **G3**:适配器实现现有 `SparseEncoder` 协议,失败时优雅降级为空向量(与 `ServiceSparseEncoder` 行为一致),最终退化为纯 dense。
- **G4**:为后续组件更换抽象——sparse 适配器实现与重依赖 import 集中隔离,新增/移除实现不影响 `QdrantRetriever`、ingest、协议。

## 2. 范围

### 2.1 In Scope

- 新增 `FastEmbedSparseEncoder`(实现 `SparseEncoder.encode`,延迟导入 `fastembed`)。
- `_build_sparse_encoder()` 增加 `"fastembed"` 分支。
- 配置:复用 `sparse_model` 作为 FastEmbed 模型名;明确取值约定与校验;`requirements` 可选依赖说明。
- 入库侧(`scripts/ingest_knowledge.py`)使用同一编码器产出 sparse 的一致性约束(确保 query/index 同源)。
- 单测:FastEmbed 适配器(用 fake model 注入,不真装模型)、工厂分发、降级。

### 2.2 Out of Scope

- 不改 `query_hybrid` 的 RRF 融合逻辑、不改 dense embedding、不改 rerank/query-rewrite。
- 不引入 GPU 部署要求(BM25/BM42 纯 CPU 即可;SPLADE 走 CPU onnx)。
- 不做 sparse 三方案的离线质量对比评测(可另立 eval 阶段)。

## 3. 名词与概念

| 术语        | 含义                                                     |
| ----------- | -------------------------------------------------------- |
| FastEmbed   | Qdrant 官方轻量 embedding 库,支持稀疏模型                |
| BM25 / BM42 | 词法稀疏,index=token id;BM42 为 attention 加权改进版     |
| SPLADE      | 学习式稀疏,带词项扩展(同义/相关词),召回质量高            |
| 延迟导入    | `import fastembed` 仅在实例化适配器时执行,避免全局强依赖 |

## 4. 功能需求

- **FR-1 FastEmbed 适配器**:`FastEmbedSparseEncoder.encode(text) -> {"indices": [int], "values": [float]}`,内部用 `SparseTextEmbedding(model_name=settings.sparse_model)`,输出对齐 `query_hybrid` 期望的 `using:"sparse"` 向量格式。

- **FR-2 延迟导入与隔离**:`from fastembed import SparseTextEmbedding` 放在 `__init__`(或模块级懒加载),`fastembed` 仅 `fastembed` 路径需要;其它后端/测试不触发。建议把适配器单独放 `app/tools/adapters/fastembed_sparse.py`,重依赖只在该文件出现(便于后续整组件替换/删除)。

- FR-3 工厂分发

  :

  ```
  _build_sparse_encoder()
  ```

   改为:

  - `retrieval_use_hybrid=False` → `None`(不变)
  - `sparse_encoder=="service"` → `ServiceSparseEncoder`(不变)
  - `sparse_encoder=="fastembed"` → `FastEmbedSparseEncoder`(新增)
  - 其它/缺省 → `LocalLexicalSparseEncoder`(不变,兜底)

- **FR-4 优雅降级**:模型加载失败或编码异常时 `encode` 返回 `{"indices": [], "values": []}`;`QdrantRetriever` 据此退化为纯 dense(沿用现有 `sparse_encoder is not None` + 空向量行为,不报错)。

- **FR-5 模型取值约定**:`sparse_model` 在 `fastembed` 模式下取 FastEmbed 模型标识(如 `Qdrant/bm25`、`Qdrant/bm42-all-minilm-l6-v2-attentions`、`prithivida/Splade_PP_en_v1`);为空时给出明确默认(建议 `Qdrant/bm25`)或降级日志。

- **FR-6 入库一致性**:ingest 写 sparse 时必须使用与检索同一 `sparse_encoder` 配置;切换 encoder 需重建 collection(因 index 空间/语义不同)。

## 5. 接口与数据契约

- **sparse 向量格式**(与 R4.3 完全一致,保证 `query_hybrid` 零改动):

```json
{ "indices": [12, 88, 1043], "values": [0.7, 0.4, 0.9] }
```

- **`SparseEncoder` 协议**:沿用现有定义,`FastEmbedSparseEncoder` 实现之,不新增协议方法。
- **`RetrievalResult` / payload**:不变。

## 6. 配置项(遵循 `PAGENT_` 参数规范)

**复用现有字段,尽量不新增**,把改动面压到最小:

| 字段                   | 环境变量                      | 现状/取值               | 本阶段约定                                                   |
| ---------------------- | ----------------------------- | ----------------------- | ------------------------------------------------------------ |
| `sparse_encoder`       | `PAGENT_SPARSE_ENCODER`       | `local`(默认)/`service` | **新增合法值 `fastembed`**                                   |
| `sparse_model`         | `PAGENT_SPARSE_MODEL`         | `""`                    | `fastembed` 模式下复用为 FastEmbed 模型名;空时默认 `Qdrant/bm25` |
| `retrieval_use_hybrid` | `PAGENT_RETRIEVAL_USE_HYBRID` | `false`                 | 不变,总开关                                                  |
| `hybrid_fusion`        | `PAGENT_HYBRID_FUSION`        | `rrf`                   | 不变                                                         |

<aside>
 🔐

不新增敏感字段:FastEmbed 本地推理无需 API Key,因此**无 `to_public_dict()` 排除项变更**。若 `sparse_model` 默认值落地为 `Qdrant/bm25`,需同步默认值 + 环境变量测试(按参数规范)。

</aside>

## 7. 非功能需求

- **NFR-1 依赖约束(关键)**:`fastembed` 为**可选依赖**,写入 `requirements`(可选 extra 或注释标注),安装前确认(沿用 SPEC 依赖约束条款)。默认 `local` 路径仍零新依赖。
- **NFR-2 离线可测**:测试用**注入式 fake model**(monkeypatch 掉 `SparseTextEmbedding` 或注入实现 `encode` 的桩),不真实下载模型、不触网。
- **NFR-3 合规**:本地推理不外发文本,天然优于 `service`;不引入新的敏感外发面。
- **NFR-4 一致性**:入库与检索的 `sparse_encoder`/`sparse_model` 必须一致;建议把当前 sparse 配置写入入库日志或 collection 元数据,换 encoder 强制重建索引。
- **NFR-5 兼容**:`retrieval_use_hybrid=false` 或 `sparse_encoder!=fastembed` 时行为与 R4.3 完全一致。
- **NFR-6 性能**:BM25/BM42 CPU 毫秒级;SPLADE 首次加载模型有冷启动开销,需在文档标注(进程内单例复用)。

## 8. 验收标准

- **A1**:`tests/test_sparse_encoders.py`(扩充)—— 注入 fake FastEmbed model,`encode` 正确产出 `{indices, values}`;模型加载/编码异常时返回空向量。
- **A2**:`tests/test_retrieval_tool.py`(扩充)—— `sparse_encoder="fastembed"` 时 `_build_sparse_encoder` 返回 FastEmbed 适配器;`query_hybrid` 被正确调用;sparse 失败退化为 dense;时效过滤 / `as_of` 仍生效。
- **A3**:依赖隔离验证 —— 不安装 `fastembed` 时,`local`/`service` 路径与全量测试仍通过(import 不在模块顶层触发)。
- **A4**:`pytest` 全量通过 + `python -m compileall app tests scripts` 通过;无真实网络 / 无模型下载 / 无敏感外发。
- **验证命令**:

```bash
conda run -n autoGLM pytest tests/test_sparse_encoders.py tests/test_retrieval_tool.py
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests scripts
```

## 9. 风险与边界

- **索引错配(高)**:`local`(hash 100 万维)与 `fastembed`(token-id 空间)向量空间不兼容,切换必须重建 collection;通过元数据落盘 + 启动校验缓解。
- **可选依赖体积(中)**:SPLADE 模型较大、冷启动慢;默认不启用,BM25/BM42 体积小优先。
- **中文支持(中)**:多数 SPLADE 预训练为英文;中文专利建议优先 `Qdrant/bm25`/`bm42`(词法,语言无关性更好)或选中文 sparse 模型。
- **边界**:不真实下载模型进 CI;不提交模型权重;不改 RRF 融合与 dense 链路。

## 10. 里程碑 / 任务切片(供 PLAN 展开)

1. **P1 适配器** → `app/tools/adapters/fastembed_sparse.py`:`FastEmbedSparseEncoder`(延迟导入 + 降级)+ 单测(fake model)。A1。
2. **P2 工厂接入** → `_build_sparse_encoder()` 增 `"fastembed"` 分支 + `sparse_model` 默认约定 + 单测。A2。
3. **P3 依赖与配置** → `requirements` 可选依赖标注;`sparse_model` 默认值/环境变量测试;依赖隔离验证。A3。
4. **P4 入库一致性** → ingest 使用同一编码器配置,补 sparse 配置元数据/日志。
5. **P5 项目级验收** → 全量回归 + 编译检查 + 文档(CLAUDE/SPEC 增补 `fastembed` 取值说明)。A4。