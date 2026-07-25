# Materials Project 性质与基底文档增强实施计划

依据：`docs/superpowers/specs/2026-07-25-lammps-default-mapping-and-mp-docs-design.md`

## Task 1：补充文档契约测试（RED）

修改或新增 `tests/test_documentation.py`：

1. 检查中文手册包含六类性质名称：`thermo`、`electronic`、`magnetism`、`dielectric`、`phonon`、`elasticity`。
2. 检查手册包含各类代表性字段，如 `energy_above_hull`、`band_gap`、`is_magnetic`、`epsilon_static`、`phonon_dos`、`shear_modulus`。
3. 检查手册说明 `available`、`endpoint`、`method`、`error`。
4. 检查手册说明 `substrates` 使用 MP material ID，并列出 `sub_id`、`sub_form`、`film_orient`、`orient`、`area`、`energy`。
5. 检查手册不引入特定模型厂商或内置模型适配器说明。
6. 运行测试并确认当前手册版本先失败或覆盖不足。

## Task 2：更新中文用户手册（GREEN）

修改 `docs/user-guide.zh-CN.md`：

1. 将 LAMMPS 映射说明改为“显式映射优先，缺失时警告并按原子序数自动映射”。
2. 增加六类 MP 性质的实际 endpoint、典型字段和缺失数据语义。
3. 增加性质结果包装字段说明。
4. 增加基底搜索命令、结构记录语义、典型返回字段和后续界面构造流程。
5. 明确当前 CLI 接受 MP material ID，不把本地结构文件直接伪装成基底查询输入。
6. 保留 API Key 安全、轻量检查和责任声明。

## Task 3：文档与实际接口校验

1. 使用当前 parser 解析手册中的命令示例。
2. 核对 `MPCollector.PROPERTY_ENDPOINTS` 与手册六类性质名称一致。
3. 核对 `search_substrates()` 实际返回模型字段与手册一致。
4. 运行文档契约测试、完整 pytest 和 compileall。

## Task 4：验证与提交

1. 只暂存文档测试、中文手册和本计划涉及的 spec/plan 文件。
2. 提交：`docs: document Materials Project properties and substrates`。

## 完成条件

- 手册准确覆盖六类性质、典型字段和统一结果包装。
- 手册准确说明基底搜索输入、结果字段和能力边界。
- 文档命令与 CLI 实际 parser 一致。
- 不增加未实现的本地结构基底搜索承诺。
