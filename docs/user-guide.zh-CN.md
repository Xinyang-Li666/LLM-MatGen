# LLM-MatGen 中文用户手册

### SOAP-FPS

安装可选依赖：`python -m pip install -e ".[soap]"`。SOAP-FPS 使用周期
DScribe SOAP，并按 TM/B/O 类别池化均值、总体标准差和存在掩码；
`examples/sampling/tmb2-soap.json` 给出不含绝对路径的 TMB2 参数。`r_cut`、
`n_max`、`l_max`、原子数和帧数都会显著影响 CPU 时间，应先对小子集做基准。
已有训练集 warm start 必须使用相同 species、SOAP 参数、类别和池化配置；
SOAP-FPS 不负责非物理结构清洗或 DFT/发表质量判断，必须先完成轨迹清洗。

## 代表性轨迹采样（RDF-FPS）

`sample representative` 是独立于旧版 uniform/random 的代表性采样入口。
RDF-FPS 读取已经清洗的多帧轨迹，使用元素对 RDF、配位/近邻统计、晶胞与
密度特征，经稳健缩放和可选 PCA 后执行确定性 FPS。多来源默认按候选帧数
比例分配配额，也可使用 `--allocation global` 统一采样。

```bash
python -m llm_matgen sample representative trajectory.extxyz \
  --method rdf-fps --count 5000 --allocation proportional \
  --output-root output/tmb2
```

多来源配置使用 `--source-config examples/sampling/tmb2-clean-sources.example.json`。
输入路径应由用户替换为本机路径，示例不包含绝对路径。每次运行都会创建
唯一目录，主要输出为 `selected.extxyz`，并同时写出 `selection.jsonl`、
`summary.json`、`manifest.json`；可选 POSCAR/CIF/LAMMPS 导出由后续写出接口
完成。缓存支持断点续跑，输入文件哈希、元素映射或描述符参数变化会使缓存失效。

清洗必须先于采样；FPS 只衡量描述符空间中的多样性，不是非物理结构审查，
也不承诺 DFT 收敛、训练质量或发表质量。SOAP-FPS 与 RDF-FPS 是两个完全
独立但可以串联的后端。

LLM-MatGen 用于生成材料晶体结构，提供命令行、Python 和 MCP 接口，覆盖九类结构生成器。程序默认执行轻量检查，并可导出 POSCAR、CIF 和 LAMMPS data。

本项目只负责结构生成与基础几何检查。用户需要自行完成结构弛豫、能量与稳定性计算，并判断结构是否适合实验、工程应用或学术发表。

## 1. 安装

### 1.1 环境要求

- Python 3.10 或更高版本
- Windows、Linux 或 macOS
- Materials Project 搜索和下载需要网络及用户自己的 MP API Key

### 1.2 安装核心功能

```bash
git clone <your-repository-url>
cd LLM-MatGen
python -m pip install -e .
```

可选功能：

```bash
# MCP 服务
python -m pip install -e ".[mcp]"

# SQS 固溶体
python -m pip install -e ".[sqs]"

# 开发与测试
python -m pip install -e ".[dev]"
```

验证安装：

```bash
llm-matgen --help
llm-matgen generate --help
```

如果终端找不到 `llm-matgen`，使用模块形式：

```bash
python -m llm_matgen --help
```

### 1.3 命令总览

| 命令 | 用途 |
| --- | --- |
| `llm-matgen search` | 搜索 Materials Project 结构 |
| `llm-matgen download` | 下载 Materials Project 结构 |
| `llm-matgen properties` | 查询 Materials Project 性质 |
| `llm-matgen substrates` | 查询与薄膜结构匹配的基底候选 |
| `llm-matgen generate` | 使用九类生成器构造结构 |
| `llm-matgen check` | 对结构执行轻量检查 |
| `llm-matgen export` | 转换结构文件格式 |
| `llm-matgen db` | 导入、导出或查询本地快照 |
| `llm-matgen mcp` | 启动 MCP 服务 |
| `llm-matgen config` | 管理非敏感的本地配置 |

运行 `llm-matgen <命令> --help` 查看子命令参数。`config` 不用于保存 API Key；密钥应通过环境变量或外部客户端提供。

## 2. 输入、输出与通用参数

### 2.1 输入格式

程序根据文件名自动识别：

- `POSCAR`、`.vasp`、`.poscar`
- `.cif`
- `.data`、`.lammps`

读取 LAMMPS data 时，显式元素映射优先；缺少全部或部分映射时，程序会提示警告并将未映射的 type ID 按元素原子序数自动映射。例如：

```bash
llm-matgen check structure.data --lammps-element 1=Fe --lammps-element 2=C
```

当前 LAMMPS data 读取器支持正交盒以及 `atomic`、`charge` atom style。

### 2.2 通用生成参数

所有生成器都支持：

- `--format poscar|cif|lammps-data`：输出格式；可重复提供以同时导出多种格式。
- `--output-root PATH`：运行结果根目录，默认 `output`。`--output-root` 必须位于当前工作目录内部，不能用绝对路径或 `..` 跳出工作区。
- `--max-structures N`：本次生成的最大结构数，默认 1000。
- `--max-atoms N`：单个结构最大原子数，默认 100000。
- `--lammps-element TYPE=ELEMENT`：覆盖 LAMMPS type 到元素的映射；缺失的 type ID 自动按原子序数解释。

示例：

```bash
llm-matgen generate vacancy \
  --input path/to/si.cif \
  --target-element Si \
  --count 1 \
  --seed 7 \
  --format poscar \
  --format cif \
  --output-root output
```

### 2.3 输出目录

一次生成对应一个独立运行目录：

```text
output/
└── run-xxxxxxxxxxxx/
    ├── manifest.json
    └── structures/
        ├── <structure-id>.vasp
        └── <structure-id>.cif
```

`manifest.json` 记录：

- 输入来源和软件版本
- 请求参数与实际离散参数
- 结构 ID、原子数和组成
- 随机种子
- 轻量检查结果
- 输出文件相对路径与 SHA-256
- 责任边界声明

同一目录中已有同名运行或 manifest 时，程序不会静默覆盖。

## 3. 九类生成器

参数中的三维整数或浮点矢量均使用逗号分隔，例如 `1,1,1`；二维坐标写作 `0.5,0.5`。

### 3.1 空位 `vacancy`

从指定元素位点删除一个或多个原子。可按数量或浓度生成，二者不能同时使用。

主要参数：

- `--target-element ELEMENT`：需要移除的元素，可重复。
- `--count N`：空位数，可重复。
- `--concentration VALUE`：空位比例，接受 `0.05` 或 `5%`。
- `--variants N`：每个空位数生成的构型数量。
- `--seed N`：随机种子。

```bash
llm-matgen generate vacancy \
  --input path/to/si.cif \
  --target-element Si \
  --count 1 \
  --variants 2 \
  --seed 7
```

### 3.2 间隙原子 `interstitial`

在 Voronoi 候选位点或随机候选位置插入元素。

主要参数：

- `--element ELEMENT`：插入元素，可重复。
- `--count N`：插入数量，可重复。
- `--candidate-mode voronoi|random`：候选点生成方式。
- `--min-distance Å`：新原子与已有原子的最小距离。
- `--variants N`：每个数量生成的构型数。
- `--seed N`：随机种子。

```bash
llm-matgen generate interstitial \
  --input path/to/si.cif \
  --element Li \
  --count 1 \
  --candidate-mode voronoi \
  --min-distance 1.0 \
  --seed 7
```

如果候选位点不足，程序可能少于请求数量或返回明确错误；应检查 manifest 中的实际参数和警告。

### 3.3 取代掺杂 `doping`

用掺杂元素替换目标元素。

主要参数：

- `--dopant-element ELEMENT`：掺杂元素，可重复。
- `--target-element ELEMENT`：被替换元素，可重复。
- `--count N`：替换数量，可重复。
- `--variants N`：每组组合生成的构型数。
- `--allow-repeated-dopant`：允许同一掺杂元素重复参与组合。
- `--seed N`：随机种子。

```bash
llm-matgen generate doping \
  --input path/to/al.cif \
  --target-element Al \
  --dopant-element Mg \
  --count 2 \
  --variants 3 \
  --seed 7
```

### 3.4 固溶体 `solid-solution`

按比例将目标元素替换为一种或多种组元。

主要参数：

- `--target-element ELEMENT`：基体中被替换的元素。
- `--substituent ELEMENT=RATIO`：替代元素及比例，可重复。
- `--method random|sqs`：随机替换或 SQS。
- `--sqs-iterations N`：SQS 优化迭代次数，默认 50000。
- `--variants N`：生成构型数。
- `--seed N`：随机种子。

```bash
llm-matgen generate solid-solution \
  --input path/to/ni.cif \
  --target-element Ni \
  --substituent Co=0.2 \
  --method random \
  --variants 2 \
  --seed 7
```

有限原子数会使请求比例离散化，实际比例以 manifest 为准。`sqs` 需要安装 `.[sqs]`。如果 SQS 依赖缺失或优化失败，程序会报告原因并建议使用 `--method random`；不会静默回退为随机结构。

### 3.5 表面 `surface`

按 Miller 面生成具有指定厚度和真空层的 slab。

主要参数：

- `--miller H,K,L`：表面 Miller 指数，可重复。
- `--slab-size Å`：slab 最小厚度。
- `--vacuum-size Å`：真空层最小厚度。
- `--no-center`：不将 slab 居中。
- `--conventional`：先转换为标准常规晶胞。
- `--cell-shape native|near-orthogonal`：晶胞表示；默认 `native`，近似正交模式只使用面内整数超胞。
- `--orthogonal-max-area N`：近似正交面内面积倍率上限，默认 8。
- `--orthogonal-tolerance DEG`：严格正交判定的角度容差，默认 0.1°。

```bash
llm-matgen generate surface \
  --input path/to/si.cif \
  --miller 1,1,1 \
  --slab-size 12 \
  --vacuum-size 15 \
  --conventional \
  --format poscar
```

不同终止面可能生成多个结构，并受 `--max-structures` 限制。

`near-orthogonal` 会先使 c 轴接近表面法向，再搜索面内整数变换，使三个晶格夹角尽量接近 90°、面内长宽比尽量接近 1。不施加应变，也不保证三边等长（尤其是含真空的 c 轴），因此应理解为“近似正交”而不是严格立方晶胞。正交化可能按面积倍率增加原子数；实际变换矩阵、倍率、夹角、边长、原子厚度和真空估计写入 manifest。

如果有限面积内无法达到 0.1° 容差，程序仍输出最佳近似结构并标记 `approximate`；如果 pymatgen 能力不可用，则记录 `fallback-native` 或 `fallback-c-orthogonal`。当前 LAMMPS data 导出器只支持严格正交晶胞，近似或回退得到的斜晶胞应优先导出 POSCAR/CIF。

近似正交示例：

```bash
llm-matgen generate surface \
  --input path/to/si.cif \
  --miller 1,1,1 \
  --slab-size 12 \
  --vacuum-size 15 \
  --cell-shape near-orthogonal \
  --orthogonal-max-area 8 \
  --orthogonal-tolerance 0.1 \
  --format poscar
```

### 3.6 晶界 `grain-boundary`

按旋转轴、角度及可选晶界面生成晶界。

主要参数：

- `--rotation-axis U,V,W`：旋转轴。
- `--angle DEGREE`：旋转角度，可重复。
- `--plane H,K,L`：可选晶界面。
- `--expand-times N`：晶界方向扩展次数。
- `--vacuum-thickness Å`：可选真空厚度。
- `--ab-shift X,Y`：两个面内方向的相对平移。

```bash
llm-matgen generate grain-boundary \
  --input path/to/cu.cif \
  --rotation-axis 0,0,1 \
  --angle 90 \
  --expand-times 4 \
  --ab-shift 0,0
```

角度和晶格对称性可能导致无法构造有限 CSL 晶胞；此时应调整角度、晶面或原子数上限。

### 3.7 界面 `interface`

匹配薄膜和基底表面并构造共格候选界面。该生成器需要两个输入文件。

主要参数：

- `--film PATH`、`--substrate PATH`：薄膜和基底结构。
- `--film-miller H,K,L`、`--substrate-miller H,K,L`：两个表面，可重复。
- `--film-thickness Å`、`--substrate-thickness Å`：两侧厚度。
- `--vacuum-thickness Å`：界面结构真空厚度。
- `--gap Å`：薄膜与基底间距。
- `--max-area Å²`：匹配超胞最大面积。
- `--max-area-ratio-tol`、`--max-length-tol`、`--max-angle-tol`：匹配容差。

```bash
llm-matgen generate interface \
  --film path/to/film.cif \
  --substrate path/to/substrate.cif \
  --film-miller 1,0,0 \
  --substrate-miller 1,0,0 \
  --film-thickness 12 \
  --substrate-thickness 15 \
  --vacuum-thickness 15 \
  --gap 2 \
  --max-area 300
```

面积或失配容差过严时可能没有候选结果；放宽参数前应先确认材料和晶面选择合理。

### 3.8 层错 `stacking-fault`

在指定平面位置对晶体一侧施加刚性位移。

主要参数：

- `--plane H,K,L`：层错面。
- `--slip-vector X,Y,Z`：滑移矢量。
- `--fault-position VALUE`：沿法向的分数位置，默认 0.5。
- `--repetitions A,B,C`：扩胞倍率。
- `--vacuum-thickness Å`：可选真空厚度。

```bash
llm-matgen generate stacking-fault \
  --input path/to/al.cif \
  --plane 1,1,1 \
  --slip-vector 0.5,0,0 \
  --fault-position 0.5 \
  --repetitions 2,2,1
```

滑移矢量的物理意义取决于输入晶格和所选滑移系，用户需要自行核对。

### 3.9 位错 `dislocation`

使用各向同性弹性位移场生成 edge、screw 或 mixed 位错。

主要参数：

- `--line-direction U,V,W`：相对于输入晶格的位错线方向。
- `--burgers-vector X,Y,Z`：Cartesian Burgers 矢量，单位 Å，不是 Miller 指数。
- `--slip-plane H,K,L`：滑移面。
- `--character edge|screw|mixed`：位错类型。
- `--core-position X,Y`：定向后横截面的分数位置。
- `--radius Å`：位错芯到横向边界的最小目标距离。
- `--poisson-ratio VALUE`：Poisson 比。

下面给出一个几何自洽的立方晶格 edge 位错示例：

```bash
llm-matgen generate dislocation \
  --input path/to/cubic.cif \
  --line-direction 0,0,1 \
  --burgers-vector 0,2.5,0 \
  --slip-plane 1,0,0 \
  --character edge \
  --core-position 0.5,0.5 \
  --radius 20 \
  --poisson-ratio 0.3 \
  --format poscar \
  --format lammps-data
```

生成器先定向晶胞，使位错线成为第三个周期轴，再沿两个横向方向扩胞，并对完整超胞施加位移。`radius` 不会通过圆柱掩码删除外圈原子。

输入 primitive 和 conventional 晶胞时 Miller 指数的含义可能不同。指定常见滑移系前，应确认输入晶格基底与所用指数约定一致。

## 4. 轻量检查

```bash
llm-matgen check structure.vasp
llm-matgen check a.cif b.vasp
```

检查内容包括：

- 是否为空结构
- 晶格是否有限且体积为正
- 分数坐标是否有限
- 是否存在小于默认阈值的近距离原子

`warning` 表示需要人工复核，但不一定阻止导出；`error` 表示存在明显格式或几何问题。轻量检查不进行结构弛豫、能量、声子或稳定性计算。

## 5. 格式转换

```bash
llm-matgen export structure.vasp --format cif --output-root converted
llm-matgen export structure.cif --format poscar --format lammps-data --output-root converted
```

导出后程序会重新读取文件，检查原子数和组成是否保持一致。

LAMMPS data 注意事项：

- 当前导出器要求正交晶格。
- 输出包含盒尺寸、原子、类型和质量。
- 输出不包含势函数、键参数、计算设置或经过验证的电荷。
- 再次读取时可用 `--lammps-element TYPE=ELEMENT` 覆盖类型映射；未覆盖的 type ID 按原子序数解释。

## 6. Materials Project

### 6.1 API Key

只通过环境变量提供真实密钥，不要写进代码、脚本、文档或 Git 提交。

Linux/macOS：

```bash
export MP_API_KEY="your-mp-api-key"
```

Windows PowerShell：

```powershell
$env:MP_API_KEY = "your-mp-api-key"
```

`.env.example` 只包含虚假占位符。

### 6.2 搜索

```bash
llm-matgen search --formula Si --limit 10
llm-matgen search --element Li --element O --n-elements 3 --band-gap-min 1.0
llm-matgen search --chemsys Li-Co-O --structure-class layered
```

可用结构分类包括 `layered`、`perovskite`、`spinel`、`rocksalt` 和 `fluorite`。分类属于轻量几何筛选，应结合材料来源人工复核。

### 6.3 下载

```bash
llm-matgen download mp-149 --output-dir downloads
llm-matgen download mp-149 mp-13 --output-dir downloads
```

下载目录包含 CIF 和 metadata JSON。已有且哈希匹配的文件会被复用；冲突文件不会被静默覆盖。

### 6.4 性质与基底

```bash
llm-matgen properties mp-149 --property electronic
llm-matgen properties mp-149 --property elasticity
llm-matgen substrates mp-149
```

### MP 性质字段

可请求六类性质。返回值是对应 Materials Project endpoint 的文档，具体字段可能随服务版本变化。

| CLI 类型 | 典型内容 |
| --- | --- |
| `thermo` | `energy_per_atom`、`formation_energy_per_atom`、`energy_above_hull`、`is_stable`、`decomposes_to`、`thermo_type` |
| `electronic` | `band_gap`、`cbm`、`vbm`、`efermi`、`is_gap_direct`、`is_metal`、`bandstructure`、`dos` |
| `magnetism` | `ordering`、`is_magnetic`、`num_magnetic_sites`、`types_of_magnetic_species`、`magmoms`、`total_magnetization` |
| `dielectric` | `total`、`ionic`、`electronic`、`e_total`、`e_ionic`、`e_electronic`、`n` |
| `phonon` | `phonon_bandstructure`、`phonon_dos`、`force_constants`、`born`、`epsilon_static`、`thermal_displacement_data` |
| `elasticity` | `elastic_tensor`、`compliance_tensor`、`bulk_modulus`、`shear_modulus`、`young_modulus`、`homogeneous_poisson`、`universal_anisotropy`、`debye_temperature` |

每个性质结果还包含 `value`、`available`、`endpoint`、`method` 和 `error`。`available=false` 表示数据缺失或查询失败，不应解释为数值零。

### 基底搜索

当前命令根据 MP material ID 所代表的结构记录搜索基底候选：

```bash
llm-matgen substrates mp-149
```

典型结果字段包括 `film_id`、`sub_id`、`sub_form`、`film_orient`、`orient`、`area`、`energy` 和 `norients`。这里的“根据结构搜索”是根据 MP 中该 material ID 对应的结构及取向匹配记录查询；当前 CLI 不直接将本地 CIF/POSCAR 上传到基底 endpoint。

获得候选后，可下载薄膜和基底，再用 `generate interface` 指定 Miller 面、厚度、gap 和失配容差构造实际界面。基底候选不等同于已弛豫或已验证的界面结构。

性质类型包括 `thermo`、`electronic`、`magnetism`、`dielectric`、`phonon` 和 `elasticity`。Materials Project 未提供某项数据时，不应将缺失值解释为零。

## 7. MCP 与自然语言客户端

安装并启动：

```bash
python -m pip install -e ".[mcp]"
llm-matgen mcp --output-root output
```

MCP 客户端负责管理模型和模型凭据，并将自然语言请求转为 LLM-MatGen 工具调用。项目本身不绑定特定模型服务。

MCP 资源只能读取已登记在 manifest 中且位于输出根目录内的文件，不能通过相对路径跳出输出目录。

自然语言示例见 [自然语言工作流](examples/natural-language-workflows.md)，接口细节见 [MCP 文档](mcp.md)。

## 8. 本地数据库

本地快照数据库支持：

```bash
llm-matgen db import --help
llm-matgen db export --help
llm-matgen db query --help
llm-matgen db list --help
llm-matgen db stats --help
```

在执行导入、导出或查询前，使用相应的 `--help` 核对数据库路径和过滤参数。公开发布时不要提交本地数据库文件。

## 9. MD 轨迹非物理结构审查

轨迹审查支持 extended XYZ、LAMMPS dump、XDATCAR 和 ASE trajectory。默认强制检查数值、
晶胞和组成完整性，并检查元素对原子重叠：

```bash
llm-matgen filter trajectory production.dump \
  --lammps-element 1=Ti --lammps-element 2=B \
  --output-root output
```

使用参考轨迹后可增加力和配位环境审查：

```bash
llm-matgen filter trajectory target.dump \
  --reference clean.dump \
  --checks overlap force coordination \
  --output-root output
```

输出位于唯一运行目录，包含 clean/anomalous 轨迹、`frame-review.jsonl`、`summary.json` 和
`threshold-profile.json`。逐帧结果会区分 `pass`、`fail` 和 `not_evaluated`；缺少力数据、
参考轨迹或阈值时不会伪装成检查通过。

LAMMPS dump 缺少映射时，交互模式会提示将 type ID 作为原子序数；非交互运行必须显式添加：

```bash
--assume-type-is-z
```

完整参数、退出码和兼容参数请查看：

```bash
llm-matgen filter trajectory --help
```

## 10. 常见问题

### 找不到命令

确认当前 Python 环境已经安装项目：

```bash
python -m pip show llm-matgen
python -m llm_matgen --help
```

### 输入文件无法识别

检查扩展名是否为 `.vasp`、`.poscar`、`.cif`、`.data` 或 `.lammps`。无扩展名的 VASP 文件应命名为 `POSCAR`。

### LAMMPS data 缺少元素映射

LAMMPS 类型编号通常只是任意编号。未提供映射时程序会继续执行并按原子序数解释，同时发出警告：

```text
type 6  -> C
type 26 -> Fe
```

如果 type ID 并非元素原子序数，请显式覆盖：

```bash
llm-matgen check structure.data --lammps-element 1=Fe --lammps-element 2=C
```

部分映射也会继续执行：显式映射优先，其余 type 使用原子序数。type 小于 1 或超过元素周期表范围时会报错。

### 生成结构太多或原子太多

降低候选数量、扩胞尺寸或 `--max-structures`，并检查 `--max-atoms`。不要仅为了绕过限制而设置无法处理的超大上限。

### 结果只有警告

查看 manifest 中的 `check_issues`。近距离原子警告通常意味着需要进一步检查或弛豫，不等同于程序崩溃。

### MP 请求失败

检查：

1. `MP_API_KEY` 是否已设置；
2. 网络是否可访问 Materials Project；
3. material ID 和查询字段是否有效；
4. API Key 是否仍有效。

不要在报错截图或 issue 中粘贴真实密钥。

## 11. 安全与发布边界

不要提交：

- 真实 API Key 或本地凭据
- `.env` 和个人配置
- Materials Project 下载缓存
- `output/`、`test-results/` 等生成结果
- 本地 SQLite 数据库
- 包含个人绝对路径的日志或脚本

如果密钥曾经出现在聊天、终端输出、文件或提交历史中，应先撤销并轮换，再进行公开发布。

## 12. 责任声明

LLM-MatGen 生成的是计算工作流输入候选，不是经过验证的材料结论。项目不保证：

- 热力学或动力学稳定性
- 实验可合成性
- 势函数或 DFT 设置适用性
- 结构弛豫收敛
- 计算结果正确性
- 论文发表质量

所有下游计算、验证和科研判断均由用户负责。
