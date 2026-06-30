<aside>
 🎯

**一句话目标**：把 QA 节点从「单步检索 → 回答」升级为「检索 → 评估证据充分性 →（不足则改写 query 再检索）→ 回答」的**受限 ReAct 小循环**；步数 / token / 超时全程封顶、优雅收敛，并对每一步落 trace。补齐 R5.2 中唯一尚未真正兑现的部分。

</aside>

本 PRD 对应仓库 `Chenhaja/Pagent`，承接 R5.2（QA 回答实质化）之后的收尾阶段，沿用既有分层骨架与 R 编号风格。

## 1. 背景与目标

R5.2 已让 QA 节点走通「检索 → 带 provenance 证据注入 → 真实 LLM 结构化回答 → 风险 / 时效标注 → trace」的闭环。但当前 `qa.py` 的检索是**单步**的（`steps_used = 1 if retrieval_results else 0`）：护栏参数 `max_steps / token_budget / timeout_seconds` 已接入并对 `<=0` 生效，但模型**不会**在「第一批证据不足」时自行改写 query 再检索一次——即还不是真正的 bounded ReAct。

本阶段目标：

- 在 QA 节点内部实现**受限的 Reason–Act 循环**：检索 → 评估 →（必要时再检索）→ 回答。
- 循环严格受 `max_steps / token_budget / timeout_seconds` 约束，超预算**优雅收敛**到「基于现有证据作答 + 诚实标注依据不足」，绝不中断或无限发散。
- 全局编排仍是确定性的：ReAct 只在 QA 节点内部，**不允许 LLM 改变 workflow 走向**。
- 默认测试不触网；`raw_input` 永远保留；输出仍明确标注为辅助初稿。

### 目标用户

- 普通发明人 / 下游 workflow：希望证据不足时系统能「多查一轮」而非草率作答。
- 开发与测试人员：需要可断言「循环在 N 步收敛」「不足触发再检索」「预算耗尽优雅收敛」。

## 2. 现状盘点（基于当前代码）

| 模块                     | 现状                                                       | 缺口                                                        |
| ------------------------ | ---------------------------------------------------------- | ----------------------------------------------------------- |
| `nodes/qa.py`            | 单步检索后直接调 skill 回答；护栏参数已接入且对 `<=0` 生效 | 无「评估证据是否充分」环节；无再检索；`steps_used` 恒为 0/1 |
| `nodes/query_rewrite.py` | 已有 query 改写能力（入口阶段）                            | 未在 QA 循环内被复用做「检索 query 改写」                   |
| `tools/retrieval.py`     | 支持 `top_k` 检索、结果带 provenance                       | 多轮检索结果未累积 / 去重                                   |
| `skills/patent_qa.py`    | 单次生成结构化答复                                         | 无「判断证据是否足够回答」的中间判定                        |

## 3. 范围

### In scope（本轮）

- QA 节点内 bounded ReAct 循环（检索 → 评估 → 再检索 → 回答）。
- 证据充分性评估（先用可解释的启发式：命中数 / 分数阈值；预留 LLM 评估开关）。
- 轮次间检索 query 改写（复用 `query_rewrite` 能力）。
- 跨轮证据累积与按 `document_id` 去重。
- 每轮 trace（`qa_react_step`）+ 收敛原因 trace。
- 配套 TDD 测试与回归修正。

### Non-goals（本轮不做）

- 不做跨节点 / 全局 ReAct；不让 LLM 决定 workflow 顺序。
- 不做多轮会话级长程 ReAct（留待记忆阶段）。
- 不接真实付费检索源 / 第三方专利库（检索仍 mock / 本地）。
- 不引入新的外部 agent 框架。
- 不做前端，仍以 API / service 为入口。

### 设计约束（为未来复用留缝，本轮不实现通用原语）

本轮 ReAct 仅服务 QA 一个使用方；但循环逻辑须与 QA 状态解耦（写成相对独立、可平移的单元）、trace 预留 `node_name` 字段、预算 / 阈值走 settings 不硬编码，以便未来低成本抽取为节点无关的通用 ReAct 原语（不在本轮实现）。

## 4. 详细需求

### R5.3.1 受限 ReAct 循环（P0）

执行策略：在 `max_steps / token_budget / timeout_seconds` 预算内循环。

1. **初次检索**：用当前 `question` 检索 `top_k`。
2. **证据充分性评估**：默认启发式——(a) 命中数 ≥ `retrieval_react_min_results` 且 (b) 最高分 ≥ `retrieval_react_min_score` 即判「充分」。预留 `retrieval_react_use_llm_judge` 开关走 LLM 判定（仅输出 JSON、指令 / 数据分离）。
3. **不足且仍有预算**：调用 query 改写生成新检索 query（带上「已检索过、还缺什么」的线索），再检索一轮。
4. **证据累积**：跨轮合并结果，按 `document_id` 去重，保留高分。
5. **收敛条件**（任一触发即停并作答）：判定充分 / 达到 `max_steps` / token 预算耗尽 / 超时。
6. **优雅收敛**：预算耗尽时基于现有证据作答，并在 `risk_notes` / `disclaimer_hint` 标注「依据可能不足」。

验收标准：

- 证据充分时只检索 1 步即作答（与现状行为兼容）。
- 证据不足且有预算时触发「改写 query → 再检索」，可被测试断言。
- 达到 `max_steps` / 预算 / 超时时停止并优雅收敛，不抛裸异常。
- 多轮证据按 `document_id` 去重；`basis` 回链真实来源。
- `max_steps<=0` / 预算 `<=0` 时不检索（保持现有行为）。

### R5.3.2 可观测与 trace（P0）

- 每轮落 `qa_react_step`：`step_index` / `query_len`（脱敏，仅长度）/ `result_count` / `top_score` / `sufficient`(bool)。
- 收敛时落 `qa_react_converged`：`reason`（`sufficient` | `max_steps` | `token_budget` | `timeout`）/ `steps_used` / `total_evidence`。

## 5. 数据契约

`app/models/schemas.py` 调整：

- 新增 `ReActStepTrace`（`step_index:int`, `result_count:int`, `top_score:float`, `sufficient:bool`, `reason:str|None`），或以 dict 形式写入 `dialog_context["qa_react_steps"]`。

- `WorkflowState.dialog_context["qa_retrieval_results"]` 改为承载**累积去重后**的证据。

- 复用现有 settings：`retrieval_max_steps` / `retrieval_token_budget` / `retrieval_timeout_seconds` / `retrieval_top_k`。

- 新增 settings（

  ```
  PAGENT_
  ```

   前缀、通用命名，不绑定具体 Node）：

  - `retrieval_react_min_results`（默认如 `1`）
  - `retrieval_react_min_score`（默认如 `0.3`）
  - `retrieval_react_use_llm_judge`（默认 `False`）

## 6. 项目结构变更

```
app/
  nodes/qa.py            # 单步 → bounded ReAct 循环（抽出 _retrieve_loop）
  skills/patent_qa.py    # （可选）新增证据充分性 LLM 判定
  prompts/patent_qa.py   # （可选）新增充分性判定 prompt
  core/config.py         # 新增 react 相关通用配置
  models/schemas.py      # 新增 ReActStepTrace（可选）
tests/
  test_qa_node.py            # 扩展:循环/收敛/去重断言
  test_qa_react_loop.py      # 新增:多步与预算收敛
  test_retrieval_dedup.py    # 新增（可选）
```

## 7. 安全与可观测（trace 事件）

| 事件名               | 触发       | data（脱敏）                                                 |
| -------------------- | ---------- | ------------------------------------------------------------ |
| `qa_react_step`      | 每轮检索后 | `step_index` / `result_count` / `top_score` / `sufficient` / `query_len` |
| `qa_react_converged` | 循环结束   | `reason` / `steps_used` / `total_evidence`                   |
| `qa_completed`       | 回答生成   | `basis_count` / `has_retrieval`                              |

约束：trace 与日志不记录完整 query 原文 / 完整检索正文 / 密钥；只记录长度、计数、分数、布尔与原因。`allow_cloud_sensitive_content=False` 时不向云模型发送完整敏感材料。

## 8. 测试策略（TDD）

- [ ]  证据充分 → 只检索 1 步即作答。
- [ ]  证据不足且有预算 → 触发改写 query 再检索，断言检索被调用 2 次。
- [ ]  达到 `max_steps` → 在第 N 步停止并作答。
- [ ]  `token_budget` / `timeout` 耗尽 → 优雅收敛 + 对应 `reason` trace。
- [ ]  多轮结果按 `document_id` 去重。
- [ ]  `max_steps<=0` / 预算 `<=0` → 不检索（回归现有行为）。
- [ ]  LLM 充分性判定开关关闭时用启发式，开启时注入 stub 断言。
- [ ]  默认配置不触网、不崩溃。

## 9. 边界

### Always do

- ReAct 仅限 QA 节点内部，步数 / 预算 / 超时封顶。
- 证据累积去重；`basis` 回链真实来源；标注辅助初稿、非法律意见。
- 默认测试使用 fake，不触网。

### Ask first

- 是否启用 LLM 做证据充分性判定（增加调用成本）。
- 是否提高 `max_steps` / 预算上限做人工验收。
- 是否接入真实检索源。

### Never do

- 不让 LLM 决定全局 workflow 顺序。
- 不做无界 / 长程 ReAct。
- 不伪造检索来源、法条或现有技术。
- 不在 trace / 日志记录完整敏感正文或密钥。

## 10. 验收清单（Definition of Done）

- [ ]  QA 节点实现 bounded ReAct 循环并对四种收敛条件生效。
- [ ]  证据跨轮累积去重，`basis` 回链真实来源。
- [ ]  新增 react 配置项（`PAGENT_` 前缀、通用命名）。
- [ ]  `qa_react_step` / `qa_react_converged` trace 落地。
- [ ]  新增 / 更新测试全部通过，默认不触网。
- [ ]  `pytest && python -m compileall app tests` 通过。

## 11. 实施顺序（建议）

1. `config`：新增 react 通用配置项。
2. 先写 `test_qa_react_loop.py`（可断言循环与收敛）。
3. 改 `qa.py`：抽出 `_retrieve_loop`（检索 → 评估 → 改写 → 再检索 → 收敛）。
4. 证据累积去重工具函数 + 测试。
5. （可选）LLM 充分性判定 + prompt + 开关。
6. 回归：修正 `test_qa_node.py` 相邻断言，跑全量 `pytest` + `compileall`。