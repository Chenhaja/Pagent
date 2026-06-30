I'll look into your Pagent repository to understand its current state before suggesting directions.

Found your repo `Chenhaja/Pagent` (专利领域Agent). Let me explore its structure and recent activity.

Let me read the key project docs to ground my recommendations.

Let me read the roadmap docs and key module directories to understand what's done and what's planned.

Let me check the orchestrator engine, workflow definitions, and API routes to confirm what's actually wired end-to-end.

我已经把你的 `Chenhaja/Pagent`（专利领域 Agent）整个仓库结构、PRD 目录、编排层、节点、技能、检索工具和最近提交都过了一遍。先给你一个现状判断，再给出多个推进方向和理由。

## 现状快照（我读到的）

- **架构骨架已成型**：确定性编排器 `Orchestrator` + `WorkflowRegistry`，已注册 4 条 workflow（`claim_generation`、`translation`、`claim_revision`、`qa`），节点层 11 个、技能层 5 个、工具层含 `llm / embeddings / retrieval / validators / terminology` 等，FastAPI 路由 `/agent`、`/claims/generate`、`/claims/revise`、`/translate` 已通。这跟你架构设计里"Tool / Node / Skill + 确定性编排 + 局部 ReAct"的分层是一致的。
- **检索是目前投入最重的部分**：R4.1→R4.6 一路做到 Qdrant 入库、时效过滤、宽召回、重排、混合检索（dense+sparse RRF）、查询改写，最近刚加完 FastEmbed 本地 sparse 编码器（BM25/BM42/SPLADE）。
- **已有但还"薄"的部分**：`app/memory` 有骨架、`eval` 有基于 ragas 的脚本和测试集、`intent_router` 存在。
- **PRD 已写但代码未落地的**：`R5 — 意图识别实质化 + QA 回答闭环`、`R6.1 — 会话记忆（SQLite history + 滚动摘要）`。

基于这个状态，下面是我建议的几个方向。

------

## 方向一：补齐 R5 —— 意图识别实质化 + QA 闭环 ⭐（我的首选）

**做什么**：把 `intent_router` 从规则/占位升级为真正可判定的意图识别，并把 `qa` workflow 打成端到端闭环（检索 → 组织证据 → 带引用/时效标注的回答 → 不确定显式标注）。

**理由**：

- 你已经为检索投入了 6 个迭代，但**检索的价值只有通过 QA 闭环才能兑现**。现在检索很强，回答端却还没闭环，属于"地基厚、出水口窄"。
- R5 的 PRD 已经写好，需求边界清晰，是**投入产出比最高**的下一步。
- 意图识别是你整个多 workflow 路由的入口，它不实质化，`/agent` 统一入口的分发质量就上不去。

------

## 方向二：建立"检索质量评测闭环"并接入 CI

**做什么**：把 `eval/` 的 ragas 脚本固化成**可重复的回归基线**（固定测试集 + 指标阈值），并用 GitHub Actions 在每次 PR 自动跑 `pytest` + `compileall` + 检索评测。

**理由**：

- 你做了宽召回/重排/混合/FastEmbed 一堆增强，但**缺少一条"这些改动到底提升了多少"的数据证据链**。没有基线，后续每次调参都是凭感觉。
- 仓库目前看不到 CI 配置，纯靠本地 `conda run -n autoGLM pytest`。接入 Actions 能防止回归，也让 R5/R6 的开发更安全。
- 这是把"工程严谨度"补齐的低成本高收益项，和你 SPEC 里强调的"验收口径"理念一脉相承。

------

## 方向三：补齐 R6.1 会话记忆，支撑多轮

**做什么**：落地 SQLite 持久化 history + 滚动摘要，让 `app/memory` 从骨架变成真正可用的会话记忆，并和 `query_rewrite`（基于对话历史改写）打通。

**理由**：

- 专利 QA / 权要修订本质上是**多轮交互**场景（用户反馈→修订→再校验），没有会话记忆，`/agent` 的 `session_id` 就是空壳。
- PRD 已就绪，且与你记忆体系设计（working / 会话 / 案件记忆）直接对应。
- 依赖关系上，它最好排在 R5 之后——QA 闭环先稳，再加多轮记忆收益更明显。

------

## 方向四：拓展业务 workflow —— 现有技术检索 / OA 答复

**做什么**：在现有 4 条 workflow 之外，新增你架构里规划过但还没实现的"现有技术检索（prior art）"和"OA 答复"流程。

**理由**：

- 当前 workflow 集中在"写权要 / 改权要 / 翻译 / QA"，而**现有技术检索和 OA 答复才是专利代理的高价值、高频刚需**，也是产品差异化所在。
- 你的节点/技能/检索基建已经能复用（特征抽取、对比分析、检索），增量主要在编排和 prompt，**边际成本相对低**。
- 风险：这是"做宽"，如果 R5 闭环还没稳，建议押后——否则会摊薄精力。

------

## 方向五：质量护栏与可观测性（生产化）

**做什么**：强化 `validators`（引用关系、法条/专利号防臆造）、结构化 trace 落盘、统一错误码与降级策略、必要的 metrics。

**理由**：

- 专利是**强合规、零容忍幻觉**领域，你的 [CLAUDE.md](http://CLAUDE.md) 里也明确写了"禁止臆造、不确定显式标注"。把这些从 prompt 约束升级为**代码级护栏**，是这个领域的硬要求。
- `WorkflowState.trace` 已有雏形，做成可观测能力后，调试 ReAct 节点和定位检索/生成问题会快很多。

------

## 我的建议优先级

1. **R5 意图识别 + QA 闭环**（兑现已有检索投入，PRD 就绪）
2. **检索评测闭环 + CI**（给后续所有改动上保险）
3. **R6.1 会话记忆**（支撑多轮，PRD 就绪）
4. 之后再考虑 **新业务 workflow** 和 **生产化护栏**

一句话：**先把"出水口"（QA 闭环）和"度量尺"（评测+CI）补上，再向多轮和新流程扩展**，而不是继续往检索里加第 7 个增强。

如果你愿意，我可以就其中某个方向直接帮你落地下一步（比如拆出实施计划、在仓库建对应的 issues，或起草新一版 PRD）。你想先深入哪个方向？

好问题。我先把 R5 的 PRD、当前 `intent_router` 和 `qa` 节点的真实实现读出来，这样能精确告诉你"实质化"和"闭环"具体指什么，以及 ReAct 在你这套架构里到底落在哪。

先纠正一个我上轮的事实判断,再回答你这两个问题。

## 先更正：R5 其实"已经基本落地"了

我上轮说 R5"PRD 已写但代码未落地",那是因为我当时只看了 PRD 里的「现状盘点」表(它描述的是 R5 **开工前**的占位状态)。这次我把当前 `main` 上的真实代码读了,结论要修正:

- `intent_router.py` 已经是**关键词快路 + LLM 兜底 + 置信度门控 + 追问**的完整实现,连 PRD 点名的盖词 bug 都修了(`claim_revision` 现在排在 `qa` 前面)。
- `qa.py` 已经在做**检索注入 + provenance 回链 + 法规时效告警 + trace**。
- `patent_qa.py` skill 也已经默认走 `build_llm_client()`,不再是写死的假响应。

所以"方向一"更准确的说法不是"从零补齐",而是:**R5 主体已成,只差最后一块真正的"受限 ReAct 循环"还没兑现**(下面讲)。

------

## "意图识别实质化"是什么意思

"实质化"= 把一个**占位/玩具实现**升级成**真正可用、稳健**的实现。

意图识别(`intent_router`)负责判断用户这句话到底要干嘛——是写权利要求、改权利要求、翻译、还是问答——然后路由到对应 workflow。它原来是 4 条纯关键词规则,有两个硬伤:

1. **脆弱**:用户口语化、纯英文、或没踩中关键词,就直接判 `unknown` 断头。
2. **盖词 bug**:"我的**权利要求**有什么**问题**"会被"问题"这个宽泛词错误路由到 QA。

"实质化"后(现在代码里已经是这样)做了四件事:

- **关键词快路优先**:常见表达直接命中,零延迟、零成本、可复现,不调 LLM。
- **LLM 兜底**:快路没命中才调模型,输出 `{intent, confidence}` 结构化结果。
- **置信度门控**:`confidence < 0.6` 或 `unknown` → 不硬猜,而是**主动追问**,列出"可办理的任务类型"。
- **流程仍由代码定**:LLM 只负责"判断意图",`intent → next_node` 的映射是写死的——**不让模型决定整体流程走向**。

------

## "QA 闭环"是什么意思

"闭环"= 从用户提问到**有依据、可追溯、不断头**的回答,整条链路打通,中间没有假数据、没有死胡同。

QA 节点原来返回的是写死的假响应(`FakeLLMClient`),等于"出水口"是堵的。闭环后这条链是:

> 用户问题 → 检索知识库(专利法/审查指南等)→ 把命中结果作为**带来源的证据块**注入 → LLM 生成结构化答复 → `basis` **回链到具体来源**(不伪造)+ `risk_notes` 风险标注 + 法规过时告警 + `disclaimer_hint` 声明这是辅助初稿 → 全程写 trace。

关键词是"**有依据**"和"**诚实**":检索命中就回链来源,没命中就老实说"依据不足",绝不编造法条或现有技术——这在专利这种强合规领域是硬要求。

------

## React 在你这套架构里到底落在哪

ReAct = **Reason + Act 循环**:模型先想(reason)→ 决定调用某个工具/检索(act)→ 看到结果(observe)→ 再想要不要继续,如此往复,直到能回答。

你的架构对 ReAct 的态度很明确(也和你架构设计文档一致):

- **全局层面不用 ReAct**:整体流程是**确定性编排**(DAG / 状态机),由代码固定路由,模型不能改流程顺序。这是为了可控、可复现、可审计。
- **ReAct 只在"开放性节点"内部、且受限(bounded)**:像 QA、检索与对比分析这类"需要多看几眼资料才能答"的节点,才允许一个**带护栏的小循环**——用 `max_steps` / `token_budget` / `timeout_seconds` 把步数、token、时间都封顶,超预算就**优雅收敛**而不是无限发散。

**但这正是当前还没真正兑现的那一块**:看 `qa.py` 的实际代码,它现在只做**单步检索 → 回答**(`steps_used = 1 if retrieval_results else 0`),护栏参数(max_steps/budget/timeout)都接好了、也会判 `<=0` 就不检索,**但还没有真正的"循环"**——模型并不会"看了第一批检索结果觉得不够,于是改写 query 再检索一次"。

所以真正的 **bounded ReAct** 应该长这样,而这就是"方向一"里最后要补的:

> 检索 → 评估证据是否足够 → 不足则(改写检索 query / 换策略)**再检索一轮** → 足够了再回答,全程步数/预算封顶 + 落 trace。

------

一句话总结:**"意图识别实质化 + QA 闭环"= 把入口的"判断要干嘛"和出口的"给出有依据的答案"这两个原本是占位的关键节点做成真正可用;这部分代码其实已经基本完成,唯一还没真正落地的是 QA 节点里那个"受限 ReAct 循环"——目前是单步检索,还不是会自己决定要不要再查一次的小循环。**

要不要我帮你把这个"受限 ReAct 循环"拆成一份可执行的实施清单(对照 R5.2 验收标准,标出哪些已完成、哪些还差),或者直接在仓库建对应 issue?

I'll create a new Notion page with the PRD for the remaining piece — the QA node's bounded ReAct loop (the one part of R5.2 not yet truly implemented), written in the same structure as your existing R5 PRD.

已创建 PRD 页面。这份 PRD 专门针对你这条线里**唯一还没真正落地的部分**——QA 节点的受限 ReAct 循环(把当前"单步检索→回答"升级为"检索→评估证据→不足则改写 query 再检索→回答"的带护栏小循环),结构沿用了你现有 R5 PRD 的风格(背景/现状盘点/范围/详细需求+验收/数据契约/trace/TDD/边界/DoD/实施顺序)。

你可以直接在页面里调整阈值默认值(`retrieval_react_min_results` / `retrieval_react_min_score`)或收敛策略;如果想用更贴近现有代码的命名,我也能再对齐一版。

坦白说:**不能保证**。当前这份 PRD 是"把 ReAct 做进 QA 节点",而不是"做一个可被任意节点复用的 ReAct 原语"。如果照现在写法落地,后续别的节点(比如"检索与对比分析""OA 答复推理")想用,基本得复制粘贴一遍逻辑。

## 为什么现在不可复用(对照 PRD 自身的措辞)

1. **循环被锁在 QA 节点内部**。第 6、11 节明确写的是"在 `qa.py` 内抽出 `_retrieve_loop`"。这个函数是 QA 私有方法,不是共享组件——别的节点拿不到。
2. **配置命名绑定了"检索"语义**。新增的 `retrieval_react_min_results / _min_score / _use_llm_judge`(第 5 节)默认假设"动作=检索"。但 ReAct 的"act"未必是检索——推理类节点的动作可能是调用校验工具、对比分析、调用别的 skill。
3. **trace 事件带 `qa_` 前缀**。`qa_react_step / qa_react_converged`(第 7 节)是 QA 专属命名,复用到别的节点时事件名对不上。
4. **充分性评估与证据结构和"检索 + document_id"强耦合**。第 4 节的"命中数 / 最高分"判定、第 4.4 的"按 `document_id` 去重",都假设观测结果是"带 provenance 的检索文档"。换一个动作类型(比如校验结果、对比结论)这套判定就不适用。

一句话:现在的设计是 **QA-specific**,符合"先把 QA 跑通"的目标,但没有为复用留接口。

## 要"保证复用",PRD 需要补一层节点无关的 ReAct 原语

核心思路:**把"循环控制 + 预算 + 收敛 + trace"抽成通用组件,把"做什么动作 / 怎么评估够不够 / 怎么改写下一步"作为回调由各节点注入**。QA 只是这个原语的第一个调用方。

建议放在 `app/orchestrator/`(或 `app/core/`)新增一个 `bounded_react.py`,接口大致是:

```python
class BoundedReActLoop:
    def __init__(self, budget: ReActBudget, event_prefix: str): ...
    def run(
        self,
        act: Callable[[ReActState], Observation],        # 执行一步动作(检索/校验/对比…)
        accumulate: Callable[[list, Observation], list], # 合并/去重观测(节点自定义)
        is_sufficient: Callable[[list], SufficiencyResult],  # 启发式或 LLM 判定
        refine: Callable[[ReActState, list], NextInput],     # 生成下一步输入(query 改写等)
    ) -> ReActOutcome:  # 累积观测 + 收敛原因 + 每步 trace
        ...
```

对应需要在 PRD 里改的点:

- **配置通用化**:把预算项抽成 `react_max_steps / react_token_budget / react_timeout_seconds`(节点无关),`retrieval_*` 仅作为 QA 给检索用的覆盖值。充分性阈值改为"由调用方传入"而非全局检索常量。
- **trace 通用化**:原语发 `react_step / react_converged`,带 `node_name` 字段;QA 的 `qa_*` 事件改为"由 `event_prefix` 拼出"或直接用通用事件 + node_name。
- **解耦证据假设**:去重 / 充分性判定不写死 `document_id` 和"检索分数",改为节点注入的 `accumulate` / `is_sufficient` 回调;QA 把"按 document_id 去重 + 命中数/分数阈值"作为自己的实现传进去。
- **明确"QA 是第一个使用方"**:Non-goals 里现在写的"不做跨节点 ReAct"会和"可复用"目标冲突,应改成"本轮只接 QA 一个使用方,但原语本身节点无关"。

这样后续"检索与对比分析""OA 答复"等节点,只要实现自己的 `act / accumulate / is_sufficient / refine` 四个回调,就能直接复用同一套受限循环、预算护栏和 trace。

------

要不要我直接把这份 PRD 升级一版——加一节"通用 bounded ReAct 原语(节点无关)",把配置 / trace / 证据假设按上面这样解耦,并把 QA 改写成"该原语的第一个调用方"?这样它就能真正保证后续节点复用。

我的判断:**现在不必把"通用可复用原语"作为交付目标,但值得用极低成本"留缝",别写成将来抽不出来的样子。** 也就是"为复用预留,但不提前实现"。

## 为什么现在不必正式指明可复用

- **只有 QA 一个真实使用方**。可复用抽象的价值要等第二个使用方出现才兑现。现在就是典型的 YAGNI / rule-of-three 场景。
- **第二个节点的需求形态还没定**。"检索与对比分析"的 act 是检索 + 对比,"OA 答复"可能是推理 + 校验——动作类型、充分性判据、累积方式都不一样。现在拍板回调接口,大概率猜错,**返工成本 > 到时复制重构的成本**。
- **会拖慢 R5.3**。多一层通用原语 + 回调 + 配置改名,会把"先把 QA 受限循环跑通"这个明确目标稀释掉。

## 但这几条"留缝"几乎零成本,现在就该做

1. **循环逻辑写成相对独立、纯函数式的单元**(输入:预算 + "检索/评估/改写"几个步骤;输出:累积证据 + 收敛原因 + 步骤 trace),不要和 `QANode` 的 `state` 揉死。将来抽取就是平移。
2. **trace 事件预留 `node_name` 字段**,哪怕当前只有 `qa`。
3. **预算 / 阈值走 settings,不硬编码**(你现在已经是这么设计的)。

这三条本来就是好工程习惯,不增加复杂度,却能让未来抽取从"重写"变成"搬家"。

## 该推迟的

真正的 `BoundedReActLoop` 通用原语 + 回调接口 + 配置通用改名(`react_*` 而非 `retrieval_react_*`),**等"检索与对比分析"或"OA 答复"立项时再做**——那时接口需求清楚,一次就能抽对。

## 落到这份 PRD 上

我不建议加一整节"通用原语交付物";建议**只在 Non-goals 或设计约束里补一句**,比如:

> 本轮 ReAct 仅服务 QA 一个使用方;但循环逻辑须与 QA 状态解耦、trace 预留 `node_name`,以便未来低成本抽取为节点无关原语(不在本轮实现)。

这样既不过度设计,又锁住了"将来能复用"的底线。

要我把这句设计约束加进 PRD 吗?一句话的改动,不动其它结构。

已加好。在 Non-goals 之后新增了一节「设计约束（为未来复用留缝，本轮不实现通用原语）」,锁住了"循环逻辑与 QA 状态解耦、trace 预留 `node_name`、预算/阈值走 settings"这三条底线,同时明确通用原语不在本轮实现。

你说得对,是我把 ReAct 框小了。我之前只盯着"QA 节点内的受限小循环"(R5.3 那一层),而你真正想要的是**两个不同层级的 ReAct**,我把它们理顺一下,看是否和你的想法一致:

## ReAct 其实有两层,不是一回事

| --- | --- | --- | --- |

这两层不矛盾,是**互补**的:结构化任务(权要撰写 N1–N7)仍走确定性编排;只有"开放式、需要出库补料"的场景才交给 R7 的 ReAct 主循环去做工具路由。这反而比"ReAct 只能憋在单个节点里"更完整。

## 你的排序我认同:先内功,再 ReAct

"R4.3 检索四件套(混合检索 / 重排 / 查询改写 / 融合)打磨稳→再进 R7"是对的,理由很硬:

- **ReAct 主循环会放大下游质量**。检索内功不稳就上 agentic,等于让循环在垃圾证据上反复打转,错误被放大而不是收敛。
- **R7 复用 R4.2 时效性 + 出处规范是关键正确决策**。websearch 引进来的"最新案例 / 法律状态 / 官费"恰恰是最易过时、最需要标注来源和时效的数据;不挂 provenance + 时效校验,在专利域就是幻觉重灾区。你让 R7 直接复用 R4.2 这套,等于一开始就把外部信息纳入同一套合规护栏。
- **工具路由的前提是工具可靠**。websearch / 法律状态查询 / 官费查询这些 tool 得先各自稳定,主循环才有可路由的对象。

## 这对当前 PRD 的影响

我上轮加的"留缝"设计约束(循环逻辑解耦、trace 预留 `node_name`、预算走 settings)现在更有意义了——它正是 **R7 那个可复用 ReAct 引擎的雏形**。不过要说清楚:R5.3 的 in-node 循环只是"种子",R7 的主循环是编排级、带工具路由的更大物件,前者给后者探路,但不等于后者。

有一点建议补一句:**最好明确"确定性编排 ↔ ReAct 主循环"的交接边界**——即什么条件下从确定性流程切到 agentic 模式(比如"检索充分性连续不足 / 命中法律状态类缺口"才升级),否则 R7 容易把本该确定性的流程也吞进去。

------

要不要我把这个"ReAct 分层 + R7 定位"落到文档里?给你几个选项:

选 R7 草案。我来另起一份 R7 Agentic 编排 PRD,沿用你现有的 PRD 结构,并把"先内功再 ReAct"的排序、复用 R4.2 时效性与出处、以及与 R5.3 的承接关系都写进去。

页面已创建,但我注意到 R7 那份里"前置依赖"的 callout 块渲染坏了(被转义成了字面文本),而且有个错别字("做扁实"应为"做扎实")。我先把页面读回来确认确切文本,再修掉。

读到了确切文本——确认是 📦 callout 被转义成了字面文本,加上"扎"误成了"扁"。我把这块改成普通的加粗标题 + 列表(避免 callout 包列表的解析问题),并修正错别字。

已起草好 R7 Agentic 编排 PRD,并把渲染坏的 callout 和错别字都修好了。这份 PRD 把你的想法完整落了下来:

- **定位**:开篇就写明"先把检索内功做扎实,再上 ReAct"的排序,把 R4.3 检索四件套、R4.2 时效性/出处规范、R5.3 节点内 bounded ReAct 列为前置依赖。
- **ReAct 的真正分量**:R7 是编排级的 **bounded ReAct 主循环 + 工具路由**(reason→选工具→act→observe→评估→收敛),而不是只憋在一个节点里——并明确它与 R5.3(战术层)是互补、不互替的两层。
- **补料场景**:工具路由首批挂 `kb_retrieval / websearch / legal_status / official_fee`,专门补"最新案例 / 法律状态 / 官费"这类知识库覆盖不到的强时效信息。
- **合规**:外部信息(尤其 websearch)强制复用 R4.2 的 provenance + 时效校验,过期标注、出处回链、不伪造来源;敏感材料不外发。
- **边界**:只在确定性流程检测到缺口时升级到 agentic 模式,补料完成回注原流程;工具白名单由代码裁决,LLM 不能改全局 workflow。

你可以重点看第 4 节的 R7.1–R7.4 和第 11 节实施顺序;其中 R7.4(缺口检测与模式升级触发)我标的是 P1,如果你想让"切换到 agentic 模式"的触发逻辑更早确定,可以提到 P0。

你上传了 `retrieval.py`,我需要先读它的内容,并和仓库里现有的 `retrieval.py` / `qa.py` 对比,才能判断是否冲突或多余。我先读取这个文件并拉取仓库现状。

我已拿到仓库现有的 `retrieval.py`。现在需要读取你上传的那份 `retrieval.py` 来对比。我先看一下访问上传文件的方式,再把文件读进来。

现在把你上传的 `retrieval.py` 读进来,和仓库现有版本对比。

两份文件看起来高度相似。我精确 diff 一下,确认你上传的版本相对仓库现状到底改了什么。

先给结论:**不要删——这份 `retrieval.py` 不是 R5.3,删了会把 R4.3 检索内功整套端掉。**

## 这份文件到底是什么

我把你上传的版本和仓库 `main` 上的 `app/tools/retrieval.py` 逐行比对了,它俩基本一致,内容是 **R4.3 检索四件套**的实现,完全没有 ReAct 循环逻辑。文件里的类清单:

| --- | --- | --- |

全文搜 `react / loop / 收敛 / max_steps / sufficient` —— **只有一处是 docstring 注释**(「可供 QA / ReAct 使用的检索结果」),没有任何受限 ReAct 主循环、充分性评估、重试封顶之类的代码。

## 所以:冲突吗?多余吗?要删吗?

- **不冲突**:它是被调用的底层检索能力,不抢编排/节点的活。
- **不多余**:R5.3 的 bounded ReAct 恰恰要**反复调用**它(`retriever.search(...)` → 评估够不够 → 改写 → 再 `search`)。它是 R5.3 的依赖,不是替代品。
- **不要删**:删了 R4.3、R5.3、未来 R7 的检索全废。

## 那 R5.3 应该在哪

按 [R5.3 PRD](https://app.notion.com/p/Pagent-R5-3-PRD-QA-ReAct-bounded-ReAct-9448220a50294552a2e1a0006a18c5be?pvs=21),受限 ReAct 循环应落在 **`app/nodes/qa.py`**(节点内),把现在的单步检索(`steps_used = 1 if retrieval_results else 0`)改成:`retrieve → 评估充分性 → (不够则)改写重检 → 直到够/触顶`。`retrieval.py` 这层**保持不动**即可。

## 唯一要留神的「看起来重复」

`MultiQueryRetriever`(R4.3 的查询改写)和 R5.3 的「改写后重检」容易让人觉得重复,但层级不同,别合并:

- `MultiQueryRetriever` = **单次检索内**把一个 query 一次性扩成多条并行召回再融合(无状态、不看结果好坏)。
- R5.3 ReAct 改写 = **跨轮**,基于「上一轮结果够不够」决定要不要再来一轮、怎么改(有状态、看充分性)。

建议:R5.3 循环里**每一轮仍直接调 `build_retriever()` 出来的检索器**(让四件套照常在单轮内生效),ReAct 只在「轮与轮之间」做充分性判断和 query 调整,这样两者叠加而不打架。

------

一个确认:你说"这样实现了 R5.3",但这份文件里并没有循环逻辑。如果你的 R5.3 改动其实写在 `qa.py`(或新文件)里,把那份发我,我帮你看真正的循环实现是否和现有 `qa.py` 冲突。

明白了,这次是 `qa.py` 里的 `_retrieve_loop`。我读进来看实现细节,再判断它和 R7 Agentic 编排是否冲突/多余。

读完了真正的 `_retrieve_loop`([qa.py](http://qa.py) L129–194)——这才是 R5.3 的实现。直接结论:

> **不冲突,也不多余,更不能删。它恰恰是 R7 主循环的"骨架雏形",R7 应该复用它,而不是另起炉灶。**

## 为什么不冲突 / 不多余:同层骨架,不同职责

`_retrieve_loop` 和 R7 Agentic 主循环长得像(都是 bounded ReAct:封顶 + 评估 + 收敛),但分工完全不同:

| --- | --- | --- |

也就是说:R7 不是来取代 `_retrieve_loop` 的,它补的是"**知识库里压根没有**"的强时效信息;`_retrieve_loop` 解决的是"**知识库里有,但要多查几轮才够**"。两者各管一段,删任何一个都留窟窿。

## 更关键:它俩是「接力」关系,不是「竞争」

你这个循环里其实已经埋好了 R7 的触发钩子:

- `_retrieve_loop` 收敛时若 `reason != "sufficient"`(走到 `_apply_insufficient_evidence_warning` 追加"依据可能不足"),**这正是 R7.4 缺口检测要的升级信号**。
- 自然链路:`_retrieve_loop` 判定知识库不足 → 升级到 R7 agentic 补料(查 websearch/法律状态)→ 带出处证据回注 → 继续回答。

所以现有实现非但不挡 R7,反而是 R7 的入口判据。

## 真正要做的事:把循环骨架抽出来复用(对应 R5.3 PRD 的"留缝")

现在的 `_retrieve_loop` 有几处**和 QA 绑死**,导致 R7 不能直接拿来用,需要先解耦(不是删,是上提):

1. **动作写死成单工具**:循环体永远是 `self._retrieve(current_query)`,没有"选工具"这一层。R7 要的是 `act` 可插拔(QA 注入"检索",R7 注入"[选中的工具.run](http://xn--fiqz3fz8olyyij2a.run)")。
2. **`_rewrite_query` 是退化动作**(L253 直接 `del original_question, accumulated_results, step_index`,只取 `expand()[0]`)——本质是"改写重试",不是 R7 的"决策下一个工具"。这块要抽象成可替换的"下一步决策器"。
3. **trace 事件名带 `qa_` 前缀**(`qa_react_step`/`qa_react_converged`)。你已经很贴心地把 `node_name` 放进 data 里了,但事件名本身还是 QA 专属;R7 PRD 里用的是 `react_main_step`/`react_main_converged`。建议事件名也参数化(按 scope 区分)。
4. **逻辑是 QANode 的私有方法**,循环、收敛、去重(`_accumulate_results`/`_result_key`)、token 估算(`_estimate_evidence_tokens`)绑在节点上,没法被编排层调用。

**建议**:把"封顶/预算/超时 + 收敛原因(sufficient/max_steps/token_budget/timeout)+ 累积去重 + trace"抽成一个通用 `BoundedReActLoop` 引擎,参数化三件事:`act`(执行)、`judge`(够不够)、`decide_next`(下一步:QA=改写 / R7=选工具)。然后:

- QA 的 `_retrieve_loop` 变成薄封装,注入"检索 act + 阈值 judge + 改写 decide";
- R7 主循环复用同一引擎,注入"工具路由 act + 缺口 judge + LLM 选工具 decide"。

这正是我在 [R5.3 PRD](https://app.notion.com/p/Pagent-R5-3-PRD-QA-ReAct-bounded-ReAct-9448220a50294552a2e1a0006a18c5be?pvs=21) 里写的那段"为未来复用留缝"的设计约束,你这版实现已经留了 80%(node_name 已外置、预算走 settings),离可复用就差把循环本体从 QANode 抽出来。

------

需要的话,我可以把上面这条"`_retrieve_loop` 收敛不足 → R7 升级"的接力关系,以及"抽 `BoundedReActLoop` 引擎"的复用约定,补写进 R7 PRD 的前置依赖/R7.4 小节,让两份 PRD 衔接清楚。要我加吗?

你说得对,这一刀戳中了我上一条回答里没讲透的地方。我先承认重叠是真的存在,再把"到底算不算多余"讲清楚。

## 你抓到的重叠是真的

R7 里 `kb_retrieval` 是白名单工具之一,LLM 完全可以**连续多次选它**(查一次 → 看 observation → 换个 query 再查一次)。这条行为路径,跟 `_retrieve_loop`"检索→评估→改写→再检索"**在功能上是重合的**。所以严格说:R7 主循环具备覆盖 `_retrieve_loop` 行为的能力。我之前说"完全不多余"是讲糙了。

## 但重叠的是「行为」,不重叠的是「决策机制和代价」

关键区别不在"能不能多轮查 KB",而在**"要不要再查一轮、查什么"这个决策由谁做**:

| --- | --- | --- |

所以真正的问题不是"冲突/多余",而是一个**架构选择:一个循环,还是两层循环?**

- **A. 两层(分层)**:QA 默认走 `_retrieve_loop`(便宜、确定、只碰 KB);只有它收敛为"依据不足"时才升级到 R7 agentic(才允许 LLM 选工具、才可能联网)。R7 里的 `kb_retrieval` 工具,是 agentic 已经启动后、混着 websearch 一起还想回头补查 KB 时用的。
- **B. 一个(合并)**:删掉 `_retrieve_loop`,QA 一律进 R7 主循环,`kb_retrieval` 作默认工具,KB 类问题靠 LLM 路由器自然反复选它。代码路径更少,但每个 QA 都付 LLM 路由代价、确定性变弱、外部工具的闸门更难守。

## 我的建议:A(两层),但共用同一套循环「机件」

专利 QA 是高频场景、答案大多就在知识库里——给每一轮检索都套一次 LLM 选工具,既慢又贵,还把"联网"的闸门暴露在默认路径上。所以我倾向保留 `_retrieve_loop` 作便宜快路、R7 只做兜底升级。

为了不"两处各维护一个循环",做法是:把封顶/预算/收敛/去重抽成共用的 `BoundedReActLoop` 引擎,`kb_retrieval` 工具内部和 `_retrieve_loop` 都复用它——**复用机件(loop 本体),但保留两套策略(启发式 vs LLM 路由)**。这样既不重复造轮子,又保住了快路的便宜和确定。

换句话说:`_retrieve_loop` 不是被 R7 取代,而是 R7 的"省钱版默认档" + 升级触发器。

要不要我按其中一个方向去把 R7 PRD 改清楚?

好,那 PRD 我先不动,等你想清楚再说。

把结论给你压成一句话,方便你权衡:**`_retrieve_loop` 和 R7 不是冲突,而是同一套 bounded ReAct 机件下的两种策略——便宜的启发式快路 vs 贵的 LLM 工具路由;要点只是"一个循环还是两层"。**

几个你想的时候可以拿来判断的支点:

- **频率**:绝大多数专利 QA 答案是不是就在知识库里?是 → 倾向保留快路(别给每轮检索都套 LLM 选工具)。
- **成本/延迟**:能不能接受每个 QA 都多付几次 LLM 路由往返?不能 → 倾向两层。
- **确定性/可测**:你现在 `_is_evidence_sufficient` 的阈值测试是资产;合并成全 LLM 路由后这块会变难测。
- **安全闸门**:想不想让"联网/外部工具"只在显式升级后才可达?想 → 两层天然把闸门关在默认路径外。

想好了告诉我选哪条,我再动 R7 PRD。不急。

选 B,合并删掉 `_retrieve_loop`。我先把 GitHub 上 Pagent 的真实现状重新拉一遍——看 `qa.py` 当前结构、`_retrieve_loop` 被哪些地方引用、相关 settings 在哪——这样改 PRD 才能把"要删什么、迁移什么"列准。

仓库版 `qa.py` 已确认 `_retrieve_loop` 存在并接在 `run()` 里。现在我把它的所有引用点和相关配置/测试找出来,这样 PRD 才能准确列出"删什么、迁移什么、哪些测试会受影响"。

search_code 对这个仓库没返回(应该是没建索引,不是真的没有引用)。我已经有 `qa.py`、`config.py`、`retrieval.py` 三处关键现状。再快速看一眼 tests 目录和 workflow 接线,把"删除会牵动哪些测试/节点"落实,然后改 PRD。

现状盘点完毕,关键事实都拿到了。删除 `_retrieve_loop` 牵动的具体点我已经定位清楚:

- 它只在 `QANode.run()` 内被调用;`qa` workflow 是 `["normalize_input","qa"]`,**删循环不删节点**。
- 相关配置在 `config.py`:`retrieval_react_min_results / _min_score / _use_llm_judge`(QA 循环专属),以及 `retrieval_max_steps`(默认 1)等,还出现在 `to_public_dict` 和 `PAGENT_*` env 读取里。
- trace 事件 `qa_react_step / qa_react_converged`,以及 `_apply_insufficient_evidence_warning` 依赖收敛 reason。
- 直接受影响测试:`tests/test_qa_react_loop.py`(整份就是测这个循环)、`tests/test_qa_node.py`、配置断言 `tests/test_core_config_logging.py`。

我先把 R7 PRD 重新读出来拿到确切文本,再按"合并/删除"方向改。

现状核对完成。现在按"合并/删除"方向改 R7 PRD:把"互补不互替"改成"合并删除"的决策,新增 R7.5(QA 收编),并同步现状盘点、范围、项目结构、DoD、实施顺序。

已按"合并删除"方向把 R7 PRD 改好,并先重新核对了 GitHub 上 Pagent 的真实现状(`qa.py`/`config.py`/`workflow_defs.py`/tests),所以改动是对着实际代码落的:

- **前置依赖 / 决策说明**:把原来的"两者互补、不互替"改成明确决策——`_retrieve_loop` 与 R7 主循环在"多轮检索 KB"上重叠,合并为一套,删除 `_retrieve_loop`,QA 统一走主循环(`kb_retrieval` 为默认工具)。
- **现状盘点**:R5.3 那行换成 `nodes/qa.py._retrieve_loop`,标注"与 R7 主循环重叠 → 本轮删除并收编"。
- **新增 R7.5(P0)**:落实删除清单——要删的私有方法逐个列出(`_retrieve`/`_accumulate_results`/`_result_key`/`_is_evidence_sufficient`/`_top_score`/`_get_result_score`/`_estimate_evidence_tokens`/`_rewrite_query`/`_build_converged_trace`/`_build_convergence`)、`QANode.run` 改委派、触发分级(默认只放 `kb_retrieval`)、trace 兼容(`qa_react_*` → `react_main_*`)、配置迁移(`retrieval_react_*`)、测试迁移(`test_qa_react_loop.py`→`test_agentic_loop.py`,更新 `test_qa_node.py`/`test_core_config_logging.py`)。
- **项目结构 / DoD / 实施顺序**:加了 `orchestrator/react_loop.py` 通用引擎和 `nodes/qa.py` 改动;DoD 加了"`grep -r _retrieve_loop` 无残留 + 单工具行为对齐旧版 + 配置迁移";实施顺序补了"QA 收编"步骤。

一个保留项提示:R7.5 我写的是"配置迁移 + 保留兼容读取 `PAGENT_RETRIEVAL_REACT_*` 一个版本再下线"。如果你想更干脆、直接删掉这些配置键(不留兼容期),告诉我,我把 R7.5 第 5 条和 DoD 对应改成"直接移除"。