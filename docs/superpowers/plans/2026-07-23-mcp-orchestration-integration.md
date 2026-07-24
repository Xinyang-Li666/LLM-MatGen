# MCP、LLM 编排、Skill 与端到端集成实施计划

## 目标

把已完成的确定性服务通过单一 Tool Registry 暴露给 MCP 和可选内置 Provider。提供可复用 Skill 和九类自然语言演示，不把厂商消息格式渗透到核心代码。

## 文件映射

```text
llm_matgen/orchestration/__init__.py
llm_matgen/orchestration/models.py
llm_matgen/orchestration/tools.py
llm_matgen/orchestration/providers.py
llm_matgen/orchestration/runner.py
llm_matgen/orchestration/prompts.py
llm_matgen/mcp/__init__.py
llm_matgen/mcp/server.py
integrations/providers/anthropic.py
integrations/providers/openai.py
integrations/skills/llm-matgen/SKILL.md
docs/examples/natural-language-workflows.md
docs/mcp.md
docs/api.md
README.md
tests/test_orchestration/test_tools.py
tests/test_orchestration/test_runner.py
tests/test_orchestration/test_providers.py
tests/test_mcp/test_server.py
tests/test_integration/test_natural_language_workflows.py
```

## 内部协议

```python
class ToolCall(BaseModel):
    call_id: str
    name: str
    arguments: dict[str, JsonValue]

class ToolResult(BaseModel):
    call_id: str
    ok: bool
    summary: str
    structured_content: dict[str, JsonValue]
    artifact_refs: list[str]
    error_code: str | None = None

class ModelTurn(BaseModel):
    text: str | None
    tool_calls: list[ToolCall]
    finish_reason: str

class LLMProvider(Protocol):
    def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
    ) -> ModelTurn: ...

class WorkflowRunner:
    def ask(self, user_input: str) -> AgentResult: ...
```

## Task 1：Tool Registry 和 Schema

1. 写失败测试：九类 generate、search/download/properties、check/export、db query 工具名称唯一且顺序稳定。
2. 实现 `ToolDefinition(name, description, input_schema, output_schema, handler, mutates_files)`。
3. 从 Pydantic 参数模型生成 JSON Schema，禁止 `additionalProperties`。
4. 添加 Schema 与 handler 签名不一致、重复名称、无描述测试。
5. 提交：`feat: define deterministic tool registry`。

## Task 2：Tool 执行与 artifact 返回

1. 写失败测试：合法调用、未知工具、参数错误、handler error。
2. 实现 `ToolExecutor.call()`，把领域异常转换为稳定 error code。
3. 结构和文件内容不直接进入结果；只返回摘要、结构化统计、artifact/manifest 路径。
4. 路径必须位于配置 output root，结果中使用规范化相对路径。
5. 提交：`feat: execute tools with structured results`。

## Task 3：MCP Server 基础

1. 写 MCP initialize、tools/list、tools/call 合约失败测试。
2. 实现 stdio MCP Server，并从 Tool Registry 构造工具。
3. 工具列表顺序稳定，input/output schema 与 Registry 完全相同。
4. 添加协议版本不兼容、错误参数、handler 异常测试。
5. 提交：`feat: expose registry through mcp`。

## Task 4：MCP 资源和运行目录

1. 写 manifest/artifact 资源读取测试。
2. 只允许读取 output root 内、已登记在 manifest 的文件。
3. 添加 `..`、绝对路径、符号链接逃逸、未登记文件测试。
4. 大文件返回资源链接和元数据，不把完整内容作为 tool result。
5. 提交：`feat: expose safe generation artifacts`。

## Task 5：MCP CLI 与无厂商 SDK 安装

1. 写 `llm-matgen mcp --help` 和启动 smoke test。
2. 将 MCP 依赖置于 optional extra；未安装时错误信息给出 `pip install "llm-matgen[mcp]"`。
3. 在只安装 core+mcp、没有 anthropic/openai 的环境运行 tools/list。
4. 提交：`feat: add mcp server command`。

## Task 6：Provider 协议与 fake provider

1. 写 fake provider 的文本结束、单工具、多工具、provider error 测试。
2. 实现与厂商无关的 Message、ModelTurn、AgentResult。
3. Tool call ID 在整个运行中必须唯一；重复 ID 判为协议错误。
4. 提交：`feat: define provider-neutral model protocol`。

## Task 7：有界 WorkflowRunner

1. 写失败测试：正常两轮、达到 `max_turns`、同一失败调用循环、空响应。
2. 实现最大轮数、累计工具调用数、累计生成结构数限制。
3. 同一工具+规范化参数连续失败三次时终止并返回诊断。
4. 并行 tool calls 默认串行执行；只有显式 `read_only=True` 的工具允许并发。
5. 提交：`feat: run bounded llm tool workflows`。

## Task 8：Anthropic 适配器

1. 以 SDK 响应 fixture 写文本、tool use、tool result、API error 映射测试。
2. 在 `integrations/providers/anthropic.py` 实现延迟导入和消息归一化。
3. 无依赖、无 API Key、未知 stop reason 均给出明确错误。
4. 核心 `llm_matgen` 不 import Anthropic 类型。
5. 提交：`feat: add optional anthropic provider`。

## Task 9：OpenAI 适配器

1. 以 SDK 响应 fixture 写文本、tool call、多 tool call、API error 映射测试。
2. 实现延迟导入和与 Anthropic 相同的内部协议。
3. 运行 provider 参数化合约测试，断言两个适配器对相同语义输出同一 `ModelTurn` 形状。
4. 提交：`feat: add optional openai provider`。

## Task 10：ask/chat CLI

1. 写 provider/model 配置解析和 fake provider 端到端测试。
2. 实现 `ask` 单轮入口和 `chat` 会话入口。
3. 会话历史默认只存在当前进程；显式保存时写到 output root 并脱敏。
4. API Key 不进入日志、异常、history 或 manifest。
5. 提交：`feat: add provider-neutral natural language cli`。

## Task 11：系统提示词责任边界

1. 写提示词快照测试，断言包含：默认检查、默认 POSCAR、多格式、规模限制、责任声明。
2. 实现通用 prompt，不包含 Claude/OpenAI 专用语法。
3. Tool 描述明确 warning 不阻断、LAMMPS data 不含势函数。
4. 提交：`docs: define neutral generation prompt`。

## Task 12：创建 LLM-MatGen Skill

1. 编写 `integrations/skills/llm-matgen/SKILL.md`，只描述工具使用、九类参数和恢复流程。
2. 添加静态测试：frontmatter、工具名称与 Registry 一致、无 API Key、无厂商硬绑定。
3. Skill 示例覆盖本地输入、MP 输入、多格式导出和检查警告解释。
4. 提交：`feat: add optional llm-matgen skill`。

## Task 13：九类自然语言黄金工作流

1. 在 `docs/examples/natural-language-workflows.md` 为九类各写一条中文指令和预期工具序列。
2. 使用 scripted fake provider 执行九条工作流。
3. 断言每条都调用正确生成器、默认检查、导出和 manifest。
4. Interface 示例包含 film/substrate；随机类示例固定 seed。
5. 提交：`test: cover nine natural language workflows`。

## Task 14：两个接入面的兼容验收

1. 使用 MCP test client 执行 vacancy 和 interface 示例。
2. 分别使用 Anthropic、OpenAI 的 scripted response fixture 通过 WorkflowRunner 执行相同示例。
3. 比较三条路径的规范化参数、结构哈希、manifest 核心字段；模型文本不要求一致。
4. 为真实 API smoke test 添加显式标记和环境变量门控，默认测试套件不产生外部费用。
5. 确认生成器代码无 provider 条件分支。
6. 提交：`test: verify llm-independent orchestration`。

## Task 15：完整文档与最终测试

1. 完成 README：安装矩阵、core/MCP/provider extras、九类命令、责任边界。
2. 完成 `docs/api.md` 和 `docs/mcp.md`，列出公共签名、工具 Schema 和安全限制。
3. 在干净环境分别安装 core、core+mcp、all-llm，运行对应测试。
4. 运行 `pytest -q` 和全部九类 CLI smoke tests。
5. 搜索仓库，确认无明文 key、无未完成标记、无旧包名引用。
6. 提交：`docs: complete v0.1 integration guide`。

## 本计划完成条件

- 同一 Tool Registry 服务于 MCP 和内置 Provider。
- 至少两个不同接入面完成相同生成工作流，核心无需修改。
- Agent 循环、工具调用、路径和结构数量均有确定性上限。
- Skill 不承载算法、安全边界或密钥。
- 九类自然语言示例、错误恢复和责任声明齐全。
