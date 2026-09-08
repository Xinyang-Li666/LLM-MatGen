---
name: llm-matgen
description: Generate material crystal structures through provider-neutral LLM tool calls.
---

# LLM-MatGen

Use the registered tools to generate structures. The ten generators are
`vacancy`, `interstitial`, `doping`, `solid-solution`, `surface`,
`grain-boundary`, `interface`, `stacking-fault`, `dislocation`, and
`adsorption`.

Always provide an input path (or `film` and `substrate` for `interface`),
explicit generator parameters, a bounded output root, and a reproducible
`seed` where randomness is used. Outputs default to POSCAR; request `cif` or
`lammps-data` as needed. Lightweight checks run by default and emit warnings;
they do not establish publication quality or physical stability.

After a tool call, inspect the returned manifest and artifact references. On a
failure, correct only the reported arguments and retry; do not fabricate files.
The MCP client manages the conversational model and all model/API credentials;
LLM-MatGen only executes deterministic, typed tools and never requires an
embedded provider key.

## Surface → adsorption workflow

For a surface request, call `generate_surface` first. It returns every bounded
surface termination as candidate metadata; do not silently select one. Ask the
user which candidate or termination to use, then pass that selected slab path
to `generate_adsorption` together with an adsorbate molecule path and a
one-based `anchor_index`. The adsorption tool accepts `reference_axis` for
multi-atom rigid adsorbates and returns an offline `viewer` artifact when
enabled.

`history_policy` controls audited case reuse: `off` uses only deterministic
proposals, `prefer` falls back to deterministic proposals when history is
missing or invalid, and `require` reports failure if no valid history proposal
exists. A failed generation is not a license to invent a structure or file.
