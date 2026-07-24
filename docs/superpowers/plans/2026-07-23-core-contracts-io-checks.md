# 核心契约、轻量检查与多格式 I/O 实施计划

## 目标

建立可被九类生成器、CLI、MCP 共用的无 LLM 核心：强类型参数/结果、稳定结构 ID、默认轻量检查、POSCAR/CIF/LAMMPS data 导出和运行级 manifest。

## 文件映射

```text
pyproject.toml
llm_matgen/__init__.py
llm_matgen/generators/__init__.py
llm_matgen/generators/base.py
llm_matgen/generators/models.py
llm_matgen/checks/__init__.py
llm_matgen/checks/models.py
llm_matgen/checks/checker.py
llm_matgen/io/__init__.py
llm_matgen/io/readers.py
llm_matgen/io/exporters.py
llm_matgen/io/manifest.py
llm_matgen/utils/__init__.py
llm_matgen/utils/structure.py
tests/conftest.py
tests/fixtures/structures/LiCoO2.cif
tests/test_models.py
tests/test_structure_utils.py
tests/test_checks.py
tests/test_readers.py
tests/test_exporters.py
tests/test_manifest.py
```

## 公共接口

```python
class OutputFormat(StrEnum):
    POSCAR = "poscar"
    CIF = "cif"
    LAMMPS_DATA = "lammps-data"

class CheckLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

class BaseGenerationParams(BaseModel):
    max_structures: PositiveInt = 1000

class RandomGenerationParams(BaseGenerationParams):
    seed: int | None = None

class Provenance(BaseModel):
    generator: str
    generator_version: str
    input_source: str
    input_structure_hash: str
    parameters: dict[str, JsonValue]
    seed: int | None
    created_at: datetime

class StructureRecord(BaseModel):
    structure_id: str
    parent_structure_id: str
    formula: str
    n_atoms: PositiveInt
    actual_parameters: dict[str, JsonValue]
    site_mapping: dict[str, str | None]

@dataclass
class GeneratedStructure:
    structure: Structure
    record: StructureRecord

@dataclass
class GenerationResult:
    defect_type: str
    input_count: int
    skipped_count: int
    generated: list[GeneratedStructure]
    warnings: list[str]
    provenance: Provenance

class Generator(Protocol, Generic[P]):
    defect_name: str
    def generate(self, structure: Structure, params: P) -> GenerationResult: ...

class LightStructureChecker:
    def check(
        self,
        structure: Structure,
        reference: Structure | None = None,
        min_distance: float = 0.8,
    ) -> CheckReport: ...

class StructureExporter:
    def export_structure(
        self,
        structure: Structure,
        structure_id: str,
        options: ExportOptions,
    ) -> ExportResult: ...
```

## Task 1：创建可安装包骨架 ✅ 已完成（提交受 git 权限阻塞）

1. 新建 `tests/test_package.py`，断言 `import llm_matgen` 成功且 `__version__ == "0.1.0"`。
2. 运行 `pytest tests/test_package.py -q`，确认因包不存在失败。
3. 创建 `pyproject.toml`、`llm_matgen/__init__.py` 及空子包；核心依赖仅包含 pymatgen、mp-api、numpy、ase、pydantic。
4. 运行同一测试，确认通过。
5. 提交：`chore: scaffold llm-matgen package`。

## Task 2：定义公共枚举与结果模型 ✅ 已完成（提交受 git 权限阻塞）

1. 在 `tests/test_models.py` 写失败测试：合法 `BaseGenerationParams`、`RandomGenerationParams` 的负/空 seed 行为、`max_structures=0` 拒绝、三种 `OutputFormat`、Provenance JSON round-trip。
2. 运行测试并确认导入失败。
3. 在 `generators/models.py` 实现上述模型；seed 接受所有 Python `int` 或 `None`，`max_structures` 必须大于 0。
4. 添加 `GenerationResult.generated_count` 只读属性和 `combine()`；拒绝合并不同 `defect_type`。
5. 补充合并成功与类型冲突测试并运行通过。
6. 提交：`feat: define generation contracts`。

## Task 3：实现稳定结构哈希与位点 ID ✅ 已完成（提交受 git 权限阻塞）

1. 在 `tests/test_structure_utils.py` 写失败测试：相同结构副本哈希相同、坐标变化后哈希变化、重复调用位点 ID 稳定。
2. 实现 `canonical_structure_payload(structure)`：规范化分数坐标到 `[0,1)`，保留晶格、物种、占位和固定小数精度。
3. 实现 `structure_sha256()` 和 `assign_site_ids()`；site ID 由父结构哈希、原始索引和物种组成。
4. 添加乱序结构测试，明确哈希是“精确表示哈希”而非结构等价哈希；等价去重后续使用 `StructureMatcher`。
5. 运行 `pytest tests/test_structure_utils.py -q`。
6. 提交：`feat: add deterministic structure identity`。

## Task 4：实现轻量检查数据模型 ✅ 已完成（提交受 git 权限阻塞）

1. 在 `tests/test_checks.py` 写 `CheckIssue`、`CheckReport.can_export` 序列化测试。
2. 运行并确认失败。
3. 在 `checks/models.py` 实现 `CheckIssue(code, level, message, site_ids, details)` 与 `CheckReport(n_atoms, formula, issues, metrics)`。
4. 将 `can_export` 实现为“没有 ERROR issue”的只读属性。
5. 运行测试通过。
6. 提交：`feat: define lightweight check reports`。

## Task 5：实现内存结构轻量检查 ✅ 已完成（提交受 git 权限阻塞）

1. 添加失败测试：正常 LiCoO2 无 error、空结构 error、奇异晶格 error、NaN 坐标 error、过近原子 warning。
2. 运行并记录失败。
3. 在 `checks/checker.py` 实现晶格有限性/体积、物种与占位、坐标有限性、PBC 最短距离检查。
4. 确保最短距离 warning 不改变 `can_export=True`。
5. 添加 `reference` 存在时的原子数、组成变化 metrics；不把变化判为错误。
6. 运行 `pytest tests/test_checks.py -q`。
7. 提交：`feat: add non-blocking structure checks`。

## Task 6：实现三格式读取器 ✅ 已完成（提交受 git 权限阻塞）

1. 在 `tests/test_readers.py` 写 POSCAR、CIF、LAMMPS data 读取测试，以及未知扩展名、损坏文件错误测试。
2. 运行并确认失败。
3. 实现 `read_structure(path, fmt=None) -> Structure`；显式格式优先，自动检测只处理已支持扩展名。
4. 为 LAMMPS data 要求调用方提供或从文件恢复元素映射；无法可靠恢复时抛出 `StructureReadError`。
5. 运行测试通过。
6. 提交：`feat: add supported structure readers`。

## Task 7：实现 POSCAR 与 CIF 导出和 round-trip ✅ 已完成（提交受 git 权限阻塞）

1. 在 `tests/test_exporters.py` 写 POSCAR/CIF 导出失败测试：文件存在、可重读、组成与原子数一致。
2. 实现 `ExportOptions`、安全文件名和运行目录内路径解析。
3. 实现 POSCAR/CIF 写出、重读和 SHA-256；round-trip 不一致记为 ERROR 并从成功文件列表排除。
4. 添加目标文件已存在时使用确定性序号且不静默覆盖的测试。
5. 运行相关测试通过。
6. 提交：`feat: export poscar and cif artifacts`。

## Task 8：实现 LAMMPS data 导出 ✅ 已完成（提交受 git 权限阻塞）

1. 写失败测试：`atom_style="charge"` 输出、元素到 type 映射、质量、重读原子数/组成。
2. 实现 LAMMPS data 导出；拒绝不支持的 `atom_style`。
3. 在导出元数据中记录 `atom_style`、type map、masses，并明确 `contains_force_field=False`。
4. 添加部分占位结构无法导出的错误测试。
5. 运行 `pytest tests/test_exporters.py -q`。
6. 提交：`feat: export lammps data structures`。

## Task 9：实现 manifest ✅ 已完成（提交受 git 权限阻塞）

1. 在 `tests/test_manifest.py` 写失败测试：运行元数据、结构 lineage、三格式文件哈希、检查 issue、免责声明。
2. 实现 Pydantic `RunManifest`、`ManifestArtifact`、`ManifestStore.write_atomic()`。
3. 使用临时文件加同目录原子替换写入，避免中断留下半个 JSON。
4. 添加重复写入同一 `run_id` 拒绝覆盖测试。
5. 运行测试通过。
6. 提交：`feat: write reproducible run manifests`。

## Task 10：贯通生成结果、检查、导出 ✅ 已完成（提交受 git 权限阻塞）

1. 创建测试用 `IdentityGenerator`，写失败测试验证“生成 → 默认检查 → 多格式导出 → manifest”。
2. 实现 `GenerationPipeline.run(generator, structure, params, export_options)`。
3. 确保 warning 结构仍输出；error 结构仅跳过自身；统计和 manifest 正确。
4. 添加全部结构 error 时仍生成 manifest、命令结果为失败状态的测试。
5. 运行 `pytest tests/test_models.py tests/test_checks.py tests/test_exporters.py tests/test_manifest.py -q`。
6. 提交：`feat: connect generation export pipeline`。

## Task 11：锁定依赖并完成本计划验收 ✅ 已完成（提交受 git 权限阻塞）

1. 在 `pyproject.toml` 添加 `dev` 依赖：pytest、pytest-cov、pip-tools。
2. 生成并提交 `requirements/lock-py312.txt`。
3. 从新 Python 3.12 虚拟环境按锁文件安装并运行 `pytest -q`。
4. 运行 `pytest --cov=llm_matgen --cov-report=term-missing`，核心契约、checks、io 分支覆盖率不低于 90%。
5. 确认核心安装未引入 anthropic/openai/mcp SDK。
6. 提交：`test: verify core contracts and io`。

## 本计划完成条件

- 三种格式均有 happy path、损坏输入、round-trip 失败测试。
- warning 不阻断输出，error 只跳过对应结构。
- 相同 seed/输入可记录相同结构哈希。
- manifest 含责任声明、lineage、版本和文件哈希。
- 公共类型没有 `dict` 形式的未校验入口；开放元数据字段限定为 JSON value。
