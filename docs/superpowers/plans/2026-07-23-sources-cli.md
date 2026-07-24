# 结构来源与 CLI 实施计划

## 目标

实现本地/Materials Project 结构来源、结构类别后筛选、统一运行服务和完整 CLI。所有 `generate` 命令默认执行轻量检查并导出 manifest。

## 文件映射

```text
llm_matgen/sources/__init__.py
llm_matgen/sources/models.py
llm_matgen/sources/local.py
llm_matgen/sources/mp.py
llm_matgen/sources/classifier.py
llm_matgen/services/__init__.py
llm_matgen/services/generation.py
llm_matgen/config.py
llm_matgen/__main__.py
tests/test_sources/test_local.py
tests/test_sources/test_mp.py
tests/test_sources/test_classifier.py
tests/test_services/test_generation.py
tests/test_cli/test_search.py
tests/test_cli/test_generate.py
tests/test_cli/test_check_export.py
tests/test_cli/test_config.py
```

## 接口

```python
class StructureSource(Protocol):
    def get(self, reference: str) -> SourceStructure: ...

class SourceStructure(BaseModel):
    artifact_id: str
    source_kind: Literal["local", "materials-project"]
    source_reference: str
    structure_hash: str
    database_version: str | None
    retrieved_at: datetime
    local_path: Path | None

class MaterialSearchQuery(BaseModel):
    elements: list[str] | None = None
    chemsys: str | None = None
    formula: str | None = None
    material_ids: list[str] | None = None
    n_elements: PositiveInt | None = None
    formation_energy_max: float | None = None
    band_gap_min: NonNegativeFloat | None = None
    band_gap_max: NonNegativeFloat | None = None
    structure_class: Literal["layered", "perovskite", "spinel", "rocksalt", "fluorite"] | None = None
    limit: PositiveInt = 100

class ExecutionLimits(BaseModel):
    max_structures: PositiveInt = 1000
    max_atoms_per_structure: PositiveInt = 100_000
    output_root: Path
```

## Task 1：本地结构来源

1. 写失败测试：读取 POSCAR/CIF/LAMMPS data，返回统一 `SourceStructure` 和内存 `Structure`。
2. 实现格式检测并复用 `io.readers`。
3. 添加不存在、目录路径、损坏文件、符号链接逃出允许根目录测试。
4. 实现 `allowed_roots` 解析，所有路径先 `resolve()` 再验证。
5. 提交：`feat: add local structure source`。

## Task 2：MP 客户端依赖注入与错误模型

1. 写 fake `MPRester` 测试，定义 `MPClientFactory` Protocol。
2. 实现 `MPCollector(api_key=None, client_factory=...)`，API Key 只从参数或 `MP_API_KEY` 环境变量读取。
3. 定义 `MPAuthenticationError`、`MPRateLimitError`、`MPUnavailableError`、`MPDataError`。
4. 添加无 key、401/403、429、5xx、超时和 malformed response 测试。
5. 提交：`feat: establish materials project client boundary`。

## Task 3：MP 搜索与分页/上限

1. 写失败测试：formula、chemsys、elements、能量/带隙筛选映射到 summary endpoint。
2. 实现 `search(query) -> list[MaterialSummary]`，结果按 material ID 稳定排序并强制 `limit`。
3. 添加互斥/冲突条件测试：`band_gap_min > band_gap_max`、空 query、超系统上限。
4. 实现分页迭代，不在内存中无限累计。
5. 提交：`feat: search materials project structures`。

## Task 4：MP 下载与 provenance

1. 写失败测试：下载结构、跳过已存在文件、数据库版本、检索时间和结构哈希。
2. 实现先写临时文件再原子替换，文件名使用 material ID。
3. 已存在文件只有在 manifest/hash 匹配时才跳过；否则生成不覆盖的新版本路径。
4. 添加部分批次失败测试，成功项保留、失败项结构化返回。
5. 提交：`feat: download mp structures reproducibly`。

## Task 5：MP 性质和特殊查询

1. 为 thermo/electronic/magnetism/dielectric/phonon/elasticity/substrates/grain_boundaries 编写 fake endpoint 合约测试。
2. 实现批量 `fetch_properties()`，每个属性记录 endpoint/计算方法来源。
3. 缺失属性保持 `None` 并记录 unavailable，不把整个材料判为失败。
4. 实现 substrate 和 grain-boundary 查询；它们只提供来源数据，不替代本地生成器。
5. 提交：`feat: collect mp properties and references`。

## Task 6：重试、速率限制与取消

1. 用 fake clock 写 429/5xx 指数退避测试；断言尊重 `Retry-After`。
2. 实现最大尝试数、带 jitter 的退避和请求间隔。
3. 4xx 参数错误不重试；取消信号立即停止批次。
4. 添加重试耗尽后保留原始异常链测试。
5. 提交：`feat: harden mp request execution`。

## Task 7：结构类别后筛选

1. 为 layered/perovskite/spinel/rocksalt/fluorite 写固定 fixture 分类测试。
2. 定义 `StructureClassifier` Protocol 和 `ClassificationResult(label, matched, score, method, evidence)`。
3. 实现基于明确结构算法/局部环境的分类器；不允许使用 formula 名称或 LLM 猜测。
4. 搜索带 `structure_class` 时先取结构再后筛选，并在结果中返回分类依据。
5. 添加无法分类和分类器异常测试；记为 unknown 而非匹配。
6. 提交：`feat: classify downloaded crystal structures`。

## Task 8：统一生成服务

1. 写失败测试：`GenerationService.run(request)` 解析 source、选择 generator、检查上限、调用 pipeline。
2. 定义 `GenerationRequest(generator, input_refs, parameters, export_options, limits)`。
3. 实现 generator registry，九个稳定名称与参数模型一一对应。
4. 估算超限时在生成前拒绝；生成过程中再次检查实际结构数/原子数。
5. 添加未知 generator、参数 schema 错误、双输入 interface 缺 substrate 测试。
6. 提交：`feat: add unified generation service`。

## Task 9：CLI 骨架和帮助

1. 写 `python -m llm_matgen --help`、各子命令帮助快照测试。
2. 使用 argparse 实现 `search/download/properties/substrates/generate/check/export/db/config` 层级。
3. 九个 generate 子命令由参数模型元数据生成公共选项，特有参数显式定义。
4. CLI 错误输出到 stderr，成功摘要输出到 stdout；定义 0/2/3/4 退出码：成功/参数错误/部分失败/系统失败。
5. 提交：`feat: scaffold llm-matgen cli`。

## Task 10：九类 generate CLI

1. 为九类命令各写至少一个解析测试，确认百分数转小数、seed、多个格式和输出目录。
2. 接入 `GenerationService`。
3. 默认格式为 POSCAR；默认检查不可通过普通生成命令关闭。
4. 接口命令要求 `--film` 和 `--substrate`；其他生成器要求单 `--input`。
5. 添加结构上限、原子上限和输出根逃逸测试。
6. 提交：`feat: expose all generators through cli`。

## Task 11：check/export CLI

1. 写 `check` 的 warning 退出码 0、error 退出码 3 测试。
2. 写 `export` 的单/多格式、round-trip 和已有文件测试。
3. 实现批量 glob 由 shell/调用方展开；CLI 本身接受明确路径列表，避免跨平台 glob 差异。
4. 每次 export 也生成 manifest 并包含来源哈希。
5. 提交：`feat: add check and export commands`。

## Task 12：安全配置

1. 写 `config set-provider`、`set-model`、`show` 测试。
2. 实现用户配置文件只保存非敏感字段；原子写入并限制文件权限（平台能力允许时）。
3. `show` 对包含 key/token/secret 的环境和配置字段统一脱敏。
4. 明确拒绝 `config set-key`，错误信息指导使用环境变量或系统 keyring。
5. 提交：`feat: manage non-sensitive cli configuration`。

## Task 13：CLI 端到端验收

1. 在无网络、无 API Key 环境运行九类本地 fixture 命令。
2. 每类至少选择 POSCAR，并轮换覆盖 CIF/LAMMPS data；检查所有 manifest。
3. 使用 fake MP server 运行 search/download/properties，不访问真实服务。
4. 运行 `pytest tests/test_sources tests/test_services tests/test_cli -q`。
5. 确认命令中断后已完成文件和 manifest 可诊断，且无半写文件。
6. 提交：`test: verify sources and cli workflows`。

## 本计划完成条件

- 本地九类生成不需要网络或 API Key。
- “层状”等术语由确定性分类器后筛选并附证据。
- CLI 默认检查、默认 POSCAR、可多格式导出。
- 路径、结构数和原子数限制同时在入口和执行层生效。
- 密钥不进入配置文件、日志、manifest 或 CLI 回显。

## 执行状态

- Task 1（本地结构来源）：✅ 已完成
- Task 2（MP 客户端边界与错误模型）：✅ 已完成
- Task 3（MP 搜索与分页上限）：✅ 已完成
- Task 4（MP 下载与 provenance）：✅ 已完成
- Task 5（MP 性质与特殊查询）：✅ 已完成
- Task 6（重试、速率限制与取消）：✅ 已完成
- Task 7（确定性结构类别后筛选）：✅ 已完成
- Task 8（统一生成服务）：✅ 已完成
- Task 9–13：待执行
