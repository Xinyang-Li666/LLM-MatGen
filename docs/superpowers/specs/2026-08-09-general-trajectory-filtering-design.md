# 通用分子动力学轨迹非物理结构审查设计

## 1. 背景与目标

现有轨迹过滤原型面向 TMB2 升温轨迹，实现了原子重叠、最大力和分组配位数审查，
但其自定义格式解析、正交晶胞距离算法、全量内存加载和静默跳过检查等行为不适合
作为公开的通用功能。

本次重构目标是构建适用于任意材料体系和常见 MD 轨迹格式的帧级审查功能：

- 正确处理正交、三斜和部分周期晶胞；
- 支持 extxyz、LAMMPS dump、XDATCAR、ASE trajectory 等常见格式；
- 对十万帧级轨迹保持有界内存占用；
- 明确区分检查通过、检查失败和未执行；
- 保留原始帧索引、晶胞、力与元数据，保证审查可追溯；
- 安全地产生 clean、anomalous、逐帧报告和汇总文件；
- 保留现有 CLI 与 Python API 的短期迁移路径。

本工具用于快速排除明显的非物理帧，不对结构是否具有发表质量或真实物理稳定性作保证。

## 2. 总体方案

采用“统一轨迹模型 + ASE 读取 + 可组合检测器 + 双遍流式处理”的架构。

```text
ASE 轨迹读取器
    -> 标准化与硬输入验证
    -> Numeric / Overlap / Force / Coordination / Cell / Continuity 检测器
    -> 帧级判定
    -> clean/anomalous 轨迹 + JSONL 报告 + summary + manifest
```

首版使用 ASE neighbor list。检测器接口为将来替换为 freud、MDAnalysis 或专用 cell-list
后端预留扩展点，但首版不增加新的高性能依赖。

## 3. 结果语义

每个检测维度必须返回以下状态之一：

- `pass`：该维度已执行且通过；
- `fail`：该维度已执行且发现异常；
- `not_evaluated`：缺少必要数据、阈值或参考轨迹，无法执行。

任一硬检查失败，或任一已启用的统计检测器失败，整帧进入 anomalous。未执行的检查
不会被表示成通过。启用严格模式时，任何显式请求但未执行的维度使命令返回非零退出码。

## 4. 统一帧模型

扩展项目已有 `TrajectoryFrame`，不再由过滤模块维护独立 `RawFrame`：

```python
@dataclass(frozen=True)
class TrajectoryFrame:
    atomic_numbers: np.ndarray
    positions: np.ndarray
    cell: np.ndarray | None
    pbc: np.ndarray
    forces: np.ndarray | None
    source_index: int
    timestep: int | float | None
    metadata: dict[str, Any]
```

约束：

- `atomic_numbers` 形状为 `(N,)`，值位于受支持的元素范围；
- `positions` 和可选 `forces` 形状为 `(N, 3)`；
- `cell` 存在时形状为 `(3, 3)`；
- `pbc` 始终保留三个方向；
- `source_index` 是原始轨迹的零基帧索引；
- timestep、能量、温度等信息在可用时写入 metadata；
- 输入数组在检测前完成形状和有限性验证。

## 5. 轨迹读取

统一扩展 `ASETrajectoryReader`，流式产出 `TrajectoryFrame`。支持：

- extended XYZ；
- LAMMPS dump text；
- VASP XDATCAR；
- ASE `.traj`；
- 其他经验证可由 ASE 正确读取的多帧格式。

LAMMPS dump 必须覆盖：

- `x/y/z`、`xs/ys/zs` 和 `xu/yu/zu`；
- 正交与三斜 box；
- 三个方向独立的边界条件；
- 任意原子列顺序；
- 存在或缺少力列；
- 原子 ID 顺序变化。

### 5.1 LAMMPS 元素映射

- 明确提供 `TYPE=ELEMENT` 时使用该映射；
- 缺少映射时，交互终端提示“继续则将 type ID 作为原子序数”；
- 非交互环境必须提供 `--assume-type-is-z`；
- type ID 超出支持的原子序数范围时失败；
- 未知元素符号失败，禁止静默转换为 `0`；
- profile 和 summary 记录最终采用的映射及来源。

## 6. 检测规则

### 6.1 数值、晶胞与组成完整性

该检测器始终启用且不可关闭。以下情况直接标记异常：

- 坐标、力或晶胞含 `NaN/Inf`；
- 原子数为零；
- 数组形状不一致；
- 非法原子序数；
- 周期晶胞奇异、体积非正或周期方向尺度接近零；
- 同一轨迹原子数或元素组成意外改变。

用户可用 `--allow-variable-composition` 显式允许可变组成，但单帧数值与形状检查仍强制执行。

### 6.2 原子重叠

取消金属/非金属硬编码和“只检查十个近邻”逻辑。元素对最小距离定义为：

```text
d_min(i,j) = max(absolute_floor, overlap_scale * (r_cov(i) + r_cov(j)))
```

默认参数：

- `overlap_scale = 0.55`；
- `absolute_floor = 0.55 Å`；
- `overlap_ratio = 0.01`；
- 共价半径来自 ASE 数据表；
- 支持元素对距离覆盖。

使用完整晶胞和三方向 PBC 的 neighbor list。任意距离低于对应阈值的 70% 时直接判定
异常；其余违规在违规原子比例大于等于 `overlap_ratio` 时判定异常。未知半径不能
静默回退为任意常数。

### 6.3 力异常

不提供跨材料体系的固定默认力阈值。支持：

- 用户提供绝对最大力阈值；
- 依据干净参考轨迹或 profile 标定阈值。

参考阈值取以下两个稳健统计量的较大值：

```text
Q3 + force_iqr * IQR
median + force_mad * MAD
```

默认 `force_iqr=3.0`、`force_mad=8.0`。缺少力或阈值时返回 `not_evaluated`；
显式请求该检查且启用严格模式时命令失败。非有限力由数值检查器直接拦截。

### 6.4 配位环境

配位检查必须具有参考轨迹或已保存 profile，不允许默认使用待检查的脏轨迹自标定。

默认按元素分别统计，同时支持用户定义元素组。每帧至少记录：

- 平均与中位配位数；
- 低配位、高配位原子比例；
- 配位分布分位点。

元素对邻居截断优先来自参考轨迹 RDF 的第一极小值；无法稳定求取时回退为记录在
profile 中的共价半径规则。零 IQR、小样本和参考/目标元素不兼容必须明确处理，不能
形成无提示的零宽阈值。

### 6.5 晶胞演化

默认仅执行晶胞有效性硬检查。显式启用相对晶胞检查后，可检测：

- 每原子体积变化；
- 晶格方向伸缩；
- 晶胞剪切与条件数；
- 相邻帧晶胞突变。

NPT、热膨胀和相变轨迹可关闭相对晶胞检查。

### 6.6 时间连续性

可选检查相邻帧最小镜像位移或速度跳变。正确区分 wrapped 与 unwrapped 坐标。
由于时间步长和采样间隔没有通用阈值，首版默认关闭。

## 7. 检测器接口

```python
class FrameDetector(Protocol):
    name: str

    def calibrate(
        self,
        frames: Iterable[TrajectoryFrame],
    ) -> DetectorProfile | None: ...

    def evaluate(
        self,
        frame: TrajectoryFrame,
        profile: DetectorProfile | None,
    ) -> DetectionResult: ...
```

```python
@dataclass
class DetectionResult:
    detector: str
    status: Literal["pass", "fail", "not_evaluated"]
    severity: Literal["info", "warning", "error"]
    metrics: dict[str, float | int | str]
    reasons: list[str]
```

```python
@dataclass
class FrameReview:
    source_index: int
    timestep: int | float | None
    anomalous: bool
    results: list[DetectionResult]
```

多原因帧既增加 `multi`，也分别增加命中的具体原因计数。

## 8. 流式处理

采用双遍流程：

1. 第一遍对参考轨迹进行确定性均匀抽样或蓄水池随机抽样，建立力和配位 profile；
2. 第二遍逐帧读取目标轨迹、执行检测并立即写入输出和 JSONL 报告。

内存目标从 `O(frame_count * atom_count)` 降为：

```text
O(sample_count * atom_count + atom_count * neighbour_count)
```

普通磁盘文件通过重新打开实现双遍。不可重复读取的数据流需要先安全转存临时轨迹，
否则明确拒绝需要标定的操作。

## 9. 阈值 Profile

`threshold-profile.json` 必须版本化并记录：

- schema 和软件版本；
- 参考轨迹哈希；
- 元素组成与映射；
- 检测器参数；
- 抽样方法、随机种子、样本数和样本索引；
- 力、配位和元素对阈值；
- 创建时间。

使用 profile 时校验目标元素集合和必要元数据。元素集合不兼容时拒绝；仅原子数不同但
元素集合兼容时警告并按检测器规则决定能否继续。

## 10. 输出

每次执行创建唯一运行目录：

```text
output/filter-<timestamp>-<short-uuid>/
├── clean.extxyz
├── anomalous.extxyz
├── frame-review.jsonl
├── summary.json
├── threshold-profile.json
└── manifest.json
```

extxyz 为默认输出，因为它可保留完整晶胞、PBC、原子序数、力和帧元数据。用户可选择
LAMMPS dump 输出，但写入器必须保留三斜晶胞和正确边界条件。

逐帧 JSONL 至少包含帧索引、timestep、异常状态、所有原因及关键指标。summary 中记录
总帧数、clean/anomalous 数量、每个原因计数、未执行维度、阈值和输出路径。

## 11. 写入安全

- `model_name` 仅作为元数据，不参与实际路径拼接；
- 输出路径解析后必须位于允许的输出根目录；
- 每次执行创建唯一且不存在的目录；
- 禁止输入与输出为同一文件；
- 不覆盖既有文件；
- 通过临时文件和原子重命名完成最终写入；
- 中断后不得留下看似完整的结果；
- 失败运行记录 `incomplete=true`，或仅清理由本次创建的安全临时文件；
- 校验符号链接不能使输出逃出允许目录。

## 12. CLI

### 12.1 基本命令

```bash
llm-matgen filter trajectory INPUT --output-root output
```

默认强制执行数值/晶胞/元素完整性和原子重叠检查。

### 12.2 参考轨迹与 Profile

```bash
llm-matgen filter trajectory target.dump \
  --reference clean.dump \
  --checks overlap force coordination \
  --output-root output
```

```bash
llm-matgen filter trajectory target.dump \
  --threshold-profile threshold-profile.json \
  --output-root output
```

`--reference` 与 `--threshold-profile` 互斥。

### 12.3 参数分组

```text
输入输出：
  --input-format FORMAT
  --output-root PATH
  --output-format extxyz|lammps-dump
  --model-name NAME

参考标定：
  --reference PATH
  --threshold-profile PATH
  --sample-count 300
  --sample-method uniform|random
  --seed INTEGER

检查选择：
  --checks overlap force coordination cell continuity

重叠：
  --overlap-scale 0.55
  --overlap-floor 0.55
  --overlap-ratio 0.01
  --pair-min-distance Ti-B=1.20

力：
  --force-max VALUE
  --force-iqr 3.0
  --force-mad 8.0

配位：
  --coord-group cation=Ti,Zr,Hf
  --coord-iqr 3.0
  --coord-cutoff Ti-B=2.80

可选检查：
  --cell-volume-change FRACTION
  --displacement-max ANGSTROM

行为：
  --strict
  --fail-on-anomaly
  --allow-variable-composition
  --assume-type-is-z
```

所有距离、比例、采样数、阈值和元素参数均在 CLI 与 Python API 边界验证。

### 12.4 退出码

- `0`：检查正常完成；
- `2`：参数、输入格式、元素映射或 profile 错误；
- `3`：严格模式存在未执行维度，或 `--fail-on-anomaly` 检出异常；
- `4`：读取、写入或内部系统错误。

默认发现异常帧不代表命令执行失败。

## 13. 兼容迁移

当前功能未进入公开提交，因此核心实现可直接重构；为本地脚本保留一个次版本兼容层。

CLI 映射：

| 旧参数 | 新行为 |
|---|---|
| `--dimensions` | 映射为 `--checks` |
| `--force-threshold MODEL=VALUE` | 当前模型的 `--force-max` |
| `--n-iqr` | 映射为配位 IQR 并给出弃用警告 |
| `--coord-cutoff VALUE` | 全局配位截断回退值 |
| `--overlap-ratio` | 保持不变 |

Python API 暂时保留 `FilterConfig`、`FilterResult`、`filter_trajectory()`、`RawFrame`、
`read_lammps_dump()` 和 `read_extxyz()`，内部通过兼容适配器调用新引擎并发出弃用警告。

提供 `--legacy-flat-output` 生成旧式 `{model}_clean.dump` 和
`{model}_anomalous.dump`，但拒绝覆盖，并继续生成 summary 和逐帧报告。

旧 TMB2 参数迁移为 `examples/profiles/tmb2-heating.json`，明确标识为体系专用配置，
不作为通用默认值。

## 14. 测试矩阵

### 14.1 模型和输入验证

- 空结构、数组形状不一致、非法原子序数；
- 坐标/力/晶胞的 NaN 与 Inf；
- 奇异、负体积、近零晶胞；
- 固定组成和允许可变组成；
- 三方向不同 PBC。

### 14.2 几何正确性

- 正交与三斜晶胞；
- 周期边界两侧近邻；
- 部分周期边界；
- wrapped、scaled、unwrapped 坐标；
- 平移、原子排序、周期映像不变性；
- 与 ASE 独立参考距离一致。

### 14.3 格式读取

- LAMMPS 三类坐标、任意列顺序、有/无力、三斜 box、ID 重排；
- extxyz 多种 `Properties=` 顺序、有/无晶胞与力；
- XDATCAR、ASE `.traj`、未知格式和显式格式覆盖；
- 完整、缺失和非法 LAMMPS 元素映射；
- 截断或损坏帧。

### 14.4 检测器

- 严重与普通重叠、元素对覆盖、第 11 近邻回归；
- 绝对力阈值、参考 IQR/MAD、缺失力、非有限力；
- 单/多元素配位、表面与缺陷、零 IQR、小样本、不兼容 profile；
- 合法热膨胀、体积崩溃、剪切与晶胞突变；
- PBC 跨边界与真实位移跳变。

### 14.5 分类、输出与安全

- 单原因、多原因和独立原因累计；
- `pass/fail/not_evaluated`；
- 空 clean/anomalous、单原子帧、索引与 timestep 保持；
- summary、JSONL 与轨迹帧数一致；
- 路径穿越、符号链接越界、输入输出相同、禁止覆盖；
- 中断写入和原子重命名；
- extxyz/LAMMPS 输出往返读取保持结构信息。

### 14.6 流式、性能和 CLI

- 使用只允许单次迭代的读取器证明无隐式全量加载；
- 确定性均匀/随机抽样；
- 72 原子、100,000 帧时峰值内存目标低于 300 MB；
- 1,000 原子场景不构建完整距离矩阵；
- reference/profile 互斥、映射确认、严格模式、异常退出码、JSON 输出；
- 旧参数兼容警告和 README 示例执行测试。

性能测试独立运行，不加入普通快速单元测试。

## 15. 实施阶段

1. **统一帧模型与 ASE 读取**：解决格式、晶胞、PBC 和元素映射问题；
2. **检测器框架与硬检查**：实现结果模型、数值检查和 neighbor-list 重叠检查；
3. **参考标定与统计检测**：实现 profile、力、配位和可选晶胞检查；
4. **双遍流式引擎与安全输出**：实现有界内存、JSONL、manifest 和原子写入；
5. **CLI 与兼容层**：新参数、退出码、旧接口适配和弃用警告；
6. **真实轨迹回归与性能验证**：TMB2 代表数据、逐帧差异审计和十万帧基准；
7. **文档与发布**：用户手册、profile 示例、迁移说明和发布检查。

阶段 1 至 5 构成核心重构；阶段 6 通过后才能合入公开版本。时间连续性检测可在第二轮
实现，不阻塞首版核心功能。

## 16. 验收标准

- 正交、三斜和部分周期结构的距离结果与 ASE 参考一致；
- NaN/Inf、奇异晶胞和严重重叠不会被静默放行；
- 所有检查维度明确报告 pass、fail 或 not_evaluated；
- 常见 extxyz、LAMMPS dump、XDATCAR 和 ASE trajectory 可流式处理；
- 十万帧代表轨迹满足峰值内存目标；
- 输出可重新读取，并保留晶胞、PBC、元素、力、索引和 timestep；
- 路径穿越、覆盖和不完整写入测试通过；
- 旧 CLI/Python API 在兼容期内可运行并产生弃用提示；
- TMB2 回归差异具有逐帧记录和可解释结论；
- 全量单元、集成、CLI、安全与发布检查通过。
