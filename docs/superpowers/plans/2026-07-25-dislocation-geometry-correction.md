# 位错几何与原子数守恒修复实施计划

> 执行原则：按 TDD 顺序实施；先写失败测试，再修改生成器。DS-GEN 只作为行为参照，不直接复制其轴定义不一致的实现。

## 已确认的根因

Nb 复现案例使用常规 BCC 晶胞（2 原子）、`radius=15 Å`。当前实现得到 `10×10×1` 超胞，共 200 原子，随后由
`keep = distance_to_line <= radius` 删除 24 个外圈原子，最终输出 176 原子。

此外，当前实现先扩胞，再用扩胞后的晶格解释 `[111]`。由于扩胞倍率为 `10×10×1`，实际局部位错线变成近似
`[0.7053, 0.7053, 0.0705]`，与输出晶胞的周期轴夹角约 `85.96°`。因此，仅删除 `keep` 掩码不足以修复结构。

DS-GEN 的可复用不变量是：

1. 先按位错几何定向晶胞；
2. 仅在垂直位错线的两个方向扩胞；
3. 对完整超胞的全部原子施加位移；
4. 位移前后原子数严格相等。

DS-GEN 的注释中“a 方向是位错线”与实际对 z 坐标施加 screw 位移并不完全一致，因此不复制其 preset/轴编号。

## 文件范围

- 修改：`llm_matgen/generators/dislocation.py`
- 修改：`tests/test_generators/test_dislocation.py`
- 修改：`docs/user-guide.zh-CN.md`
- 修改：`docs/llm-matgen-design.md`
- 回归输入：`test-results/live-representative-fc7d1e08c32c/downloads/mp-75.cif`

## Task 1：用测试固定 Nb 回归与几何不变量

1. 在 `tests/test_generators/test_dislocation.py` 增加一个完全离线的 BCC Nb fixture：
   - `a = 3.317632378768019 Å`；
   - 常规 `Im-3m` 晶胞；
   - `[111]` screw；
   - `a/2[111]` Cartesian Burgers 矢量；
   - `(1 -1 0)` 滑移面；
   - `radius=15 Å`。
2. 增加失败测试 `test_bcc_111_screw_preserves_all_oriented_supercell_atoms`：
   - 比较施加位移前的定向超胞原子数与输出原子数；
   - 断言二者相等；
   - 禁止以“screw 与 edge 原子数相等”代替真正的输入/输出守恒断言。
3. 增加失败测试 `test_bcc_111_screw_aligns_line_with_periodic_axis`：
   - 将输入 `[111]` 用原始晶格转换为 Cartesian 方向；
   - 断言输出晶格的周期轴与该方向平行；
   - 断言误差使用归一化叉积，不比较未经归一化的向量。
4. 增加失败测试 `test_dislocation_radius_sets_minimum_cross_section_without_cropping`：
   - 两个横向投影宽度均不小于 `2 * radius`；
   - 输出不再是带空洞的“圆柱掩码 + 矩形晶格”。
5. 运行：

   ```powershell
   python -m pytest tests/test_generators/test_dislocation.py -q
   ```

   预期：新增的原子数和轴对齐测试先失败，证明测试捕获了当前缺陷。

## Task 2：分离方向解析、晶胞定向和位移三个阶段

1. 在 `llm_matgen/generators/dislocation.py` 增加私有几何辅助函数，职责分别为：
   - 将 `line_direction` 由原始直接晶格转换为 Cartesian；
   - 将 `slip_plane` 由原始倒易晶格转换为 Cartesian 法向；
   - 构造以位错线为第三个晶格轴的整数晶胞变换；
   - 计算横向投影宽度及扩胞倍率。
2. 所有方向必须在扩胞前由原始晶格解释，禁止使用已经乘过 repetition 的晶格解释 Miller 指数。
3. 晶胞变换必须满足：
   - 第三个晶格矢量与 `line_direction` 平行；
   - 变换矩阵为非奇异整数矩阵；
   - 定向后原子数等于原始原子数乘以变换矩阵行列式绝对值；
   - 不通过浮点坐标枚举和经验距离去重来“猜”原子数。
4. 使用滑移面法向和位错线建立正交局部基：
   - `e3`：位错线；
   - `e2`：滑移面法向；
   - `e1 = e2 × e3`；
   - 对三者重新归一化并检查正交性。
5. 把 Burgers 矢量明确作为 Cartesian Å 输入；在 `generate()` 获得原始晶格后校验：
   - screw：`b` 与 `e3` 平行；
   - edge：`b` 与 `e3` 垂直；
   - mixed：同时含平行和垂直分量。
6. `DislocationParams` 继续做与晶格无关的有限值、范围和 Miller 指数校验；删除“Cartesian Burgers 矢量与 Miller 整数直接点乘/叉乘”的校验。

## Task 3：取消圆柱删原子并明确 radius 语义

1. 定向后仅对前两个晶格方向扩胞，第三个周期方向 repetition 固定为 1。
2. 将 `radius` 定义为“位错芯到横向边界的最小目标距离”，据横向投影宽度计算 repetition。
3. 删除 `keep` 掩码、`local_points[keep]`、筛选后的 species 构造逻辑。
4. 对定向超胞的全部原子计算并施加位移。
5. 构造输出后立即检查：
   - 输出原子数等于位移前原子数；
   - species 计数完全一致；
   - 坐标均为有限值；
   - 不满足时抛出明确的内部一致性错误。
6. 在 `actual_parameters` 中记录：
   - 整数定向矩阵；
   - 横向 repetition；
   - 位错线对应的周期轴；
   - 位移前/后原子数；
   - `radius` 的 `minimum_boundary_distance` 语义。
7. 保留当前输出格式兼容性；不在本修复中引入位错偶极子、四极子或结构弛豫。

## Task 4：补充回归测试与格式往返

1. 增加 screw、edge、mixed 三类的原子数守恒参数化测试。
2. 增加非 `[001]` 位错线测试，确保扩胞倍率变化不会改变方向解释。
3. 对 Nb 回归结构分别导出并读回 POSCAR 与 LAMMPS data：
   - 两种格式原子数等于内存结构；
   - 元素计数一致；
   - 晶格和坐标为有限值。
4. 保留现有解析场单点公式测试，确保重构没有改变各向同性位移公式。
5. 运行：

   ```powershell
   python -m pytest tests/test_generators/test_dislocation.py tests/test_io -q
   ```

## Task 5：更新用户可见契约

1. 在 `docs/user-guide.zh-CN.md` 中说明：
   - `line_direction` 和 `slip_plane` 是晶格指数；
   - `burgers_vector` 是 Cartesian Å；
   - `radius` 控制最小横向尺寸，不会裁掉外圈原子；
   - 单位错结构仍需用户自行选择边界条件并进行弛豫。
2. 在 `docs/llm-matgen-design.md` 中记录“定向 → 横向扩胞 → 全量位移 → 守恒检查”的生成流程。
3. 删除或修正文档中把 `to_unit_cell=True` 等同于“位错拓扑必然正确”的表述。

## Task 6：真实 Nb 回归验收

1. 复用本地 `mp-75.cif`，不得在单元测试中访问网络。
2. 重新生成 `[111]` screw 结构。
3. 输出验收摘要：
   - 原始、定向、扩胞、最终原子数；
   - 定向矩阵和 repetition；
   - 位错线与周期轴夹角；
   - POSCAR/LAMMPS data 读回原子数。
4. 运行完整测试：

   ```powershell
   python -m pytest --import-mode=importlib -q
   python -m compileall -q llm_matgen integrations
   ```

## 完成条件

- Nb 输出不再从完整超胞删除 24 个原子。
- `[111]` 位错线与声明的周期轴平行，而不是约 `85.96°`。
- 所有位错类型在位移前后保持原子数和组成不变。
- POSCAR 与 LAMMPS data 往返保持原子数。
- 全量测试通过，文档与参数实际语义一致。
