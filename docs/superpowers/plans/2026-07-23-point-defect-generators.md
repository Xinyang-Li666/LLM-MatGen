# 点缺陷与固溶体生成器实施计划

## 目标

在冻结的公共契约上实现 Vacancy、Interstitial、Doping、SolidSolution 四类生成器。所有随机选择使用局部 `numpy.random.Generator`，不得修改全局随机状态。

## 文件映射

```text
llm_matgen/generators/base.py
llm_matgen/generators/vacancy.py
llm_matgen/generators/interstitial.py
llm_matgen/generators/doping.py
llm_matgen/generators/solid_solution.py
llm_matgen/utils/structure.py
tests/test_generators/test_base.py
tests/test_generators/test_vacancy.py
tests/test_generators/test_interstitial.py
tests/test_generators/test_doping.py
tests/test_generators/test_solid_solution.py
tests/fixtures/golden/point_defects/
```

## 参数接口

```python
class Supercell(BaseModel):
    matrix: tuple[
        tuple[int, int, int],
        tuple[int, int, int],
        tuple[int, int, int],
    ]

class VacancyParams(RandomGenerationParams):
    target_elements: list[str]
    concentration: float | None = Field(default=None, gt=0, lt=1)
    counts: list[PositiveInt] | None = None
    variants_per_count: PositiveInt = 1
    supercell: Supercell | None = None

class InterstitialParams(RandomGenerationParams):
    elements: list[str]
    counts: list[PositiveInt]
    variants_per_count: PositiveInt = 1
    min_distance: PositiveFloat = 0.8
    max_attempts: PositiveInt = 1000
    candidate_mode: Literal["voronoi", "random"] = "voronoi"
    supercell: Supercell | None = None

class DopingParams(RandomGenerationParams):
    dopant_elements: list[str]
    target_elements: list[str]
    dopant_counts: list[PositiveInt]
    variants_per_combination: PositiveInt = 1
    allow_repeated_dopant: bool = False
    supercell: Supercell | None = None

class SolidSolutionParams(RandomGenerationParams):
    target_element: str
    substituents: dict[str, float]
    method: Literal["random", "sqs"] = "random"
    variants: PositiveInt = 1
    supercell: Supercell | None = None
```

## 公共规则

- 浓度使用 `[0,1]` 分数，不接受 CLI 百分数直接进入核心接口；CLI 负责把 `5%` 转为 `0.05`。
- seed 未提供时由生成器创建一次随机 seed，并把解析后的整数写入 provenance；同一 `GenerationResult` 内不得重新播种。
- 实际浓度按可用目标位点数取最近可表示整数，并记录 `requested_concentration`、`actual_concentration` 和误差。
- 目标元素不存在、计数超过可用位点、空结果均返回明确错误，不静默生成原结构。
- 构型先以位点集合去重，再以 `StructureMatcher` 去重。
- `max_structures` 在枚举前估算并在生成过程中二次强制。

## Task 1：共享超胞与结果构造工具 ✅ 已完成（提交受 git 权限阻塞）

1. 在 `test_base.py` 写失败测试：单位矩阵保持结构、对角超胞原子数正确、奇异/非整数矩阵拒绝。
2. 实现 `apply_supercell(structure, Supercell) -> Structure`，不修改输入对象。
3. 写 `build_generation_result()` 测试，确认 provenance、父子 ID 和 site mapping 齐全。
4. 实现结果构造器和局部 RNG 工厂 `make_rng(seed)`。
5. 运行测试通过。
6. 提交：`feat: add shared generator utilities`。

## Task 2：Vacancy 参数与单计数生成 ✅ 已完成（提交受 git 权限阻塞）

1. 写失败测试：删除一个 Co、输入对象不变、组成/映射正确。
2. 实现 `VacancyGenerator.generate()` 的单 target、单 count 路径。
3. 添加目标不存在、count=可用位点数、count 超限测试。
4. 对“删除全部原子”返回参数错误，不生成空结构。
5. 运行测试通过。
6. 提交：`feat: generate vacancy structures`。

## Task 3：Vacancy 浓度、变体和确定性 ✅ 已完成（提交受 git 权限阻塞）

1. 写失败测试：5% 请求在固定超胞中记录实际浓度；相同 seed 哈希一致，不同 seed 可产生不同位点。
2. 实现浓度取整和多个 target/count 组合。
3. 实现位点集合去重、`variants_per_count` 和 `max_structures` 截断警告。
4. 添加所有可能构型少于请求变体数的测试。
5. 保存固定 seed 黄金 manifest 摘要。
6. 提交：`feat: add reproducible vacancy sampling`。

## Task 4：Interstitial 候选位点 ✅ 已完成（提交受 git 权限阻塞）

1. 写 Voronoi 候选失败测试：候选在晶胞内、与已有原子距离满足阈值、结果稳定排序。
2. 实现 `find_voronoi_candidates()`，把分数坐标规范化并按坐标排序。
3. 写 random fallback 测试，固定 seed 得到固定候选。
4. 实现最多 `max_attempts` 次尝试；耗尽时返回警告而非死循环。
5. 运行测试通过。
6. 提交：`feat: find interstitial candidates`。

## Task 5：Interstitial 组合生成 ✅ 已完成（提交受 git 权限阻塞）

1. 写失败测试：插入 H/O、多个 count、site mapping 中新增位点的 parent 为 `None`。
2. 实现候选组合选择和多元素笛卡尔组合，生成前估算总数。
3. 添加候选不足、count 超候选数、全部构型重复测试。
4. 确保过近候选不会进入结果；轻量检查仍作为导出阶段第二道检查。
5. 保存固定 seed 黄金摘要并运行测试。
6. 提交：`feat: generate interstitial structures`。

## Task 6：Doping 单元素替换 ✅ 已完成（提交受 git 权限阻塞）

1. 写失败测试：Co→Ni 单替换、目标不存在、掺杂元素等于目标元素。
2. 实现单 target、单 dopant、单 count。
3. 相同元素替换判为无操作错误；不得输出与输入完全相同的结构。
4. 记录被替换 site ID、原物种和新物种。
5. 运行测试通过。
6. 提交：`feat: generate substitutional doping`。

## Task 7：Doping 多元素组合与限制 ✅ 已完成（提交受 git 权限阻塞）

1. 写失败测试：Ni/Mn 多掺杂、重复 dopant 开关、多个 target。
2. 实现组合枚举和固定 seed 采样。
3. 添加目标位点不足、重复组合、预计数量超过上限测试。
4. 确保截断发生在确定性排序之后，使相同 seed 结果稳定。
5. 保存黄金摘要并运行测试。
6. 提交：`feat: enumerate multi-element doping`。

## Task 8：SolidSolution random 模式 ✅ 已完成（提交受 git 权限阻塞）

1. 写失败测试：比例和为 1、比例不合法、target 不存在、不可表示比例取整。
2. 实现 largest-remainder 方法将比例转为整数占位数；记录实际比例。
3. 实现固定 seed 的随机分配和多 variants 去重。
4. 添加 substituents 包含 target、自身比例以及 0 比例处理测试；0 比例项规范化删除。
5. 运行测试通过。
6. 提交：`feat: generate random solid solutions`。

## Task 9：SolidSolution SQS 适配

1. 用 fake backend 写失败合约测试，避免单元测试依赖真实 sqsgenerator。
2. 定义 `SQSBackend` Protocol 和延迟导入适配器。
3. 未安装可选依赖且请求 `method="sqs"` 时抛出包含安装命令的 `OptionalDependencyError`；不静默回退 random。
4. 添加 backend 返回组成错误、空结构和超上限的错误测试。
5. 在安装 sqsgenerator 的集成标记下运行一个小结构 smoke test。
6. 提交：`feat: add optional sqs generation backend`。

## Task 10：四类生成器端到端导出

1. 为每类写 pipeline 测试：固定 LiCoO2 → 生成 → 默认检查 → POSCAR/CIF/LAMMPS data → manifest。
2. 断言 warning 不阻断文件、格式 error 只跳过单结构。
3. 断言 manifest 中每个结构都有父结构 ID、seed、实际浓度/比例和文件哈希。
4. 运行 `pytest tests/test_generators tests/test_exporters.py tests/test_manifest.py -q`。
5. 检查四类生成器分支覆盖率不低于 90%。
6. 提交：`test: verify point defect generation workflows`。

## 本计划完成条件

- 四类生成器无文件 I/O 副作用。
- 所有随机路径在固定 seed 下稳定。
- 不可表示的浓度/比例公开实际值，不伪装为精确值。
- 组合爆炸受 `max_structures` 双重限制。
- 所有错误路径都有用户可理解的异常类型和测试。
## 执行状态

- Task 9（SolidSolution SQS 适配）：✅ 已完成（提交受 git 权限阻塞）
- Task 10（四类生成器端到端导出）：✅ 已完成（提交受 git 权限阻塞）
