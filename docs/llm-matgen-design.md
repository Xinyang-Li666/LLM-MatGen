# LLM-MatGen 设计文档 — LLM 驱动的材料结构生成工作流

> **版本**: v1.1
> **日期**: 2026-07-23
> **状态**: 设计修订完成，待实施计划

---

## 1. 概述

### 1.1 项目定义

**LLM-MatGen**（LLM-driven Material Structure Generation）是一个 LLM 无关的 CLI + Python API + MCP 工具平台，用自然语言驱动晶体结构获取、九类结构生成、轻量格式与几何检查以及多格式导出。确定性的材料结构操作由 Python 核心库执行，LLM 只负责理解意图、组织参数和编排工具。

### 1.2 产品责任边界

LLM-MatGen 是**结构生成器**，不是材料稳定性或可发表性判定系统。

项目保证：

- 输入参数经过 Schema 校验，生成过程可执行并返回结构化结果
- 输出文件能够被对应格式解析器重新读取
- 默认执行非阻断的轻量检查，并完整报告警告
- 记录输入来源、生成参数、随机种子、软件版本和父子结构关系

项目不保证：

- 生成结构的热力学、动力学或机械稳定性
- 结构能够合成、弛豫收敛或直接用于发表
- 未指定势函数、赝势、计算参数时的能量或物性可信度

所有检查结果均使用“格式通过”“几何警告”等措辞，不使用“结构有效”“结构合理”作为科学结论。最终判断和后续弛豫由用户负责。

### 1.3 核心用户故事

```
用户: "从 MP 下载所有含 Co 的层状氧化物，生成 10% Co 空位和 Co→Ni 掺杂 5% 的结构，
      默认检查，同时输出 POSCAR 和 CIF"

LLM-MatGen:
  1. [MP 查询] 搜索含 Co 的氧化物 → 筛选层状结构 → 下载 POSCAR
  2. [生成] 对每个候选生成：① Co 空位 10% ② Co→Ni 掺杂 5%
  3. [轻量检查] 默认检查格式、晶格、坐标和过近原子；警告不阻止输出
  4. [导出] 按用户选择输出 POSCAR、CIF 或 LAMMPS data
  5. [报告] 生成结构化目录 + manifest.json + 警告清单
```

### 1.4 核心原则

- **确定性代码做执行，LLM 做编排和理解** — LLM 负责意图理解→参数结构化→工具选择；随机算法必须显式记录随机种子
- **LLM 无关** — 核心库不依赖任何模型 SDK；MCP 是主要工具协议，厂商适配器和 Skill 均为可选集成
- **pymatgen 是唯一的结构语言** — 所有结构 I/O 统一为 pymatgen `Structure`
- **每个功能是独立可调用的 Tool** — 可供 LLM Agent 调用，也供人类直接调用
- **从 DS-Gen/prior-py 提取最佳实现** — 提取核心逻辑，统一重构，去除 GUI 依赖
- **MP 是默认在线数据源而非运行前提** — 生成器同时接受本地 POSCAR/CIF/LAMMPS data 输入，离线时仍可运行
- **生成与导出分离** — 生成器只返回 `Structure` 和元数据；Exporter 负责文件写入
- **检查默认执行但不阻断输出** — 除无法解析或无法序列化等硬错误外，检查问题均作为警告写入 manifest

### 1.5 与 DS-Gen 的关系

| 维度 | DS-Gen（现有 v0.2） | LLM-MatGen（新建） |
|------|:---:|:---:|
| 界面 | PySide6 GUI | CLI + Python API |
| LLM 集成 | 无 | MCP 优先，支持任意兼容 LLM Host；可选厂商适配器与 Skill |
| 结构生成 | 手动填参数 × 8 类 | 自然语言 → 参数 + 手动 × 9 类 |
| MP 数据库 | 仅晶界本地 DB（55 元素） | 完整 MP 查询 + 批量下载 + 性质收集 |
| 晶界来源 | 本地 .vasp 文件索引 | 从输入结构构建；MP 查询作为可选来源 |
| 轻量检查 | 无 | 格式/晶格/坐标/间距默认检查，仅报告警告 |
| 性质收集 | 无 | 15+ 特征批量收集 |
| HPC 弛豫 | 完整 SSH+SLURM+DeepMD | 暂不支持（v0.2 后集成） |
| 本地性质 DB | 无 | SQLite 缓存，支持离线查询 |

### 1.6 参考资源

| 来源 | 路径 | 提取内容 |
|------|------|---------|
| DS-Gen generators | `D:\DS-Gen\dsgen\generators\` | 8 类生成器核心逻辑 + BaseGenerator 工具方法 |
| prior-py 脚本集 | `D:\DS-Gen\prior-py\` | doping.py 掺杂枚举逻辑、Vacancy.py 空位生成、interstitial_atom.py 间隙插入 |
| coll_mp.py | `Desktop\LiNiO2\...\coll_mp.py` | MP 7 端点 15 特征收集逻辑 |
| mp_Aolly.py | `Desktop\Aolly\3\mp_Aolly.py` | 批量二元化合物下载模式 |
| coll_grain_boundary.py | `Desktop\Aolly\coll_grain_boundary.py` | MP 晶界 API 查询逻辑 |
| coll_Substrate.py + make_interface.py | `D:\DS-Gen\prior-py\` | MP 基底查询 + CIB/ZSL 界面构建 |

---

## 2. 整体架构

### 2.1 分层架构图

```text
┌──────────────────────────────────────────────────────────────────┐
│ 接入层                                                           │
│ CLI │ Python API │ MCP Host（Codex/Claude/其他）│ 可选 Skill      │
├──────────────────────────────────────────────────────────────────┤
│ 协议与编排层                                                     │
│ Tool Registry │ JSON Schema │ Workflow Runner │ MCP Server        │
│ 可选 Provider Adapter（仅供内置 ask/chat；不进入核心依赖）        │
├──────────────────────────────────────────────────────────────────┤
│ 核心功能层                                                       │
│ Sources │ 9 Generators │ Light Checks │ Exporters │ Manifest      │
│ MP/本地   结构生成       默认非阻断     POSCAR/CIF/LAMMPS data    │
├──────────────────────────────────────────────────────────────────┤
│ 基础设施层                                                       │
│ pymatgen │ ASE │ mp-api │ SQLite Cache │ logging                  │
└──────────────────────────────────────────────────────────────────┘
```

**层间关系**：

- 核心功能层完全不依赖 LLM、MCP 或 Skill
- MCP Server 将同一组强类型 Python 操作暴露为标准工具
- Skill 只提供工具使用说明、工作流模板和示例，不承载生成算法
- 内置 `ask/chat` 通过 `LLMProvider` 协议接入模型；厂商 SDK 为可选依赖
- 用户可以通过 CLI 或 Python API 完全绕过自然语言层

### 2.2 目录结构

```
LLM-MatGen/
├── llm_matgen/                       # 核心包
│   ├── __init__.py                   # 版本号
│   ├── __main__.py                   # CLI 入口 (argparse)
│   │
│   ├── sources/                      # 输入结构与外部数据源
│   │   ├── __init__.py               # 导出 MPCollector, MaterialSummary, PropertySet
│   │   ├── mp.py                     # MPCollector — MP API 统一封装
│   │   ├── local.py                  # 本地 POSCAR/CIF/LAMMPS data 输入
│   │   ├── models.py                 # 数据模型：MaterialSummary, PropertySet, SubstrateCandidate, GBStructure
│   │
│   ├── generators/                   # 结构生成模块
│   │   ├── __init__.py               # 导出 Generator 协议、结果与 9 个生成器
│   │   ├── base.py                   # Generator 协议 + 共享结构操作
│   │   ├── models.py                 # 强类型参数、GenerationResult、Provenance
│   │   ├── vacancy.py                # VacancyGenerator — 空位
│   │   ├── interstitial.py           # InterstitialGenerator — 间隙
│   │   ├── doping.py                 # DopingGenerator — 掺杂（prior-py 提取）
│   │   ├── solid_solution.py         # SolidSolutionGenerator — 固溶体 (random + SQS)
│   │   ├── surface.py                # SurfaceGenerator — 表面
│   │   ├── grain_boundary.py         # GBGenerator — 晶界构建
│   │   ├── interface.py              # InterfaceGenerator — 界面 (MP 查询 + CIB/ZSL)
│   │   ├── stacking_fault.py         # StackingFaultGenerator — 层错
│   │   └── dislocation.py            # DislocationGenerator — 位错
│   │
│   ├── checks/                       # 默认轻量检查
│   │   ├── checker.py                # 格式、晶格、坐标、近邻检查
│   │   └── models.py                 # CheckReport、CheckIssue
│   │
│   ├── io/                           # 输入输出与 manifest
│   │   ├── readers.py                # POSCAR/CIF/LAMMPS data 读取
│   │   ├── exporters.py              # 三种格式导出与 round-trip 检查
│   │   └── manifest.py               # 运行级 manifest.json
│   │
│   ├── pipeline.py                   # 生成→检查→导出→manifest 管线
│   │
│   ├── orchestration/                # LLM 无关编排
│   │   ├── runner.py                 # 有轮数/规模上限的工作流执行器
│   │   ├── tools.py                  # 工具注册表与 JSON Schema
│   │   ├── providers.py              # LLMProvider Protocol
│   │   └── prompts.py                # 通用系统提示词
│   │
│   ├── mcp/                          # MCP Server 适配层
│   │   └── server.py
│   │
│   ├── database/                     # 本地性质数据库
│   │   ├── __init__.py               # 导出 LocalStore
│   │   ├── store.py                  # LocalStore — SQLite CRUD
│   │   └── schema.py                 # 数据库 Schema 定义
│   │
│   └── utils/                        # 工具函数
│       ├── __init__.py
│       └── structure.py              # 结构哈希、位点映射、去重
│
├── integrations/
│   ├── providers/                    # 可选模型厂商适配器
│   │   ├── anthropic.py
│   │   └── openai.py
│   └── skills/                       # Codex/Claude 等可选 Skill
│
├── tests/                            # 测试
│   ├── conftest.py                   # 共享 fixtures
│   ├── test_mp_collector.py
│   ├── test_generators/
│   │   ├── test_vacancy.py
│   │   ├── test_interstitial.py
│   │   ├── test_doping.py
│   │   ├── test_solid_solution.py
│   │   ├── test_surface.py
│   │   ├── test_grain_boundary.py
│   │   ├── test_interface.py
│   │   ├── test_stacking_fault.py
│   │   └── test_dislocation.py
│   ├── test_checks.py
│   ├── test_exporters.py
│   ├── test_manifest.py
│   ├── test_pipeline.py
│   ├── test_local_store.py
│   ├── test_tool_contracts.py
│   ├── test_mcp_server.py
│   └── test_cli.py
│
├── docs/                             # 文档
│   ├── llm-matgen-design.md          # 本设计文档
│   └── api.md                        # API 参考
│
├── pyproject.toml
├── README.md
└── CHANGELOG.md
```

---

## 3. 模块深度设计

---

### 3.1 `sources/` — 结构来源与 MP 数据模块

#### 3.1.1 设计目标

从 `coll_mp.py`、`mp_Aolly.py`、`coll_Substrate.py`、`coll_grain_boundary.py` 提取 MP 访问逻辑，统一为 `MPCollector`。同时提供 `LocalStructureSource`，使九类生成器能够直接处理本地 POSCAR、CIF 和 LAMMPS data 文件，不把网络或 MP API 作为生成前提。

#### 3.1.2 关键改进

| 问题 | 现有代码 | LLM-MatGen 方案 |
|------|---------|----------------|
| 单材料限制 | coll_mp.py 只处理一个 MATERIAL_ID | 批量查询，支持 `material_ids` 列表 |
| API Key 硬编码 | 3 个文件明文写入 | `__init__(api_key)` 注入 |
| 错误处理不统一 | 各脚本各自 try/except | 统一 `MPCollectorError` + 自动 retry |
| 速率限制 | coll_grain_boundary 无 sleep | 统一 `_rate_limit()` 0.3s 间隔 |
| 数据格式不统一 | 各脚本输出各异 | 统一 `PropertySet` / `MaterialSummary` 数据类 |

#### 3.1.3 数据模型

```python
@dataclass
class MaterialSummary:
    """MP 材料搜索结果摘要。"""
    material_id: str
    formula: str
    elements: list[str]
    n_elements: int
    formation_energy_per_atom: float | None
    band_gap: float | None
    symmetry_number: int | None
    density: float | None

@dataclass
class PropertySet:
    """材料完整性质集（15+ 特征）。"""
    material_id: str
    formula: str
    elements: list[str]
    n_elements: int
    # 基础
    density: float | None                # g/cm³
    symmetry_number: int | None          # 空间群编号
    # 热力学
    formation_energy_per_atom: float | None  # eV/atom
    oxidation_states: dict | None
    # 电子结构
    band_gap: float | None               # eV
    is_metal: bool | None
    vbm_energy: float | None             # eV
    cbm_energy: float | None             # eV
    is_direct_gap: bool | None
    # 磁性
    total_magnetization: float | None    # μB
    # 力学
    bulk_modulus: float | None           # GPa (VRH)
    shear_modulus: float | None          # GPa (VRH)
    # 热学
    debye_temperature: float | None      # K
    thermal_conductivity: float | None   # W/m·K (Cahill)
    # 元数据
    retrieval_date: str                  # ISO timestamp
    source_database_version: str | None
    structure_hash: str | None
    property_origins: dict[str, str]      # 属性名 → 来源端点/计算方法

@dataclass
class SubstrateCandidate:
    """基底候选。"""
    film_id: str
    sub_id: str
    film_formula: str
    sub_formula: str
    film_orient: tuple[int, int, int]
    orient: tuple[int, int, int]         # 基底取向
    energy: float | None
    area: float | None

@dataclass
class GBStructure:
    """晶界结构条目。"""
    material_id: str
    sigma: int
    gb_type: str                         # "tilt" | "twist"
    gb_plane: tuple[int, int, int] | None
    rotation_angle: float | None
    initial_structure: Structure | None
    final_structure: Structure | None
    formation_energy: float | None
```

#### 3.1.4 `MPCollector` 接口

```python
class MPCollector:
    """Materials Project 统一数据收集器。

    封装 9 个 MP API 端点：
      - materials.summary.search      (结构搜索)
      - materials.thermo.search       (热力学)
      - get_bandstructure_by_material_id (能带)
      - magnetism.search              (磁性)
      - materials.dielectric.search   (介电)
      - materials.phonon.search       (声子)
      - materials.elasticity.search   (弹性)
      - materials.substrates.search   (基底)
      - materials.grain_boundaries.search (晶界)
    """

    def __init__(self, api_key: str | None = None):
        """初始化。api_key=None 时从环境变量 MP_API_KEY 读取。"""
        ...

    # ── 结构搜索 ──
    def search(
        self,
        *,
        elements: list[str] | None = None,
        chemsys: str | None = None,          # "Li-Co-O"
        formula: str | None = None,          # "LiCoO2"
        material_ids: list[str] | None = None,
        n_elements: int | None = None,       # 1=单质, 2=二元...
        formation_energy_max: float | None = None,
        band_gap_min: float | None = None,
        band_gap_max: float | None = None,
        structure_class: str | None = None,  # "layered" 等；本地结构后筛选
        limit: int = 100,
    ) -> list[MaterialSummary]:
        """多条件搜索材料。返回摘要列表。"""
        ...

    # ── 结构下载 ──
    def download_structures(
        self,
        material_ids: list[str],
        output_dir: Path,
        skip_existing: bool = True,
        fmt: str = "poscar",                 # "poscar" | "cif" | "json"
    ) -> list[Path]:
        """批量下载晶体结构文件。返回文件路径列表。"""
        ...

    # ── 性质收集 ──
    def fetch_properties(
        self,
        material_ids: list[str],
        properties: list[str] | None = None,
    ) -> list[PropertySet]:
        """批量收集材料性质。

        properties 可选子集：
          ["formation_energy", "band_gap", "elastic",
           "magnetic", "dielectric", "phonon"]
        默认为 None（全部收集）。
        """
        ...

    # ── 特殊查询 ──
    def search_substrates(
        self,
        film_id: str,
    ) -> list[SubstrateCandidate]:
        """查询薄膜的基底候选（排除同质外延）。"""
        ...

    def search_grain_boundaries(
        self,
        material_id: str,
        sigma_max: int = 9,
    ) -> list[GBStructure]:
        """查询材料的晶界结构。"""
        ...

    # ── 批量下载快捷方法 ──
    def download_by_elements(
        self,
        elements: list[str],
        output_dir: Path,
        nonmetal: list[str] | None = None,   # 二元化合物自动配对
        formation_energy_max: float | None = None,
    ) -> dict[tuple[str, str], list[Path]]:
        """按元素配对批量下载（整合 mp_Aolly.py 模式）。

        例: download_by_elements(["Li", "Na", "K"], output_dir,
                                  nonmetal=["O", "S"])
        """
        ...
```

`layered`、`perovskite` 等自然语言结构类别通常不是 MP 查询字段。`structure_class` 必须在下载结构后通过明确的分类器做后筛选，并在结果中记录分类方法和置信/匹配依据；不得让 LLM 凭名称自行判定。

#### 3.1.5 错误处理策略

```python
class MPCollectorError(Exception): ...

def _retry(func, max_retries=3, backoff=2.0):
    """指数退避重试。处理 429 (rate limit) 和 5xx 错误。"""
    ...

def _rate_limit(min_interval=0.3):
    """请求间最小间隔。"""
    ...
```

---

### 3.2 `generators/` — 结构生成模块

#### 3.2.1 提取策略

从 DS-Gen 和 prior-py 提取核心生成逻辑，做以下改造：

1. **输入统一**：接收 pymatgen `Structure` 对象，不再直接读 POSCAR 文件
2. **参数强类型化**：每种生成器使用独立的参数模型，不接受无约束 `dict`
3. **输出统一**：返回 `GenerationResult`，文件写入由 Exporter 决定
4. **去 GUI 依赖**：移除 `progress_callback`，改用 Python logging
5. **新增 DopingGenerator**：从 `prior-py/doping.py` 提取组合掺杂逻辑
6. **随机过程可复现**：所有随机生成器必须接受 `seed`，并写入 provenance
7. **GB 支持本地构建**：优先从输入结构构建晶界，MP 查询仅作为可选结构来源

#### 3.2.2 9 类生成器总览

| # | 生成器 | defect_name | 缺陷类型 | 来源 |
|---|--------|-------------|---------|------|
| 1 | `VacancyGenerator` | `vacancy` | 随机移除原子 | DS-Gen |
| 2 | `InterstitialGenerator` | `interstitial` | 随机插入间隙原子 | DS-Gen |
| 3 | `DopingGenerator` | `doping` | 元素替换（组合枚举） | prior-py 提取 |
| 4 | `SolidSolutionGenerator` | `solid_solution` | 固溶体（random/SQS） | DS-Gen |
| 5 | `SurfaceGenerator` | `surface` | Miller 晶面切面 | DS-Gen |
| 6 | `GBGenerator` | `grain_boundary` | 从输入结构构建晶界 | DS-Gen + pymatgen |
| 7 | `InterfaceGenerator` | `interface` | 共格界面（CIB+ZSL） | DS-Gen |
| 8 | `StackingFaultGenerator` | `stacking_fault` | 层错（刚性位移） | DS-Gen |
| 9 | `DislocationGenerator` | `dislocation` | 位错（各向同性弹性） | DS-Gen |

位错生成流程固定为“方向解析 → 晶胞定向 → 横向扩胞 → 对完整超胞施加位移 → 原子数守恒检查”。
`line_direction` 和 `slip_plane` 按输入晶格解释，`burgers_vector` 使用 Cartesian Å；`radius` 只用于确定横向边界，不用于删原子。

#### 3.2.3 `BaseGenerator` 重构

```python
class Generator(Protocol, Generic[P]):
    """所有生成器遵循的无 I/O 协议。"""

    defect_name: str = "base"
    defect_display: str = "基类"

    # ── 抽象接口 ──
    def generate(self, structure: Structure, params: P) -> GenerationResult:
        """只生成内存结构，不写文件。"""
        ...

    # ── 共享工具方法（从 DS-Gen 提取）──
    def _expand_cell(self, structure: Structure, na: int, nb: int, nc: int) -> Structure: ...
    def _add_vacuum(self, structure: Structure, vacuum: float) -> Structure: ...
    def _build_unit_cell(self, structure_type: str, element: str, a: float, b: float | None, c: float | None) -> Structure: ...
    def _orient_cell(self, structure: Structure, orientation: tuple) -> Structure: ...
    def _lattice_divisor(self, miller: list[int], structure: Structure) -> int: ...
    def _filter_by_min_atoms(self, structures: list[Structure], min_atoms: int) -> tuple[list[Structure], int]: ...

    def _find_valid_interstitial_position(self, positions, cell, min_distance, max_attempts) -> np.ndarray | None: ...

@dataclass
class GenerationResult:
    defect_type: str = ""
    input_count: int = 0
    skipped_count: int = 0
    generated_count: int = 0
    structures: list[Structure] = field(default_factory=list)
    records: list[StructureRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    provenance: Provenance | None = None

    def __add__(self, other: GenerationResult) -> GenerationResult: ...
```

`StructureRecord` 为每个输出保存稳定 ID、父结构哈希、生成参数、随机种子、目标/实际浓度和位点映射。Exporter 在后续阶段为记录追加文件路径和文件哈希。

#### 3.2.4 `GBGenerator` — 本地构建优先

```python
class GBGenerator:
    """从输入体相结构构建晶界；可选使用 MP 晶界作为输入或参考。"""

    defect_name = "grain_boundary"
    defect_display = "晶界"

    def generate(
        self,
        structure: Structure,
        params: GrainBoundaryParams,
    ) -> GenerationResult:
        """参数包括：
            sigma_max: int         最大 Sigma 值（默认 9）
            gb_types: list[str]    晶界类型 ["tilt", "twist"]
            states: list[str]      弛豫状态 ["initial", "final"]
        """
        ...
```

#### 3.2.5 `DopingGenerator` — prior-py 提取设计

**与 SolidSolutionGenerator 的区别**：
- Doping: 小浓度（几个原子），支持多元素组合枚举，允许指定被替换元素
- SolidSolution: 大浓度（at%），SQS 保证无序分布，替换全部指定元素

```python
class DopingGenerator(BaseGenerator):
    """掺杂结构生成器（从 prior-py/doping.py 提取优化）。

    支持：
      - 多掺杂元素组合枚举
      - 多档掺杂原子数（1/2/3个）
      - 指定被替换元素或全部可替换
      - 每个组合生成多个随机位点变体
    """

    defect_name = "doping"
    defect_display = "掺杂"

    def generate(
        self,
        structure: Structure,
        params: DopingParams,
    ) -> GenerationResult:
        """参数包括：
            dopant_elements: list[str]  掺杂元素列表
            dopant_counts: list[int]    掺杂原子数列表 [1, 2, 3]
            n_per_combo: int            每个组合的结构数（不同位点）
            target_elements: list[str] | None  被替换的目标元素（None=全部可替换）
            allow_duplicate: bool       是否允许同一元素多次掺杂
            supercell: tuple[int,int,int] 超胞扩展
            seed: int                   随机种子
        """
        ...
```

---

### 3.3 `orchestration/` + `mcp/` — LLM 无关编排

#### 3.3.1 设计原则

- **MCP 优先**：核心能力作为 MCP tools 暴露，由任意兼容 Host 和模型调用
- **单一工具注册表**：Python API、CLI、MCP 和内置 `ask/chat` 共用同一套强类型定义
- **模型响应归一化**：厂商适配器只负责在厂商消息格式与内部 `ToolCall`/`ToolResult` 之间转换
- **有界执行**：限制最大 Agent 轮数、单次输出结构数、最大原子数和输出目录
- **大对象不进入上下文**：工具返回 artifact ID、摘要和 manifest 路径，不把完整 `Structure` 序列化给 LLM
- **提示词不是安全边界**：参数校验、路径限制、预算和默认检查均由确定性代码执行

#### 3.3.2 Tool 定义清单

| Tool 名称 | 功能描述 | 对应 Python 函数 |
|-----------|---------|-----------------|
| `search_materials` | 搜索 MP 材料（支持多条件过滤） | `MPCollector.search()` |
| `download_structures` | 批量下载结构 | `MPCollector.download_structures()` |
| `fetch_properties` | 批量收集材料性质 | `MPCollector.fetch_properties()` |
| `search_substrates` | 查询基底候选 | `MPCollector.search_substrates()` |
| `search_grain_boundaries` | 查询晶界结构 | `MPCollector.search_grain_boundaries()` |
| `generate_vacancy` | 生成空位缺陷结构 | `VacancyGenerator.generate()` |
| `generate_interstitial` | 生成间隙原子结构 | `InterstitialGenerator.generate()` |
| `generate_doping` | 生成掺杂结构 | `DopingGenerator.generate()` |
| `generate_solid_solution` | 生成固溶体结构 | `SolidSolutionGenerator.generate()` |
| `generate_surface` | 生成表面 Slab | `SurfaceGenerator.generate()` |
| `generate_grain_boundary` | 生成晶界结构 | `GBGenerator.generate()` |
| `generate_interface` | 生成界面结构 | `InterfaceGenerator.generate()` |
| `generate_stacking_fault` | 生成层错结构 | `StackingFaultGenerator.generate()` |
| `generate_dislocation` | 生成位错结构 | `DislocationGenerator.generate()` |
| `check_structures` | 执行默认轻量检查 | `LightStructureChecker.check_batch()` |
| `export_structures` | 导出 POSCAR/CIF/LAMMPS data | `StructureExporter.export()` |
| `query_local_db` | 查询本地性质数据库 | `LocalStore.query()` |
| `list_output_files` | 列出已生成的文件 | `ManifestStore.list_outputs()` |
| `read_structure_info` | 读取结构文件信息 | `utils.get_structure_info()` |

每个生成工具默认在内部完成“生成 → 轻量检查 → 导出 → manifest”，也允许 Python API 用户分别调用这四个阶段。

#### 3.3.3 Provider 协议与工作流执行器

```python
class LLMProvider(Protocol):
    def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
    ) -> ModelTurn: ...


class WorkflowRunner:
    def __init__(
        self,
        provider: LLMProvider,
        registry: ToolRegistry,
        limits: ExecutionLimits,
    ): ...

    def ask(self, user_input: str) -> AgentResult:
        """在 max_turns 内执行工具循环并返回结构化结果。"""
        ...


@dataclass
class ExecutionLimits:
    max_turns: int = 12
    max_structures: int = 1000
    max_atoms_per_structure: int = 100_000
    output_root: Path = Path("./output")
```

MCP Host 直接负责模型对话时，不需要 `LLMProvider` 或内置 Runner；它只连接 `llm-matgen mcp` 并调用同一 Tool Registry。

#### 3.3.4 Skill 定位

可选 Skill 包含：

- 九类生成器的适用场景和参数解释
- “搜索/读取 → 生成 → 默认检查 → 导出 → 汇报”的推荐工作流
- 自然语言示例和常见错误恢复方式
- 项目责任边界与输出解释

Skill 不包含厂商 API Key、不实现生成算法，也不作为参数校验或检查规则的唯一载体。

#### 3.3.5 系统提示词设计

核心要点：
- **角色**：材料结构生成助手，负责将自然语言转化为受约束的生成参数
- **工具使用约束**：
  - 先确认输入结构来源、生成类型、输出格式和输出数量
  - 未指定格式时默认输出 POSCAR
  - 每次生成默认执行轻量检查，检查警告不阻止文件输出
  - 预计超出执行上限时先向用户报告并请求缩小范围
- **输出要求**：
  - 最终输出包含生成统计、格式、文件路径、manifest 路径和检查警告
  - 不将轻量检查解释为稳定性、可合成性或发表质量证明

---

### 3.4 `checks/` — 默认轻量检查

#### 3.4.1 检查维度

轻量检查在每次生成后默认运行，目标是发现格式错误和明显几何问题，不评价结构的科学质量。

| 检查项 | 默认行为 | 结果级别 |
|--------|---------|---------|
| pymatgen 内存结构 | 结构非空、物种和坐标可序列化 | error |
| 晶格 | 有限数值、非奇异、体积为正 | error |
| 分数坐标/占位 | 有限数值、占位合法；坐标规范化 | error/warning |
| 过近原子 | PBC 最小距离，小于可配置阈值 | warning |
| 导出 round-trip | 写出后用对应格式重新读取 | error |
| 原子数/组成一致性 | 导出前后比较组成与原子数 | error |
| 对称性摘要 | 可选记录空间群变化，不判定通过/失败 | info |

键长、配位数和价态分析可作为扩展检查器启用，但不进入 v0.1 默认判定。

#### 3.4.2 接口设计

```python
CheckLevel = Literal["info", "warning", "error"]

@dataclass
class CheckIssue:
    code: str
    level: CheckLevel
    message: str
    site_ids: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

@dataclass
class CheckReport:
    can_export: bool                    # 仅表示能否安全序列化
    n_atoms: int
    formula: str
    issues: list[CheckIssue]
    metrics: dict[str, float | int | str]

class LightStructureChecker:
    def check(
        self,
        structure: Structure,
        reference: Structure | None = None,
        min_distance: float = 0.8,
    ) -> CheckReport: ...
```

规则：

- `warning` 和 `info` 不阻止输出
- `error` 只用于无法可靠导出的硬错误；该结构跳过写出，其他结构继续处理
- 报告不得将 `can_export=True` 描述为结构稳定、合理或可发表

---

### 3.5 `database/` — 本地性质数据库

#### 3.5.1 设计目标

- 缓存 MP 查询结果，避免重复 API 调用
- 支持本地快速查询（元素、带隙、形成能等条件）
- SQLite 存储，零配置，跨平台
- 保留数据库版本、结构哈希与属性来源，避免缓存覆盖后失去复现依据

#### 3.5.2 Schema

```sql
CREATE TABLE IF NOT EXISTS material_snapshots (
    snapshot_id      TEXT PRIMARY KEY,       -- UUID
    material_id      TEXT NOT NULL,
    source_db_version TEXT,
    structure_hash   TEXT,
    formula          TEXT NOT NULL,
    elements_json    TEXT NOT NULL,        -- JSON array
    n_elements       INTEGER NOT NULL,

    -- 基础属性
    density          REAL,
    symmetry_number  INTEGER,

    -- 热力学
    formation_energy_per_atom REAL,        -- eV/atom
    oxidation_states_json     TEXT,        -- JSON dict

    -- 电子结构
    band_gap         REAL,                -- eV
    is_metal         INTEGER,             -- 0/1
    vbm_energy       REAL,                -- eV
    cbm_energy       REAL,                -- eV
    is_direct_gap    INTEGER,             -- 0/1

    -- 磁性
    total_magnetization REAL,             -- μB

    -- 力学
    bulk_modulus     REAL,                -- GPa
    shear_modulus    REAL,                -- GPa

    -- 热学
    debye_temperature     REAL,           -- K
    thermal_conductivity REAL,            -- W/m·K

    -- 元数据
    property_origins_json TEXT NOT NULL,    -- 字段 → 来源端点/计算方法
    raw_json         TEXT,                -- 完整原始 MP 响应
    fetched_at       TEXT NOT NULL        -- ISO 8601
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_material_id ON material_snapshots(material_id);
CREATE INDEX IF NOT EXISTS idx_formula ON material_snapshots(formula);
CREATE INDEX IF NOT EXISTS idx_band_gap ON material_snapshots(band_gap);
CREATE INDEX IF NOT EXISTS idx_formation_energy ON material_snapshots(formation_energy_per_atom);
```

#### 3.5.3 接口设计

```python
class LocalStore:
    """基于 SQLite 的本地材料性质数据库。"""

    def __init__(self, db_path: Path | None = None):
        """db_path=None 时使用默认路径 ~/.llm-matgen/materials.db。"""
        ...

    # ── CRUD ──
    def upsert(self, property_set: PropertySet): ...
    def upsert_batch(self, property_sets: list[PropertySet]): ...
    def get_snapshot(self, snapshot_id: str) -> PropertySet | None: ...
    def get_latest(self, material_id: str) -> PropertySet | None: ...
    def delete_snapshot(self, snapshot_id: str): ...

    # ── 查询 ──
    def query(
        self,
        *,
        elements: list[str] | None = None,  # 必须包含的元素
        n_elements: int | None = None,       # 精确元素数
        band_gap_min: float | None = None,
        band_gap_max: float | None = None,
        formation_energy_max: float | None = None,
        formula_pattern: str | None = None,  # SQL LIKE pattern
        limit: int = 100,
    ) -> list[PropertySet]: ...

    def list_all(self, limit: int = 1000) -> list[str]: ...
    def count(self) -> int: ...

    # ── 导入导出 ──
    def import_from_json(self, path: Path): ...
    def export_to_json(self, path: Path, material_ids: list[str] | None = None): ...
```

---

### 3.6 `io/` — 多格式导出与 manifest

#### 3.6.1 支持格式

| CLI 值 | 文件 | 说明 |
|--------|------|------|
| `poscar` | `POSCAR` 或 `*.vasp` | VASP 结构输入；默认 Direct 坐标，可配置 Cartesian |
| `cif` | `*.cif` | 标准 CIF 结构文件 |
| `lammps-data` | `*.data` | LAMMPS data 结构与原子类型；不包含势函数、pair coefficients 或计算参数 |

同一次任务可选择一个或多个格式。未指定时默认 `poscar`。LAMMPS 导出必须显式记录 `atom_style`、元素到 atom type 的映射和质量；它不是可直接运行的完整 LAMMPS input deck。

```python
OutputFormat = Literal["poscar", "cif", "lammps-data"]

@dataclass
class ExportOptions:
    formats: list[OutputFormat] = field(default_factory=lambda: ["poscar"])
    output_dir: Path = Path("./output")
    poscar_direct: bool = True
    lammps_atom_style: str = "charge"

class StructureExporter:
    def export_structure(
        self,
        structure: Structure,
        structure_id: str,
        options: ExportOptions,
    ) -> ExportResult:
        """导出单个结构并执行格式 round-trip。"""
        ...
```

#### 3.6.2 `manifest.json`

每次运行生成一个运行级 manifest，至少包含：

- `run_id`、创建时间、软件和依赖版本
- 输入来源、原始文件哈希或 MP material ID/数据库版本
- 生成器名称、完整参数、随机种子
- 每个结构的稳定 ID、父结构 ID、组成、原子数和位点映射
- 请求格式、实际输出路径、文件 SHA-256
- 轻量检查结果、跳过原因和执行统计
- “仅负责结构生成，不保证稳定性或发表质量”的责任声明

---

## 4. CLI 设计

### 4.1 命令层级

```
llm-matgen
├── ask <自然语言任务>     可选内置 Provider 的自然语言模式
├── chat                   交互式对话模式
├── mcp                    启动 MCP Server
│
├── search [选项]          搜索 MP 材料
├── download <ids...>      下载结构文件
├── properties <ids...>    收集材料性质
├── substrates <film_id>   查询基底候选
│
├── generate <缺陷类型>    直接生成缺陷结构
│   ├── vacancy
│   ├── interstitial
│   ├── doping
│   ├── solid-solution
│   ├── surface
│   ├── grain-boundary
│   ├── interface
│   ├── stacking-fault
│   └── dislocation
│
├── check <结构文件>       执行非阻断轻量检查
├── export <结构文件>      转换/导出 POSCAR、CIF、LAMMPS data
│
├── db                      本地数据库操作
│   ├── import <material_ids...>
│   ├── query [选项]
│   ├── export [选项]
│   ├── list
│   └── stats
│
└── config                  非敏感配置管理
    ├── set-provider <name>
    ├── set-model <model>
    └── show               显示脱敏后的当前配置
```

API Key 不通过 CLI 明文落盘。MP 与模型厂商密钥从环境变量或系统 keyring 读取。

### 4.2 使用示例

```bash
# LLM Agent 模式（主要使用方式）
llm-matgen ask "从MP搜索LiCoO2，生成5% Co空位和Mn掺杂，默认检查，同时输出POSCAR和CIF"

# 交互式对话
llm-matgen chat

# 直接搜索
llm-matgen search --elements Li Co O --band-gap-min 2.0 --limit 50

# 批量下载
llm-matgen download mp-19017 mp-19033 mp-755322 -o ./structures/

# 性质收集
llm-matgen properties mp-19017 --fields formation_energy,band_gap,elastic

# 直接生成缺陷
llm-matgen generate vacancy --input LiCoO2.vasp --concentration 5.0 --seed 42 --format poscar cif -o ./output/
llm-matgen generate doping --input LiCoO2.cif --dopants Ni Mn --counts 1 2 --format lammps-data

# 单独检查或格式转换
llm-matgen check output/*.vasp
llm-matgen export LiCoO2.cif --format poscar lammps-data -o ./converted/

# 本地数据库
llm-matgen db import mp-19017 mp-19033
llm-matgen db query --elements Li Co O --band-gap-min 2.0
llm-matgen db export -o properties.json
```

---

## 5. 数据流

### 5.1 自然语言模式数据流

```text
用户自然语言输入
        │
        ▼
┌──────────────────────────────────────────────────────┐
│  MCP Host 或 WorkflowRunner                           │
│                                                      │
│  [轮1] LLM → search_materials                        │
│         ← 返回 3 个匹配材料                            │
│                                                      │
│  [轮2] LLM → download_structures                     │
│         ← 返回 artifact ID + 结构摘要                  │
│                                                      │
│  [轮3] LLM → generate_vacancy / generate_doping      │
│         ← 生成 + 默认检查 + 指定格式导出               │
│                                                      │
│  [轮4] LLM → 最终文本回答                              │
│         "生成 150 个结构；3 个几何警告；见 manifest"   │
└──────────────────────────────────────────────────────┘
        │
        ▼
   AgentResult:
     final_text: "生成完成！…"
     artifacts: [结构与输出文件引用]
     manifest_path: ./output/<run_id>/manifest.json
     tool_calls: [工具调用记录]
```

### 5.2 CLI 直接模式数据流

```
llm-matgen generate vacancy --input LiCoO2.vasp --conc 5.0 --seed 42 --format poscar cif
        │
        ▼
CLI 解析参数 → VacancyGenerator.generate(structure, params)
        │
        ▼
GenerationResult:
  - structures: [50 个 pymatgen Structure]
  - records: [50 个 StructureRecord]
  - generated_count: 50
        │
        ▼
默认轻量检查 → Exporter → POSCAR/CIF → manifest.json
```

---

## 6. LLM 提示词与 Skill 设计

### 6.1 系统提示词模板

```markdown
你是材料结构生成助手，负责把自然语言要求转换为工具参数并执行结构生成工作流。

## 可用工具
你有以下工具可用：
- search_materials: 搜索 Materials Project 数据库
- download_structures: 下载晶体结构
- fetch_properties: 收集材料性质（形成能、带隙、弹性常数等）
- search_substrates: 查询薄膜基底候选
- search_grain_boundaries: 查询晶界结构
- generate_vacancy: 生成空位缺陷
- generate_interstitial: 生成间隙原子
- generate_doping: 生成掺杂结构
- generate_solid_solution: 生成固溶体
- generate_surface: 生成表面 slab
- generate_grain_boundary: 生成晶界结构
- generate_interface: 生成界面结构
- generate_stacking_fault: 生成层错
- generate_dislocation: 生成位错
- check_structures: 执行默认轻量格式与几何检查
- export_structures: 导出 POSCAR、CIF 或 LAMMPS data
- query_local_db: 查询本地材料性质数据库
- read_structure_info: 读取结构文件信息

## 工作流规则
1. 输入：确认输入来自 MP、artifact 或本地结构文件
2. 参数：确认生成类型；随机任务未指定 seed 时由系统生成并记录
3. 格式：未指定时输出 POSCAR；允许同时选择 POSCAR/CIF/LAMMPS data
4. 检查：生成后默认执行轻量检查；warning 不阻止输出
5. 规模：预计超过系统上限时先提示用户缩小范围
6. 输出：报告生成统计、格式、文件、manifest 和检查警告

## 领域知识
- Materials Project (MP) 材料 ID 格式为 mp-xxxxx
- 常见晶体结构：岩盐 (NaCl-type)、钙钛矿 (perovskite)、尖晶石 (spinel)、
  层状 (layered, 如 LiCoO2)、萤石 (fluorite)
- 缺陷类型：空位 (随机移除原子)、间隙 (插入轻原子如 H/C/N/O)、
  掺杂 (替换特定元素)、固溶体 (SQS 无序分布)
- 轻量检查仅用于发现格式、晶格、坐标和明显近距离问题
- 检查结果不代表稳定性、可合成性或发表质量

## 输出格式
每次任务完成后输出：
1. 任务摘要（做了什么，生成多少结构）
2. 生成统计（输入数 → 跳过数 → 成功数）
3. 文件清单（关键文件路径）
4. manifest 路径与轻量检查警告
5. 责任说明：本工具只负责生成，用户负责后续弛豫与质量判断
```

---

## 7. 依赖管理

### 7.1 `pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "llm-matgen"
version = "0.1.0"
description = "LLM-driven Material Structure Generation Workflow"
requires-python = ">=3.10"
dependencies = [
    "pymatgen>=2024",
    "mp-api>=0.5",
    "numpy>=1.24",
    "ase>=3.22",
    "pydantic>=2.0",
]

[project.optional-dependencies]
sqs = ["sqsgenerator>=0.5"]
anthropic = ["anthropic>=0.40"]
openai = ["openai>=1.0"]
mcp = ["mcp>=1.0"]
all-llm = ["anthropic>=0.40", "openai>=1.0", "mcp>=1.0"]
dev = [
    "pytest>=7.0",
    "pytest-cov>=4.0",
]

[project.scripts]
llm-matgen = "llm_matgen.__main__:main"

[tool.setuptools.packages.find]
where = ["."]
include = ["llm_matgen*"]
```

发布元数据使用兼容版本范围；仓库同时提交锁文件，CI 和 manifest 记录实际解析版本。至少维护一组经过端到端验证的 Python/依赖版本矩阵。

### 7.2 与 DS-Gen 依赖对比

| 依赖 | DS-Gen | LLM-MatGen | 说明 |
|------|:---:|:---:|------|
| pymatgen | ✅ | ✅ | 核心结构库 |
| ase | ✅ | ✅ | 结构操作辅助 |
| numpy | ✅ | ✅ | 数值计算 |
| mp-api | ❌ | ✅ | MP API 客户端 |
| 模型厂商 SDK | ❌ | 可选 | 不进入核心依赖 |
| MCP SDK | ❌ | 可选 | 推荐的 LLM 工具接入层 |
| pydantic | ❌ | ✅ | 参数、结果和 manifest Schema |
| sqsgenerator | 可选 | 可选 | SQS 生成 |
| PySide6 | ✅ | ❌ | GUI（不迁移） |
| deepmd-kit | ✅ | ❌ | DP 弛豫（不迁移） |
| paramiko | ✅ | ❌ | SSH（不迁移） |
| Jinja2 | ✅ | ❌ | 模板（不迁移） |

---

## 8. 实施阶段规划

### Phase 1: 公共契约 + I/O
1. 初始化 `llm_matgen` 包、强类型参数和 `GenerationResult`
2. 实现 POSCAR/CIF/LAMMPS data 读写、round-trip 和 manifest
3. 实现默认轻量检查及格式测试

### Phase 2: 九类生成器横向覆盖
1. 迁移 BaseGenerator 共享结构操作
2. 接入 Vacancy、Interstitial、Doping、SolidSolution、Surface
3. 接入 GrainBoundary、Interface、StackingFault、Dislocation
4. 每类至少包含一个固定 seed 的黄金样例和输出格式测试

### Phase 3: Sources + CLI/Python API
1. 实现本地结构来源与 MPCollector
2. 完整接入 `generate/check/export` CLI
3. 加入规模上限、路径约束、错误恢复和运行目录

### Phase 4: MCP + 自然语言展示
1. 从 Tool Registry 生成 MCP tools 和 JSON Schema
2. 实现 MCP Server、提示词和 Skill
3. 实现至少一个可选 Provider Adapter 以支持内置 `ask/chat`
4. 对九类生成器建立自然语言端到端演示

### Phase 5: 缓存、集成测试与文档
1. 实现带数据版本和 provenance 的 SQLite 缓存
2. Provider 合约测试、MCP 测试和端到端测试
3. README、API、MCP/Skill 安装说明和九类示例

---

## 9. 风险与注意事项

| 风险 | 缓解措施 |
|------|---------|
| MP API 速率限制 | `_rate_limit()` + 指数退避重试 |
| MP API 数据不完整（部分材料缺声子/介电） | 所有性质字段为 Optional |
| 外部数据源变化影响复现 | manifest 记录 MP 数据库版本、检索时间和原始结构哈希 |
| 九类同时覆盖造成接口分裂 | 先冻结公共参数/结果契约，再迁移各生成器 |
| 组合枚举导致结构数量爆炸 | 强制结构数、原子数、Agent 轮数和输出目录上限 |
| 随机生成不可复现 | 所有随机生成器接受并记录 seed |
| LLM 厂商接口变化 | 核心不依赖厂商 SDK；Provider Adapter 做格式归一化 |
| LLM 误解轻量检查 | 提示词、Tool 描述和 manifest 均声明非稳定性判断 |
| LAMMPS data 被误当完整输入脚本 | 明确只导出结构、类型和质量，不包含势函数或运行参数 |
| 密钥泄露 | 环境变量或系统 keyring；CLI 不保存或回显明文密钥 |
| DS-Gen 生成器移植兼容性 | TDD：先写测试，确保行为一致 |
| sqsgenerator 版本兼容 | 可选依赖，random 模式作为fallback |

---

## 10. v0.1 验收标准

1. 九类生成器均可通过 Python API、CLI 和 MCP Tool 调用，并至少完成一个自然语言端到端示例。
2. 每类生成器使用强类型参数模型；随机生成在相同输入、参数、版本和 seed 下产生相同结构哈希。
3. 用户可选择 `poscar`、`cif`、`lammps-data` 中一个或多个格式；未指定时默认 POSCAR。
4. 每个成功写出的文件均通过对应解析器 round-trip，且原子数和组成保持一致。
5. 每次生成默认执行轻量检查；warning 不阻止输出，无法序列化的结构以 error 记录并单独跳过。
6. 每次运行生成完整 `manifest.json`，包含来源、参数、seed、版本、结构 lineage、文件哈希和检查结果。
7. 核心包在未安装任何 LLM 厂商 SDK、未配置 MP API Key、无网络环境下，仍可对本地结构完成九类生成、检查和导出。
8. 至少两个不同 LLM Host/Provider 能通过同一 Tool Registry 完成相同示例，核心生成器代码无需修改。
9. CLI、Tool 描述、Skill 和 manifest 均明确说明：项目只负责结构生成，不保证稳定性、可合成性或发表质量。
