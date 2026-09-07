# 表面近似正交晶胞实施计划

> 依据：[表面近似正交晶胞设计](../specs/2026-09-07-near-orthogonal-surface-cell-design.md)

## 1. 范围和约束

本计划为 `SurfaceGenerator` 增加显式 `near-orthogonal` 晶胞模式，同时保持默认 `native` 模式的结构输出不变。

必须满足：

- 先写失败测试，再写生产代码；
- 只使用面内整数超胞变换，不施加连续应变；
- 处理所有 Miller 指数和全部终止面；
- near-orthogonal 模式在最终变换后检查原子数；
- 正交化或搜索异常按设计回退并记录状态；
- 不修改 interface、grain-boundary 或 LAMMPS 三斜晶胞导出能力；
- 不暂存工作树中与本功能无关的用户文件。

## 2. 文件映射

新增：

```text
llm_matgen/generators/surface_cell.py
tests/test_generators/test_surface_cell.py
```

修改：

```text
llm_matgen/generators/surface.py
llm_matgen/__main__.py
tests/test_generators/test_surface.py
tests/test_cli/test_generate.py
tests/test_generators/test_extended_determinism.py
tests/nl-tests/harness.py
README.md
docs/user-guide.zh-CN.md
docs/llm-matgen-design.md
```

设计文档已经存在，不在实施提交中重复改写，除非测试揭示已批准规格存在事实错误。

## 3. 内部接口

在 `llm_matgen/generators/surface_cell.py` 中定义私有实现所需的公开到包内接口：

```python
SEARCH_COEFFICIENT_LIMIT = 8

@dataclass(frozen=True)
class InplaneTransform:
    matrix: tuple[tuple[int, int], tuple[int, int]]
    lattice_angles: tuple[float, float, float]
    area_multiplier: int
    inplane_aspect_ratio: float
    total_angle_error: float
    strict: bool

def lattice_angle(first: np.ndarray, second: np.ndarray) -> float: ...
def lattice_angles(matrix: np.ndarray) -> tuple[float, float, float]: ...
def orthogonalize_c_axis(slab: Slab) -> Slab: ...
def find_inplane_transform(
    slab: Slab,
    *,
    max_area: int,
    tolerance: float,
    coefficient_limit: int = SEARCH_COEFFICIENT_LIMIT,
) -> InplaneTransform: ...
def apply_inplane_transform(slab: Slab, transform: InplaneTransform) -> Slab: ...
def measure_slab_dimensions(slab: Structure) -> tuple[float, float]: ...
```

`find_inplane_transform` 只计算晶格，不复制结构。`apply_inplane_transform` 构造 `[[p,q,0],[r,s,0],[0,0,1]]` 并只执行一次 `make_supercell`。

`surface.py` 增加包内辅助方法：

```python
def _shape_surface_cell(
    slab: Slab,
    params: SurfaceParams,
) -> tuple[Structure, dict[str, object], list[str]]: ...
```

返回最终结构、写入 `actual_parameters` 的诊断字段和 warnings。回退逻辑集中在此方法，`generate()` 不重复实现搜索细节。

## 4. Task 1：参数契约和 CLI 解析

### 4.1 RED：参数模型测试

修改 `tests/test_generators/test_surface.py`：

1. 新增 `test_surface_cell_shape_defaults_preserve_native_mode`：
   - 构造未传新字段的 `SurfaceParams`；
   - 断言 `cell_shape == "native"`；
   - 断言 `orthogonal_max_area == 8`；
   - 断言 `orthogonal_tolerance == 0.1`。
2. 新增参数化测试，断言以下输入被拒绝：
   - `cell_shape="cubic"`；
   - `orthogonal_max_area=0`；
   - `orthogonal_tolerance=0`。

运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_generators\test_surface.py -k "cell_shape or orthogonal" -q
```

确认因字段不存在或非法值未被拒绝而失败。

### 4.2 GREEN：实现参数模型

修改 `llm_matgen/generators/surface.py`：

- 从 `typing` 导入 `Literal`；
- 在 `SurfaceParams` 增加：

```python
cell_shape: Literal["native", "near-orthogonal"] = "native"
orthogonal_max_area: PositiveInt = 8
orthogonal_tolerance: PositiveFloat = 0.1
```

运行 Task 1 定向测试，确认通过。

### 4.3 RED/GREEN：CLI 参数透传

修改 `tests/test_cli/test_generate.py`，新增 `test_surface_cli_exposes_near_orthogonal_cell_options`：

- 解析带 `--cell-shape near-orthogonal`、`--orthogonal-max-area 6`、`--orthogonal-tolerance 0.2` 的 surface 命令；
- 断言 `GenerationRequest.parameters` 中三个值完全一致；
- 解析不带新选项的命令，断言请求使用 `native/8/0.1`。

先运行并确认 RED：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_cli\test_generate.py -k "surface_cli" -q
```

修改 `llm_matgen/__main__.py`：

- 给 surface 子命令增加三个 CLI 参数和默认值；
- 在 `build_generation_request()` 的 surface 分支透传三个值；
- 不改变现有参数名称或其他生成器分支。

再次运行参数模型和 CLI 定向测试，确认 GREEN。

### 4.4 提交

只暂存本任务文件：

```powershell
git add -- llm_matgen/generators/surface.py llm_matgen/__main__.py tests/test_generators/test_surface.py tests/test_cli/test_generate.py
git commit -m "feat: define near-orthogonal surface options"
```

## 5. Task 2：二维整数超胞搜索

### 5.1 RED：新建算法单元测试

新增 `tests/test_generators/test_surface_cell.py`，构造小型 FCC Al bulk，并通过 pymatgen 生成原始 (111) slab。增加以下测试：

1. `test_fcc_111_transform_is_strict_area_two`：
   - 先调用 `get_orthogonal_c_slab()`；
   - 搜索 `max_area=8, tolerance=0.1`；
   - 断言 `strict is True`、`area_multiplier == 2`；
   - 断言三个角与 90°偏差不超过 0.1°。
2. `test_already_orthogonal_surface_prefers_identity`：
   - 使用正交 (001) slab；
   - 断言矩阵为 `((1,0),(0,1))`、倍率为 1。
3. `test_transform_is_integer_positive_and_bounded`：
   - 断言所有系数为 Python `int`；
   - 断言行列式等于 `area_multiplier`，且在 `[1,max_area]`。
4. `test_apply_transform_scales_atoms_and_preserves_composition`：
   - 应用 FCC (111) 变换；
   - 断言原子数乘以面积倍率；
   - 断言约化组成不变；
   - 断言 c 晶格矢量长度和方向不变。
5. `test_search_is_deterministic`：重复调用两次并比较整个 dataclass。
6. `test_no_strict_candidate_returns_best_approximation`：使用低对称二维晶格和受限 `max_area=1`；断言 `strict is False`，并与单位矩阵预期角度一致。
7. `test_invalid_or_degenerate_lattice_is_rejected`：零长度/非有限晶格得到明确 `ValueError`。

运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_generators\test_surface_cell.py -q
```

确认因模块不存在而失败。

### 5.2 GREEN：实现晶格工具

新增 `llm_matgen/generators/surface_cell.py`：

1. `lattice_angle`：
   - 检查两个向量有限且范数大于 `1e-12`；
   - 点积余弦裁剪到 `[-1,1]`；
   - 返回度数。
2. `lattice_angles`：按 pymatgen 顺序返回 `(alpha, beta, gamma)`。
3. `orthogonalize_c_axis`：
   - 能力检测 `get_orthogonal_c_slab`；
   - 缺失时抛出包含方法名的 `RuntimeError`；
   - 检查返回晶格和坐标为有限数。
4. `find_inplane_transform`：
   - 枚举 `[-coefficient_limit, coefficient_limit]`；
   - 丢弃零向量、`det<=0`、`det>max_area` 和非有限候选；
   - 计算角度、面积倍率、长宽比和总误差；
   - 严格候选按 `(D,R,E,I,p,q,r,s)` 排序；
   - 无严格候选时按 `(E,D,R,I,p,q,r,s)` 排序；
   - `I` 为相对单位矩阵的距离，优先保留已经满足条件的原胞；
   - 无有效候选时抛出明确 `RuntimeError`。
5. `apply_inplane_transform`：深复制 slab，嵌入三维矩阵并调用一次 `make_supercell`。
6. `measure_slab_dimensions`：沿 c 单位向量计算原子投影跨度和非负真空估计。

运行算法单元测试，确认全部通过。

### 5.3 REFACTOR 和提交

- 将评分元组构造集中为小函数，避免严格/近似分支重复计算；
- 不缓存或复制所有候选结构；
- 运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_generators\test_surface_cell.py -q
```

提交：

```powershell
git add -- llm_matgen/generators/surface_cell.py tests/test_generators/test_surface_cell.py
git commit -m "feat: search near-orthogonal surface supercells"
```

## 6. Task 3：接入 SurfaceGenerator 和 manifest

### 6.1 RED：生成器集成测试

修改 `tests/test_generators/test_surface.py`，增加：

1. `test_native_mode_preserves_existing_surface_hashes`：
   - 固定输入和参数分别显式/隐式使用 native；
   - 断言结构 ID、晶格、坐标和原子数一致。
2. `test_fcc_111_near_orthogonal_records_diagnostics`：
   - 请求 near-orthogonal；
   - 对每个最终输出断言三个夹角在 0.1°内；
   - 断言 `status="strict"`、面积倍率 2、变换矩阵和实际诊断字段存在；
   - 断言输入结构未被修改。
3. `test_near_orthogonal_processes_all_terminations_before_dedup`：
   - monkeypatch `SlabGenerator.get_slabs()` 返回两个可区分 slab；
   - 断言整形方法被调用两次，两个非等价结构均保留。
4. `test_approximate_result_is_kept_with_warning`：
   - monkeypatch 搜索返回 `strict=False`；
   - 断言输出存在、状态为 approximate，warnings 包含实际角度和面积倍率。
5. `test_c_orthogonalization_failure_falls_back_per_termination`：
   - 第一终止面抛错，第二终止面成功；
   - 断言第一份为 fallback-native、第二份正常生成，整体不中断。
6. `test_inplane_search_failure_keeps_c_orthogonal_slab`：
   - 断言状态为 fallback-c-orthogonal 且 warning 明确。
7. `test_shaped_atom_limit_skips_only_oversized_termination`：
   - 一个变换后超限、另一个未超限；
   - 断言只输出未超限终止面；
   - warning 包含基础原子数、倍率、预计最终数和上限。
8. `test_all_shaped_terminations_over_limit_raise_summary`：
   - 全部超限时断言抛出含具体数字的 `ValueError`。
9. `test_slab_dimension_measurements_are_finite_nonnegative`。

先运行新增测试并确认它们因生成流程尚未接入而失败。

### 6.2 GREEN：生成流程接入

修改 `llm_matgen/generators/surface.py`：

1. 导入 `surface_cell.py` 的工具和 `InplaneTransform`。
2. 实现 `_shape_surface_cell()`：
   - native 返回副本、单位矩阵、倍率 1 和 status=native；
   - near-orthogonal 先调用 c 轴正交化，再搜索/应用面内矩阵；
   - 分别捕获 c 正交化异常和搜索异常，返回设计规定的回退状态；
   - approximate 正常返回并附加 warning；
   - 对最终结构统一计算边长、夹角、长宽比、厚度和真空。
3. 在 `generate()` 中对每个 `get_slabs()` 终止面调用 `_shape_surface_cell()`。
4. native 保留当前 fail-fast 原子数检查语义。
5. near-orthogonal 若单个最终结构超限：记录 warning、跳过该终止面并继续；如果全部候选都失败，抛出汇总错误。
6. 对整形后的最终结构执行 `StructureMatcher` 去重。
7. 将以下字段写入 `actual_parameters`：
   - `cell_shape_requested`；
   - `cell_shape_status`；
   - `inplane_transform`；
   - `area_multiplier`；
   - `lattice_lengths`；
   - `lattice_angles`；
   - `inplane_aspect_ratio`；
   - `cell_height`；
   - `material_span`；
   - `vacuum_estimate`。
8. 保留 Miller 指数、termination、父结构 ID、去重和 `max_structures` 行为。

### 6.3 验证和提交

运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_generators\test_surface_cell.py tests\test_generators\test_surface.py tests\test_generators\test_extended_determinism.py -q
```

若确定性测试尚未覆盖 near-orthogonal，修改 `tests/test_generators/test_extended_determinism.py`，在 surface case 中显式使用 `cell_shape="near-orthogonal"`，重复运行并比较结构 ID 和变换矩阵。

提交：

```powershell
git add -- llm_matgen/generators/surface.py tests/test_generators/test_surface.py tests/test_generators/test_extended_determinism.py
git commit -m "feat: generate near-orthogonal surface cells"
```

## 7. Task 4：导出边界与 LLM 参数说明

### 7.1 RED：格式边界测试

在 `tests/test_generators/test_surface.py` 增加 pipeline 测试：

1. 严格正交 FCC Al(111) 可导出并回读 POSCAR、CIF 和 LAMMPS data。
2. monkeypatch 一个 `status="approximate"` 的斜晶胞：
   - POSCAR/CIF 可导出；
   - 请求 LAMMPS data 时沿用现有导出器错误，并断言错误信息明确指出需要正交晶胞。

不得修改 LAMMPS 导出器去支持三斜 box，也不得对晶格矩阵直接对角化。

### 7.2 RED/GREEN：自然语言工具说明

修改 `tests/nl-tests/harness.py` 中 `GENERATE_SCHEMA` 的 surface 描述，加入：

```text
cell_shape (native|near-orthogonal),
orthogonal_max_area (int, default 8),
orthogonal_tolerance (float degree, default 0.1)
```

增加或更新 schema 测试，断言：

- 描述包含 `near-orthogonal`；
- 明确其表示近似正交/面内接近矩形，不保证 a≈b≈c；
- 提醒 approximate 斜晶胞不一定可导出 LAMMPS data。

若仓库没有独立 harness schema 测试，则在 `tests/test_documentation.py` 增加精确字符串契约，避免引入新的测试框架。

### 7.3 验证和提交

运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_generators\test_surface.py tests\test_documentation.py tests\test_cli\test_generate.py -q
```

提交：

```powershell
git add -- tests/test_generators/test_surface.py tests/nl-tests/harness.py tests/test_documentation.py
git commit -m "test: cover surface cell export and llm contracts"
```

若 `tests/test_documentation.py` 无需修改，不得为了匹配提交清单制造空改动。

## 8. Task 5：用户文档和设计总览

### 8.1 RED：文档契约

修改 `tests/test_documentation.py`，增加断言：

- README 和中文手册均出现 `--cell-shape near-orthogonal`；
- 中文手册包含 `--orthogonal-max-area` 和 `--orthogonal-tolerance`；
- 中文手册明确“不保证三边等长”“不施加应变”“可能增加原子数”；
- 中文手册说明 approximate/fallback 和 LAMMPS data 限制。

运行并确认失败：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_documentation.py -q
```

### 8.2 GREEN：更新文档

修改 `README.md`：

- 将 surface 能力改为“按 Miller 指数生成带真空层的表面，可选近似正交晶胞”；
- 增加一个最短 CLI 示例；
- 不在 README 展开内部搜索算法。

修改 `docs/user-guide.zh-CN.md` 的 surface 小节：

- 列出三个新参数及默认值；
- 解释 native 与 near-orthogonal；
- 说明整数超胞、不施加应变、面积倍率及原子数增长；
- 说明严格、近似和回退状态在 manifest 中可见；
- 说明 slab 的 c 轴含真空，不保证三边等长；
- 说明 approximate/fallback 斜晶胞应使用 POSCAR/CIF，当前 LAMMPS data 仅支持严格正交晶胞；
- 提供完整 CLI 示例。

修改 `docs/llm-matgen-design.md`：

- 更新 SurfaceGenerator 参数模型；
- 增加 native/near-orthogonal 分支流程；
- 记录不改变其他生成器和不施加应变的边界；
- 将本规格文档列为设计依据。

### 8.3 验证和提交

运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_documentation.py -q
```

执行 Markdown 与空白检查：

```powershell
git diff --check
rg -n "TODO|TBD|待定|占位" README.md docs/user-guide.zh-CN.md docs/llm-matgen-design.md docs/superpowers/specs/2026-09-07-near-orthogonal-surface-cell-design.md
```

提交：

```powershell
git add -- README.md docs/user-guide.zh-CN.md docs/llm-matgen-design.md tests/test_documentation.py
git commit -m "docs: explain near-orthogonal surface cells"
```

## 9. Task 6：完整验证和收尾

### 9.1 定向测试

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\test_generators\test_surface_cell.py `
  tests\test_generators\test_surface.py `
  tests\test_generators\test_extended_determinism.py `
  tests\test_cli\test_generate.py `
  tests\test_documentation.py -q
```

### 9.2 全生成器回归

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_generators tests\test_pipeline.py tests\test_services\test_generation.py tests\test_cli -q
```

### 9.3 全量测试与构建

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m build
```

### 9.4 手工烟雾验证

在临时目录创建 FCC Al 结构，运行：

```powershell
.\.venv\Scripts\python.exe -m llm_matgen generate surface `
  --input .\tmp-surface\Al.cif `
  --miller 1,1,1 `
  --slab-size 12 `
  --vacuum-size 12 `
  --cell-shape near-orthogonal `
  --format poscar `
  --format cif `
  --output-root .\tmp-surface\runs
```

核验：

- 命令成功；
- 所有输出可由 LLM-MatGen 回读；
- manifest 中 FCC Al(111) 为 strict、面积倍率 2；
- 三个夹角在 0.1°内；
- 输入文件未变化；
- 临时输出不进入提交。

### 9.5 工作树审计

```powershell
git status --short
git diff --check
git log -6 --oneline
```

确认：

- 只提交本计划范围内文件；
- 未暂存用户已有未跟踪文件；
- 无真实研究数据、API key、临时结构或构建产物进入提交；
- 若全量测试存在与本功能无关的既有失败，记录测试名和证据，不修改无关模块。

本任务只做验证，不为“测试通过”制造新的代码提交。若验证发现本功能缺陷，回到对应 RED/GREEN 任务修复并单独提交。

## 10. 完成标准

- 设计中的每个参数、状态、回退和诊断字段均已实现并测试；
- 默认 native 的结构结果保持不变；
- FCC Al(111) 得到面积倍率 2 的严格正交表面超胞；
- 已正交表面不产生无意义扩胞；
- 低对称表面可输出最佳近似结果；
- 单个 near-orthogonal 终止面失败不会阻止其他终止面；
- 原子数限制依据最终结构执行；
- POSCAR/CIF 和严格正交 LAMMPS 输出边界得到验证；
- CLI、Python 参数模型、自然语言工具说明和文档一致；
- 定向测试、全生成器回归、全量测试和构建结果均已记录；
- Git 提交按任务拆分且不包含用户无关文件。
