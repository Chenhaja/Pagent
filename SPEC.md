# R5.3 QA 节点受限 ReAct 循环规格说明

## 1. Objective

### 目标

R5.3 的目标是把 QA 节点从「单步检索 → 回答」升级为 QA 节点内部的受限 Reason–Act 循环：检索 → 评估证据充分性 → 证据不足时改写 query 再检索 → 基于累积证据回答。

完成标准：

- QA 节点在 `retrieval_max_steps` / `retrieval_token_budget` / `retrieval_timeout_seconds` 预算内执行 bounded ReAct 循环。
- 证据充分时只检索 1 步即作答，保持现有成功路径兼容。
- 证据不足且仍有预算时触发「query 改写 → 再检索」，可由测试断言检索调用次数。
- 达到 `max_steps`、token 预算耗尽或超时时停止循环，并基于已有证据优雅作答，不抛裸异常。
- 多轮检索结果按 `document_id` 累积去重，保留高分证据，`basis` 回链真实来源。
- `max_steps <= 0` 或 token 预算 `<= 0` 时不检索，保持现有护栏行为。
- 每轮写入 `qa_react_step` trace；收敛时写入 `qa_react_converged` trace。
- 输出继续明确标注为辅助初稿 / 非法律意见，不伪造检索来源、法条、专利号或现有技术。

### 目标用户

- 普通发明人 / 下游 workflow：希望证据不足时系统能多查一轮，而不是草率作答。
- 开发与测试人员：需要可断言循环在预算内收敛、不足触发再检索、预算耗尽优雅收敛。

### 非目标

- 不做跨节点或全局 ReAct，不允许 LLM 改变 workflow 走向。
- 不做多轮会话级长程 ReAct。
- 不接真实付费检索源或第三方专利库。
- 不引入新的外部 agent 框架。
- 不做前端，仍以 API / service 为入口。
- 本轮默认不启用 LLM 证据充分性判定，仅预留配置与扩展点。

---

## 2. Commands

项目使用 conda 环境 `autoGLM`。所有 Python / pytest / 脚本命令必须通过 `conda run -n autoGLM` 执行，不能依赖 `conda activate` 的跨命令状态。

```bash
# QA ReAct 循环核心测试
conda run -n autoGLM pytest tests/test_qa_react_loop.py

# QA 节点回归测试
conda run -n autoGLM pytest tests/test_qa_node.py

# 配置测试
conda run -n autoGLM pytest tests/test_config.py

# 全量测试
conda run -n autoGLM pytest

# 编译检查
conda run -n autoGLM python -m compileall app tests scripts
```

最终验收命令：

```bash
conda run -n autoGLM pytest tests/test_qa_react_loop.py tests/test_qa_node.py tests/test_config.py
conda run -n autoGLM pytest
conda run -n autoGLM python -m compileall app tests scripts
```

约束：

- 默认测试必须使用 fake / stub / monkeypatch，不触网、不调用真实付费模型或真实检索源。
- 不新增外部依赖；如确需新增依赖，必须先确认并同步 `requirements.txt`。
- 不运行会修改真实外部服务状态的命令，除非用户明确要求。

---

## 3. Project Structure

R5.3 聚焦 QA 节点内部循环，循环逻辑应与 QA 状态尽量解耦，便于未来抽取为节点无关的 ReAct 原语，但本轮不实现通用框架。

目标变更：

```text
pagent/
  app/
    core/
      config.py                         # 新增通用 retrieval_react_* 配置
    nodes/
      qa.py                             # 单步检索改为 bounded ReAct 循环，抽出 _retrieve_loop
      query_rewrite.py                  # 复用现有 query 改写能力
    tools/
      retrieval.py                      # 继续提供 top_k 检索和 provenance 结果
    skills/
      patent_qa.py                      # 继续负责最终结构化回答；可预留 LLM judge 扩展
    prompts/
      patent_qa.py                      # 如实现 LLM judge，prompt 必须集中在此处
    models/
      schemas.py                        # 可选新增 ReActStepTrace，或继续使用 dialog_context dict
  tests/
    test_qa_react_loop.py               # 新增：循环、多步、预算、收敛、去重测试
    test_qa_node.py                     # 扩展：QA 节点回归与 trace 断言
    test_config.py                      # 扩展：新增配置默认值、环境变量、公开配置
  SPEC.md                               # 本规格
```

### QA ReAct 循环契约

建议在 `app/nodes/qa.py` 中抽出 `_retrieve_loop` 或等价私有单元，职责为：

1. 接收原始 `question`、检索器、query 改写能力、预算参数与 trace 写入能力。
2. 在预算内循环检索。
3. 每轮检索后使用证据充分性评估器判定是否停止。
4. 证据不足且仍有预算时生成下一轮检索 query。
5. 跨轮累积证据并按 `document_id` 去重。
6. 返回累积证据、实际步数、收敛原因与每轮 trace 数据。

收敛原因枚举：

```text
sufficient     # 证据充分
max_steps      # 达到最大步数
token_budget   # token 预算不足或耗尽
timeout        # 超过超时限制
```

约束：

- ReAct 只在 QA 节点内部执行，不影响全局 workflow 编排。
- LLM 不得决定节点跳转或 workflow 顺序。
- 循环必须有明确上限，不能无界递归或无限 while。
- 预算耗尽、超时或无证据时仍应进入最终回答阶段，由回答内容诚实标注依据不足。

### 证据充分性评估契约

默认使用启发式评估：

```text
result_count >= retrieval_react_min_results
AND
top_score >= retrieval_react_min_score
```

字段含义：

- `result_count`：本轮或累积去重后的可用证据数量，具体口径在实现中保持一致并由测试固定。
- `top_score`：当前证据集合中的最高检索分数；无结果时为 `0.0`。
- `sufficient`：同时满足数量和分数阈值时为 `True`。

LLM judge 预留：

- 配置项 `retrieval_react_use_llm_judge` 默认 `False`。
- 本轮默认不实现真实 LLM judge；若实现，必须只输出 JSON，并严格指令 / 数据分离。
- LLM judge 失败时应回退启发式，不打断 QA。

### Query 改写契约

证据不足且仍有预算时，复用现有 `nodes/query_rewrite.py` 能力或等价 helper 生成下一轮检索 query。

约束：

- 改写输入可包含原始 question、已检索轮次、已有证据摘要或缺口描述。
- trace / 日志不得记录完整 query 原文，只记录 `query_len`。
- 改写失败时可使用原 query 或停止于已有证据，但不得抛裸异常打断 QA。
- 不新增散落在业务逻辑中的 prompt；如需要 prompt，必须集中在 `app/prompts/`。

### 证据累积与去重契约

多轮结果合并规则：

- 使用 `document_id` 作为主要去重键。
- 同一 `document_id` 多次出现时保留高分结果。
- 若结果缺少 `document_id`，使用现有 provenance 中可稳定标识来源的字段兜底；仍无法标识时保守保留，避免误删证据。
- `WorkflowState.dialog_context["qa_retrieval_results"]` 存储累积去重后的证据。
- 最终回答的 `basis` 必须回链真实检索结果来源。

### Trace 契约

每轮检索后写入 `qa_react_step`：

```json
{
  "node_name": "qa",
  "step_index": 1,
  "query_len": 12,
  "result_count": 2,
  "top_score": 0.67,
  "sufficient": true
}
```

循环收敛时写入 `qa_react_converged`：

```json
{
  "node_name": "qa",
  "reason": "sufficient",
  "steps_used": 1,
  "total_evidence": 2
}
```

约束：

- trace 不记录完整 query、完整检索正文、密钥、凭证或敏感材料。
- `query_len` 只记录长度。
- `top_score` 无结果时使用 `0.0`。
- `steps_used` 与实际检索轮数一致。
- 继续保留既有 `qa_completed` trace，字段包括 `basis_count` / `has_retrieval`。

### 配置契约

复用现有通用检索预算配置：

| 配置字段 | 环境变量 | 说明 |
| --- | --- | --- |
| `retrieval_max_steps` | `PAGENT_RETRIEVAL_MAX_STEPS` | QA 内部 ReAct 最大检索步数 |
| `retrieval_token_budget` | `PAGENT_RETRIEVAL_TOKEN_BUDGET` | QA 检索循环可用 token 预算 |
| `retrieval_timeout_seconds` | `PAGENT_RETRIEVAL_TIMEOUT_SECONDS` | QA 检索循环超时时间 |
| `retrieval_top_k` | `PAGENT_RETRIEVAL_TOP_K` | 每轮检索 top_k |

新增通用配置：

| 配置字段 | 环境变量 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `retrieval_react_min_results` | `PAGENT_RETRIEVAL_REACT_MIN_RESULTS` | `1` | 判定证据充分的最小命中数 |
| `retrieval_react_min_score` | `PAGENT_RETRIEVAL_REACT_MIN_SCORE` | `0.3` | 判定证据充分的最低最高分 |
| `retrieval_react_use_llm_judge` | `PAGENT_RETRIEVAL_REACT_USE_LLM_JUDGE` | `False` | 是否启用 LLM 证据充分性判定 |

要求：

- 配置名保持通用检索作用域，不新增 `qa_*` 等绑定单 Node 的字段。
- 新增配置必须同步 `Settings` 默认值、环境变量读取、`to_public_dict()` 和测试。
- 非敏感配置可进入 `to_public_dict()`；不得将 API Key、token、secret、password 等敏感字段公开。
- Node / 模块构造参数如需覆盖全局配置，使用 `None` 表示继承，避免 `arg or settings.xxx` 吞掉 `0` / `False`。

---

## 4. Code Style

### 基本原则

- 最小化、局部化改动，优先复用现有 QA、retrieval、query rewrite、patent QA skill 与 trace 结构。
- 不引入新框架，不把本轮 QA 内部循环扩展成通用 agent 框架。
- 循环逻辑应独立成清晰私有函数或小型单元，避免把预算、检索、去重、trace 全部堆在主函数中。
- 公共函数、公共方法、公共类必须添加中文 Google 风格 docstring，包含 Args / Returns / Raises（如有）。
- 私有简单 helper 可用一行中文概述；只在边界处理、预算判断、去重策略等不直观处加行内注释。
- 日志 / trace 沿用中文 message + 稳定英文 event 风格。
- 不记录完整 query、检索正文、密钥、凭证或过长文本。

### Prompt 规范

如新增 LLM judge 或 query 改写 prompt，必须满足项目 prompt 规范：

- prompt 集中在 `app/prompts/`，不得内联散落在业务逻辑里。
- 覆盖任务目标、上下文 / 判定规则、角色、受众、样例、输出格式六要素。
- 外部 / 用户 / 检索内容必须包裹在 `<data>...</data>` 或三引号中，并声明数据区不作为指令。
- 默认要求仅输出 JSON，并明确字段类型、必填项、枚举值与 `additionalProperties: False`。
- 专利域约束必须明确：禁止臆造、不确定显式标注、使用规范术语。

### 错误处理与降级

- 检索异常、改写异常或 judge 异常不得以裸异常打断 QA；应记录可恢复 warning / trace 后基于已有证据收敛。
- 预算为 `<= 0` 时不检索，直接走无检索 / 依据不足回答路径。
- 超时判断必须在循环中生效，不能只在循环结束后检查。
- token 预算不足时应停止新增检索或改写，收敛 reason 为 `token_budget`。
- 最终回答应在 `risk_notes` / `disclaimer_hint` 标注依据可能不足。

---

## 5. Testing Strategy

### QA ReAct 循环测试

必须覆盖：

- 证据充分时只检索 1 步即作答。
- 证据不足且有预算时触发 query 改写并再次检索，断言检索被调用 2 次。
- 达到 `retrieval_max_steps` 后停止，收敛 reason 为 `max_steps`。
- token 预算耗尽时停止，收敛 reason 为 `token_budget`，最终回答包含依据不足提示。
- 超时时停止，收敛 reason 为 `timeout`，最终回答不抛异常。
- `max_steps <= 0` 或 token 预算 `<= 0` 时不调用检索。
- 循环步数、`steps_used`、trace 数量与实际检索次数一致。

### 证据评估与去重测试

必须覆盖：

- 命中数达到 `retrieval_react_min_results` 且最高分达到 `retrieval_react_min_score` 时判定充分。
- 命中数不足时判定不足。
- 最高分不足时判定不足。
- 多轮结果按 `document_id` 去重。
- 同一 `document_id` 多次出现时保留高分证据。
- 去重后的证据写入 `dialog_context["qa_retrieval_results"]`。
- 最终 `basis` 回链真实来源，不生成伪来源。

### Trace 测试

必须覆盖：

- 每轮写入 `qa_react_step`。
- `qa_react_step` 包含 `step_index`、`query_len`、`result_count`、`top_score`、`sufficient`。
- `qa_react_step` 不包含完整 query 原文或完整检索正文。
- 收敛时写入 `qa_react_converged`。
- `qa_react_converged` 包含 `reason`、`steps_used`、`total_evidence`。
- 既有 `qa_completed` trace 保持可用。

### 配置测试

必须覆盖：

- `retrieval_react_min_results` 默认值为 `1`，可被 `PAGENT_RETRIEVAL_REACT_MIN_RESULTS` 覆盖。
- `retrieval_react_min_score` 默认值为 `0.3`，可被 `PAGENT_RETRIEVAL_REACT_MIN_SCORE` 覆盖。
- `retrieval_react_use_llm_judge` 默认值为 `False`，可被 `PAGENT_RETRIEVAL_REACT_USE_LLM_JUDGE` 覆盖。
- 新增非敏感配置进入 `to_public_dict()`。
- 覆盖参数使用 `None` 继承全局配置，不吞掉 `0` / `False`。

### LLM judge 预留测试

若本轮实现 LLM judge 开关，必须覆盖：

- 开关关闭时只使用启发式，不调用 LLM judge。
- 开关开启时可注入 stub judge，并以 stub 返回结果决定是否继续检索。
- LLM judge 返回非法 JSON 或异常时回退启发式。
- judge prompt 指令 / 数据分离，输出仅 JSON。

如本轮仅预留配置、不实现真实 judge，则必须至少测试开关关闭路径，并避免默认测试触网。

### 验收口径

- `conda run -n autoGLM pytest tests/test_qa_react_loop.py tests/test_qa_node.py tests/test_config.py` 通过。
- `conda run -n autoGLM pytest` 通过。
- `conda run -n autoGLM python -m compileall app tests scripts` 通过。
- 默认测试不触网、不调用真实付费 LLM、不连接真实外部检索源。

---

## 6. Boundaries

### Always do

- 始终把 ReAct 限定在 QA 节点内部。
- 始终受 `retrieval_max_steps` / `retrieval_token_budget` / `retrieval_timeout_seconds` 封顶。
- 始终在证据不足、预算耗尽或超时时优雅收敛并作答。
- 始终累积并去重证据，`basis` 回链真实来源。
- 始终保留 `raw_input`。
- 始终标注辅助初稿、非法律意见。
- 始终用 fake / stub / monkeypatch 做默认测试，不触网。
- 始终使用通用检索配置名，不新增绑定单 Node 的 `qa_*` 配置。
- 始终使用 `conda run -n autoGLM` 执行 Python、pytest 和脚本命令。

### Ask first

- 是否启用真实 LLM 做证据充分性判定。
- 是否提高 `max_steps`、token 预算或超时上限做人工验收。
- 是否接入真实检索源或真实付费专利库。
- 是否修改全局 workflow 编排或让 LLM 参与节点路由。
- 是否新增外部依赖。

### Never do

- 不让 LLM 决定全局 workflow 顺序。
- 不做无界或长程 ReAct。
- 不伪造检索来源、法条、专利号或现有技术。
- 不在 trace / 日志记录完整敏感正文、完整 query、完整检索正文或密钥。
- 不让预算耗尽、超时或检索不足导致裸异常中断 QA。
- 不在默认单测中触网、下载模型或调用真实付费服务。
- 不新增绑定单 Node 的 `qa_*` 检索配置。

---

## 7. Functional Acceptance Checklist

- [ ] QA 节点实现 bounded ReAct 循环。
- [ ] 证据充分时只检索 1 步。
- [ ] 证据不足且有预算时触发 query 改写和二次检索。
- [ ] 达到 `retrieval_max_steps` 时收敛 reason 为 `max_steps`。
- [ ] token 预算耗尽时收敛 reason 为 `token_budget`。
- [ ] 超时时收敛 reason 为 `timeout`。
- [ ] `max_steps <= 0` 或 token 预算 `<= 0` 时不检索。
- [ ] 多轮证据按 `document_id` 去重。
- [ ] 同一 `document_id` 保留高分证据。
- [ ] `dialog_context["qa_retrieval_results"]` 存储累积去重后的证据。
- [ ] 最终 `basis` 回链真实来源。
- [ ] 预算耗尽或依据不足时 `risk_notes` / `disclaimer_hint` 明确标注依据可能不足。
- [ ] 新增 `retrieval_react_min_results` 配置及环境变量读取。
- [ ] 新增 `retrieval_react_min_score` 配置及环境变量读取。
- [ ] 新增 `retrieval_react_use_llm_judge` 配置及环境变量读取。
- [ ] 新增配置进入 `to_public_dict()` 且无敏感信息。
- [ ] 每轮写入 `qa_react_step` trace。
- [ ] 收敛时写入 `qa_react_converged` trace。
- [ ] trace 不记录完整 query 或检索正文。
- [ ] `qa_completed` trace 保持可用。
- [ ] 默认测试不触网、不调用真实付费服务。
- [ ] `conda run -n autoGLM pytest` 通过。
- [ ] `conda run -n autoGLM python -m compileall app tests scripts` 通过。

---

## 8. Implementation Order

1. 配置：新增 `retrieval_react_min_results`、`retrieval_react_min_score`、`retrieval_react_use_llm_judge`，同步环境变量、`to_public_dict()` 和配置测试。
2. 测试：新增 `tests/test_qa_react_loop.py`，先覆盖充分即停、不足再检索、max_steps、token_budget、timeout、去重和 trace。
3. 循环：在 `app/nodes/qa.py` 抽出 `_retrieve_loop` 或等价私有单元，实现检索、评估、改写、累积、收敛。
4. 去重：实现证据累积去重 helper，按 `document_id` 保留高分证据。
5. Trace：落地 `qa_react_step` 与 `qa_react_converged`，确保脱敏字段符合规格。
6. 回答降级：预算耗尽或依据不足时，将提示写入 `risk_notes` / `disclaimer_hint` 并保持最终回答结构化。
7. 回归：更新 `tests/test_qa_node.py` 相邻断言，运行目标测试、全量测试和 compileall。
