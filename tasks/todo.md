# 查询改写 LLM 化 Todo

## Phase 0 — 口径确认与基线锁定

- [ ] 确认本需求只处理检索层查询改写 LLM 化。
  - 验收：计划不包含 ReAct、QANode、rerank、embedding、Qdrant 或检索合并逻辑重写。
  - 验证：review `tasks/plan.md`。
- [ ] 确认 `retrieval_use_query_rewrite` 默认仍关闭。
  - 验收：默认配置仍为 `False`。
  - 验证：配置测试 / review。
- [ ] 确认开启查询改写后的默认 backend 为 `llm`。
  - 验收：`query_rewrite_backend` 默认值为 `llm`。
  - 验证：配置测试。
- [ ] 确认保留 legacy `HTTPQueryRewriter`。
  - 验收：`query_rewrite_backend=service` 时仍可构造 `HTTPQueryRewriter`。
  - 验证：backend 选择测试。
- [ ] 确认默认测试不触网、不调用真实 LLM。
  - 验收：新增测试全部使用 fake / stub。
  - 验证：review 测试实现。

## Phase 1 — Prompt/schema 与配置垂直切片

- [ ] 新增 `app/prompts/query_expand.py`。
  - 验收：模块可 import，导出 schema、system prompt、user prompt 构造函数。
  - 验证：`conda run -n autoGLM pytest tests/test_retrieval_tool.py`
- [ ] 定义 `QUERY_EXPAND_OUTPUT_SCHEMA`。
  - 验收：包含 required `queries`，`queries` 为 string array，`additionalProperties=False`。
  - 验证：prompt/schema 单测。
- [ ] 定义 `QUERY_EXPAND_SYSTEM_PROMPT`。
  - 验收：包含 `multi` 与 `hyde` 两种模式；覆盖任务目标、规则、角色、受众、样例、输出格式。
  - 验证：prompt 单测 / review。
- [ ] 实现 `build_query_expand_user_prompt(...)`。
  - 验收：原 query、mode、count 位于 `<data>...</data>`；声明数据区不作为指令。
  - 验证：prompt 单测。
- [ ] 在 prompt 中加入专利域安全约束。
  - 验收：禁止臆造法条、专利号、检索结果、引用、IPC 或技术事实；要求仅输出 JSON。
  - 验证：prompt 单测 / review。
- [ ] 新增 `Settings.query_rewrite_backend`。
  - 验收：默认 `llm`；`PAGENT_QUERY_REWRITE_BACKEND` 可覆盖。
  - 验证：`conda run -n autoGLM pytest tests/test_core_config_logging.py`
- [ ] 新增 `Settings.query_rewrite_model`。
  - 验收：默认 `None`；`PAGENT_QUERY_REWRITE_MODEL` 可覆盖。
  - 验证：配置测试。
- [ ] 新增 `Settings.query_rewrite_temperature`。
  - 验收：默认 `0.3`；`PAGENT_QUERY_REWRITE_TEMPERATURE` 可覆盖为 float。
  - 验证：配置测试。
- [ ] 更新 `Settings` docstring。
  - 验收：新增配置在 docstring 中说明用途。
  - 验证：review。
- [ ] 更新 `to_public_dict()`。
  - 验收：新增非敏感查询改写配置进入 public dict；不包含 key / token / secret。
  - 验证：配置测试。

## Phase 2 — LLMQueryRewriter 单组件闭环

- [ ] 在 `retrieval.py` 引入 LLM 与 query expand prompt 依赖。
  - 验收：复用 `LLMClient`、`LLMMessage`、`build_llm_client`，不新增 LLM SDK。
  - 验证：import 测试 / pytest。
- [ ] 新增 `LLMQueryRewriter` 类。
  - 验收：构造函数接收 `Settings` 与可选 `LLMClient`；公共类有中文 Google 风格 docstring。
  - 验证：`conda run -n autoGLM pytest tests/test_retrieval_tool.py`
- [ ] 实现空 query 直接返回 `[]`。
  - 验收：空字符串或空白字符串不调用 LLM。
  - 验证：单测断言 fake trace / calls 为空。
- [ ] 实现 `LLMClient.generate(...)` 调用。
  - 验收：传入 messages、`QUERY_EXPAND_OUTPUT_SCHEMA`、model、temperature、timeout、trace_context。
  - 验证：FakeLLMClient trace 断言。
- [ ] 实现模型回退顺序。
  - 验收：`query_rewrite_model or llm_cheap_model or llm_model`。
  - 验证：单测覆盖三种配置。
- [ ] 实现成功响应解析。
  - 验收：从 `response.content["queries"]` 读取字符串列表。
  - 验证：FakeLLMClient 成功响应测试。
- [ ] 实现原 query 首位、去重保序、过滤空白、截断。
  - 验收：返回最多 `query_rewrite_count + 1` 条，首项为原 query。
  - 验证：单测。
- [ ] 实现错误响应返回 `[]`。
  - 验收：`response.errors` 非空时返回 `[]`。
  - 验证：FakeLLMClient(error=...) 测试。
- [ ] 实现非法结构返回 `[]`。
  - 验收：content 非 dict、缺 `queries`、queries 空或不可用时返回 `[]`。
  - 验证：单测。
- [ ] 确认 `LLMQueryRewriter` 不自建 HTTP 调用。
  - 验收：实现中不使用 `urllib` / `requests` 调用 LLM，只调用 `llm_client.generate`。
  - 验证：review。

## Phase 3 — build_retriever backend 切换闭环

- [ ] 新增 `_build_query_rewriter(settings)`。
  - 验收：函数有中文 docstring；根据 `query_rewrite_backend` 构造 rewriter。
  - 验证：backend 单测。
- [ ] 支持 `query_rewrite_backend=llm`。
  - 验收：返回 `LLMQueryRewriter`。
  - 验证：`conda run -n autoGLM pytest tests/test_retrieval_tool.py`
- [ ] 支持 `query_rewrite_backend=service`。
  - 验收：返回 legacy `HTTPQueryRewriter`。
  - 验证：backend 单测。
- [ ] 调整未知 backend 的安全默认。
  - 验收：未知值不导致检索工厂崩溃，按 spec 默认到 LLM 或现有配置风格处理。
  - 验证：单测 / review。
- [ ] 修改 `build_retriever()` 默认查询改写构造。
  - 验收：开启 `retrieval_use_query_rewrite` 且未注入 rewriter 时使用 `_build_query_rewriter(...)`。
  - 验证：工厂测试。
- [ ] 保持显式注入 `query_rewriter` 优先。
  - 验收：传入 fake rewriter 时不构造默认 LLM / HTTP rewriter。
  - 验证：工厂测试。
- [ ] 保持关闭查询改写行为不变。
  - 验收：`retrieval_use_query_rewrite=false` 时不包裹 `MultiQueryRetriever`。
  - 验证：工厂回归测试。
- [ ] 保持装配顺序 base/hybrid → multi-query → rerank。
  - 验收：既有 hybrid + rewrite + rerank 测试继续通过。
  - 验证：`conda run -n autoGLM pytest tests/test_retrieval_tool.py`

## Phase 4 — MultiQueryRetriever 降级可观测闭环

- [ ] 调整 `_expand_queries()` 异常路径日志。
  - 验收：rewriter 抛异常时 `logger.warning`，extra event 为 `query_rewrite_failed`，返回 `[query]`。
  - 验证：caplog 单测。
- [ ] 调整 `_expand_queries()` 空结果日志。
  - 验收：过滤后无 query 时 `logger.info`，extra event 为 `query_rewrite_empty`，返回 `[query]`。
  - 验证：caplog 单测。
- [ ] 保持正常结果顺序。
  - 验收：正常扩展时过滤空白字符串，保留 rewriter 返回顺序。
  - 验证：MultiQueryRetriever 单测。
- [ ] 确认降级后仍执行单查询召回。
  - 验收：inner retriever 收到原 query。
  - 验证：既有 / 新增 fallback 测试。
- [ ] 确认日志不泄露敏感信息。
  - 验收：日志不包含完整 query、扩展式、prompt、API key。
  - 验证：review / 日志断言。

## Phase 5 — 总体验收与提交准备

- [ ] 运行目标测试。
  - 命令：`conda run -n autoGLM pytest tests/test_retrieval_tool.py tests/test_core_config_logging.py`
  - 验收：全部通过。
- [ ] 运行全量测试。
  - 命令：`conda run -n autoGLM pytest`
  - 验收：全部通过。
- [ ] 运行编译检查。
  - 命令：`conda run -n autoGLM python -m compileall app tests scripts`
  - 验收：无语法错误。
- [ ] 检查默认 backend 不依赖 `/query-rewrite`。
  - 验收：`retrieval_use_query_rewrite=true` 默认构造 `LLMQueryRewriter`。
  - 验证：单测 / review。
- [ ] 检查 legacy service backend 仍可用。
  - 验收：`query_rewrite_backend=service` 构造 `HTTPQueryRewriter`，旧 HTTP 单测通过。
  - 验证：单测。
- [ ] 检查关闭态完全一致。
  - 验收：`retrieval_use_query_rewrite=false` 时工厂返回原有 base / rerank 组合，不新增 LLM 调用。
  - 验证：工厂测试。
- [ ] 检查 diff 范围。
  - 验收：只包含本需求相关文件；无密钥、临时文件、调试代码。
  - 验证：`git status` / `git diff`。
- [ ] 阶段性提交。
  - 验收：目标测试和 compileall 通过后，按 `<type>(scope): <summary>` 中文提交规范提交。
  - 验证：`git status` clean。

## 需用户另行确认的可选项

- [ ] 是否运行真实 LLM 网关 smoke test。
  - 默认：不运行。
- [ ] 是否运行 ragas baseline / multi / hyde 对比。
  - 默认：不运行。
- [ ] 是否删除 legacy `HTTPQueryRewriter`。
  - 默认：不删除。
- [ ] 是否把 `retrieval_use_query_rewrite` 默认改为开启。
  - 默认：不改，仍为关闭。
