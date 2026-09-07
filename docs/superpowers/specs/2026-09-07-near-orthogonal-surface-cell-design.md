# 表面近似正交晶胞设计

## 1. 背景与目标

LLM-MatGen 当前通过 `pymatgen.core.surface.SlabGenerator` 按 Miller 指数、最小表面厚度和最小真空厚度生成 slab。输出可以正确表达目标表面，但对于 FCC (111) 等晶面，面内基矢通常形成 60°/120° 夹角，所得斜晶胞不便于后续建模、可视化和部分计算工作流。

DS-GEN 已增加“c 轴正交化 + 面内整数超胞搜索”：先使 c 轴垂直于表面，再使用原面内晶格矢量的整数线性组合寻找尽量接近正交的等价超胞。本设计将这项能力以兼容方式引入 LLM-MatGen。

本功能所称“近似正交”是指：

- c 轴尽量垂直于表面面内的 A、B 基矢；
- A、B 夹角尽量接近 90°；
- 在满足正交性目标后，面内长宽比尽量接近 1；
- 不要求含真空层的 c 边与 A、B 等长，因此不宣称生成严格立方晶胞。

目标：

1. 用户可显式请求近似正交表面晶胞。
2. 不指定新参数时，保持当前 surface 生成行为不变。
3. 不通过连续剪切或应变强制修改表面晶格。
4. 保留 LLM-MatGen 当前生成全部终止面的行为。
5. 记录完整变换和实际晶胞诊断，使输出可追溯、可复现。

## 2. 非目标

- 不保证 `a ≈ b ≈ c`。
- 不保证任意低对称晶体和 Miller 面都能在有限面积内严格正交。
- 不改变表面终止面的枚举规则。
- 不改变 `SlabGenerator` 的厚度、真空、中心化或 primitive/conventional 语义。
- 不增加固定层、选择性动力学或表面钝化功能。
- 不把晶胞整形自动扩展到 interface、grain-boundary 或其他生成器。
- 不以连续应变、直接对角化晶格矩阵或修改原子相对几何来换取 90°晶胞。

## 3. 方案选择

采用可选、向后兼容的近似正交模式。

未采用“所有表面默认正交化”，因为正交化可能增加原子数、改变结构哈希和输出晶胞，会静默改变现有自动化任务结果。

未采用通用晶胞整形服务，因为本轮需求只涉及表面生成；过早抽象会扩大 interface 和 grain-boundary 的回归范围。

处理流程：

```text
bulk structure
      ↓
SlabGenerator（枚举全部终止面）
      ↓
cell_shape = native ─────────────→ 保持当前 slab
      ↓ near-orthogonal
c 轴正交化
      ↓
面内二维整数超胞搜索
      ↓
应用一次超胞变换
      ↓
最终原子数检查 → 去重 → 记录诊断 → 输出
```

## 4. 参数契约

在 `SurfaceParams` 中增加：

```python
cell_shape: Literal["native", "near-orthogonal"] = "native"
orthogonal_max_area: PositiveInt = 8
orthogonal_tolerance: PositiveFloat = 0.1
```

含义：

- `cell_shape="native"`：不进行新增的晶胞整形，完整保持原行为。
- `cell_shape="near-orthogonal"`：启用 c 轴正交化和面内整数超胞搜索。
- `orthogonal_max_area`：面内整数变换允许的最大面积倍率；默认 8。
- `orthogonal_tolerance`：判断严格正交的角度容差，单位为度；默认 0.1°。

整数系数搜索范围固定为 `[-8, 8]`，作为内部实现常量，不增加公开参数。面积上限才是控制原子数增长的用户契约。

CLI 增加：

```text
--cell-shape {native,near-orthogonal}
--orthogonal-max-area N
--orthogonal-tolerance DEG
```

示例：

```bash
llm-matgen generate surface \
  --input Al.cif \
  --miller 1,1,1 \
  --slab-size 12 \
  --vacuum-size 12 \
  --cell-shape near-orthogonal
```

CLI、Python API、自然语言测试工具和 MCP/工具模式使用同一参数命名与默认值，不建立第二套语义。

## 5. 算法设计

### 5.1 c 轴正交化

对 `SlabGenerator.get_slabs()` 返回的每个终止面分别处理。

当请求 `near-orthogonal` 时，调用 `Slab.get_orthogonal_c_slab()`，使 c 轴与表面面内晶格垂直。该操作调整周期表示，不对面内晶格施加连续应变，也不主动复制 c 方向。

若当前 pymatgen 版本或返回对象不支持该方法，则该终止面保留原始 slab，并记录 `fallback-native` warning；不因一个终止面失败而中断其他终止面或 Miller 指数。

### 5.2 面内整数超胞搜索

设正交化后的面内基矢为 `a、b`，搜索二维整数变换：

```text
A = p a + q b
B = r a + s b

M = [[p, q],
     [r, s]]
```

其中 `p,q,r,s ∈ [-8,8]`。

候选必须满足：

- A、B 均非零；
- `det(M) > 0`，避免奇异变换和翻转 c 轴手性；
- `det(M) ≤ orthogonal_max_area`；
- 所有长度和夹角均为有限数。

对候选计算：

- `alpha = angle(B, c)`；
- `beta = angle(A, c)`；
- `gamma = angle(A, B)`；
- 总角度误差 `E = |alpha-90| + |beta-90| + |gamma-90|`；
- 面积倍率 `D = det(M)`；
- 面内长宽比 `R = max(|A|,|B|) / min(|A|,|B|)`。

### 5.3 确定性评分

候选分为严格候选和近似候选：

- 严格候选：三个夹角与 90°的偏差均不超过 `orthogonal_tolerance`；
- 近似候选：至少一个夹角超过容差。

若存在严格候选，按以下顺序选择：

```text
(面积倍率 D, 长宽比 R, 总角度误差 E, 单位变换距离 I, p, q, r, s)
```

若不存在严格候选，按以下顺序选择：

```text
(总角度误差 E, 面积倍率 D, 长宽比 R, 单位变换距离 I, p, q, r, s)
```

`I` 表示候选矩阵相对于单位矩阵的距离；它优先保留已经满足条件的原胞，避免在没有几何收益时引入不必要的超胞。将矩阵系数放入最终评分元组，保证完全相同的输入和参数得到确定的变换。

搜索阶段只计算晶格向量，不复制原子。确定最佳矩阵后，将其嵌入三维整数超胞矩阵：

```text
[[p, q, 0],
 [r, s, 0],
 [0, 0, 1]]
```

并只调用一次 `make_supercell`。

### 5.4 终止面、去重和限制

LLM-MatGen 继续处理每个 Miller 指数下的全部终止面，不采用 DS-GEN 当前只取第一个 slab 的行为。

处理顺序为：

1. 生成一个终止面 slab；
2. 按请求整形晶胞；
3. 对最终结构检查 `max_atoms_per_structure`；
4. 对最终结构执行现有对称等价去重；
5. 写入结构记录。

原子数限制必须在面内变换后检查，因为最终原子数等于基础 slab 原子数乘以面积倍率。若 near-orthogonal 的最终结构超限，该终止面记为失败并给出包含基础原子数、面积倍率、预计最终原子数和上限的 warning；不得静默回退到较小但不满足请求的 native slab。生成器继续处理其他终止面；若全部候选均失败，则汇总具体原因并抛出错误。

native 模式继续沿用现有原子数限制和 fail-fast 行为，避免默认执行路径发生兼容性变化。

## 6. 回退和状态语义

`cell_shape_status` 使用以下值：

- `native`：用户请求 native，未运行整形。
- `strict`：近似正交模式找到满足容差的整数超胞。
- `approximate`：找到有效超胞，但未满足严格角度容差。
- `fallback-native`：c 轴正交化不可用，保留原始 slab。
- `fallback-c-orthogonal`：c 轴正交化成功，但面内搜索无法产生有效候选，保留 c 轴正交化结果。

正常的 `approximate` 是成功结果，同时附带 warning。回退也是成功结果并附带 warning。只有结构无效、最终原子数超限或底层 slab 生成失败时，该终止面才失败。

理论上，当 `orthogonal_max_area ≥ 1` 且面内晶格非退化时，单位矩阵始终是有效候选；`fallback-c-orthogonal` 主要用于防御异常数值和未来算法约束变化。

## 7. 诊断与可追溯性

每个输出结构的 `actual_parameters` 至少记录：

```json
{
  "miller_index": [1, 1, 1],
  "termination": 0,
  "cell_shape_requested": "near-orthogonal",
  "cell_shape_status": "strict",
  "inplane_transform": [[1, 1], [-1, 1]],
  "area_multiplier": 2,
  "lattice_lengths": [5.73, 4.96, 27.20],
  "lattice_angles": [90.0, 90.0, 90.0],
  "inplane_aspect_ratio": 1.155,
  "cell_height": 27.20,
  "material_span": 12.40,
  "vacuum_estimate": 14.80
}
```

`lattice_angles` 顺序明确为 pymatgen 的 `[alpha, beta, gamma]`。`area_multiplier` 对 native 和 fallback-native 为 1；`inplane_transform` 为单位矩阵。

原子厚度定义为所有原子笛卡尔坐标在 c 轴单位向量上的投影跨度。真空估计定义为晶胞沿 c 轴的周期高度减去原子投影跨度，并截断到非负值。

厚度和真空是诊断值，不宣称等于用户请求值；`SlabGenerator` 会因完整原子层和周期堆垛产生合理取整。

## 8. 风险与控制

### 8.1 原子数增长

面积倍率最高为 8，可能使输出显著增大。通过公开的面积上限、变换后的原子数检查以及 manifest 诊断控制。

### 8.2 结构哈希变化

近似正交模式会改变晶胞表示和原子数，因此结构哈希与 native 模式不同。该模式必须显式请求，默认不启用。

### 8.3 去重语义变化

不同终止面在整形后可能被 `StructureMatcher` 判为等价。去重必须作用于最终结构，并在 warning 中记录被跳过的 Miller 指数和终止面编号。

### 8.4 低对称表面无法严格正交

有限面积整数超胞并不总能达到 90°。程序输出最佳近似候选并明确记录实际夹角，不把“近似”写成“严格正交”或“立方”。

### 8.5 pymatgen 能力差异

不同 pymatgen 版本对 `get_orthogonal_c_slab()` 的支持和返回细节可能不同。使用能力检测、异常隔离和 fallback-native，并针对项目锁定版本运行回归测试。

### 8.6 面法向与晶胞方向误解

文档明确 c 轴是 slab 的周期法向方向；不承诺 c 长度等于面内边长。manifest 输出实际夹角和边长供用户核验。

### 8.7 LAMMPS data 格式限制

当前 LLM-MatGen 的 LAMMPS data 导出器只支持严格正交晶胞。`cell_shape_status="strict"` 且实际三个夹角满足导出器数值容差时可正常导出；`approximate` 或回退结果仍可能是斜晶胞，导出 LAMMPS data 时必须给出明确错误，用户可改用 POSCAR/CIF，或后续单独扩展三斜 LAMMPS box 支持。本功能不通过对角化晶格绕过该限制。

## 9. 测试矩阵

### 9.1 参数与兼容性

1. `SurfaceParams` 默认 `cell_shape="native"`。
2. native 模式在固定输入下保持现有结构、原子数和结构哈希。
3. 非法 `cell_shape`、非正面积上限和非正容差被 Pydantic 拒绝。
4. 输入结构不被任何模式原地修改。

### 9.2 算法单元测试

1. FCC Al(111) 找到严格正交、面积倍率为 2 的面内超胞。
2. 已正交表面优先选择单位矩阵，不进行无意义扩胞。
3. 返回矩阵为整数、正行列式且不超过面积上限。
4. 应用变换后原子数严格乘以 `det(M)`，组成比例不变。
5. 三维超胞矩阵 c 方向倍率为 1。
6. 同一 slab 和参数重复搜索得到相同矩阵。
7. 无严格候选时返回角度误差最小的近似候选。

### 9.3 生成器集成测试

1. FCC Al(111)：alpha、beta、gamma 均在 0.1°容差内，面积倍率为 2。
2. BCC Fe(110)：c 与 A、B 垂直，组成和终止面保持正确。
3. 至少一个低对称晶体表面：不能严格正交时仍成功并产生 approximate warning。
4. 多终止面：所有终止面分别整形，最终再去重。
5. 正交化方法缺失或抛错：输出 fallback-native，其他终止面继续。
6. 面内搜索异常：输出 fallback-c-orthogonal。
7. 变换后超过 `max_atoms_per_structure`：跳过该终止面，warning 包含基础原子数、倍率和最终原子数；其他终止面继续，全部失败时抛出汇总错误。
8. `material_span`、`vacuum_estimate`、边长、夹角和长宽比均为有限非负值。
9. pipeline 的 POSCAR 和 CIF 输出可回读，manifest 与结构一致；严格正交结果额外验证 LAMMPS 输出，近似或回退的斜晶胞验证其得到明确的格式限制错误。

### 9.4 CLI 与 LLM 工具测试

1. CLI 正确解析三项新增参数。
2. 未传新参数时生成请求仍为 native。
3. 自然语言工具模式公开相同字段、枚举、默认值和单位。
4. LLM 请求“近似立方/正交/矩形表面超胞”时可映射为 `near-orthogonal`，同时向用户说明不保证三边等长。
5. 旧 CLI 测试和九类生成器清单不变。

## 10. 文档更新范围

实施时同步更新：

- `README.md`：表面能力简述和一条近似正交示例。
- `docs/user-guide.zh-CN.md`：参数、算法语义、面积/原子数增长和回退说明。
- `docs/llm-matgen-design.md`：SurfaceGenerator 契约和近似正交处理流程。
- `tests/nl-tests/harness.py`：自然语言工具字段说明。

文档统一使用“近似正交表面晶胞”；可说明其常用于获得更接近矩形或方形的面内晶胞，但不使用“保证立方”的表述。

## 11. 预计修改文件

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

如果实现中发现 CLI 请求模型由其他集中映射文件生成，应更新该真实单一来源，不复制参数定义。

## 12. 实施与提交边界

采用测试驱动开发，按以下边界提交：

1. 参数契约和 RED 测试。
2. c 轴正交化、整数超胞搜索和生成流程接入。
3. CLI、manifest 与 LLM 工具契约。
4. 文档和完整回归验证。

每一步完成定向测试后再进入下一步。最终运行 surface、CLI、pipeline、确定性测试以及全部生成器回归测试。

## 13. 验收标准

- 默认 native 模式无行为变化。
- 用户可通过 CLI、Python API和 LLM 工具请求 near-orthogonal。
- FCC Al(111) 在默认面积上限内得到面积倍率 2 的严格正交表面超胞。
- 所有整形只使用整数超胞变换，不施加连续应变。
- 所有终止面得到独立处理，最终结构再执行原子数检查和去重。
- 严格、近似和回退状态均可从 manifest 与 warning 中识别。
- 输出记录实际边长、夹角、面内长宽比、原子厚度、真空估计、变换矩阵和面积倍率。
- 相关定向测试与全部生成器回归测试通过。
