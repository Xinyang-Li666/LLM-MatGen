# MCP integration

Install `pip install "llm-matgen[mcp]"`, then run `llm-matgen mcp --output-root output`.
The server exposes the same deterministic structure generation Tool Registry through `initialize`,
`tools/list`, `tools/call`, and safe `resources/read` requests. Artifact paths
are relative to the configured output root and must be present in a manifest;
path traversal and unregistered files are rejected.

Typed tools include `generate_surface`, `generate_adsorption`, `cases_status`,
`cases_query`, `cases_inspect`, and `revision_import`. `generate_surface`
returns all termination candidates; the client chooses one before calling
`generate_adsorption`. The server does not expose `cases_scan`, does not run
DFT, and does not determine publication quality. Successful generation returns
manifest and optional offline viewer artifact references.
