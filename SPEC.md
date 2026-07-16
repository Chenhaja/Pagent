# 通用 LangChain Agent 与 Policy File Tools 规格

## 1. Objective

### 1.1 背景

当前项目中 `LangChainDraftingAgent` 与 `LangChainInputParserAgent` 存在职责重复：各自维护 Agent 调用、工具构建、权限边界和业务身份，导致新增 node/agent 时容易继续复制 `_build_tools` 模式，泛化能力不足。

本阶段目标是收敛为一个通用 LangChain Agent 运行器，并配套一组可复用的通用 file tools。业务差异不再通过不同 Agent 类表达，而是通过每个 node/agent 显式传入的参数表达：`node_name`、prompt、`allowed_tools`、file policy 等。

### 1.2 目标用户

- Pagent node/agent 开发者：需要用同一个 Agent 运行器接入不同业务 prompt 和工具权限。
- drafting workflow 维护者：需要迁移 `LangChainDraftingAgent` 相关能力，避免业务 Agent 类继续分叉。
- input parser 维护者：需要迁移 `LangChainInputParserAgent` 相关能力，并保持现有解析能力和权限边界。
- 安全与回归测试维护者：需要验证通用 file tools 在 policy 约束下不会放宽读写权限。

### 1.3 目标

- 删除 `LangChainDraftingAgent` 与 `LangChainInputParserAgent`，不保留只是换名字的业务 Agent 类或命名工厂。
- 新增或改造一个通用 LangChain Agent 运行器，由调用方传入：
  - `node_name` / `agent_name` 等业务身份字段；
  - prompt 或 prompt name；
  - `allowed_tools`；
  - file policy；
  - model、trace、workspace 等当前运行所需上下文。
- 用 `allowed_tools` 取代各业务 Agent 内部 `_build_tools`。
- 建立一组通用 file tools，至少覆盖本阶段已有 Agent 需要的文件读写能力。
- 通用 Agent 在调用 LangChain `create_agent` 前，根据 `allowed_tools` 筛选可用工具，并将 file policy 包装进工具执行链路，确保 policy 在工具真正访问文件系统前生效。
- policy 权限边界必须达到当前或更严格，不能因为通用化而放宽。
- policy 设计可表达 shell/network 等能力，但本阶段只实现和验证文件读写权限；shell/network 相关能力默认禁止或仅保留字段，不接入真实工具。

### 1.4 验收标准

- 代码中不再存在可实例化使用的 `LangChainDraftingAgent` / `LangChainInputParserAgent` 业务 Agent 类。
- 调用侧改为使用通用 Agent 运行器，并通过参数传入业务身份、prompt、`allowed_tools` 和 file policy。
- `allowed_tools` 能限制传入 `create_agent` 的工具集合；未声明的工具不会被模型看到，也不能被执行。
- file policy 能在通用 file tool 执行前拦截越权读写。
- 未显式配置写权限时，默认禁止写入。
- deny 规则优先于 allow 规则。
- 相关单元测试覆盖 allow/deny/read/write/default deny，不要求增加现有 drafting/input parser 流程集成回归。

### 1.5 非目标

- 不实现完整 shell/network 工具或联网权限系统。
- 不保留只是换名字的业务 Agent 类、薄封装类或命名工厂。
- 不改变最终 API 输出字段语义。
- 不引入新的外部沙箱系统。
- 不新增依赖，除非后续用户明确确认。
- 不在 SPEC 阶段直接实现代码。

---

## 2. Commands

所有 Python / pytest / 编译命令必须使用 conda 环境 `autoGLM`：

```bash
# 通用 Agent / file policy 单元测试
conda run -n autoGLM pytest tests/test_langchain_agent_runner.py tests/test_file_tool_policy.py

# 受影响的现有 Agent 回归测试
conda run -n autoGLM pytest tests/test_input_parser_agent.py tests/test_workflow_trace_events.py

# 安全合规回归
conda run -n autoGLM pytest tests/test_security_compliance.py

# 编译检查
conda run -n autoGLM python -m compileall app tests

# 全量回归
conda run -n autoGLM pytest
```

约束：

- 默认测试不得触网，不得调用真实外部 LLM。
- 如新增依赖，必须先确认，并同步更新 `requirements.txt`。
- 优先复用当前 LangChain / `create_agent` / middleware trace 能力，不凭印象假设 API。
- 不执行 `git push`、`git reset --hard`、强制推送等危险操作，除非用户明确确认。
- 每完成一个可独立验证阶段，按项目规范单独 commit；提交前只添加相关文件。

---

## 3. Project Structure

目标结构应围绕“通用 Agent runner + 通用 file tools + policy layer + trace adapter”组织。

```text
pagent/
  app/
    tools/
      subagents/
        agent_runner.py          # 通用 LangChain create_agent 运行器
        file_tools.py            # 通用文件工具定义与注册
        file_policy.py           # 文件访问策略、路径匹配与校验
    tracing/
      langchain_trace.py         # 现有 LangChain trace adapter，继续复用
      workflow_trace.py          # 统一 trace schema 与脱敏摘要
  tests/
    test_langchain_agent_runner.py
    test_file_tool_policy.py
    test_input_parser_agent.py
    test_workflow_trace_events.py
```

实际文件名可结合现有结构调整，但职责边界必须保持清晰：

- Agent runner 只负责组装 `create_agent`、筛选/包装 tools、执行 prompt、接入 trace。
- File tools 只负责提供通用能力，如读取文件、写入文件、列目录、搜索文件等。
- File policy 只负责判断当前 agent/node 是否允许访问指定路径。
- 业务 node 只负责传入参数，不再通过业务 Agent 类自建工具集合。

### 3.1 通用 Agent 参数

通用 Agent 运行器至少应支持以下输入概念：

```python
agent = LangChainAgentRunner(
    node_name="drafting_parse_input",
    agent_name="input-parser",
    prompt=INPUT_PARSER_PROMPT,
    allowed_tools=["read_file", "write_file"],
    file_policy=FileToolPolicy(...),
    # model / middleware / trace emitter / workspace 等沿用现有上下文
)
```

要求：

- `node_name` / `agent_name` 用于日志、trace、policy 上下文和错误定位。
- `allowed_tools` 是当前 agent 可见工具白名单。
- 未出现在 `allowed_tools` 的工具不得传给 `create_agent`。
- file policy 应在工具执行函数内部或包装层执行，而不是只在 runner 初始化时检查。

### 3.2 通用 File Tools

通用 file tools 应通过稳定工具名注册，例如：

- `read_file`
- `write_file`
- `list_files`
- `search_files`

本阶段按现有需求最小化落地；如果现有迁移只需要读写，则可以先实现读写，并为列表/搜索保留设计边界。

要求：

- 工具本身不绑定 drafting/input-parser 等业务。
- 工具执行前必须调用 policy 校验。
- 工具输入路径必须归一化后再校验，避免 `../`、绝对路径、隐藏路径等绕过。
- 工具返回值应避免泄露过长正文、敏感路径或密钥内容；trace 中只能记录摘要。

### 3.3 File Policy 表达

推荐 policy 分两层：核心用前缀，细粒度用 glob。

```json
{
  "readRoots": ["docs/", "src/"],
  "writeRoots": ["outputs/"],
  "allowGlobs": ["docs/**/*.md", "src/**/*.ts"],
  "denyGlobs": ["**/.env", "**/secrets/**", "**/*.pem", "**/*.key"]
}
```

语义：

- `readRoots`：允许读取的路径前缀。
- `writeRoots`：允许写入的路径前缀。
- `allowGlobs`：更细粒度的允许规则，可进一步收窄或补充前缀规则。
- `denyGlobs`：拒绝规则，优先级最高。
- 未显式允许的读取默认拒绝。
- 未显式允许的写入默认拒绝。
- 写权限不能从读权限推导，必须显式配置 `writeRoots` 或等价允许规则。

建议判定顺序：

1. 归一化路径，并确认路径仍在 workspace/root 内。
2. 命中 `denyGlobs` 则拒绝。
3. 根据操作类型检查 `readRoots` 或 `writeRoots`。
4. 如配置了 `allowGlobs`，再检查 glob 细粒度规则。
5. 未命中允许规则则拒绝。

### 3.4 Policy 如何在 `create_agent` 中生效

policy 必须作用于传入 `create_agent` 的工具执行链路：

```text
node 参数
  -> 通用 Agent runner
  -> 根据 allowed_tools 选择通用工具
  -> 用 file_policy 包装 file tool callable
  -> create_agent(model, tools=wrapped_tools, ...)
  -> 模型选择工具
  -> wrapped tool 执行前校验 policy
  -> 允许后访问文件系统 / 拒绝则返回受控错误
```

要求：

- 不能只在 prompt 中告诉模型“不要访问某路径”。
- 不能只在 `allowed_tools` 层控制工具是否存在；具体路径必须由 policy 在执行前校验。
- policy 拒绝时应返回可诊断但不泄露敏感路径细节的错误信息，并记录脱敏 trace。

---

## 4. Code Style

- 优先最小化、局部化改动。
- 复用现有 helper、trace schema、workspace/path 工具、settings，不随意引入新抽象。
- 删除确定不再需要的业务 Agent 类，不保留无意义兼容壳。
- 日志、注释、docstring 使用中文风格。
- 新增公开类、公开函数、公开方法必须有中文 Google 风格 docstring。
- 工具名、policy 字段名保持稳定、可测试、可追踪。
- 业务 node 不内联构造复杂工具逻辑，只声明 `allowed_tools` 和 policy。
- 不为单个 node 新增临时全局配置项；新增配置必须保持通用作用域，并同步 `Settings`、环境变量读取、`to_public_dict()` 和测试。
- trace / 日志中不得记录完整 prompt、长正文、完整工具输入输出、API key、token、secret、password。

---

## 5. Testing Strategy

### 5.1 单元测试

`tests/test_file_tool_policy.py` 应覆盖：

- `readRoots` 允许读取指定前缀内文件。
- 未配置读取允许规则时默认拒绝读取。
- `writeRoots` 允许写入指定前缀内文件。
- 未配置写入允许规则时默认拒绝写入。
- `denyGlobs` 优先于 `readRoots` / `writeRoots`。
- `allowGlobs` 能提供细粒度匹配。
- `../`、绝对路径、隐藏/敏感文件路径不能绕过校验。
- `.env`、`secrets/`、`*.pem`、`*.key` 等默认敏感模式被拒绝，或能通过默认 deny policy 覆盖。

`tests/test_langchain_agent_runner.py` 应覆盖：

- `allowed_tools` 只把白名单工具传给 `create_agent`。
- 未声明工具无法被执行。
- file tool 被传入 `create_agent` 前已被 policy 包装。
- policy 拒绝时不会访问真实文件系统。
- `node_name` / `agent_name` 能进入 trace 上下文或错误上下文。

`tests/test_input_parser_agent.py` / 相关现有测试应调整为：

- 不再直接依赖 `LangChainInputParserAgent` 类。
- 验证 input parser node 使用通用 Agent runner 后行为保持等价。

如现有 drafting agent 测试存在，应调整为：

- 不再直接依赖 `LangChainDraftingAgent` 类。
- 验证 drafting node 通过参数传入 prompt、`allowed_tools`、file policy。

### 5.2 回归测试

本阶段必须至少运行：

```bash
conda run -n autoGLM pytest tests/test_langchain_agent_runner.py tests/test_file_tool_policy.py
conda run -n autoGLM pytest tests/test_input_parser_agent.py tests/test_workflow_trace_events.py
conda run -n autoGLM pytest tests/test_security_compliance.py
conda run -n autoGLM python -m compileall app tests
```

如改动影响 workflow 边界，再补跑相关 workflow 测试。

全量变更完成前运行：

```bash
conda run -n autoGLM pytest
```

### 5.3 测试替身要求

- 默认测试使用 fake model / fake agent / fake LangChain event source，不触网。
- 不通过 mock 掉 policy 校验来假装权限成功。
- 文件工具测试使用临时 workspace，不访问用户真实敏感路径。
- 越权路径测试应验证“未访问文件系统”这一点。
- 不要求新增 drafting/input parser 端到端集成回归。

---

## 6. Boundaries

### 6.1 Always

- 始终通过通用 Agent runner 调用 LangChain `create_agent`。
- 始终由 node/agent 参数传入业务身份、prompt、`allowed_tools` 和 file policy。
- 始终在工具执行前做 policy 校验。
- 始终让 `denyGlobs` 优先于 allow 规则。
- 始终默认禁止未显式允许的读写操作，尤其写操作。
- 始终保持权限边界不比当前更松。
- 始终保持默认测试离线可运行。
- 始终使用 `conda run -n autoGLM ...` 执行 Python / pytest / 编译命令。

### 6.2 Ask First

- 如果要新增依赖、升级 LangChain 或改变模型 SDK，必须先确认。
- 如果要改变最终 API 输出字段名称、结构或语义，必须先确认。
- 如果要引入真实 shell/network 工具或联网权限系统，必须先确认。
- 如果要引入独立沙箱、容器隔离或外部权限服务，必须先确认。
- 如果 policy 表达需要从前缀/glob 扩展到复杂 ACL、角色继承或动态规则，必须先确认。
- 如果要改 QA workflow、数据库、前端 UI 或外部服务调用，必须先确认。

### 6.3 Never

- 不保留只是换名字的业务 Agent 类或命名工厂。
- 不让模型通过 prompt 自律替代工具层 policy 校验。
- 不让 `allowed_tools` 替代路径级 policy 校验。
- 不在未显式配置写权限时允许写入。
- 不把完整交底书、附件正文、prompt 全文、完整工具输入输出写入 trace 或日志。
- 不硬编码密钥、凭证、API key。
- 不用不可信输入拼接 shell 命令或 SQL。
- 不执行 `git push`、`git reset --hard`、强制推送等危险操作，除非用户明确要求。
- 不在 SPEC 阶段直接开始实现。
