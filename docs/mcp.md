# MCP integration

Install `pip install "llm-matgen[mcp]"`, then run `llm-matgen mcp --output-root output`.
The server exposes the same deterministic Tool Registry through `initialize`,
`tools/list`, `tools/call`, and safe `resources/read` requests. Artifact paths
are relative to the configured output root and must be present in a manifest;
path traversal and unregistered files are rejected.
