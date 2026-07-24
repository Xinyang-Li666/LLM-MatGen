# LLM-MatGen

Provider-neutral crystal-structure generation for nine generator families.
Install core with `pip install -e .`; optional MCP and provider extras are
`[mcp]`, `[anthropic]`, `[openai]`, and `[all-llm]`.

The generator performs lightweight checks and writes POSCAR by default, with
optional CIF and LAMMPS data exports. It does not claim thermodynamic
stability, synthesizability, relaxation convergence, or publication quality.
Use `llm-matgen mcp` for MCP clients and consult `docs/examples/natural-language-workflows.md`.
