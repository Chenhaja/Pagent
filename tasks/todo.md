# R4.4 Todo

## 1. 写入计划文档

- [x] 目标：生成 `tasks/plan.md`，说明 R4.4 办事指南入库的背景、依赖图、阶段、检查点和验收命令。
- 依赖：`SPEC.md` 与 R4.4 实施计划。
- 验收标准：文件标题为 R4.4 办事指南入库计划；包含 `scripts/ingest_knowledge.py`、`app/tools/retrieval.py`、`tests/test_ingest_procedure.py`、`tests/test_retrieval_tool.py`、`knowledge/procedure/专利.md`。
- 验证命令：人工读取 `tasks/plan.md`。

## 2. 写入任务清单

- [x] 目标：生成 `tasks/todo.md`，按垂直切片列出目标、依赖、验收标准、验证命令。
- 依赖：任务 1。
- 验收标准：每个任务可独立验证；任务顺序与依赖关系一致。
- 验证命令：人工读取 `tasks/todo.md`。

## 3. 建立 procedure 入库测试

- [x] 目标：新增 `tests/test_ingest_procedure.py`，覆盖 H2/H3、locator、防误抓、噪声清洗、payload、幂等 point id。
- 依赖：任务 1、任务 2。
- 验收标准：`load_chunks(tmp_path)` 能生成 `doc_type == "procedure"` 的 chunk；locator 为 `办事指南·{事项名}·{规范化小节}`；content 以 `【{事项名} / {小节}】` 开头；payload 包含 `item_name`、`section`、`category`；噪声行过滤且金额、期限、材料保留。
- 验证命令：`pytest tests/test_ingest_procedure.py`

## 4. 实现 procedure 入库闭环

- [x] 目标：扩展 `scripts/ingest_knowledge.py`，支持 procedure 目录读取、H2/H3 解析、清洗、locator 与 payload 透传。
- 依赖：任务 3。
- 验收标准：Task 3 测试通过；law/template/term 既有入库行为不变；不新增外部依赖。
- 验证命令：`pytest tests/test_ingest_procedure.py tests/test_ingest_knowledge.py && python -m compileall scripts`

## 5. 建立 law-only 检索测试

- [ ] 目标：补充 `tests/test_retrieval_tool.py`，验证 procedure/template/term 不受 law 时间过滤误伤。
- 依赖：任务 4。
- 验收标准：默认 current 与 `as_of` 过滤下，非 law 文档仍可返回；Qdrant filter 包含非 law 分支；procedure payload 的 `doc_type`、`locator` 进入 provenance。
- 验证命令：`pytest tests/test_retrieval_tool.py`

## 6. 调整检索过滤（如需要）

- [ ] 目标：仅当测试暴露误判时，小幅调整 `app/tools/retrieval.py` 的 law 判断。
- 依赖：任务 5。
- 验收标准：既有 law current/as_of 过滤通过；procedure/template/term 均不受 law 时间过滤误伤。
- 验证命令：`pytest tests/test_retrieval_tool.py && python -m compileall app`

## 7. 接入 procedure 专利知识文件

- [ ] 目标：创建 `knowledge/procedure/专利.md` 的最小代表样例，覆盖费用、材料、渠道、时限等办理类小节。
- 依赖：任务 4。
- 验收标准：`load_chunks("knowledge")` 能读取该文件；locator 包含事项名和规范化小节；完整 28 项或完整外部来源文档需用户确认后再补齐。
- 验证命令：通过测试/fake 验证，不连接真实 Qdrant。

## 8. 运行验收

- [ ] 目标：运行 R4.4 目标测试、全量回归和编译检查。
- 依赖：任务 3 至任务 7。
- 验收标准：目标测试通过；全量 `pytest` 通过；编译检查通过；未引入真实网络依赖、真实 API Key 或敏感内容。
- 验证命令：`pytest tests/test_ingest_procedure.py tests/test_ingest_knowledge.py tests/test_retrieval_tool.py && pytest && python -m compileall app tests scripts`
