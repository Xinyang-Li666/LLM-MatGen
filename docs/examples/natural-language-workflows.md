# Nine natural-language workflows

Each request is translated into one generator call followed by the default
lightweight check, export, and manifest publication. The examples are
provider-neutral and can run through MCP or an in-process fake provider.

1. “从 `inputs/sto.vasp` 删除两个 Ti 空位，输出 POSCAR 和 CIF，seed=7。” → `vacancy` → `check` → `export` → manifest.
2. “在 `inputs/si.cif` 中插入一个 Li，输出 POSCAR，seed=7。” → `interstitial` → `check` → `export` → manifest.
3. “将 `inputs/al.cif` 的两个 Al 替换为 Mg，输出三种结构。” → `doping` → `check` → `export` → manifest.
4. “对 `inputs/ni.cif` 生成 Ni/Co=0.8/0.2 固溶体，seed=7。” → `solid-solution` → `check` → `export` → manifest.
5. “从 `inputs/si.cif` 建立 (1,1,1) 表面，真空 15 Å。” → `surface` → `check` → `export` → manifest.
6. “从 `inputs/cu.cif` 构造 [0,0,1]、90° 晶界。” → `grain-boundary` → `check` → `export` → manifest.
7. “将 `film.vasp` 与 `substrate.vasp` 按给定 Miller 面构造界面，gap=2 Å。” → `interface` → `check` → `export` → manifest.
8. “在 `inputs/si.cif` 的 (1,1,1) 面施加滑移 (0.5,0,0)。” → `stacking-fault` → `check` → `export` → manifest.
9. “在 `inputs/fe.cif` 构造 screw 位错，给定 Burgers 向量和半径。” → `dislocation` → `check` → `export` → manifest.

The user is responsible for downstream relaxation, stability, and publication
quality assessment.
