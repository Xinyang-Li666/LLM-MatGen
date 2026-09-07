# 通用 MD 轨迹非物理结构审查实施计划

设计依据：[2026-08-09-general-trajectory-filtering-design.md](../specs/2026-08-09-general-trajectory-filtering-design.md)

## Task 1：标准帧模型与流式读取

1. 新增 `llm_matgen/trajectories/filtering/models.py`，定义 `FilterFrame`、
   `DetectionResult`、`FrameReview`、`DetectorProfile`，保留完整 cell、pbc、forces、
   source_index、timestep 和 metadata。
2. 新增 `tests/test_trajectory_filter_models.py`，覆盖数组形状、非有限数值、非法原子序数、
   奇异晶胞和可变组成策略；先运行确认失败。
3. 新增 `llm_matgen/trajectories/filtering/readers.py`，使用 ASE `iread` 流式读取
   extxyz、LAMMPS dump、XDATCAR 和 ASE trajectory，支持完整/部分 PBC、三斜晶胞、
   `x/xs/xu` 坐标列和力列。
4. 新增 `tests/test_trajectory_filter_readers.py`，覆盖格式识别、元素映射提示、坐标列、
   三斜 box、部分 PBC、损坏帧和单次迭代读取。
5. 通过后保留现有 `ASETrajectoryReader` 作为采样/转换 API，过滤引擎使用新 reader。

## Task 2：硬检查和几何检测器

1. 新增 `filtering/numeric.py`，实现数值、晶胞、数组形状和组成完整性检查。
2. 新增 `filtering/overlap.py`，基于 ASE neighbor list 和元素共价半径计算元素对最小距离，
   支持覆盖值、绝对下限和违规比例。
3. 新增 `tests/test_filter_numeric.py` 与 `tests/test_filter_overlap.py`，覆盖 NaN/Inf、
   奇异晶胞、正交/三斜/部分 PBC、第 11 个邻居违规、周期平移不变性和元素对覆盖。
4. 使用失败测试驱动实现，确保重叠检查不再依赖完整 NxN 距离矩阵或未排序的 argpartition。

## Task 3：参考标定与统计检测器

1. 新增 `filtering/profiles.py`，实现确定性均匀/蓄水池抽样、profile 版本、参考轨迹哈希和
   元素兼容性检查。
2. 新增 `filtering/force.py`，实现绝对阈值、IQR/MAD 参考阈值及缺失力的
   `not_evaluated` 状态。
3. 新增 `filtering/coordination.py`，实现按元素/元素组的配位统计、稳健边界和零 IQR 处理。
4. 新增 `filtering/cell.py`，实现可选相对体积、伸缩、剪切和条件数检查。
5. 新增对应单元测试，覆盖空/小样本参考、脏参考、元素不兼容、常数数据、缺失力和合法热膨胀。

## Task 4：双遍引擎与安全输出

1. 新增 `filtering/engine.py`，实现第一遍 profile 标定、第二遍逐帧分类和结果聚合，
   不将完整轨迹转换为 list。
2. 新增 `filtering/writers.py`，实现唯一运行目录、extxyz/LAMMPS 输出、JSONL、summary、
   profile 和 manifest 的临时文件原子写入。
3. 新增 `filtering/service.py`，提供统一 `filter_trajectory` 服务，并阻止输入/输出重合、
   路径越界、名称穿越和覆盖已有运行目录。
4. 新增引擎/写入器测试，使用只允许单次迭代的 reader 验证流式行为，覆盖多原因计数、空输出、
   中断写入、路径穿越和输出往返读取。

## Task 5：CLI 与旧接口兼容

1. 在 `llm_matgen/__main__.py` 增加 `--checks`、`--threshold-profile`、`--assume-type-is-z`、
   `--strict`、`--fail-on-anomaly`、输出格式和采样参数，完成参数范围验证和退出码定义。
2. 增加 `--dimensions`、`--force-threshold`、`--n-iqr` 等旧参数适配与弃用警告。
3. 在旧 `llm_matgen.trajectories.filter` 中保留 `FilterConfig`、`FilterResult`、
   `RawFrame`、旧读取函数和 `filter_trajectory` 包装器，内部委托新引擎。
4. 增加 CLI 集成测试，覆盖默认命令、profile/reference 互斥、映射确认、严格模式、
   fail-on-anomaly、JSON 输出和旧参数兼容。

## Task 6：回归、性能与文档

1. 将 TMB2 旧参数固化为 `examples/profiles/tmb2-heating.json`，准备小型脱敏轨迹 fixture。
2. 编写新旧实现逐帧对比报告，解释新增/取消标记及原因。
3. 添加 72 原子 × 100,000 帧和 1,000 原子压力测试，记录速度与峰值内存；普通单元测试不依赖压力测试。
4. 更新 `README.md`、`docs/user-guide.zh-CN.md` 和新增轨迹过滤说明文档。
5. 执行全量单元、集成、CLI、安全检查、编译检查和发布前密钥扫描。

每个 Task 完成后单独运行对应测试并提交一个聚焦提交；不得把现有工作区中无关的实验文件加入提交。
