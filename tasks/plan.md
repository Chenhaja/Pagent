# R3.1 Query Rewrite Node 执行计划

## 背景

R3.1 将 `NormalizeInputNode` 的职责收敛为当前输入的机械归一化，并在 `intent_router` 前新增轻量 `QueryRewriteNode`：

```text
normalize_input → query_rewrite → intent_router → workflow
```

目标：

- `normalize_input` 只做空白归一化和空输入检查。
- `query_rewrite` 在有对话历史时调用 LLM 改写为自包含问题。
- 无历史、LLM 失败或响应非法时安全降级为原文，不阻断主流程。
- `intent_router` 继续消费 `state.normalized_input or state.raw_input`。

## 依赖图

```text
app/prompts/query_rewrite.py
  └── app/nodes/query_rewrite.py
        ├── app/models/schemas.py
        ├── app/orchestrator/node_base.py
        ├── app/tools/llm.py
        └── app/services/agent_dispatch_service.py
              └── app/nodes/intent_router.py
```

## 阶段

1. 固化并简化 normalize：测试先表达不读取历史，再移除历史拼接逻辑。
2. 增加 LLM client factory：配置完整返回真实 client，默认不完整返回 fake。
3. 增加 query rewrite prompt：集中放在 `app/prompts/`，满足六要素、结构化输出、指令/数据分离。
4. 增加 `QueryRewriteNode`：覆盖 skip / success / fallback，失败路径均返回 success。
5. 接入 dispatch：在 normalize 后、intent_router 前执行 query rewrite。
6. 修正相邻 trace 断言并全量回归。

## 验证命令

```bash
pytest --collect-only
pytest tests/test_normalize_input_node.py
pytest tests/test_llm_tool.py
pytest tests/test_query_rewrite_node.py
pytest tests/test_agent_dispatch_service.py
pytest tests/test_agent_api.py tests/test_known_intent_services.py tests/test_phase3_workflows.py
pytest tests/test_claim_generation_e2e.py tests/test_translate_e2e.py
pytest
python -m compileall app tests
```

## 边界

- 不引入 skill 抽象。
- 不实现多步 ReAct。
- 不让 LLM 修改 `raw_input`。
- 不因 LLM 错误阻断主流程。
- 不在 trace / 日志中记录完整 history、prompt、密钥或敏感长文本。
- 默认测试不触发真实 LLM 或网络请求。
