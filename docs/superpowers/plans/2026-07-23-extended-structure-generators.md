# 扩展结构生成器实施计划

## 目标

实现 Surface、GrainBoundary、Interface、StackingFault、Dislocation 五类生成器。它们只负责构造结构和记录参数，不承诺弛豫后稳定性。

## 文件映射

```text
llm_matgen/generators/surface.py
llm_matgen/generators/grain_boundary.py
llm_matgen/generators/interface.py
llm_matgen/generators/stacking_fault.py
llm_matgen/generators/dislocation.py
llm_matgen/generators/backends.py
tests/test_generators/test_surface.py
tests/test_generators/test_grain_boundary.py
tests/test_generators/test_interface.py
tests/test_generators/test_stacking_fault.py
tests/test_generators/test_dislocation.py
tests/fixtures/golden/extended_structures/
```

## 参数接口

```python
MillerIndex = tuple[int, int, int]

class SurfaceParams(BaseGenerationParams):
    miller_indices: list[MillerIndex]
    min_slab_size: PositiveFloat
    min_vacuum_size: PositiveFloat
    center_slab: bool = True
    primitive: bool = True
    max_normal_search: PositiveInt | None = None

class GrainBoundaryParams(BaseGenerationParams):
    rotation_axis: MillerIndex
    rotation_angles: list[float]
    plane: MillerIndex | None = None
    expand_times: PositiveInt = 4
    vacuum_thickness: NonNegativeFloat = 0
    ab_shift: tuple[float, float] = (0.0, 0.0)

class InterfaceParams(BaseGenerationParams):
    film_millers: list[MillerIndex]
    substrate_millers: list[MillerIndex]
    film_thickness: PositiveFloat
    substrate_thickness: PositiveFloat
    vacuum_thickness: NonNegativeFloat
    gap: NonNegativeFloat
    max_area: PositiveFloat
    max_area_ratio_tol: PositiveFloat
    max_length_tol: PositiveFloat
    max_angle_tol: PositiveFloat

class StackingFaultParams(BaseGenerationParams):
    plane: MillerIndex
    slip_vector: tuple[float, float, float]
    fault_position: float = Field(ge=0, lt=1)
    repetitions: tuple[PositiveInt, PositiveInt, PositiveInt] = (1, 1, 1)
    vacuum_thickness: NonNegativeFloat = 0

class DislocationParams(BaseGenerationParams):
    line_direction: MillerIndex
    burgers_vector: tuple[float, float, float]
    slip_plane: MillerIndex
    character: Literal["edge", "screw", "mixed"]
    core_position: tuple[float, float]
    radius: PositiveFloat
    poisson_ratio: float = Field(gt=-1, lt=0.5)
```

## Task 1：Miller 指数和结构尺寸公共校验

1. 写失败测试：`(0,0,0)` 拒绝、指数约分、负指数保留、尺寸参数非正拒绝。
2. 实现 `normalize_miller()` 和 Pydantic 校验器。
3. 写估算原子数测试，覆盖表面厚度/真空不计入原子数的规则。
4. 实现 `estimate_structure_size()` 供五类生成器在构造前调用。
5. 提交：`feat: validate extended structure parameters`。

## Task 2：Surface 单晶面生成

1. 写失败测试：LiCoO2 `(0,0,1)` slab、真空层、输入不变。
2. 用 pymatgen `SlabGenerator` 实现单 Miller 路径。
3. 添加无法生成 slab、slab 原子数超限和奇异输入晶格测试。
4. 记录 Miller、终止面序号、slab/vacuum 实际厚度。
5. 提交：`feat: generate surface slabs`。

## Task 3：Surface 多晶面、去重与黄金样例

1. 写多个 Miller 和等价 Miller 去重测试。
2. 使用对称性等价集合加 `StructureMatcher` 去重，保持确定性排序。
3. 添加不同 termination 均保留的测试。
4. 保存固定输入黄金摘要并执行三格式 pipeline 测试。
5. 提交：`test: verify surface generation variants`。

## Task 4：GrainBoundary backend 合约

1. 写 fake backend 合约测试：输入体相、轴、角度、平面，返回结构和实际参数。
2. 定义 `GrainBoundaryBackend` Protocol；封装 pymatgen 晶界生成 API。
3. 将 pymatgen 版本差异限制在 backend 文件，不暴露给生成器。
4. 添加 backend 异常、空结果、原子数超限测试。
5. 提交：`feat: define grain boundary backend`。

## Task 5：GrainBoundary 生成器

1. 写单角度 happy path 失败测试。
2. 实现多个角度循环、`ab_shift`、vacuum 和 provenance。
3. 添加不兼容旋转轴/角度、无法求 CSL、重复结构测试。
4. 明确 MP 晶界只能作为外部输入来源，不在本生成器内部联网。
5. 保存黄金摘要并运行三格式导出测试。
6. 提交：`feat: generate grain boundaries locally`。

## Task 6：Interface 双输入契约

1. 扩展 Generator 协议测试，定义 `InterfaceInput(film, substrate)`，避免把第二结构塞进参数 JSON。
2. 定义 `BinaryStructureGenerator[Input, Params]` Protocol。
3. 写 film/substrate 颠倒时 lineage 可区分的测试。
4. 实现双父结构 provenance 和 site mapping 命名空间。
5. 提交：`feat: support two-parent structure generation`。

## Task 7：ZSL 匹配与 Interface 生成

1. 用小型 mock matcher 写失败测试：候选面积、长度、角度容差过滤。
2. 定义 `InterfaceMatcherBackend`，封装 ZSL/CIB 细节。
3. 实现候选确定性排序：面积、失配、Miller、结构哈希。
4. 实现 slab 构造、gap、vacuum 和拼接；记录面内应变分配方式。
5. 添加无匹配、候选超限、重叠原子 warning 测试。
6. 提交：`feat: generate coherent interfaces`。

## Task 8：Interface 黄金样例与格式限制

1. 选择仓库内两个小型可匹配 fixture，固定匹配参数。
2. 写 POSCAR/CIF/LAMMPS data round-trip 测试。
3. 断言 film/substrate site lineage 均可追溯。
4. 断言轻量检查 warning 不被解释为界面不稳定。
5. 提交：`test: verify interface generation workflow`。

## Task 9：StackingFault 生成器

1. 写失败测试：指定 plane 上方原子按 slip vector 位移，下方保持不变。
2. 实现超胞取向、fault_position 分区和分数坐标回卷。
3. 添加零 slip、fault_position 边界、位移后重复结构和原子过近测试。
4. 零 slip 判为无操作错误；过近原子只产生 warning。
5. 保存黄金摘要并运行三格式测试。
6. 提交：`feat: generate stacking faults`。

## Task 10：Dislocation 位移场纯函数

1. 写 edge/screw 位移场数值测试，使用手算小坐标和允许误差。
2. 实现各向同性弹性位移函数；输入/输出使用笛卡尔坐标和 Å。
3. 在 core 附近使用明确 cutoff，避免除零和非有限坐标。
4. 添加非法 Poisson ratio、零 Burgers vector、线方向零向量测试。
5. 提交：`feat: calculate isotropic dislocation fields`。

## Task 11：Dislocation 结构生成

1. 写失败测试：构造超胞、选择 core、应用 edge/screw/mixed 位移。
2. 实现半径裁剪和 PBC/非 PBC 方向处理；记录实际边界条件。
3. 添加裁剪后空结构、原子数超限、mixed 分解不一致测试。
4. 保存黄金摘要并执行三格式 pipeline；几何异常仅为 warning。
5. 提交：`feat: generate dislocation structures`。

## Task 12：五类生成器回归与资源限制

1. 参数化运行五类黄金样例两次，断言结构哈希一致。
2. 对每类添加 `max_structures`、`max_atoms_per_structure` 超限测试。
3. 运行 `pytest tests/test_generators/test_surface.py tests/test_generators/test_grain_boundary.py tests/test_generators/test_interface.py tests/test_generators/test_stacking_fault.py tests/test_generators/test_dislocation.py -q`。
4. 检查五类生成器分支覆盖率不低于 85%；backend 版本适配分支全部有 fake 测试。
5. 提交：`test: verify extended structure generators`。

## 本计划完成条件

- 五类生成器均不在内部访问网络或写文件。
- Interface 明确支持两个父结构的 lineage。
- pymatgen/ZSL 版本敏感代码被 backend 隔离。
- 所有构型有确定性排序和资源上限。
- 文档与结果只描述“生成”，不对稳定性作判断。
## 执行状态

- Task 1（Miller 指数与资源限制）：✅ 已完成
- Task 2（Surface 单晶面生成）：✅ 已完成
- Task 3（Surface 去重与三格式导出）：✅ 已完成
- Task 4（GrainBoundary backend 合约）：✅ 已完成
- Task 5（GrainBoundary 生成器）：✅ 已完成
- Task 6（Interface 双父结构契约）：✅ 已完成
- Task 7（ZSL 匹配与 Interface 生成）：✅ 已完成
- Task 8（Interface 三格式与 manifest）：✅ 已完成
- Task 9（StackingFault 生成器）：✅ 已完成
- Task 10（Dislocation 位移场）：✅ 已完成
- Task 11–12：待执行
