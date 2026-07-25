# LLM-MatGen 发布加固与 SQS 实施计划

## 目标

在保持结构生成责任边界不变的前提下，移植 DS-GEN 的 SQS 适配逻辑，修复已发现的间隙候选距离问题，完善发布安全、许可证和文档一致性。

## 发布范围

纳入：核心源码、对应单元测试、README/中文手册、MIT License、发布安全扫描器及其测试。

不纳入：`tests/nl-tests/` 的运行状态、下载缓存、生成输出、来源未记录的 `inputs/` fixture、旧的内部审查报告和一次性脚本。

## 实施任务

### 1. SQS 参数与错误契约（TDD）

- 为 SQS 成功路径、缺少 `sqsgenerator`、优化失败和 random 模式编写失败测试。
- 将 `SolidSolutionParams` 增加显式 SQS 迭代参数，保持比例离散化和 seed 可复现。
- SQS 失败时返回明确错误，错误信息建议使用 `--method random`；不自动回退。
- 保留可选依赖边界，未安装依赖时不影响核心功能。

### 2. DS-GEN SQS 适配器（TDD）

- 在 `SQSBackend` 中移植 DS-GEN 的 inline structure 配置、`parse_config` 检查、`optimize`、0.5.x 手动 pymatgen 转换和单线程 seed 配置。
- 将 SQS 输出转换为 `GeneratedStructure`、`StructureRecord` 和 provenance 所需的实际参数。
- 支持 variants、最大结构数和最大原子数限制；每个 variant 使用由用户 seed 派生的确定性 seed。
- 增加真实安装环境下的最小 SQS 集成测试，并用 mock 覆盖未安装依赖和错误路径。

### 3. 结构生成器修复（TDD）

- 修复 interstitial 随机候选之间的分数坐标距离计算，并增加非正交晶格回归测试。
- 保留 vacancy 缺省参数的显式 `ValueError`，增加 API 层测试。
- 复核现有 solid-solution 测试，确保 random 与 SQS 的错误契约不冲突。

### 4. 发布安全与许可证（TDD）

- 扩展安全扫描器，识别 JSON 转义的 Windows 绝对路径、个人路径、命名密钥赋值和已知密钥模式；报告只输出规则与路径。
- 增加 MIT License 文件，并在 `pyproject.toml` 元数据中声明许可证。
- 增加测试确保 `.env.example`、忽略规则、许可证和扫描器行为一致。

### 5. 文档一致性

- README 与中文手册说明 SQS 的安装、迭代参数、失败提示和 random 替代路径。
- 删除或改写不存在的 `llm-matgen ask` 示例，统一描述外部 LLM 客户端/MCP 调用。
- 明确 SQS 仅表示算法输出，不代表弛豫、稳定性或发表质量。
- 保持不出现真实密钥、个人路径和自然语言测试运行产物。

### 6. 最终验证与发布白名单

- 运行默认 `pytest -q`、编译检查、文档测试、SQS 定向测试和安全扫描。
- 只暂存上述发布范围文件，排除自然语言测试产物、下载缓存、生成结构、来源不明 fixture 和用户未确认修改。
- 复核 staged blob、Git 历史密钥扫描、许可证和测试结果后，再等待最终推送确认。

## 验收标准

- SQS 成功、缺依赖、失败和 random 替代路径均有测试。
- interstitial 非正交晶格候选不违反最小距离约束。
- 默认全量测试通过，且不依赖 SQS/MCP 可选包是否安装。
- LICENSE、README、用户手册和项目元数据一致。
- 发布白名单不包含密钥、个人路径、下载缓存、输出产物或来源不明 fixture。
