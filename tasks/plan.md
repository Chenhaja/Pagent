# R4.4 办事指南入库计划

## 背景

R4.4 将《知识产权政务服务事项办事指南（第二版）》中的专利类指南作为新的 `procedure` doc_type 入库，用于支撑“怎么办理 / 多少钱 / 多久 / 交什么材料 / 哪里办”等办理类 QA。

现有 `scripts/ingest_knowledge.py` 仅遍历 `law` / `template` / `term`，且 law locator 会用“第X条”正则推断。procedure 正文可能包含法规引用，必须避免误抓为 law locator。现有 `app/tools/retrieval.py` 已采用“非 law 或满足 law 时间条件”的过滤结构，本次通过测试确认 procedure 不被法规时效过滤误伤。

## 依赖图

```text
SPEC.md
  -> tasks/plan.md / tasks/todo.md
  -> tests/test_ingest_procedure.py
      -> scripts/ingest_knowledge.py: KnowledgeChunk 可选字段
      -> scripts/ingest_knowledge.py: procedure H2/H3 解析
      -> scripts/ingest_knowledge.py: procedure 专属清洗
      -> scripts/ingest_knowledge.py: procedure payload 透传
  -> tests/test_retrieval_tool.py
      -> app/tools/retrieval.py: law-only 时间过滤验证
  -> knowledge/procedure/专利.md
      -> scripts/ingest_knowledge.py: load_chunks 读取 procedure 目录
```

## Phase 1 — 计划与任务文档

**修改文件**
- `tasks/plan.md`
- `tasks/todo.md`

**实施内容**
- 写入本 R4.4 实施计划。
- 按垂直切片维护可独立验证的任务清单。

**Checkpoint A**
- 确认计划与任务清单包含关键路径：`scripts/ingest_knowledge.py`、`app/tools/retrieval.py`、`tests/test_ingest_procedure.py`、`tests/test_retrieval_tool.py`、`knowledge/procedure/专利.md`。

## Phase 2 — procedure 入库最小闭环

**修改文件**
- `tests/test_ingest_procedure.py`
- `scripts/ingest_knowledge.py`

**实施内容**
- 新增 procedure 入库测试，覆盖 H2/H3 解析、locator、防误抓 law 条号、噪声清洗、payload、幂等 point id。
- 扩展 `KnowledgeChunk`，增加 `item_name`、`section`、`category` 可选字段。
- `load_chunks()` 遍历加入 `procedure`。
- procedure 文件走 H2/H3 专用解析，不走 `_split_text()`。
- 使用小节别名归一化：受理条件→条件、获取途径→渠道、申请材料→材料、办理流程→流程、收费标准/费用→费用、办理时限→时限、办理结果/相关表格→结果。
- procedure 专属清洗仅丢弃联系方式类行。
- payload 写入 `item_name`、`section`、`category`。
- `_infer_locator()` 对 `procedure` 直接返回 fallback。

**Checkpoint B**
```bash
pytest tests/test_ingest_procedure.py tests/test_ingest_knowledge.py
python -m compileall scripts
```

## Phase 3 — law-only 时间过滤兼容

**修改文件**
- `tests/test_retrieval_tool.py`
- `app/tools/retrieval.py`（仅测试证明需要时小幅调整）

**实施内容**
- 补充 Local 检索测试，验证 `procedure` / `template` / `term` 在默认 current 与 `as_of` 过滤下仍可返回。
- 补充 Qdrant filter 测试，验证 `_build_qdrant_time_filter()` 保持 `should: [doc_type != law, law_filter]` 结构。
- 补充 Qdrant hit 映射测试，验证 procedure payload 的 `doc_type`、`locator` 进入 `RetrievalResult.provenance`。
- 如测试暴露误判，将 `_payload_is_law()` 收紧为优先只认 `doc_type == "law"`。

**Checkpoint C**
```bash
pytest tests/test_retrieval_tool.py
python -m compileall app
```

## Phase 4 — 知识文件接入

**修改文件**
- `knowledge/procedure/专利.md`

**实施内容**
- 创建 procedure 知识目录与专利指南最小代表样例。
- H2 表示事项，H3 表示小节。
- 最小样例覆盖费用、材料、渠道、时限等办理类典型小节。
- 完整 28 个事项或完整外部来源文档需用户确认后再补齐。

**Checkpoint D**
- `load_chunks("knowledge")` 能读取 `knowledge/procedure/专利.md`。
- locator 包含事项名和规范化小节名。

## Phase 5 — 项目级验收

**修改文件**
- 无固定文件，按测试结果回修。

**验收命令**
```bash
pytest tests/test_ingest_procedure.py tests/test_ingest_knowledge.py tests/test_retrieval_tool.py
pytest
python -m compileall app tests scripts
```

## 边界

- 不改 QA 主流程和 `RetrievalResult` 基础结构。
- 不新增外部依赖。
- 不连接真实 Qdrant / embedding 服务。
- 不提交完整大体积指南内容，除非用户确认。
- 不让 procedure 文本中的“第X条”进入 law locator 正则。
- 不把 procedure 加入 law 时效字段或法规时间过滤。
