# LLM-MatGen v0.1 实施路线图

> 依据：`docs/llm-matgen-design.md` v1.1  
> 原则：TDD、每个任务至少一次提交、核心库不依赖任何 LLM 厂商 SDK  
> 范围：本文件只描述执行顺序和跨计划验收，不替代各子计划

当前状态：计划 1（核心契约、检查与 I/O）已完成；计划 2/3 待开始。由于工作区 git 目录权限受限，任务提交暂无法创建。

## 子计划与执行顺序

| 顺序 | 子计划 | 交付物 | 前置条件 |
|---|---|---|---|
| 1 | `2026-07-23-core-contracts-io-checks.md` | 包骨架、强类型契约、轻量检查、三格式导出、manifest | 无 |
| 2 | `2026-07-23-point-defect-generators.md` | 空位、间隙、掺杂、固溶体 | 计划 1 |
| 3 | `2026-07-23-extended-structure-generators.md` | 表面、晶界、界面、层错、位错 | 计划 1 |
| 4 | `2026-07-23-sources-cli.md` | 本地/MP 来源、CLI、运行目录和执行限制 | 计划 1–3 |
| 5 | `2026-07-23-cache-provenance.md` | SQLite 快照缓存、迁移、导入导出 | 计划 1、4 |
| 6 | `2026-07-23-mcp-orchestration-integration.md` | Tool Registry、MCP、Provider 协议、Skill和端到端文档 | 计划 1–5 |

计划 2 与计划 3 在计划 1 合并后可以并行开发；二者不得修改公共结果契约，确需修改时先回到计划 1 更新契约测试。

## 跨计划文件边界

```text
llm_matgen/
├── generators/       # 计划 1 定契约；计划 2/3 实现九类生成器
├── checks/           # 计划 1
├── io/               # 计划 1
├── sources/          # 计划 4
├── orchestration/    # 计划 6
├── mcp/              # 计划 6
├── database/         # 计划 5
└── __main__.py       # 计划 4；计划 6 添加 ask/chat/mcp 子命令
integrations/
├── providers/        # 计划 5
└── skills/           # 计划 5
tests/
├── fixtures/         # 计划 1 建立，后续计划复用
├── test_generators/  # 计划 2/3
├── test_sources/     # 计划 4
├── test_cli/         # 计划 4/6
└── test_integration/ # 计划 6
```

## v0.1 总体验收命令

在所有子计划完成后，从干净环境执行：

```powershell
python -m pip install -e ".[dev,all-llm,sqs]"
pytest -q
python -m llm_matgen --help
python -m llm_matgen mcp --help
```

随后对仓库内固定 LiCoO2 测试结构执行九类 CLI 示例，检查：

1. 每类命令退出码为 0。
2. 每个运行目录都存在 `manifest.json`。
3. POSCAR、CIF、LAMMPS data 均完成 round-trip。
4. 相同 seed 的重复运行得到相同结构哈希。
5. 未配置模型 SDK、MP API Key且断网时，本地结构生成仍可运行。
6. manifest、CLI 帮助和 Skill 均明确声明：只负责生成，不保证稳定性、可合成性或发表质量。

## 需求追踪

| 设计要求 | 覆盖计划 |
|---|---|
| 九类生成器 | 2、3 |
| POSCAR/CIF/LAMMPS data | 1 |
| 默认非阻断轻量检查 | 1、4 |
| seed、lineage、文件哈希、manifest | 1–3 |
| 本地离线运行 | 1–4 |
| MP 在线来源和版本 provenance | 4、5 |
| CLI/Python API | 1–4 |
| MCP 与任意 LLM | 6 |
| Skill 只承载工作流说明 | 6 |
| 规模/路径/Agent 轮数限制 | 4、6 |
| 缓存 | 5 |
| 端到端文档 | 6 |

## 执行交接

每份子计划单独审批。执行时使用 `executing-plans`；若用户明确要求子代理执行，再使用 `subagent-driven-development`。完成一个子计划并通过其验收后，才进入依赖它的下一份计划。
## 当前执行进度

- 计划 1：✅ 已完成，40 项测试通过，覆盖率 92%。
- 计划 2：✅ 已完成，四类点缺陷生成器及端到端导出通过。
- 计划 3：✅ 已完成（Surface、GrainBoundary、Interface、StackingFault、Dislocation）。
- 计划 4–6：待执行（sources/CLI、cache/provenance、MCP/Skill 集成）。
- Git 提交：工作区 `.git` 当前不可写，提交步骤暂时无法执行。
