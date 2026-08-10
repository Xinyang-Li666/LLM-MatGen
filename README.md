# LLM-MatGen

## Representative trajectory sampling

The independent `rdf-fps` backend selects structurally diverse frames from
cleaned XYZ, extxyz, VASP-XDATCAR, or LAMMPS trajectories. It combines partial
RDF, coordination/nearest-neighbour, and cell-density features, then applies
deterministic farthest-point sampling. Install the optional reducer with
`python -m pip install -e ".[fps]"` when PCA is enabled.

Cleaning is deliberately a separate step. FPS is a diversity sampler, not a
physical-validity check and it does not guarantee DFT convergence, training
quality, or publication quality. Use proportional source quotas for multi-model
datasets; `selected.extxyz` and the JSON/JSONL audit files are written to a new
run directory. Shared descriptor caches can be resumed and are invalidated by
input hashes, element mappings, or descriptor settings.

Example:

```bash
python -m llm_matgen sample representative trajectory.extxyz \
  --method rdf-fps --count 5000 --allocation proportional \
  --output-root output/tmb2
```

TMB2 source examples without machine-specific paths are in
`examples/sampling/`. RDF-FPS and SOAP-FPS are independent backends and may be
chained by feeding one backend's cleaned/selected extxyz into the other.

Provider-neutral crystal-structure generation for nine generator families.
LLM-MatGen exposes deterministic generators through CLI, Python, and MCP,
performs lightweight structural checks, and exports POSCAR, CIF, or LAMMPS
data files.

LLM-MatGen 是一个由任意兼容客户端驱动的材料晶体结构生成工具包。项目负责生成结构、记录参数与来源并执行默认轻量检查；模型与凭据由外部客户端管理。

> 当前版本：`0.1.0`。生成结果不代表结构已经完成弛豫，也不保证热力学稳定性、动力学稳定性、可合成性或发表质量。

## 功能

| 生成器  | CLI 名称           | 用途                                  |
| ---- | ---------------- | ----------------------------------- |
| 空位   | `vacancy`        | 按数量或浓度删除指定元素                        |
| 间隙原子 | `interstitial`   | 在候选间隙位点插入元素                         |
| 取代掺杂 | `doping`         | 用掺杂元素替换基体元素                         |
| 固溶体  | `solid-solution` | 按组成生成随机或 SQS 固溶体                    |
| 表面   | `surface`        | 按 Miller 指数生成带真空层的表面                |
| 晶界   | `grain-boundary` | 按旋转轴与角度生成晶界                         |
| 界面   | `interface`      | 匹配薄膜和基底并构造界面                        |
| 层错   | `stacking-fault` | 按滑移面和位移矢量生成层错                       |
| 位错   | `dislocation`    | 使用各向同性弹性位移场生成 edge、screw 或 mixed 位错 |

支持读取常见晶体结构文件，并可输出：

- VASP POSCAR（默认）
- CIF
- LAMMPS data

LAMMPS data 仅包含结构和原子类型，不包含势函数或计算参数。

## 安装

需要 Python 3.10 或更高版本。

```bash
git clone <your-repository-url>
cd LLM-MatGen
python -m pip install -e .
```

按需安装可选功能：

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

如果终端找不到 `llm-matgen`，可使用：

```bash
python -m llm_matgen --help
```

## 命令索引

| 命令 | 用途 |
| --- | --- |
| `llm-matgen search` | 搜索 Materials Project 结构 |
| `llm-matgen download` | 下载 Materials Project 结构 |
| `llm-matgen properties` | 查询材料性质 |
| `llm-matgen substrates` | 查询薄膜结构对应的基底候选 |
| `llm-matgen generate` | 使用九类生成器构造结构 |
| `llm-matgen check` | 执行轻量结构检查 |
| `llm-matgen export` | 转换 POSCAR、CIF 或 LAMMPS data |
| `llm-matgen db` | 管理本地数据库快照 |
| `llm-matgen mcp` | 启动 MCP 服务 |
| `llm-matgen config` | 管理非敏感的本地配置 |

使用 `llm-matgen <命令> --help` 查看对应参数。API Key 应通过环境变量或外部客户端管理，不写入本地配置。

## 五分钟快速开始

准备一个包含 Si 的 CIF 文件，并将下面的 `path/to/si.cif` 替换为实际路径。该命令生成一个 Si 空位并写出 POSCAR：

```bash
llm-matgen generate vacancy \
  --input path/to/si.cif \
  --target-element Si \
  --count 1 \
  --variants 1 \
  --seed 7 \
  --format poscar \
  --output-root output
```

Windows PowerShell 可写为一行：

```powershell
llm-matgen generate vacancy --input path/to/si.cif --target-element Si --count 1 --variants 1 --seed 7 --format poscar --output-root output
```

对已有结构执行轻量检查：

```bash
llm-matgen check path/to/si.cif
```

转换输出格式：

```bash
llm-matgen export path/to/si.cif --format cif --output-root output
llm-matgen export path/to/si.cif --format lammps-data --output-root output
```

每次生成都会保存结构文件及可复现信息，包括实际参数、结构哈希、随机种子、来源和 manifest。

## Materials Project

搜索、下载和性质查询需要用户自己的 Materials Project API Key。请只通过环境变量提供，不要写入代码、脚本、README 或提交记录。

Linux/macOS：

```bash
export MP_API_KEY="your-mp-api-key"
llm-matgen search --formula Si
llm-matgen download mp-149 --output-dir downloads
```

Windows PowerShell：

```powershell
$env:MP_API_KEY = "your-mp-api-key"
llm-matgen search --formula Si
llm-matgen download mp-149 --output-dir downloads
```

`.env.example` 只提供变量名和虚假占位符。真实密钥、下载缓存和生成结果不应进入公开仓库。

固溶体支持随机替换和可选 SQS。SQS 需要额外安装 `.[sqs]`，并可用 `--sqs-iterations N` 控制优化迭代次数。SQS 依赖缺失或优化失败时，命令会给出原因并建议使用 `--method random` 继续生成；不会静默回退。

## 任意客户端与 MCP

安装 MCP 可选依赖后启动服务：

```bash
llm-matgen mcp --output-root output
```

MCP 客户端负责选择模型、管理模型凭据并把自然语言请求转换为工具调用。LLM-MatGen 只提供确定性的结构生成、查询、检查和导出工具，因此不绑定特定模型厂商。

九类自然语言工作流示例见 [自然语言工作流](docs/examples/natural-language-workflows.md)，MCP 接口说明见 [MCP 文档](docs/mcp.md)。

## Python 接口

生成器、参数模型、检查器和导出器均可直接作为 Python 库使用。公共接口与最小示例见 [API 文档](docs/api.md)。

## 默认轻量检查

生成流程默认检查格式可读性、晶格有效性、坐标有限性和异常近邻距离。检查结果分为提示、警告和错误：

- 警告用于提醒可能需要人工复核的结构，不等同于计算失败。
- 错误表示文件或几何存在明显问题。
- 轻量检查不是能量计算、结构弛豫、声子计算或稳定性判定。

## 可复现性

- 随机生成器接受 `seed`。
- manifest 记录输入、实际参数、结构哈希和输出文件。
- 达到 `max_structures` 时会截断候选并产生警告。
- 达到 `max_atoms` 时会拒绝继续构建超大结构。
- 相同输入、参数和随机种子应得到确定性结果。

## 责任边界

本项目只负责结构生成与轻量检查。用户需要自行负责：

- 选择合理的材料、晶格、滑移系、界面和边界条件；
- 执行结构弛豫、能量和稳定性计算；
- 选择势函数、DFT 参数及收敛标准；
- 判断结构是否适合实验、工程应用或学术发表。

## 文档

- [中文用户手册](docs/user-guide.zh-CN.md)
- [Python API](docs/api.md)
- [MCP 接口](docs/mcp.md)
- [自然语言工作流](docs/examples/natural-language-workflows.md)
- [项目设计](docs/llm-matgen-design.md)

## 测试

```bash
python -m pytest --import-mode=importlib -q
python -m compileall -q llm_matgen integrations
```

## 多帧数据转换与轨迹采样

DeepMD 数据集可逐帧转换为 POSCAR/CIF/LAMMPS data，并在 manifest 中保留原始帧索引：

```bash
llm-matgen convert deepmd path/to/deepmd \
  --output-root output --format poscar --stride 1
```

长轨迹支持 extended XYZ、XDATCAR 和 LAMMPS dump 的均匀或随机采样：

```bash
llm-matgen sample trajectory XDATCAR \
  --method uniform --count 100 --format poscar --output-root samples
llm-matgen sample trajectory production.dump \
  --method random --count 100 --seed 42 --format cif --output-root samples
```

## MD 轨迹非物理结构审查

轨迹审查使用 ASE 流式读取常见轨迹格式，默认检查数值/晶胞完整性和原子重叠，输出
clean 与 anomalous 轨迹以及逐帧 JSONL 报告：

```bash
llm-matgen filter trajectory production.dump \
  --lammps-element 1=Ti --lammps-element 2=B \
  --output-root output
```

使用干净参考轨迹标定力和配位环境：

```bash
llm-matgen filter trajectory target.dump \
  --reference clean.dump \
  --checks overlap force coordination \
  --output-root output
```

每次执行都会创建唯一运行目录，包含 `clean.extxyz`、`anomalous.extxyz`、
`frame-review.jsonl`、`summary.json` 和阈值 profile。没有元素映射时，程序会提示是否将
LAMMPS type ID 作为原子序数；自动化环境请显式使用 `--assume-type-is-z`。
