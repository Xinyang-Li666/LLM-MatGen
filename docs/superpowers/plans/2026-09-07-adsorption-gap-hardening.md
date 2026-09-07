# 吸附生成差距补强实施计划

> 依据：已批准的 adsorption/history/viewer 设计，以及对 `wyz-eceshi/LLM-MatGen` 提交 `f7c6c37` 的定向审查。只逐模块吸收算法与测试思路，不覆盖主线已有 trajectory、near-orthogonal surface、case source、revision v2 和 artifact contributor。

## 目标

在进入离线 viewer 与发布整合前，补齐当前 adsorption 生成器在多原子姿态、位点集合、斜晶格验证、历史审计和 DFT 交接方面的差距，同时保持当前公共接口的可迁移性和确定性。

## 明确保留的主线约束

- adsorption 只接收准备好的 slab，不在命令内部隐式生成 surface；
- CLI 锚点使用 1-based，内部只转换一次为 0-based；
- `history=off` 不实例化或打开案例库，生成阶段不访问远程源；
- pipeline 通过窄 artifact contributor 扩展，不按 `defect_type` 字符串散布特判；
- revision v2 为写入默认，v1 仅作为迁移输入；
- 用户路径使用配置或显式参数，不接受个人绝对路径默认值；
- 不新增内置 OpenAI/Anthropic provider 或 API key 要求；
- 版本保持 `0.1.0`，直到发布计划统一更新为 `0.2.0rc1`。

## Task 1：强化 adsorption 输入与参数契约 `[completed]`

**Files:**

- Modify: `llm_matgen/generators/adsorption.py`
- Modify: `tests/adsorption/test_generation_models.py`

1. 写失败测试覆盖多原子吸附物缺少参考轴、零/非有限参考轴、断连分子、非刚性、多齿、charge/spin 不一致和额外字段。
2. 将输入角色规范为 `slab`、`molecule`、可选 `gas_reference`，兼容现有字段名，禁止静默猜测锚点。
3. 增加 `reference_axis`、`charge`、`spin_multiplicity`、`denticity=1`、`rigid=True` 契约；验证完整分子连接图。
4. 增加有界 `azimuths/tilts/rolls/heights`、显式 Cartesian 位点、`max_proposal_attempts`、锚点接触窗口和单侧真空阈值；所有浮点必须有限。
5. 运行定向测试与既有生成器契约测试，提交：`feat: harden adsorption input and pose contracts`。

## Task 2：补齐刚体姿态与算法位点

**Files:**

- Modify: `llm_matgen/adsorption/proposals.py`
- Modify: `tests/adsorption/test_proposals.py`
- Modify: `tests/adsorption/test_history_proposals.py`
- Modify: `tests/adsorption/test_proposal_stream.py`

1. 写失败测试覆盖右手正交局部坐标系、反平行参考轴、anchor 保持、键长保持、roll/tilt/azimuth 和非 z 表面。
2. 实现显式刚体旋转矩阵和 `PoseTransform`，不得用全局 z 轴启发式。
3. 将位点类型规范为 `top/bridge/hollow/hollow4/defect/doped/undercoordinated/explicit`；为 hollow4 和表面缺陷位点提供确定性、有限的发现逻辑。
4. proposal ID、位点排序和 evidence 必须稳定；显式位点只消费一次。
5. 将候选流改为惰性双源预算：历史与算法源均有尝试机会，达到 `max_attempts` 或 `max_structures` 立即停止。
6. 运行 proposal/contract 测试并提交：`feat: add rigid adsorption poses and extended sites`。

## Task 3：强化历史姿态解析与回退审计

**Files:**

- Modify: `llm_matgen/adsorption/proposals.py`
- Modify: `llm_matgen/adsorption/retrieval.py`
- Modify: `tests/adsorption/test_history_proposals.py`
- Modify: `tests/adsorption/test_retrieval.py`

1. 写失败测试覆盖 final local pose、local delta、吸附物图不匹配、原子行数不一致、缺失 revision、冻结 index revision 和 store 异常。
2. 历史 pose 只复用局部表面坐标、旋转和位移；旧 slab 的绝对 Cartesian 坐标不得直接复制。
3. `off` 完全不构造 store；`prefer` 仅在可审计的无匹配/store/pose 错误时回退；`require` 返回稳定错误码和原因。
4. retrieval trace 记录 index revision、候选数、匹配分量、fallback reason 和使用的 revision ID。
5. 运行历史与检索测试，提交：`feat: audit adsorption history pose reuse`。

## Task 4：强化非物理候选验证

**Files:**

- Modify: `llm_matgen/adsorption/validation.py`
- Modify: `tests/adsorption/test_candidate_validation.py`
- Modify: `tests/adsorption/test_fixed_layers.py`

1. 写失败测试覆盖 anchor 接触窗口、非 anchor 碰撞、完整内部距离矩阵、键图变化、吸附物二维自镜像、两侧真空和粗糙表面局部高度。
2. 使用元素共价半径与保守 fallback 计算接触窗口，不以统一固定距离替代不同元素组合。
3. 对任意斜二维晶格先做 Gauss reduction，再进行有界最近晶格矢量搜索；测试包含需要大整数系数的反例。
4. 固定层沿真实法向并支持可配置 `layer_tolerance`；与已有 selective dynamics 取交集，吸附物始终可移动。
5. 增加原子顺序、surface side、coverage、固定 flags、完全相同及对称等价候选去重。
6. 报告继续使用稳定 code、原子索引、阈值和测量值，提交：`feat: harden adsorption geometry validation`。

## Task 5：完善类型化结果和 DFT 交接

**Files:**

- Modify: `llm_matgen/generators/adsorption.py`
- Modify: `llm_matgen/adsorption/package.py`
- Modify: `llm_matgen/io/manifest.py`
- Modify: `tests/test_generators/test_adsorption.py`
- Modify: `tests/adsorption/test_package.py`

1. 写失败测试要求结果保留 clean slab、adsorbate、gas reference、retrieval trace、proposal audit、validation reports 和 DFT handoff。
2. 用户 gas reference 优先；缺省时生成有限周期盒，并保留 charge/spin 与真空仍需用户确认的说明。
3. DFT handoff 明确 clean slab/adsorbed/gas comparison、固定层、coverage、sidedness、dipole、dispersion、magnetism 和 +U 敏感性；不得包含能量或自动计算行为。
4. `combine()` 仅允许相同 slab、adsorbate、gas reference、retrieval 和 DFT 契约的结果合并。
5. artifact contributor 原子写入三个 MSON reference、validation、retrieval、proposal audit 和 handoff；强制 POSCAR/MSON，拒绝会丢失角色或固定信息的 LAMMPS data。
6. 运行 generator/package/manifest 测试并提交：`feat: complete adsorption result and dft handoff`。

## Task 6：差距补强回归验收

1. 运行全部 adsorption、case store、revision、pipeline、exporter 和 manifest 测试。
2. 运行 surface 与 near-orthogonal surface 测试，确保没有被参考实现覆盖或降级。
3. 执行 `surface → 选择 termination → adsorption → artifacts` smoke test。
4. 执行多原子 OH/CO、top/bottom/both、history off/prefer/require 和斜晶格用例。
5. 运行 `python -m compileall -q llm_matgen`、`git diff --check` 和 release safety 扫描。
6. 独立提交发现的回归修复；全部通过后进入 viewer/CLI/MCP 发布计划。

## 完成标准

- 多原子吸附物仅通过显式 anchor/reference axis 进行确定性刚体放置；
- 扩展位点和历史姿态均使用真实表面局部坐标；
- 斜二维晶格、粗糙表面、双侧真空和固定层检查通过反例测试；
- 所有候选与回退行为受预算限制并可从 manifest 审计；
- 不引入硬编码路径、远程生成时访问、provider key 或版本号提前升级；
- trajectory、near-orthogonal surface、revision v2 和旧九类生成器保持通过。
