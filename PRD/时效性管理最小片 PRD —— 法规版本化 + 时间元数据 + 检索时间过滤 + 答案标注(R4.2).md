<aside>
 🎯

**一句话目标**:让法规类知识具备时效性,做到"答现行版、可追历史版、出处带生效日期"。
 **本片范围**:实现前 4 条——① 时间元数据 ② 版本保留与状态 ③ 检索时间过滤 ④ 答案标注与兜底。第 5 条"自动更新机制"复杂度高,**列入 backlog 后续再做**,本片仅保留手动重建入口。

</aside>

## 1. 背景与问题

当前 `knowledge/law/` 入库后,chunk 只有正文与基础 `locator`,没有版本与时间信息,存在三个风险:

- **答出过时条款**:法规修订后旧版仍被召回,无法区分现行/已废止。
- **无法回答时间点问题**:专利侵权、无效判断适用的是"行为发生时/申请日时"的法律版本,而非最新版,系统却只能给最新版。
- **出处不完整**:答案引用"第 22 条"但不带版本与生效日期,违背 R5"可追溯、禁臆造"。

## 2. 目标与非目标

**目标**

- 每个法规 chunk 携带版本与时间元数据,入 Qdrant payload。
- 同一条文多版本共存,以 `status` 区分,默认只召回现行有效版。
- 支持按时间点(as-of date)过滤召回历史版本。
- QA 答案强制标注"《法规名(版本)》第X条 + 生效日期",并在可能过时时给兜底提示。

**非目标(本片不做)**

- 自动抓取/变更检测/定时重建(→ backlog,见第 10 节)。
- 跨法规冲突消解、效力位阶推理。
- 非法规类(范文/术语)的时效性处理(它们时效性弱,沿用现状)。

## 3. 需求点

### R4.2.1 时间元数据

入库时为每个 law chunk 生成并存储以下字段:

| 字段             | 类型         | 示例                      | 说明                                     |
| ---------------- | ------------ | ------------------------- | ---------------------------------------- |
| `doc_type`       | str          | law                       | 已有                                     |
| `law_name`       | str          | 中华人民共和国专利法      | 法规名称                                 |
| `version`        | str          | 2020修正                  | 版本标识                                 |
| `effective_date` | date         | 2021-06-01                | 该版本生效日                             |
| `expiry_date`    | date 或 null | null                      | 失效日,现行版为 null                     |
| `status`         | enum         | current                   | current / superseded / not_yet_effective |
| `locator`        | str          | 专利法(2020修正)·第22条   | 出处回链,带版本                          |
| `source_url`     | str          | cnipa…/art_97_155167.html | 溯源                                     |
| `retrieved_at`   | date         | 2026-06-29                | 抓取日期                                 |
| `content_hash`   | str          | sha256(正文)              | 审计/去重                                |

### R4.2.2 版本保留与状态

- 修订后**不删除旧版**:旧版 `status` 置为 `superseded` 并写 `expiry_date`;新版 `status=current`。
- `document_id` **带版本**(如 `zhuanli_fa_2020`),避免新版覆盖旧版;`build_point_id = sha256(document_id:chunk_index)` 保持幂等。
- 本片版本切换为**手动操作**(提供脚本参数),不做自动检测。

### R4.2.3 检索时间过滤

- ```
  QdrantRetriever
  ```

   查询时附加 payload filter:

  - 默认:`status == "current"`。
  - 带时间点查询:`effective_date <= as_of AND (expiry_date is null OR expiry_date > as_of)`。

- `as_of` 由调用方可选传入(默认今天)。非 law 的 doc_type 不受时间过滤影响。

### R4.2.4 答案标注与兜底

- `_build_evidence` 输出的 provenance 增加 `version` 与 `effective_date`,QA 引用格式:`《专利法(2020修正)》第22条`。
- 系统提示追加一句:"以官方最新公布文本为准,涉及具体时间点请核对当时有效版本"。
- 命中 chunk 为 `superseded`,或 `retrieved_at` 距今超过阈值(可配置)时,答案附"⚠️ 可能过时,建议核对官方最新版本"。

## 4. 数据结构变更

```python
# scripts/ingest_knowledge.py
@dataclass
class KnowledgeChunk:
    document_id: str        # 带版本,如 zhuanli_fa_2020
    chunk_index: int
    content: str
    doc_type: str
    locator: str
    # —— 新增时效性字段 ——
    law_name: str | None = None
    version: str | None = None
    effective_date: str | None = None   # ISO date
    expiry_date: str | None = None
    status: str = "current"             # current|superseded|not_yet_effective
    source_url: str | None = None
    retrieved_at: str | None = None
    content_hash: str | None = None
```

时效性字段来源:law 子目录下每个法规放一个 `meta.json`(law_name/version/effective_date/status/source_url),`load_chunks` 读取后注入同目录各 chunk;`content_hash`、`retrieved_at` 入库时自动生成。

```python
# app/tools/retrieval.py
@dataclass
class RetrievalResult:
    content: str
    provenance: str
    score: int = 0
    similarity: float = 0.0
    # 透传给 QA 用于标注
    version: str | None = None
    effective_date: str | None = None
    status: str | None = None
```

## 5. 检索过滤逻辑(QdrantRetriever)

```python
def build_time_filter(as_of: str | None, doc_type: str | None):
    # 非 law 不加时间过滤
    must = []
    if doc_type == "law":
        if as_of:
            must.append({"key": "effective_date", "range": {"lte": as_of}})
            must.append({"should": [
                {"is_null": {"key": "expiry_date"}},
                {"key": "expiry_date", "range": {"gt": as_of}},
            ]})
        else:
            must.append({"key": "status", "match": {"value": "current"}})
    return {"must": must} if must else None
```

- `LocalRetrievalTool` 同步实现等价过滤(读 payload 后内存过滤),保证 backend 可替换。

## 6. 答案侧([qa.py](http://qa.py))

- `_build_evidence`:provenance 拼成 `f"{law_name}({version})·{条号}"`,并把 `effective_date`、`status` 一并带入 evidence。
- 模型提示模板新增时效声明;命中 superseded 时在回答末尾追加过时提示。
- trace 增加 `qa_completed.evidence_versions`,便于排查召回了哪个版本。

## 7. 配置项(PAGENT_ 前缀)

| 配置                                  | 默认    | 说明                                |
| ------------------------------------- | ------- | ----------------------------------- |
| `PAGENT_RETRIEVAL_DEFAULT_STATUS`     | current | 默认只召回现行有效                  |
| `PAGENT_RETRIEVAL_ENABLE_TIME_FILTER` | true    | 是否启用 law 时间过滤               |
| `PAGENT_LAW_STALE_DAYS`               | 365     | retrieved_at 超过此天数标"可能过时" |

## 8. 验收标准

- [ ]  law chunk 入库后,Qdrant payload 含 version/effective_date/expiry_date/status/source_url/retrieved_at/content_hash。
- [ ]  同一条存在 current 与 superseded 两版时,默认查询只返回 current。
- [ ]  传入历史 `as_of` 日期时,返回该日期有效的版本。
- [ ]  QA 答案出处形如"《专利法(2020修正)》第22条",并含生效日期。
- [ ]  命中 superseded 或超过 stale 阈值时,答案带过时提示。
- [ ]  非 law(范文/术语)检索行为不受时间过滤影响,回归通过。

## 9. 任务拆解

1. `KnowledgeChunk` 增字段 + `meta.json` 读取 + content_hash/retrieved_at 生成。
2. ingest 写入 Qdrant payload(含全部时效字段)。
3. `RetrievalResult` 增字段;`QdrantRetriever`/`LocalRetrievalTool` 加时间过滤。
4. `qa.py` provenance 标注 + 兜底提示 + trace。
5. 配置项接入 `app/core/config.py`。
6. 测试:版本共存召回、as_of 时间点、过时提示、非 law 回归。
7. 为专利法 2020 全文补一份 `knowledge/law/zhuanli_fa_2020/meta.json`。

## 10. 风险与 backlog(更新机制延后)

**延后到后续片(backlog)**

- 自动抓取 `source_url` + `content_hash` 变更检测 + 增量重建。
- 修法 changelog 与人工审核流。
- 定时任务/触发器驱动重建。

**本片风险**

- 历史版本元数据需人工准备(meta.json),初期靠手动维护。
- 时间点检索依赖 effective_date 准确性,需在 meta.json 录入时校对官方生效日。
- `document_id` 命名规范若不统一会导致覆盖,需在文档约定并评审。