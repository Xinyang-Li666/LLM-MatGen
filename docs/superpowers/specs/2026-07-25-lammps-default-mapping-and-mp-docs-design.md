# LAMMPS 默认元素映射与 MP 文档增强设计

日期：2026-07-25  
状态：待用户批准

## 1. 背景

当前 LAMMPS data reader 要求用户通过 `--lammps-element TYPE=ELEMENT`
提供完整的原子类型映射。没有映射时，程序直接报错：

```text
LAMMPS data requires an element mapping
```

这对类型编号本身采用元素原子序数的 LAMMPS data 不够便利。用户希望：

1. 显式映射仍然优先；
2. 缺少全部或部分映射时提示用户；
3. 程序继续执行，并将未映射的 type ID 直接解释为元素原子序数；
4. Materials Project 性质和基底搜索在用户手册中获得更完整、明确的说明。

## 2. 目标

### 2.1 LAMMPS data

- 允许无显式映射读取 LAMMPS data。
- 允许只提供部分显式映射。
- 对所有未显式映射的 type ID，使用元素周期表原子序数作为默认映射。
- 在发生任何自动映射时发出清晰、可测试的非交互警告。
- 检查、导出、生成器、Python API 和 MCP 使用相同的 reader 行为。

### 2.2 Materials Project 文档

- 明确列出六类可请求性质及典型返回字段。
- 解释性质结果的可用性和错误字段。
- 说明可以根据 MP material ID 所代表的结构记录搜索相应基底。
- 说明基底搜索返回的主要字段和能力边界。

## 3. 非目标

- 不尝试从质量、注释、文件名或坐标猜测元素。
- 不把任意 LAMMPS type ID 自动压缩为连续元素序列。
- 不引入交互式 `Y/N` 提示。
- 不修改 LAMMPS data 文件内容。
- 不支持通过本地结构文件直接调用 Materials Project 基底搜索。
- 不保证 Materials Project 对每个材料都提供每类性质或基底候选。

## 4. LAMMPS 默认映射契约

### 4.1 映射优先级

对 LAMMPS data 中出现的每个 type ID：

1. 如果 `lammps_element_map` 包含该 ID，使用用户给出的元素；
2. 否则将该 ID 作为元素原子序数 `Z`；
3. 使用周期表元素 `Element.from_Z(Z).symbol` 得到元素符号。

示例：

| LAMMPS type | 显式映射 | 最终元素 |
| --- | --- | --- |
| 6 | 无 | C |
| 26 | 无 | Fe |
| 1 | `1=Fe` | Fe |
| 6 | `1=Fe` | C |

显式映射始终覆盖默认原子序数解释。

### 4.2 有效范围

- type ID 必须是正整数；
- 自动映射只接受 pymatgen 当前元素周期表支持的原子序数；
- type ID 无效或超出范围时停止读取并抛出 `StructureReadError`；
- 错误信息必须包含无效 type ID，但不得包含文件的其他敏感内容。

### 4.3 警告行为

只要存在至少一个自动映射的 type ID，就发出一次汇总警告，而不是每个原子发出一次。

警告内容包含：

- 缺少全部映射还是部分映射；
- 自动映射的 type ID 与元素符号；
- “LAMMPS type 通常是任意编号，默认映射可能不代表真实元素”；
- 如何用 `--lammps-element TYPE=ELEMENT` 显式覆盖。

示例语义：

```text
LAMMPS element mapping is incomplete; inferred atomic-number mappings:
6=C, 26=Fe. LAMMPS type IDs may be arbitrary; provide
--lammps-element TYPE=ELEMENT to override.
```

警告采用 Python 标准 `warnings.warn(..., UserWarning)`：

- Python API 可以捕获；
- pytest 可以断言；
- CLI 默认显示在 `stderr`；
- MCP/批处理不会因交互式输入而阻塞。

同一次 `read_structure()` 调用最多发出一次该警告。

### 4.4 部分映射

部分显式映射不会导致失败。程序先保留显式值，再只对缺失类型使用原子序数映射。

例如：

```bash
llm-matgen check structure.data --lammps-element 1=Fe
```

若文件含 type 1 和 type 6：

- type 1 使用 Fe；
- type 6 自动映射为 C；
- 程序在 `stderr` 发出一次警告后继续。

### 4.5 CLI 帮助

所有 `--lammps-element` 帮助文本统一修改为：

```text
override LAMMPS type mapping as TYPE=ELEMENT; missing types default to atomic numbers
```

帮助文本不声称自动映射必然正确。

## 5. 实现边界

默认映射逻辑集中在 `llm_matgen/io/readers.py`，不在各 CLI handler、
生成器或 MCP 工具中重复实现。

读取流程调整为：

1. 解析 header、盒尺寸和 atom style；
2. 收集原子行中的所有 type ID；
3. 合并显式映射与原子序数 fallback；
4. 对 fallback 执行范围校验；
5. 如使用 fallback，发出一次汇总警告；
6. 使用最终映射构建 `Structure`。

公开函数签名保持不变：

```python
read_structure(path, fmt=None, *, lammps_element_map=None)
```

因此已有显式映射调用无需迁移。

## 6. 测试设计

修改 `tests/test_io/test_readers.py` 或当前 reader 测试文件，覆盖：

1. **完整显式映射**
   - 使用显式元素；
   - 不发出自动映射警告。
2. **完全缺失映射**
   - type 6 和 26 映射为 C 和 Fe；
   - 发出一次警告；
   - 原子数和组成正确。
3. **部分显式映射**
   - 显式映射优先；
   - 仅缺失 type 使用原子序数；
   - 警告只列出自动映射项。
4. **非法原子序数**
   - type 0、负数或超出支持范围时抛出 `StructureReadError`。
5. **CLI 提示**
   - `check`、`export` 和 `generate` 的帮助文本说明 fallback；
   - CLI 无映射读取时警告写入 `stderr`，命令继续。
6. **回归**
   - 既有 explicit map 测试保持通过；
   - POSCAR/CIF reader 行为不变；
   - LAMMPS `atomic` 与 `charge` style 均保持支持。

## 7. Materials Project 性质文档

用户手册按当前 `MPCollector.PROPERTY_ENDPOINTS` 描述六类性质。返回值是
Materials Project 对应 endpoint 的文档，具体字段可能随服务版本变化。

### 7.1 `thermo`

典型字段：

- `energy_per_atom`
- `uncorrected_energy_per_atom`
- `formation_energy_per_atom`
- `energy_above_hull`
- `is_stable`
- `decomposes_to`
- `equilibrium_reaction_energy_per_atom`
- `thermo_type`

### 7.2 `electronic`

典型字段：

- `band_gap`
- `cbm`
- `vbm`
- `efermi`
- `is_gap_direct`
- `is_metal`
- `magnetic_ordering`
- `bandstructure`
- `dos`

### 7.3 `magnetism`

典型字段：

- `ordering`
- `is_magnetic`
- `num_magnetic_sites`
- `num_unique_magnetic_sites`
- `types_of_magnetic_species`
- `magmoms`
- `total_magnetization`
- `total_magnetization_normalized_vol`
- `total_magnetization_normalized_formula_units`

### 7.4 `dielectric`

典型字段：

- 总介电张量
- 离子贡献
- 电子贡献
- 对应的标量汇总值
- 折射率相关值（服务文档提供时）

当前安装的 MP 数据模型中常见字段包括 `total`、`ionic`、`electronic`、
`e_total`、`e_ionic`、`e_electronic` 和 `n`。

### 7.5 `phonon`

典型字段：

- `phonon_bandstructure`
- `phonon_dos`
- `force_constants`
- `born`
- `epsilon_static`
- `epsilon_electronic`
- `thermal_displacement_data`
- `supercell_matrix`
- `primitive_matrix`
- `phonon_method`

### 7.6 `elasticity`

典型字段：

- `elastic_tensor`
- `compliance_tensor`
- `bulk_modulus`
- `shear_modulus`
- `young_modulus`
- `homogeneous_poisson`
- `universal_anisotropy`
- `sound_velocity`
- `debye_temperature`
- `thermal_conductivity`
- `fitting_method`
- `state`

### 7.7 统一结果包装

每种请求返回：

- `value`：endpoint 文档；
- `available`：该 material 是否获得了对应文档；
- `endpoint`：实际查询的 Materials Project endpoint；
- `method`：服务返回的计算/拟合方法（如果存在）；
- `error`：请求失败或服务不可用时的错误摘要。

缺失数据不等于数值零。使用者必须先检查 `available`。

## 8. Materials Project 基底搜索文档

### 8.1 输入

当前 CLI：

```bash
llm-matgen substrates mp-149
```

输入是一个或多个 MP material ID。每个 material ID 代表 Materials Project
中的目标薄膜结构记录，程序查询 `materials.substrates` endpoint 获取对应的
基底参考。

“根据结构搜索基底”的含义是根据 MP 中该 material ID 对应的结构及其取向匹配
记录搜索；当前版本不接受本地 CIF/POSCAR 直接上传到该 endpoint。

### 8.2 典型返回字段

- `film_id`：目标薄膜 material ID；
- `sub_id`：候选基底 material ID；
- `sub_form`：候选基底化学式；
- `film_orient`：薄膜取向；
- `orient`：基底匹配取向；
- `area`：匹配界面面积；
- `energy`：服务提供的匹配能量指标；
- `norients`：候选取向数量。

返回候选是 Materials Project 的基底参考，不等同于已经生成界面。用户仍需：

1. 下载薄膜和基底结构；
2. 选择 Miller 面、厚度、gap 和失配容差；
3. 使用 `generate interface` 生成实际界面；
4. 执行下游弛豫和稳定性评估。

## 9. 文档修改范围

修改 `docs/user-guide.zh-CN.md`：

- 将“必须提供 LAMMPS 映射”改为显式映射优先、缺失时警告并按原子序数 fallback；
- 增加自动映射风险说明和覆盖示例；
- 将 MP 性质部分改为六类字段表；
- 丰富基底搜索输入、输出和后续界面工作流；
- 保持不介绍任何特定模型厂商或内置模型适配器。

必要时同步 `README.md` 中一句简短的 LAMMPS 输入说明，但不在 README 展开完整字段表。

## 10. 验收标准

- 无映射 LAMMPS data 能按原子序数读取并发出一次警告。
- 部分映射时显式值优先，其余 type 自动映射。
- 非法原子序数明确失败。
- 所有读取入口行为一致，不引入交互阻塞。
- CLI help 与实际行为一致。
- 用户手册明确列出六类 MP 性质的主要字段。
- 用户手册明确说明可按 MP 结构记录搜索基底及返回字段。
- 聚焦测试和完整测试全部通过。
