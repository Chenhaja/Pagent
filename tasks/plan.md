# 查询改写 LLM 化实施计划

## 背景

当前检索层查询改写由 `app/tools/retrieval.py::HTTPQueryRewriter` 调用自定义 `{llm_base_url}/query-rewrite` 端点。大多数 OpenAI 兼容网关只提供标准 `/chat/completions`，因此开启 `retrieval_use_query_rewrite` 后常因端点不存在而被 `MultiQueryRetriever._expand_queries()` 吞掉异常，最终退回单查询。

本阶段目标是新增 `LLMQueryRewriter`，复用 `app/tools/llm.py::LLMClient.generate(...)` 与 `OpenAICompatibleClient` 的 `/chat/completions` 通道；保留旧 `HTTPQueryRewriter` 为 `query_rewrite_backend=service` 的 legacy backend；不改检索合并去重语义、不改 ReAct / QA / rerank / embedding。

本计划只拆解实现路径与验收任务；实现阶段再修改业务代码。

## 当前代码基线

- `app/tools/retrieval.py`
  - `QueryRewriter` 协议已存在，契约为 `expand(query) -> list[str]`。
  - `FakeQueryRewriter` 已用于测试注入。
  - `HTTPQueryRewriter` 当前直接用 `urllib` POST 到 `{llm_base_url}/query-rewrite`，body 包含 `model/query/mode/count`。
  - `MultiQueryRetriever.recall()` 先 `_expand_queries(query)`，再对每个 query 调用 `inner.recall(...)` 并按 `(document_id, locator, content[:64])` 去重。
  - `_expand_queries()` 当前异常静默返回 `[query]`，空结果也返回 `[query]`，但没有日志。
  - `build_retriever()` 当前在 `retrieval_use_query_rewrite=true` 时默认使用 `HTTPQueryRewriter(resolved_settings)`。
- `app/tools/llm.py`
  - 已有 `LLMClient` 协议、`LLMMessage`、`LLMResponse`、`FakeLLMClient`、`OpenAICompatibleClient`。
  - `FakeLLMClient.generate(...)` 会记录 `model/temperature/timeout/trace_context` 到 trace，适合不触网测试。
  - `OpenAICompatibleClient.generate(...)` 已支持 `messages`、`output_schema`、`trace_context`。
- `app/core/config.py`
  - 已有 `retrieval_use_query_rewrite`、`query_rewrite_mode`、`query_rewrite_count`。
  - 缺 `query_rewrite_backend`、`query_rewrite_model`、`query_rewrite_temperature`。
  - `to_public_dict()` 已公开 mode/count/use_query_rewrite，但缺新增非敏感字段。
  - `get_settings()` 已读取 mode/count/use_query_rewrite 环境变量。
- `app/prompts/`
  - 已有 `query_rewrite.py`，用于入口历史指代消解，不是检索层多查询扩展。
  - 缺 `query_expand.py`。
- `tests/test_retrieval_tool.py`
  - 已覆盖 `FakeQueryRewriter`、`MultiQueryRetriever`、`HTTPQueryRewriter`、`build_retriever` 装配顺序。
  - 需要补 `LLMQueryRewriter`、backend 选择、日志降级、prompt schema。
- `tests/test_core_config_logging.py`
  - 需要补新增查询改写配置默认值、环境变量读取、public dict。

## 依赖图

```text
SPEC.md
  -> Prompt / schema contract
      -> app/prompts/query_expand.py
      -> tests/test_retrieval_tool.py          # prompt/schema 断言

  -> Config contract
      -> app/core/config.py                    # Settings 字段、env 读取、to_public_dict
      -> tests/test_core_config_logging.py
      -> app/tools/retrieval.py                # LLMQueryRewriter 读取 backend/model/temperature

  -> LLM query rewriter contract
      -> app/tools/llm.py                      # 复用 LLMClient / LLMMessage / FakeLLMClient
      -> app/tools/retrieval.py                # LLMQueryRewriter
      -> tests/test_retrieval_tool.py

  -> Retriever factory contract
      -> app/tools/retrieval.py                # _build_query_rewriter + build_retriever 默认 backend
      -> tests/test_retrieval_tool.py

  -> Observability / fallback contract
      -> app/tools/retrieval.py                # _expand_queries warning/info
      -> tests/test_retrieval_tool.py          # caplog + fallback 行为

  -> final verification
      -> tests/test_retrieval_tool.py
      -> tests/test_core_config_logging.py
      -> pytest / compileall
```

## 垂直切片原则

每个阶段都交付一条可验证路径，而不是只改一层：

1. 先补 prompt/schema 和配置，让后续 LLM rewriter 有稳定输入输出与可配置 backend。
2. 再实现 `LLMQueryRewriter` 的单组件闭环：Fake LLM → schema 输出 → 去重截断 → 错误返回空。
3. 再接 `build_retriever` 默认 backend：开关开启时默认走 LLM，显式 `service` 才走旧 HTTP。
4. 再补 `MultiQueryRetriever` 降级日志，保证失败可观测且不影响召回。
5. 最后跑目标测试、全量测试、编译检查，并按项目规范提交。

---

## Phase 0 — 口径确认与基线锁定

### 目标

确认本需求只处理检索层查询改写 LLM 化，不扩大到检索算法、rerank、ReAct、QANode、embedding 或真实评测。

### 实施要点

- 保留 `HTTPQueryRewriter`，仅改为 legacy `service` backend。
- `retrieval_use_query_rewrite` 默认仍为 `false`。
- 开启查询改写后的默认 backend 为 `llm`。
- `MultiQueryRetriever` 的 recall、合并、去重语义不变。
- 默认测试使用 `FakeLLMClient` / fake rewriter，不触网。
- 不新增依赖。

### 验收标准

- plan / todo 明确上述边界。
- 后续任务不包含检索算法重写、rerank 重写、ReAct / QA 改造、真实 LLM 调用或 ragas 评测。

### Checkpoint 0

确认计划后进入测试优先实现。

---

## Phase 1 — Prompt/schema 与配置垂直切片

### 目标

建立 `LLMQueryRewriter` 所需的 prompt/schema 与配置契约，并通过单测锁定默认值和公开字段。

### 任务

1. 新增 `app/prompts/query_expand.py`。
   - 定义 `QUERY_EXPAND_OUTPUT_SCHEMA`，要求 `queries`，`additionalProperties=False`。
   - 定义 `QUERY_EXPAND_SYSTEM_PROMPT`，包含 `multi` 与 `hyde`。
   - 定义 `build_query_expand_user_prompt(query, mode, count)`。
2. 补 prompt/schema 测试。
   - 断言 schema 非空、`additionalProperties=False`。
   - 断言 system prompt 覆盖 `multi` / `hyde`。
   - 断言 user prompt 包含 `<data>`、`</data>`，并声明数据区不作为指令。
   - 断言 prompt 含“仅输出 JSON”和禁止臆造约束。
3. 扩展 `Settings` 查询改写配置。
   - 新增 `query_rewrite_backend: str = "llm"`。
   - 新增 `query_rewrite_model: str | None = None`。
   - 新增 `query_rewrite_temperature: float = 0.3`。
   - 更新 `Settings` docstring、`get_settings()` 环境变量读取、`to_public_dict()`。
4. 补配置测试。
   - 默认值、`PAGENT_QUERY_REWRITE_BACKEND`、`PAGENT_QUERY_REWRITE_MODEL`、`PAGENT_QUERY_REWRITE_TEMPERATURE`。
   - 既有 `PAGENT_QUERY_REWRITE_MODE`、`PAGENT_QUERY_REWRITE_COUNT` 回归。
   - public dict 包含新增非敏感字段，不包含 key / token / secret。

### 验收标准

- `query_expand.py` 不依赖业务运行状态，可单独 import。
- 新增配置通过 env 覆盖且进入 public dict。
- 不触网、不创建真实 LLM client。

### 验证步骤

```bash
conda run -n autoGLM pytest tests/test_retrieval_tool.py tests/test_core_config_logging.py
```

### Checkpoint 1

确认 prompt/schema 和配置测试通过后，再实现 LLM rewriter。

---

## Phase 2 — LLMQueryRewriter 单组件闭环

### 目标

实现可注入 fake LLM 的 `LLMQueryRewriter`，证明检索层查询扩展可以只通过 `LLMClient.generate(...)` 完成。

### 任务

1. 在 `app/tools/retrieval.py` 引入 LLM 相关依赖。
   - `LLMClient`、`LLMMessage`、`build_llm_client`。
   - `QUERY_EXPAND_OUTPUT_SCHEMA`、`QUERY_EXPAND_SYSTEM_PROMPT`、`build_query_expand_user_prompt`。
2. 新增 `LLMQueryRewriter`。
   - 构造函数接收 `settings` 和可选 `llm_client`。
   - 空 query 直接返回 `[]`，不调用 LLM。
   - mode 从 `settings.query_rewrite_mode` 读取。
   - count 使用 `max(1, int(settings.query_rewrite_count))`。
   - model 使用 `query_rewrite_model or llm_cheap_model or llm_model`。
   - 调用 `llm_client.generate(messages=..., output_schema=..., temperature=..., timeout=..., trace_context=...)`。
   - `response.errors` 或 content 非 dict 时返回 `[]`。
   - 正常解析 `queries`，原 query 首位、去重保序、截断到 `count + 1`。
3. 补 `LLMQueryRewriter` 测试。
   - Fake LLM 成功返回时原 query 首位。
   - 去重保序、过滤空白、截断。
   - model 回退顺序。
   - trace context 包含 `node_name=retrieval`、`task_type=query_expand`。
   - temperature / timeout 传入 Fake trace。
   - LLM error、非 dict、缺 `queries`、空 queries 返回 `[]`。
   - 空 query 不调用 LLM。

### 验收标准

- `LLMQueryRewriter` 不使用 `urllib` / `requests` 直接调用 LLM。
- 默认测试完全通过 `FakeLLMClient` 验证。
- 失败统一返回 `[]`，交给 `MultiQueryRetriever` 兜底。

### 验证步骤

```bash
conda run -n autoGLM pytest tests/test_retrieval_tool.py
```

### Checkpoint 2

确认单组件成功 / 失败路径稳定后，再接工厂默认 backend。

---

## Phase 3 — build_retriever backend 切换闭环

### 目标

将开启查询改写后的默认构造器从 `HTTPQueryRewriter` 切为 `LLMQueryRewriter`，同时保留 service backend 与显式注入点。

### 任务

1. 新增 `_build_query_rewriter(settings)`。
   - `query_rewrite_backend=service` 返回 `HTTPQueryRewriter(settings)`。
   - 默认或 `llm` 返回 `LLMQueryRewriter(settings)`。
   - 非预期 backend 按 spec 采用安全默认，不让检索链路崩溃。
2. 修改 `build_retriever()` 查询改写装配。
   - `retrieval_use_query_rewrite=false` 时不变。
   - `retrieval_use_query_rewrite=true` 且未注入时使用 `_build_query_rewriter(resolved_settings)`。
   - 显式传入 `query_rewriter` 时仍优先使用注入对象。
   - 仍保持 base/hybrid → multi-query → rerank 的装配顺序。
3. 补 backend / 工厂测试。
   - `_build_query_rewriter(llm)` 返回 `LLMQueryRewriter`。
   - `_build_query_rewriter(service)` 返回 `HTTPQueryRewriter`。
   - 开启 rewrite 默认使用 LLM backend。
   - service backend 使用 legacy HTTP rewriter。
   - 关闭 rewrite 时仍返回原 base，不包 `MultiQueryRetriever`。
   - 注入 fake rewriter 时仍使用 fake。
   - hybrid + rewrite + rerank 既有装配顺序保持。

### 验收标准

- 默认开启查询改写不再依赖 `/query-rewrite`。
- 旧 HTTP 行为只在 `query_rewrite_backend=service` 时出现。
- 外部注入测试口保持兼容。

### 验证步骤

```bash
conda run -n autoGLM pytest tests/test_retrieval_tool.py
```

### Checkpoint 3

确认工厂装配正确后，再补降级日志与可观测性。

---

## Phase 4 — MultiQueryRetriever 降级可观测闭环

### 目标

保留现有安全降级行为，但让失败和空结果可观测。

### 任务

1. 调整 `MultiQueryRetriever._expand_queries()`。
   - 对 `query_rewriter.expand(query)` 抛异常：`logger.warning(...)`，`extra={"event": "query_rewrite_failed"}`，返回 `[query]`。
   - 对过滤后空结果：`logger.info(...)`，`extra={"event": "query_rewrite_empty"}`，返回 `[query]`。
   - 正常结果过滤空白字符串，保持 rewriter 顺序。
2. 补降级日志测试。
   - 异常路径返回 `[query]` 并记录 `query_rewrite_failed`。
   - 空结果路径返回 `[query]` 并记录 `query_rewrite_empty`。
   - 空白字符串被过滤。
   - 降级后仍调用 inner retriever 的单查询 recall。
3. 安全 review。
   - 日志不包含完整 query、完整扩展式、API key、prompt。
   - 不新增 retry，不触发额外网络调用。

### 验收标准

- 失败 / 空结果不再完全静默。
- 检索主流程不因查询改写失败而中断。
- 日志字段稳定，敏感信息不落日志。

### 验证步骤

```bash
conda run -n autoGLM pytest tests/test_retrieval_tool.py
```

### Checkpoint 4

确认降级路径可观测后，进入总体验收。

---

## Phase 5 — 总体验收与提交准备

### 目标

跑完目标测试、全量测试和编译检查，确认本阶段可以独立提交。

### 任务

1. 运行目标测试。
2. 运行全量测试。
3. 运行 compileall。
4. 检查 git diff，确认只包含本需求相关文件。
5. 如实现阶段形成可独立验证改动，按项目规范单独 commit。

### 验收标准

- 目标测试通过。
- 全量测试通过。
- 编译检查通过。
- 默认测试无真实 LLM / 网络调用。
- `retrieval_use_query_rewrite=true` 默认经 LLM chat completions 通道。
- `query_rewrite_backend=service` 仍能使用 legacy HTTP endpoint。
- `retrieval_use_query_rewrite=false` 行为不变。

### 验证步骤

```bash
conda run -n autoGLM pytest tests/test_retrieval_tool.py tests/test_core_config_logging.py
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests scripts
```

### Checkpoint 5

提交前请用户确认是否需要：

- 运行真实 LLM 网关 smoke test。
- 运行 ragas 对比 baseline / multi / hyde。
- 删除或进一步标注 legacy service backend。

---

## 风险与控制

- **LLM JSON 不稳定**：通过 `output_schema` 触发 JSON 模式；错误、非 dict、缺字段统一返回 `[]`。
- **语义漂移**：原 query 始终置首位，扩展结果去重保序，最多 `count + 1`。
- **延迟和成本**：默认 `retrieval_use_query_rewrite=false`；开启后才调用 LLM。
- **兼容旧 endpoint**：保留 `HTTPQueryRewriter`，仅 `query_rewrite_backend=service` 时使用。
- **可观测但不泄密**：只记录稳定 event 和中文 message，不记录完整 query / prompt / key。
- **测试触网风险**：所有新增测试使用 fake / stub，不调用真实网关。

## 文件改动清单

计划中的实现阶段会涉及：

- `app/prompts/query_expand.py`：新增。
- `app/tools/retrieval.py`：新增 `LLMQueryRewriter`、`_build_query_rewriter`，调整 `_expand_queries` 与 `build_retriever`。
- `app/core/config.py`：新增查询改写 backend/model/temperature 配置。
- `tests/test_retrieval_tool.py`：新增 rewriter、prompt、backend、日志降级测试。
- `tests/test_core_config_logging.py`：新增配置默认值、环境变量、public dict 测试。

不计划修改：

- `app/nodes/qa.py`
- `app/orchestrator/*`
- `app/tools/llm.py` 公共契约
- embedding / Qdrant / rerank 主逻辑
- `requirements.txt`
