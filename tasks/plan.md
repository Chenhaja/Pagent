# R5.3 QA 节点受限 ReAct 循环实施计划

## 背景

R5.3 将 `app/nodes/qa.py` 从「单步检索 → 回答」升级为 QA 节点内部 bounded ReAct：检索、评估 evidence 充分性、证据不足时改写 query 再检索、基于累积 evidence 回答。循环受 `retrieval_max_steps`、`retrieval_token_budget`、`retrieval_timeout_seconds` 封顶，并通过 trace 证明每一步可观测、可测试、不会触网。

## 依赖图

```text
SPEC.md
  -> app/core/config.py
      -> Settings 新增 retrieval_react_* 字段
      -> get_settings() 读取 PAGENT_RETRIEVAL_REACT_*
      -> to_public_dict() 暴露非敏感配置
      -> tests/test_core_config_logging.py

app/nodes/qa.py
  -> QANode.__init__ 继承配置与注入 query_rewriter
  -> _retrieve_loop(question)
      -> _retrieve(query) 复用 Retriever.search
      -> _is_evidence_sufficient(...)
      -> _accumulate_results(...)
      -> _get_result_score(...)
      -> _estimate_evidence_tokens(...)
      -> _rewrite_query(...)
  -> _build_evidence(...) 复用 provenance/citation 构造
  -> _apply_law_stale_warnings(...) 复用法规过时提示
  -> trace_events: qa_react_step / qa_react_converged / qa_completed
      -> tests/test_qa_react_loop.py
      -> tests/test_qa_node.py
```

## 关键文件

- `app/core/config.py`：新增 `retrieval_react_min_results`、`retrieval_react_min_score`、`retrieval_react_use_llm_judge`。
- `tests/test_core_config_logging.py`：覆盖默认值、环境变量、公开配置和敏感字段排除。
- `app/nodes/qa.py`：实现 bounded ReAct loop、去重、预算、超时和 trace。
- `tests/test_qa_react_loop.py`：新增 ReAct 行为测试。
- `tests/test_qa_node.py`：更新 trace 断言并保留原 QA 行为回归。

## 垂直切片计划

### Phase 1 — Config

- 新增 `Settings` 字段：`retrieval_react_min_results=1`、`retrieval_react_min_score=0.3`、`retrieval_react_use_llm_judge=False`。
- 读取 `PAGENT_RETRIEVAL_REACT_MIN_RESULTS`、`PAGENT_RETRIEVAL_REACT_MIN_SCORE`、`PAGENT_RETRIEVAL_REACT_USE_LLM_JUDGE`。
- 将三个非敏感值加入 `to_public_dict()`。
- 更新 `tests/test_core_config_logging.py`。

验收：默认值符合 SPEC；env override 生效；公开配置包含三项；敏感字段暴露不变。

### Phase 2 — QA guard and constructor

- 修复 `top_k`：使用 `settings.retrieval_top_k if top_k is None else top_k`。
- 新增 ReAct 阈值构造参数和 `query_rewriter` 注入。
- `_retrieve_loop()` 对 `max_steps<=0`、`token_budget<=0`、`timeout_seconds<=0` 短路。
- 保留空 evidence 下的 QA skill 调用和结构化回答。

验收：guard 路径不调用 retriever/rewriter；`steps_used==0`；`raw_input` 不变；trace 可观测。

### Phase 3 — Single-step ReAct

- 默认 sufficient path 只检索一次。
- `_get_result_score()` 优先非零 `similarity`，回退 `score`。
- `_is_evidence_sufficient()` 使用结果数量和 top score。
- 每轮检索输出 `qa_react_step`，收敛输出 `qa_react_converged`。
- 保留 `qa_retrieval_completed` 和 `qa_completed`。

验收：首轮充分时 retriever 调用一次；rewriter 不调用；trace 不含完整 query/content。

### Phase 4 — Multi-step and dedupe

- `_rewrite_query()` 使用注入 rewriter，失败时回退当前 query。
- `_accumulate_results()` 按 `document_id` 去重，重复项保留高分结果；缺失 ID 时用 source/locator/content fallback。
- insufficient 且预算允许时继续检索；达到步数上限 reason 为 `max_steps`。
- `state.dialog_context["qa_retrieval_results"]` 写入累积去重 evidence。

验收：不足首轮触发改写和二次检索；重复 `document_id` 保留高分；最终 evidence 可回链来源。

### Phase 5 — Token budget and timeout

- 用 `max(1, len(content)//4)` 确定性估算 evidence token。
- evidence token 达到预算时 reason 为 `token_budget`。
- 用 `time.monotonic()` 检查 timeout。
- 在 `token_budget`、`timeout`、`max_steps` 或空 evidence 时追加固定风险提示：`依据可能不足，建议补充材料或核对官方来源`。

验收：预算和超时优雅停止；检索/改写异常不裸抛；已有风险提示不被覆盖。

### Phase 6 — Regression and docs

- QA trace 断言改为按 `event` 查找。
- 保留 provenance、法规版本、过时提示、检索异常 fallback、无效 skill 输出失败等旧行为。
- 维护 `tasks/plan.md` 和 `tasks/todo.md`。

验收：目标测试、全量测试和 compileall 通过；不超出 SPEC 范围。

## 验证计划

```bash
conda run -n autoGLM pytest tests/test_core_config_logging.py
conda run -n autoGLM pytest tests/test_qa_react_loop.py tests/test_qa_node.py
conda run -n autoGLM pytest tests/test_core_config_logging.py tests/test_qa_node.py tests/test_qa_react_loop.py
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests scripts
```
