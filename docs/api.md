# Public orchestration API

`llm_matgen.orchestration` defines `ToolDefinition`, `ToolRegistry`,
`ToolExecutor`, `Message`, `ModelTurn`, `AgentResult`, and `WorkflowRunner`.
Providers implement `complete(messages, tools)` and may be supplied by the
optional external adapters. Tool results contain summaries, structured
statistics, and manifest/artifact references rather than full file contents.

The generation service exposes ten generators for deterministic structure generation. Surface generation returns all
termination candidates for explicit user selection; adsorption then consumes a
selected slab and molecule with typed anchor/reference-axis inputs. A run may
include an offline viewer artifact. Case history supports `off`, `prefer`, and
`require`, while revision sidecars are normalized to v2. This API generates and
audits structures only; it does not run DFT or claim publication quality.
