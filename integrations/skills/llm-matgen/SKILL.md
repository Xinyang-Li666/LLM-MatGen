---
name: llm-matgen
description: Generate material crystal structures through provider-neutral LLM tool calls.
---

# LLM-MatGen

Use the registered tools to generate structures. The nine generators are
`vacancy`, `interstitial`, `doping`, `solid-solution`, `surface`,
`grain-boundary`, `interface`, `stacking-fault`, and `dislocation`.

Always provide an input path (or `film` and `substrate` for `interface`),
explicit generator parameters, a bounded output root, and a reproducible
`seed` where randomness is used. Outputs default to POSCAR; request `cif` or
`lammps-data` as needed. Lightweight checks run by default and emit warnings;
they do not establish publication quality or physical stability.

After a tool call, inspect the returned manifest and artifact references. On a
failure, correct only the reported arguments and retry; do not fabricate files.
API keys and provider-specific message formats are outside this skill.
