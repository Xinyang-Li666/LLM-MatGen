# Public orchestration API

`llm_matgen.orchestration` defines `ToolDefinition`, `ToolRegistry`,
`ToolExecutor`, `Message`, `ModelTurn`, `AgentResult`, and `WorkflowRunner`.
Providers implement `complete(messages, tools)` and may be supplied by the
optional Anthropic/OpenAI adapters. Tool results contain summaries, structured
statistics, and manifest/artifact references rather than full file contents.
