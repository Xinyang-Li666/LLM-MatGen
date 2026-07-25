# LAMMPS 默认原子序数映射实施计划

依据：`docs/superpowers/specs/2026-07-25-lammps-default-mapping-and-mp-docs-design.md`

## Task 1：补充失败测试（RED）

修改 `tests/test_readers.py`：

1. 将旧的“无映射必须失败”测试改为“无映射按原子序数读取并产生一次警告”。
2. 增加部分映射测试，验证显式映射优先、缺失 type 按原子序数处理。
3. 增加 type 0、负数和超出元素周期表范围的失败测试。
4. 增加 `atomic` 与 `charge` 两种 LAMMPS atom style 的 fallback 覆盖。
5. 增加 CLI `check` 无映射时继续执行并把警告写入 stderr 的测试。
6. 运行 `python -m pytest tests/test_readers.py tests/test_cli/test_check_export.py -q`，确认新测试先失败。

## Task 2：实现集中式 fallback（GREEN）

修改 `llm_matgen/io/readers.py`：

1. 使用 `pymatgen.core.periodic_table.Element.from_Z` 将未映射 type ID 转为元素符号。
2. 读取所有 atom rows 后再解析映射，使警告可以一次汇总所有缺失 type。
3. 显式 `lammps_element_map` 优先；未提供的 type 使用 atomic-number fallback。
4. 对 type ID 做正整数和元素周期表范围检查，失败时抛出 `StructureReadError`。
5. 使用 `warnings.warn(..., UserWarning)` 每次读取最多发出一次汇总警告。
6. 警告包含自动映射项和显式覆盖提示，但不打印文件内容。
7. 保持 `read_structure(..., lammps_element_map=...)` 签名不变。

## Task 3：更新 CLI 帮助与入口回归

修改 `llm_matgen/__main__.py`：

1. 将 `--lammps-element` 帮助从“必须映射”改为“覆盖映射；缺失 type 按原子序数”。
2. 保持 `check`、`export`、九类生成器共用 reader 行为。
3. 运行聚焦测试并检查 stderr 警告不改变成功退出码。

## Task 4：验证与提交

1. 运行 reader、export、CLI 和相关 source 测试。
2. 运行完整 pytest 与 compileall。
3. 只暂存本计划涉及的代码、测试和帮助文本，提交：
   `feat: infer LAMMPS elements from atomic numbers`

## 完成条件

- 完整/部分缺失映射均可继续读取。
- 显式映射优先，非法 type 明确失败。
- 自动映射发出一次警告。
- 既有显式映射和导出 round-trip 测试保持通过。
