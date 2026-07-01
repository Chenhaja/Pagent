# 查询改写 LLM 化规格说明

## 1. Objective

### 目标

本规格目标是将检索层查询改写器从旧的自定义 `/query-rewrite` HTTP 端点，切换为复用项目已有 `OpenAICompatibleClient` 的标准 `/chat/completions` 通道。开启 `retrieval_use_query_rewrite` 后，默认由 LLM 生成 `multi` 或 `hyde` 查询扩展；关闭时保持现有行为不变。

完成标准：

- 新增 `LLMQueryRewriter`，通过 `LLMClient.generate(...)` 调用 OpenAI 兼容 LLM。
- 新增 `app/prompts/query_expand.py`，集中维护查询扩展 prompt、schema 与 user prompt 构造函数。
- `build_retriever` 在 `retrieval_use_query_rewrite=true` 时默认构造 `LLMQueryRewriter`。
- 保留 `HTTPQueryRewriter` 作为 legacy service backend，仅在 `query_rewrite_backend=service` 时使用。
- `MultiQueryRetriever` 的合并、去重、召回主循环语义保持不变。
- 查询扩展失败、返回空或返回非法结构时，确定性降级为单查询 `[query]`，并留下日志。
- LLM 扩展结果中原始 query 始终置于首位，防止语义漂移导致丢失原始意图。
- 新增非敏感配置进入 `Settings`、环境变量读取和 `to_public_dict()`。
- 默认测试使用 fake / stub LLM，不触网、不调用真实模型。

### 目标用户

- 专利 QA / RAG 用户：希望开启查询改写后真正扩展召回广度，而不是因缺少自定义端点静默退回单查询。
- 检索链路开发者：希望查询改写复用统一 LLM client、统一 trace、统一错误结构，减少自定义 HTTP 协议分叉。
- 测试与排障人员：需要通过配置、日志和 fake LLM 明确验证查询改写是否发生、扩展了几条、失败时如何降级。

### 非目标

- 不修改 `MultiQueryRetriever` 的召回、合并、排序、去重语义。
- 不修改 `RerankingRetriever`、ReAct 主循环、`QANode`、入口 `QueryRewriteNode`。
- 不解决 embedding、Qdrant、混合检索或单路召回为空问题。
- 不新增外部依赖或新 LLM SDK。
- 不在默认测试中调用真实 LLM、真实网关或真实检索后端。
- 不删除 legacy `HTTPQueryRewriter`，仅将其从默认路径移出。

---

## 2. Commands

项目使用 conda 环境 `autoGLM`。所有 Python、pytest、脚本命令必须通过 `conda run -n autoGLM` 执行，不能依赖 `conda activate` 的跨命令状态。

```bash
# 检索工具与查询改写目标测试
conda run -n autoGLM pytest tests/test_retrieval_tool.py

# 配置公开字段与环境变量测试
conda run -n autoGLM pytest tests/test_core_config_logging.py

# 本需求目标测试
conda run -n autoGLM pytest tests/test_retrieval_tool.py tests/test_core_config_logging.py

# 全量测试
conda run -n autoGLM pytest

# 编译检查
conda run -n autoGLM python -m compileall app tests scripts
```

验收命令：

```bash
conda run -n autoGLM pytest tests/test_retrieval_tool.py tests/test_core_config_logging.py
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests scripts
```

约束：

- 默认测试必须使用 fake / stub LLM，不调用真实付费模型。
- 默认测试不触网，不调用旧 `/query-rewrite` 服务。
- 不新增依赖；如确需新增，必须先确认并同步 `requirements.txt`。
- 不执行破坏性 git / 文件命令。
- 若需要运行 ragas 验收或真实 LLM 验收，必须先由用户确认模型、数据与网络调用范围。

---

## 3. Project Structure

目标结构：

```text
pagent/
  app/
    tools/
      retrieval.py          # LLMQueryRewriter、_build_query_rewriter、MultiQueryRetriever 日志降级
      llm.py                # 复用 LLMClient、LLMMessage、build_llm_client，不改公共契约
    prompts/
      query_expand.py       # 查询扩展 system prompt、output schema、user prompt 构造
    core/
      config.py             # query_rewrite_backend 等查询改写配置
  tests/
    test_retrieval_tool.py       # LLMQueryRewriter、backend 选择、MultiQueryRetriever 降级
    test_core_config_logging.py  # 新增查询改写配置默认值、环境变量、公开字段
  SPEC.md
```

### 3.1 LLMQueryRewriter 契约

`app/tools/retrieval.py` 新增 `LLMQueryRewriter`：

```python
class LLMQueryRewriter:
    """基于 OpenAI 兼容 LLM 的查询扩展器。"""

    def __init__(self, settings: Settings, llm_client: LLMClient | None = None) -> None: ...
    def expand(self, query: str) -> list[str]: ...
```

要求：

- 构造函数接收 `Settings` 与可选 `LLMClient`，便于测试注入 fake。
- 默认 LLM client 通过 `build_llm_client(settings)` 构造。
- `expand(query)` 对空 query 返回 `[]`。
- `mode` 来自 `settings.query_rewrite_mode`，支持 `multi` 与 `hyde`。
- `count` 来自 `settings.query_rewrite_count`，至少为 1。
- 调用 `llm_client.generate(...)` 时必须传入：
  - `messages=[LLMMessage(role="system", ...), LLMMessage(role="user", ...)]`
  - `output_schema=QUERY_EXPAND_OUTPUT_SCHEMA`
  - `model=settings.query_rewrite_model or settings.llm_cheap_model or settings.llm_model`
  - `temperature=settings.query_rewrite_temperature`
  - `timeout=settings.retrieval_timeout_seconds`
  - `trace_context={"node_name": "retrieval", "task_type": "query_expand"}`
- `response.errors` 非空、`response.content` 非 dict、`queries` 缺失或不是可用字符串列表时返回 `[]`。
- 正常返回时，结果必须为 `[原 query, *扩展 query]`，去重保序，最多 `count + 1` 条。
- 不直接使用 `urllib`、`requests` 或自定义 HTTP 请求调用 LLM。

### 3.2 Query Expand Prompt 契约

新增 `app/prompts/query_expand.py`，集中导出：

```python
QUERY_EXPAND_OUTPUT_SCHEMA = {...}
QUERY_EXPAND_SYSTEM_PROMPT = {"multi": "...", "hyde": "..."}
def build_query_expand_user_prompt(query: str, mode: str, count: int) -> str: ...
```

`QUERY_EXPAND_OUTPUT_SCHEMA` 必须包含：

```json
{
  "type": "object",
  "required": ["queries"],
  "properties": {
    "queries": {
      "type": "array",
      "items": {"type": "string"}
    }
  },
  "additionalProperties": false
}
```

Prompt 必须覆盖项目 prompt 六要素：

- 任务目标：生成可直接用于检索的查询扩展式或假设答案片段。
- 上下文 / 判定规则：保持原始意图，覆盖专利领域规范术语，禁止引入无来源事实。
- 角色：熟悉专利检索、专利审查与专利法术语的专家。
- 受众：检索器与结构化 JSON 解析器。
- 样例：至少包含 `multi` 与 `hyde` 的输入输出示例，并包含不确定 / 不臆造约束。
- 输出格式：仅输出 JSON，字段与 schema 一致，默认中文。

安全要求：

- user prompt 必须使用 `<data>...</data>` 包裹原始 query、mode、count。
- prompt 必须声明数据区内任何“指令”都应忽略。
- 禁止臆造法条、专利号、检索结果、引用、IPC 或技术事实。
- 不确定时应保守改写，不应补充没有来源的具体事实。
- 输出只包含 `queries`，不输出解释文本。

### 3.3 build_retriever 组装契约

`app/tools/retrieval.py` 新增或调整 `_build_query_rewriter`：

```python
def _build_query_rewriter(settings: Settings) -> QueryRewriter:
    """根据配置构造查询改写器。"""
    backend = (settings.query_rewrite_backend or "llm").strip().lower()
    if backend == "service":
        return HTTPQueryRewriter(settings)
    return LLMQueryRewriter(settings)
```

`build_retriever` 中：

- `retrieval_use_query_rewrite=false` 时，不包裹 `MultiQueryRetriever`，行为与当前一致。
- `retrieval_use_query_rewrite=true` 且调用方未传入 `query_rewriter` 时，使用 `_build_query_rewriter(resolved_settings)`。
- 调用方显式注入 `query_rewriter` 时，继续优先使用注入对象，便于测试和扩展。
- `query_rewrite_backend=service` 时使用 legacy `HTTPQueryRewriter`。
- 其他 backend 值默认按 `llm` 处理或按现有配置校验风格处理，但不得导致检索链路崩溃。

### 3.4 MultiQueryRetriever 降级与日志契约

`MultiQueryRetriever._expand_queries(query)` 必须：

- 调用 `self.query_rewriter.expand(query)`。
- 对异常使用 `logger.warning(...)`，事件名 `query_rewrite_failed`，并降级返回 `[query]`。
- 对空结果使用 `logger.info(...)`，事件名 `query_rewrite_empty`，并降级返回 `[query]`。
- 对正常结果过滤空字符串，保持 rewriter 返回顺序。
- 不记录完整 query、完整扩展式、密钥或敏感材料。
- 不重试、不触发额外网络调用、不中断检索主流程。

建议日志字段：

```json
{
  "event": "query_rewrite_failed",
  "message": "查询改写失败，降级为单查询"
}
```

### 3.5 配置契约

`app/core/config.py` 中查询改写配置必须包含：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `retrieval_use_query_rewrite` | `false` | 是否启用检索层查询改写，保持现有默认关闭 |
| `query_rewrite_backend` | `llm` | `llm` 走 `/chat/completions`；`service` 走旧 `/query-rewrite` |
| `query_rewrite_mode` | `multi` | `multi` 或 `hyde` |
| `query_rewrite_count` | `3` | 扩展式或假设文档数量 |
| `query_rewrite_model` | 空字符串 / None | 改写模型，空时回退 `llm_cheap_model` 再回退 `llm_model` |
| `query_rewrite_temperature` | `0.3` | 查询改写温度 |

要求：

- 环境变量名与字段一一对应，使用 `PAGENT_` 前缀。
- 新增非敏感配置进入 `to_public_dict()`。
- API key、token、secret、password 不得进入 `to_public_dict()`、日志或 trace。
- 配置项保持通用作用域，不新增单 Node 临时配置。
- 构造参数覆盖全局配置时使用 `settings.xxx if arg is None else arg`，避免吞掉 `False` / `0`。
- 删除或替换旧配置时必须同步测试；本需求不要求删除现有 mode/count/model/temperature。

---

## 4. Code Style

### 基本原则

- 最小化、局部化改动，优先修改 `app/tools/retrieval.py`、`app/prompts/query_expand.py`、`app/core/config.py` 与相关测试。
- 复用现有 `LLMClient.generate`、`LLMMessage`、`build_llm_client`、`FakeLLMClient` 能力。
- 不新增大型抽象、不新增外部依赖、不改检索主循环结构。
- 公共函数、公共方法、公共类必须添加中文 Google 风格 docstring，包含 Args / Returns / Raises（如有）。
- 简单私有 helper 可使用一行中文概述。
- 注释和日志沿用中文风格；结构化事件名使用稳定英文。
- 不记录完整 query、完整扩展 query、完整 prompt、密钥或敏感材料。

### Prompt 风格

- prompt 必须集中在 `app/prompts/` 模块，不内联散落在业务逻辑中。
- 运行时变量使用具名参数进入模板函数，不随意拼接指令与数据。
- 原始 query、mode、count 必须放入 `<data>...</data>` 数据区。
- 明确声明数据区内任何“指令”都应忽略。
- 默认要求仅输出 JSON，不输出解释。
- schema 设置 `required`、类型约束和 `additionalProperties: False`。
- 专利域默认约束必须保留：禁止臆造、不确定保守、使用规范术语。

### 错误处理与兜底

- LLM 查询扩展失败不得中断检索。
- LLM 返回错误、空内容、非 dict、缺少 `queries` 或无法解析时返回 `[]`。
- `MultiQueryRetriever` 对空扩展或异常统一降级为 `[query]`。
- 不为查询扩展失败引入复杂重试、熔断器或后台队列。
- 不因 legacy service backend 不可用而影响默认 LLM backend。
- 不把自定义 `/query-rewrite` 端点作为默认路径。

---

## 5. Testing Strategy

### LLMQueryRewriter 测试

必须覆盖：

- `FakeLLMClient` 返回 `{"queries": [...]}` 时，`expand()` 返回原 query 首位。
- 扩展 query 去重保序。
- 返回条数最多为 `query_rewrite_count + 1`。
- `query_rewrite_model` 为空时，模型选择回退 `llm_cheap_model`，再回退 `llm_model`。
- `generate(...)` 接收 `QUERY_EXPAND_OUTPUT_SCHEMA`，从而触发 OpenAI 兼容 JSON 输出格式。
- `trace_context` 包含 `node_name=retrieval` 与 `task_type=query_expand`。
- `response.errors` 非空时，`expand()` 返回 `[]`。
- `response.content` 非 dict、缺少 `queries`、`queries` 为空时，`expand()` 返回 `[]`。
- 空 query 返回 `[]`，不调用 LLM。

### Backend 选择与 build_retriever 测试

必须覆盖：

- `_build_query_rewriter` 在 `query_rewrite_backend=llm` 时返回 `LLMQueryRewriter`。
- `_build_query_rewriter` 在 `query_rewrite_backend=service` 时返回 `HTTPQueryRewriter`。
- `retrieval_use_query_rewrite=false` 时，`build_retriever` 不包裹 `MultiQueryRetriever`，行为与当前一致。
- `retrieval_use_query_rewrite=true` 且未注入 rewriter 时，默认使用 LLM backend。
- 显式注入 fake `query_rewriter` 时，`build_retriever` 使用注入对象。

### MultiQueryRetriever 降级测试

必须覆盖：

- rewriter 抛异常时，`_expand_queries()` 返回 `[query]`。
- rewriter 返回 `[]` 时，`_expand_queries()` 返回 `[query]`。
- rewriter 返回空字符串、空白字符串时会被过滤。
- 失败和空结果路径分别产生日志事件 `query_rewrite_failed`、`query_rewrite_empty`。
- 降级路径不影响底层 retriever 的单查询召回。

### Prompt 测试

必须覆盖：

- `QUERY_EXPAND_OUTPUT_SCHEMA` 非空，且 `additionalProperties` 为 `False`。
- `QUERY_EXPAND_SYSTEM_PROMPT` 包含 `multi` 与 `hyde`。
- user prompt 包含 `<data>` 与 `</data>`。
- user prompt 明确说明数据区不作为指令。
- prompt 中包含禁止臆造法条、专利号、检索结果或引用的约束。
- 输出格式要求为仅 JSON。

### 配置测试

必须覆盖：

- `Settings` 默认值包含 `query_rewrite_backend="llm"`。
- `PAGENT_QUERY_REWRITE_BACKEND=service` 能正确读取。
- `PAGENT_QUERY_REWRITE_MODE=hyde` 能正确读取。
- `PAGENT_QUERY_REWRITE_COUNT` 能正确读取为整数。
- `PAGENT_QUERY_REWRITE_MODEL` 能正确读取。
- `PAGENT_QUERY_REWRITE_TEMPERATURE` 能正确读取为浮点数。
- `to_public_dict()` 包含新增非敏感查询改写配置。
- `to_public_dict()` 不包含 API key、token、secret、password。

### 验收口径

- `conda run -n autoGLM pytest tests/test_retrieval_tool.py tests/test_core_config_logging.py` 通过。
- `conda run -n autoGLM pytest` 通过。
- `conda run -n autoGLM python -m compileall app tests scripts` 通过。
- 默认测试不触网、不调用真实付费 LLM。
- 开启 `retrieval_use_query_rewrite=true` 且 LLM 配置齐全时，查询扩展只经 `/chat/completions`。
- 默认 backend 不依赖自定义 `/query-rewrite` 端点。
- LLM 异常、空结果或非法 JSON 时，检索降级为单查询且留痕。
- 关闭 `retrieval_use_query_rewrite` 时行为与当前完全一致。

---

## 6. Boundaries

### Always do

- 始终默认使用 `LLMQueryRewriter` 作为开启查询改写后的 backend。
- 始终复用 `LLMClient.generate`、`LLMMessage` 与 `build_llm_client`。
- 始终通过 `output_schema` 约束 LLM 输出 JSON。
- 始终把原 query 放在扩展结果首位。
- 始终对扩展 query 去重保序并限制数量。
- 始终在查询改写失败或为空时降级为 `[query]`。
- 始终保留显式注入 `query_rewriter` 的测试 / 扩展入口。
- 始终保留 `HTTPQueryRewriter` 作为 `service` backend。
- 始终使用 `<data>...</data>` 隔离用户 query 等动态数据。
- 始终使用 `conda run -n autoGLM` 执行 Python、pytest 和脚本命令。

### Ask first

- 是否调用真实 LLM 或真实 OpenAI 兼容网关做人工验收。
- 是否运行 ragas 评测并发送真实问题 / 语料到模型或检索服务。
- 是否删除 legacy `HTTPQueryRewriter` 或旧 `/query-rewrite` backend。
- 是否新增依赖、替换 LLM client 接口或引入新 SDK。
- 是否修改 `MultiQueryRetriever` 的召回合并、排序、去重策略。
- 是否调整默认 `retrieval_use_query_rewrite` 为开启。
- 是否把完整 query、扩展式或 prompt 记录到日志 / trace 用于排障。

### Never do

- 不把自定义 `/query-rewrite` 端点作为默认查询改写路径。
- 不在 `LLMQueryRewriter` 中自建 `urllib` / `requests` 调用 LLM。
- 不让查询改写失败中断检索、QA 或 ReAct 主流程。
- 不在默认测试中触网、下载模型或调用真实付费服务。
- 不伪造法条、专利号、检索结果、引用、IPC 或 provenance。
- 不记录完整 query、完整扩展 query、完整 prompt、密钥或敏感材料。
- 不为本需求引入新存储后端、缓存系统、队列或复杂重试机制。
- 不修改入口 `QueryRewriteNode` 的职责或行为。
- 不修改 embedding、Qdrant、混合检索、rerank 或 QA 生成逻辑。

---

## 7. Functional Acceptance Checklist

- [ ] 新增 `app/prompts/query_expand.py`。
- [ ] `QUERY_EXPAND_OUTPUT_SCHEMA` 定义完整，含 `additionalProperties: False`。
- [ ] `QUERY_EXPAND_SYSTEM_PROMPT` 支持 `multi` 与 `hyde`。
- [ ] `build_query_expand_user_prompt(...)` 使用 `<data>...</data>` 隔离动态数据。
- [ ] 新增 `LLMQueryRewriter`。
- [ ] `LLMQueryRewriter.expand()` 使用 `LLMClient.generate(...)` 与 output schema。
- [ ] `LLMQueryRewriter.expand()` 原 query 首位、去重保序、截断到 `count + 1`。
- [ ] `LLMQueryRewriter.expand()` 对错误、空结果、非法结构返回 `[]`。
- [ ] 新增或调整 `_build_query_rewriter(...)`。
- [ ] `query_rewrite_backend=llm` 返回 `LLMQueryRewriter`。
- [ ] `query_rewrite_backend=service` 返回 legacy `HTTPQueryRewriter`。
- [ ] `build_retriever` 开启查询改写时默认使用 LLM backend。
- [ ] `build_retriever` 关闭查询改写时行为不变。
- [ ] 显式注入 `query_rewriter` 时仍优先使用注入对象。
- [ ] `_expand_queries` 对异常记录 `query_rewrite_failed` 并返回 `[query]`。
- [ ] `_expand_queries` 对空结果记录 `query_rewrite_empty` 并返回 `[query]`。
- [ ] 新增 `query_rewrite_backend` 配置，默认 `llm`。
- [ ] 查询改写相关非敏感配置进入 `to_public_dict()`。
- [ ] 配置环境变量读取测试通过。
- [ ] `conda run -n autoGLM pytest tests/test_retrieval_tool.py tests/test_core_config_logging.py` 通过。
- [ ] `conda run -n autoGLM pytest` 通过。
- [ ] `conda run -n autoGLM python -m compileall app tests scripts` 通过。

---

## 8. Implementation Order

1. 检查现有 `Settings`、`HTTPQueryRewriter`、`MultiQueryRetriever`、`build_retriever` 与 LLM fake 测试工具。
2. 新增 `app/prompts/query_expand.py`，定义 schema、system prompt 与 user prompt 构造函数。
3. 编写 prompt 与 schema 测试，确认数据区隔离和 JSON 输出约束。
4. 新增 `LLMQueryRewriter`，接入 `LLMClient.generate`。
5. 编写 `LLMQueryRewriter` 单测，覆盖成功、错误、空结果、去重、截断、模型回退。
6. 新增 `query_rewrite_backend` 配置，补环境变量读取与 `to_public_dict()` 测试。
7. 新增 `_build_query_rewriter`，将 `build_retriever` 默认 backend 切为 LLM。
8. 补 backend 选择和注入 rewriter 的回归测试。
9. 调整 `_expand_queries` 的异常 / 空结果日志，补降级测试。
10. 运行目标测试、全量 pytest 和 compileall。
11. 若本阶段形成可独立验证改动，按项目提交规范单独 commit。
