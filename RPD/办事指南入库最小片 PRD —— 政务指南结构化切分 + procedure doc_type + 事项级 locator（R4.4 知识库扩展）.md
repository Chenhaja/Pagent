<aside>

🎯

一句话：把《知识产权政务服务事项办事指南》作为**一个新的 `procedure` doc_type** 入库，按“**事项 × 小节**”结构化切分、用“**事项名＋小节**”做 locator，**绝不走 `law` 的「第X条」正则**，补齐 QA 里“怎么办”（费用/时限/材料/渠道）这类大头问题的支撑知识。对齐 R4.3 检索质量增强（先扩语料、再混合检索）。

</aside>

## 1. 背景与问题

- 当前语料只有 `law`/`template`/`term` 三类，**只能答“法律规定是什么”**；但真实 QA 里“怎么办理/多少钱/多久/交什么材料”才是大头，现有库答不了。
- 这份指南是**强结构政务文档**（72 个事项，每个事项固定分“受理条件 / 获取途径 / 申请材料 / 办理流程 / 收费标准 / 办理时限 / 相关表格”），不能用现有 `_split_text()` 的“空行裸切”。
- 更危险的是：文中大量引用“《专利法实施细则》第X条”，一旦走 `law` 的 `_infer_locator` 正则会被误抓成《专利法》条号，污染法条库。
- 文档夹杂电话/地址/邮编/URL 等噪声，直接入库会限带进向量。

## 2. 目标 / 非目标

**目标**

- G1 新增 `procedure` doc_type，与 `law`/`template`/`term` 并列，**不改 `RetrievalResult` / `KnowledgeChunk` 结构**（只用现有 `provenance`/`doc_type`/`locator` 字段）。
- G2 结构化切分：以“事项 × 小节”为基本 chunk，一个小节一条，保证“问费用命中费用小节”。
- G3 locator 换错：`办事指南·{事项名}·{小节}`，**由结构化解析器显式给出**，不走任何“第X条”正则。
- G4 噪声清洗：入库前过滤电话/邮编/地址/URL 等行。
- G5 不被时效过滤误伤：`procedure` 无法规版本字段，检索时间过滤只限 `doc_type=law`。
- G6 幂等可重跑：沿用 `build_point_id()` 稳定 id，重入库不产生重复点。

**非目标**

- 不改检索架构（hybrid/rerank 在 R4.3 另走）。
- 不做指南里表格/附件的下载与解析（“相关表格”小节只存名称）。
- 不扩到商标/地理标志/集成电路布图（本片只做**专利类 28 个事项**，其余事项后续补）。

## 3. 范围

- 新增语料目录 `knowledge/procedure/`（与 `law/`/`template/`/`term/` 并列）。
- 改 `scripts/ingest_knowledge.py`：新增 `procedure` 分支的加载/切分/locator 逻辑；`_infer_locator` 增加 doc_type 分发；`_clean_text` 增加噪声行过滤。
- 改检索时间过滤（`_build_qdrant_time_filter` / `_law_matches_time`）：仅对 `doc_type=law` 生效。
- 不改 `app/nodes/qa.py` 接线（召回后走同一套 `_build_evidence`）。

## 4. 架构 / 流程

```jsx
[离线入库] knowledge/procedure/*.md
   → parse_procedure()（markdown-it-py 解析 AST，遍历 heading 树切事项/小节）
   → _clean_text()（过滤电话/地址/URL 噪声）
   → KnowledgeChunk（doc_type=procedure, locator=办事指南·事项·小节）
   → embedding → upsert Qdrant
[在线问答] qa → retriever.search(query, top_k)
   → （时间过滤仅限 law，procedure 不被过滤）
   → RetrievalResult[]（provenance.locator=事项·小节）→ basis 回链
```

## 5. 知识来源与结构

源文档：《知识产权政务服务事项办事指南（第二版）》。本片取**专利类 28 个事项**。每个事项的固定小节：

| 小节（原文）        | 规范化 section | 典型问法              |
| ------------------- | -------------- | --------------------- |
| 受理条件            | `条件`         | 谁能办/什么情形下可以 |
| 获取途径            | `渠道`         | 怎么交/哪里办         |
| 申请材料            | `材料`         | 要交哪些文件          |
| 办理流程            | `流程`         | 步骤/期限内做什么     |
| 收费标准            | `费用`         | 多少钱                |
| 办理时限            | `时限`         | 多久                  |
| 办理结果 / 相关表格 | `结果`         | 出什么结果            |

## 6. 磁盘格式与切分策略

落盘格式：`knowledge/procedure/专利.md`，用二级标题表示事项、三级标题表示小节：

```markdown
## 专利无效宣告请求
### 受理条件
任何单位或个人认为该专利权的授予不符合……
### 收费标准
发明专利无效宣告请求费 3000 元……
```

解析方式：用 **`markdown-it-py`** 把 `.md` 解析成 token/AST，维护“当前 H2 事项 / 当前 H3 小节”指针遍历——遇 `heading level=2` 切事项、`heading level=3` 切小节，其余 `paragraph`/`bullet_list`/`table` 节点归入当前小节；locator 直接取 **heading 祖先路径** `办事指南·{H2}·{H3}`，不碰任何“第X条”正则。

切分规则：

- **基本粒度 = 事项 × 小节**：一个三级小节一条 chunk。
- 过短小节（< 80 字）**并入同事项相邻小节**，避免碎片。
- 超长“办理流程”（> 600 字）按步骤再切，`chunk_index` 递增，locator 后缀 `·步骤N`。
- chunk 文本头部拼接上下文锚：`【{事项名} / {小节}】` + 正文，提升嵌入可分辨性。
- **不做滑窗 overlap**：小节是语义自洁边界，块间重叠只会带来近重复命中、稀释 top-k、打乱“一小节一 locator”的映射；唯一例外是上面超长流程按步骤再切时，让相邻步骤共享 `【事项 / 小节】` 头并 carry-over 末句一行，兜住跨步引用，而非 token 滑窗。

## 7. locator 与元数据

| 字段          | 值示例                            | 说明                     |
| ------------- | --------------------------------- | ------------------------ |
| `doc_type`    | `procedure`                       | 新增枚举值               |
| `locator`     | `办事指南·专利无效宣告请求·费用`  | 结构化解析显式生成       |
| `document_id` | `procedure/专利/专利无效宣告请求` | 事项粒度                 |
| `source`      | `local://procedure/专利.md`       | 来源文件                 |
| `item_name`   | `专利无效宣告请求`                | 事项名（payload 过滤用） |
| `section`     | `费用`                            | 小节类型                 |
| `category`    | `专利`                            | 大类（专利/商标/…）      |

评测匹配规则（与 golden_qa 对齐）：`expected_locators` 用**事项名**做子串包含，命中 locator 里含该事项名即算对。

## 8. 噪声清洗规则（`_clean_text` 增强）

逐行丢弃命中以下任一模式的行（仅 `procedure`）：

```python
NOISE_PATTERNS = [
    r"^\s*(联系电话|咨询电话|传真)[：:]",
    r"\d{3,4}-\d{7,8}",            # 固电
    r"1[3-9]\d{9}",                 # 手机
    r"邮编[：:]?\s*\d{6}",
    r"https?://\S+",
    r"^\s*(地址|通讯地址)[：:]",
]
```

- 保留金额/期限/材料正文；只去联系方式类噪声。
- 清洗后空 chunk 丢弃。

## 9. 入库管线改动（`scripts/ingest_knowledge.py`）

```python
def load_chunks(path):
    for f in iter_files(path):
        doc_type = infer_doc_type(f)        # 目录名 procedure -> "procedure"
        if doc_type == "procedure":
            yield from parse_procedure(f)    # 新增：markdown-it-py 遍历 heading 树
        else:
            yield from parse_default(f)      # 原有 _split_text

def _infer_locator(chunk):
    if chunk.doc_type == "law":
        return _format_law_locator(...)      # 仅 law 走「第X条」正则
    if chunk.doc_type == "procedure":
        return chunk.locator                 # 结构化已给出，直接用
    if chunk.doc_type == "template":
        return _infer_template_locator(...)
    ...
```

- `build_point_id()` 不变：`uuid5(NAMESPACE_URL, f"{document_id}:{chunk_index}")`，幂等可重跑。
- CLI 不变：`python -m scripts.ingest_knowledge --path knowledge/`。

<aside>
 ⚠️

最关键的一条：`_infer_locator` 必须**按 `doc_type` 分发**，`procedure` 绝不能落入 `law` 的「第X条」正则分支，否则文中《专利法实施细则》第X条会被误标成《专利法》条号。

</aside>

## 10. 检索 / 时效过滤交互

- `procedure` 无 `effective_date`/`version`/`status`，**不参与时间过滤**。
- 改 `_build_qdrant_time_filter`：过滤子句变为「`doc_type != "law"` **OR** 满足时间条件」，避免 `procedure`/`template`/`term` 被误滤掉。
- payload 可按 `doc_type=procedure` 或 `item_name` 做过滤，为后续“意图路由到办理库”预留。

## 11. 配置（`PAGENT_` 前缀）

- 无新增必填项；沿用 `PAGENT_QDRANT_COLLECTION`（同一 collection，靠 `doc_type` 区分）。
- （可选）`PAGENT_RETRIEVAL_DOC_TYPES`：限定召回 doc_type 白名单，默认全部。

## 12. 验收标准 / 测试

`tests/test_ingest_procedure.py`、`tests/test_retrieval.py`：

- [ ]  解析：一个事项生成 ≤ 小节数个 chunk，每个 `doc_type=procedure`、`locator` 形如 `办事指南··`。
- [ ]  **防误抓**：含“《专利法实施细则》第四十四条”的指南段落，生成的 locator **不得出现《专利法》条号**。
- [ ]  噪声：含电话/邮编/URL 的行被过滤，金额/期限行保留。
- [ ]  时效：开启时间过滤时，`procedure` 仍能被召回（不被 law 时间条件误滤）。
- [ ]  端到端：入库后用 golden_qa 办理流程 36 题跑，命中对应事项，Recall@3 可统计。
- [ ]  幂等：重跑 `ingest` 不新增点（point_id 稳定）。

## 13. 风险与取舍

- **解析鲁棒性**：指南小节标题可能不统一（“收费标准” vs “费用”）→ 解析器用**别名表**归一化到 7 个 `section`。
- **人工整理成本**：Notion 源文 → `knowledge/procedure/专利.md` 需一次性整理；建议先做专利 28 事项，跱通后再扩。
- **与法条重叠**：个别问题（如“申请发明要交哪些文件”）法条与指南都能答 → 评测集用费用/时限/渠道这类“只有指南能答”的题保证 gold 干净。
- **同 collection 混库**：靠 `doc_type` 过滤隔离；若后期召回互扰，再拆独立 collection。