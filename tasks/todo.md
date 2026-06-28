# R3.1 Query Rewrite Node 任务清单

## Task 0：创建执行计划文件

- [x] 新增 `tasks/plan.md` 和 `tasks/todo.md`
  - 验收：两个文件可直接指导执行，todo 按垂直切片排列。
  - 验证：`pytest --collect-only`

## Task 1：固化 normalize 职责边界测试

- [x] 更新 `tests/test_normalize_input_node.py`
  - 验收：测试明确表达 normalize 不读取 `dialog_context` 做语义融合。
  - 验证：`pytest tests/test_normalize_input_node.py`

## Task 2：简化 NormalizeInputNode

- [x] 修改 `app/nodes/normalize_input.py`
  - 验收：只做当前 `raw_input` 空白归一化和空输入检查，不依赖 `dialog_context`。
  - 验证：`pytest tests/test_normalize_input_node.py`

## Task 3：添加 LLM client factory 测试

- [x] 更新 `tests/test_llm_tool.py`
  - 验收：配置完整返回 `OpenAICompatibleClient`，配置缺失返回 `FakeLLMClient`，不触发网络请求。
  - 验证：`pytest tests/test_llm_tool.py`

## Task 4：实现 build_llm_client

- [x] 修改 `app/tools/llm.py`
  - 验收：公开函数 `build_llm_client(settings=None)` 默认配置不完整时返回 fake。
  - 验证：`pytest tests/test_llm_tool.py`

## Task 5：添加 query rewrite prompt 模块

- [x] 新增 `app/prompts/query_rewrite.py`
  - 验收：prompt 覆盖六要素，数据区隔离，输出仅 JSON，含 `confidence` / `uncertain` 字段。
  - 验证：`pytest tests/test_query_rewrite_node.py`

## Task 6：添加 QueryRewriteNode 单元测试

- [x] 新增 `tests/test_query_rewrite_node.py`
  - 验收：覆盖无历史跳过、成功改写、错误/异常/非法响应 fallback、base query 优先级和 prompt safety。
  - 验证：`pytest tests/test_query_rewrite_node.py`

## Task 7：实现 QueryRewriteNode

- [x] 新增 `app/nodes/query_rewrite.py`
  - 验收：失败路径均 success + fallback trace，不修改 `raw_input`，无历史不调用 LLM。
  - 验证：`pytest tests/test_query_rewrite_node.py`

## Task 8：更新 AgentDispatchService 测试

- [x] 修改 `tests/test_agent_dispatch_service.py`
  - 验收：trace 顺序包含 query rewrite，改写结果影响 intent router，fallback 不阻断 dispatch。
  - 验证：`pytest tests/test_agent_dispatch_service.py`

## Task 9：接入 AgentDispatchService

- [x] 修改 `app/services/agent_dispatch_service.py`
  - 验收：链路为 normalize → query_rewrite → intent_router，默认无 history 不触网。
  - 验证：`pytest tests/test_agent_dispatch_service.py`

## Task 10：修正相邻回归断言

- [x] 修正硬编码 trace 顺序或列表断言
  - 验收：默认 API / service 请求不触发真实 LLM，业务流仍成功。
  - 验证：`pytest tests/test_agent_api.py tests/test_known_intent_services.py tests/test_phase3_workflows.py tests/test_claim_generation_e2e.py tests/test_translate_e2e.py`

## Task 11：全量验证与收尾

- [x] 运行全量测试和编译检查
  - 验收：全量测试通过，diff 无无关改动和敏感信息。
  - 验证：`pytest && python -m compileall app tests`
