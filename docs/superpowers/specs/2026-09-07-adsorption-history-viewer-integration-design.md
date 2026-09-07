# 表面吸附、历史案例复用、人工修订与结构查看器整合设计

- 日期：2026-09-07
- 状态：设计已确认，待实施计划
- 目标版本：`0.2.0`
- 参考实现：`llm_matgen-0.2.0` 源码包
- 当前主线：LLM-MatGen 本地开发树（包含轨迹过滤、RDF/SOAP-FPS 与近正交表面晶胞）

## 1. 背景

参考源码包新增了以下能力：

1. 表面吸附初始构型生成；
2. 历史吸附计算案例的扫描、索引、检索和几何复用；
3. slab 底层原子固定；
4. 吸附专项几何检查；
5. 人工坐标修订的校验和谱系追溯；
6. 生成后离线查看球棍模型。

参考实现相关测试具有较好覆盖：吸附、案例复用、revision 和 viewer 定向测试共 147 项通过；源码包全量测试为 323 项通过、1 项跳过，唯一失败来自源码包不包含 `.git`，导致发布安全测试无法执行 `git ls-files`，并非功能错误。

参考实现基于较早的 LLM-MatGen 主线，不能直接覆盖当前工作树。当前本地版本还包含尚未出现在参考包中的轨迹处理、代表性采样、性能优化、POSCAR 修复和近正交表面晶胞功能。因此本次采用“向前移植并重构公共接口”，不采用目录覆盖或整体替换。

## 2. 目标

### 2.1 功能目标

- 将 adsorption 作为正式的第十类结构生成器；
- 只接收已经准备好的 clean slab，不在 adsorption 命令内部隐式生成表面；
- 支持单原子和刚性、连通、单锚点分子吸附物；
- 支持 top、bridge、hollow、缺陷/掺杂/低配位等算法位点及显式位点；
- 支持 top、bottom 和 both 表面方向；
- 支持吸附高度、方位角、倾角和滚转角组合；
- 支持可配置的历史案例源和确定性检索复用；
- 支持固定 slab 最底部若干原子层；
- 对候选执行吸附专项检查和已有轻量结构检查；
- 支持多原子人工修订及完整 parent→child 追溯；
- 所有结构生成流程默认产生一个离线 `viewer.html`；
- 通过 CLI、Python 和 MCP 提供一致的能力。

### 2.2 工程目标

- 保留当前九类生成器、轨迹过滤、RDF/SOAP-FPS 和近正交表面功能；
- 不引入用户专属服务器、用户名、SSH wrapper 或绝对路径；
- 默认配置跨 Windows、Linux 和 macOS；
- 不保存密码、API token 或私钥内容；
- 保持旧 manifest、旧生成命令和单原子 revision sidecar 可读；
- 结构生成、检查、导出、manifest 和 viewer 由统一 pipeline 管理；
- 所有历史复用行为均可审计并可关闭。

## 3. 非目标与责任边界

本阶段不实现：

- 从体相结构到 slab 再到吸附的一条隐式命令；
- 多锚点、多齿吸附；
- 分子构象搜索或柔性吸附物优化；
- ML/LLM 吸附能预测或模型训练；
- 自动提交 VASP、生成 POTCAR 或运行 DFT；
- 从单个总能自动计算吸附能；
- 自动宣称全局最低能位点；
- 将未经 DFT 验证的人工修订自动加入优质历史案例；
- 为大型轨迹清洗或 FPS 采样结果自动生成 viewer。

生成结果始终标记为 `initial_configuration`。结构是否适合后续计算或发表由用户负责。

## 4. 总体架构

```text
用户 / LLM / MCP
       |
       +--> generate surface --------------+
       |                                    |
       |                         slab artifact + manifest
       |                                    |
       +--> generate adsorption <-----------+
                    |
        +-----------+------------+
        |                        |
  历史案例候选                算法几何候选
        |                        |
        +-----------+------------+
                    |
             刚体吸附物放置
                    |
         固定层 + 吸附专项几何检查
                    |
         通用检查 + 去重 + 数量限制
                    |
    POSCAR/MSON/CIF + manifest + viewer
```

历史案例子系统与生成器通过稳定接口连接：

```text
本地目录源 ----+
               +--> CaseSource --> 只读快照 --> 案例提取 --> SQLite 索引
SSH 目录源 ----+                                      |
                                                      +--> 确定性检索
```

建议新增或移植的包：

```text
llm_matgen/
├── adsorption/
│   ├── models.py
│   ├── sources/
│   │   ├── base.py
│   │   ├── local.py
│   │   └── ssh.py
│   ├── extractor.py
│   ├── schema.py
│   ├── store.py
│   ├── retrieval.py
│   ├── proposals.py
│   ├── validation.py
│   ├── revision.py
│   └── package.py
├── generators/
│   └── adsorption.py
└── viewer/
    ├── __init__.py
    └── assets/
```

`package.py` 不再维护另一套完整输出流程，只实现 adsorption 专属 artifact 扩展，并由通用 `GenerationPipeline` 调用。

## 5. 表面与吸附的串联

adsorption 命令只接受已经准备好的 slab：

```bash
llm-matgen generate adsorption \
  --slab clean-POSCAR \
  --adsorbate OH.xyz \
  --anchor 1
```

当用户以自然语言请求“生成某晶面的吸附构型”时，LLM/MCP 执行两步：

1. 调用 surface 生成器；
2. 根据用户指定或用户确认的 termination，选择一个 slab artifact；
3. 将该 artifact 作为 adsorption 的 `slab` 输入。

surface 返回值必须包含结构 artifact、structure ID、Miller 面、termination/实际参数和 viewer。若存在多个 termination 且用户没有给出选择规则，LLM 必须展示候选或请求用户选择，不得静默使用第一个结果。

两步流程各自保存独立 manifest。用户可以在两步之间执行 DFT 弛豫，也可以直接提供已有的弛豫 slab。

## 6. 吸附输入与参数模型

### 6.1 输入

`AdsorptionInput` 包含：

- `clean_slab: Structure`；
- `adsorbate: Molecule`；
- 可选 `gas_reference: Molecule | Structure`；
- 输入来源及输入哈希；
- 1-based 锚点原子编号；
- 电荷和自旋多重度；
- 多原子吸附物的参考轴；
- `denticity=1` 和 `rigid=true`。

校验规则：

- 锚点必须位于吸附物范围内；
- 多原子吸附物必须提供非零有限参考轴；
- 吸附物键图必须连通；
- 电荷、自旋必须与 Molecule 一致；
- 当前只接受单锚点刚性吸附物。

CLI 接收 XYZ 或 MSON molecule。内部统一转换为 `Molecule`，原子顺序和 1-based 锚点编号不得改变。

### 6.2 主要参数

- `history_policy = off | prefer | require`；
- `slab_state = relaxed | preview`；
- `surface_side = top | bottom | both`；
- `site_types` 和 `explicit_sites`；
- `heights`、`azimuths`、`tilts`、`rolls`；
- `coverage`；
- `fixed_bottom_layers`；
- `layer_tolerance`，默认建议 `0.35 Å`；
- `anchor_contact_window`；
- `min_vacuum_each_side`；
- `retrieval_threshold` 和 `retrieval_top_k`；
- `max_proposal_attempts`、`max_structures` 和 `max_atoms_per_structure`。

所有浮点参数必须有限；高度必须为正；倾角在 0–180°；候选尝试预算必须不小于最大接受数量。

## 7. 候选生成与确定性

### 7.1 算法候选

算法候选由表面真实法向和面内局部坐标系构造。支持：

- on-top；
- bridge；
- 三重/四重 hollow；
- defect、doped、undercoordinated；
- 用户给定 Cartesian 显式位点。

吸附物仅进行刚体平移和旋转。候选记录位点、表面方向、局部坐标系、吸附高度、旋转参数和完整 pose transform。

### 7.2 历史候选

历史候选不能直接将旧 Cartesian 坐标复制到新 slab。系统应：

1. 对化学组成、吸附物键图、锚点元素和表面方向进行严格过滤；
2. 将旧吸附几何表示为局部表面坐标；
3. 将局部 pose 映射到新候选位点；
4. 对映射结果重新执行全部几何检查。

`prefer` 先消费合格历史候选，再消费算法候选；检索不可用、无匹配或历史 pose 无法映射时记录明确 fallback reason。`require` 在没有可用历史候选时失败。`off` 不打开案例库。

### 7.3 排序与去重

- 案例检索固定按总分、完整度、case ID、revision ID 排序；
- 算法位点、姿态参数和 surface side 使用稳定排序；
- 相同输入、案例索引 revision 和参数得到相同候选顺序；
- 候选经结构匹配或稳定几何指纹去重；
- 达到尝试预算或结构上限时记录 audit，而不是静默截断。

## 8. 可配置历史案例源

### 8.1 数据源接口

定义只读 `CaseSource` 协议：

```python
class CaseSource(Protocol):
    def discover(self) -> Iterable[str]: ...
    def snapshot(self, relative_job_dir: str) -> JobSnapshot: ...
```

首批内置：

- `LocalDirectoryCaseSource`；
- `SSHCaseSource`；
- `InMemoryCaseSource`，仅用于测试。

未来可通过稳定协议增加对象存储或数据库源，但首版不开放第三方 entry point 插件。

### 8.2 配置文件

采用跨平台用户配置目录；建议引入 `platformdirs`：

- Windows：用户 AppData 下的 LLM-MatGen 配置/数据目录；
- Linux：遵循 XDG config/data 目录；
- macOS：遵循 Application Support 目录。

继续使用当前 `ConfigManager` 的 JSON 文件和原子写入行为，避免引入第二种配置格式。现有 `provider`、`model` 字段保持可读；新增 `adsorption` 嵌套对象。示例：

```json
{
  "provider": "external-client",
  "adsorption": {
    "store_root": "D:/LLM-MatGen-data/adsorption-cases",
    "sources": {
      "local-lab": {
        "type": "local",
        "root": "D:/DFT/adsorption",
        "follow_symlinks": false
      },
      "cluster-a": {
        "type": "ssh",
        "host": "cluster.example.edu",
        "user": "username",
        "root": "/work/username/adsorption",
        "port": 22,
        "timeout_seconds": 120
      }
    }
  }
}
```

配置优先级：

```text
CLI 参数 > 环境变量 > 用户配置文件 > 跨平台默认值
```

配置文件不得包含密码、token 或私钥内容。敏感字段检查必须递归覆盖所有嵌套对象和列表，而不是只检查顶层键。SSH 认证由系统 SSH agent 或用户已有密钥完成。允许记录 identity file 的路径，但不复制或读取其内容进入 manifest。

### 8.3 本地目录源

- 根目录在初始化时解析并固定；
- 默认不跟随符号链接；
- 所有候选文件解析后必须仍位于根目录；
- 遍历采用稳定排序；
- 大型 OUTCAR 采用流式标记提取，不整体加载；
- 扫描只读，不修改原始计算目录。

### 8.4 SSH 源

- 使用系统 `ssh` 可执行文件，兼容 Windows/Linux/macOS；
- 不依赖个人 PowerShell wrapper；
- 不使用 `shell=True`；
- 不允许用户配置任意远程命令模板；
- host、user、port、root 和 identity path 分别验证并作为参数处理；
- 远程脚本固定在包内，仅执行发现、stat、hash 和受限读取；
- 相对路径拒绝绝对路径、`..`、NUL、换行和根目录逃逸；
- 远程真实路径必须保持在声明根目录内；
- 生成 adsorption 时不连接远程源，只有显式 `cases scan` 才访问远程。

## 9. 案例提取、索引与检索

### 9.1 快照和质量门

快照记录文件身份、大小、mtime、SHA-256、稳定性和解析标记。案例提取至少检查：

- POSCAR/CONTCAR 可读；
- 计算正常结束；
- 电子和离子步骤满足配置的收敛要求；
- 无命中的致命警告；
- clean slab 参考可识别且哈希一致；
- 吸附前后原子身份及角色可以恢复；
- 结构与证据文件在快照期间未变化。

不满足质量门的案例可以保留审计状态，但不得作为 `eligible` 检索候选。

### 9.2 SQLite 索引

案例库位于用户数据目录，保存：

- source profile 和 root ID；
- 位置、存在区间和扫描批次；
- 不可变 case revision；
- 文件证据与哈希；
- 特征和质量审计；
- duplicate/superseded 关系；
- 单调递增的 index revision；
- 扫描锁和恢复审计。

一次扫描必须事务化发布一个新 index revision。失败扫描不得部分可见。artifact 先写入 staging，完成数据库事务后原子发布。

### 9.3 检索

检索采用两层策略：

1. 严格过滤化学不兼容、索引版本不兼容、已失效或质量不合格案例；
2. 对表面组成、局部配位、位点类型、吸附物、覆盖度和 pose 等固定特征加权评分。

检索结果固定到某个 index revision，并输出 `RetrievalTrace`：查询特征、阈值、分数组成、接受/拒绝原因、匹配 revision 和 fallback reason。当前不训练模型。

## 10. 底层原子固定

### 10.1 分层

沿 clean slab 的真实表面法向投影原子，不假设 c 轴严格垂直。投影差超过 `layer_tolerance` 时创建新层。层按投影由低到高排序，`fixed_bottom_layers=N` 固定最低 N 层。

“bottom”始终表示相对于 canonical top normal 的最低层，与 `surface_side` 参数独立。若在 bottom/both 表面吸附且同时固定底层，程序必须发出明确警告，因为固定区域可能位于吸附面。

### 10.2 Selective Dynamics 合并

- 输入 slab 已有约束必须保留；
- 新固定层与已有固定自由度取并集；
- 新增吸附物原子默认 `[True, True, True]`；
- 验证器依据“输入约束 + 新固定策略”计算期望值，不得假定所有未选 slab 原子均可移动；
- manifest 记录层容差、每层投影、固定原子 0-based/1-based 索引和最终标记。

## 11. 吸附专项几何检查

### 11.1 拒绝候选的硬错误

- 原子数或元素顺序变化；
- proposal side 与真实外法向不一致；
- slab–adsorbate 原子碰撞；
- 吸附物内部距离超出刚性容差；
- 吸附物键图变化；
- 吸附物与其二维周期镜像碰撞；
- Selective Dynamics 与计算出的固定策略不一致；
- 对称或几何重复候选。

### 11.2 默认可配置为错误的检查

- 锚点—表面接触距离超出半径缩放窗口；
- 任一侧法向真空小于阈值；
- 请求覆盖度与候选覆盖度不一致。

### 11.3 警告

- preview slab 被用于正式候选；
- bottom/both 吸附与底层固定组合；
- 候选达到结构数量或尝试预算；
- 历史检索失败后回退；
- 经验吸附高度或覆盖度可疑但未越过硬阈值。

所有报告包含稳定 code、原子索引、消息、测量值和阈值。默认只保存被拒绝候选的摘要，避免大量无效结构占用磁盘。

## 12. 统一输出与 manifest

adsorption 使用通用 `GenerationPipeline`。通用 pipeline 负责：

- 安全创建 run 目录；
- 通用轻量检查；
- POSCAR/MSON/CIF 导出；
- artifact hash；
- manifest；
- viewer；
- 失败和 warning 汇总。

adsorption 专属扩展写入：

```text
run-.../
├── manifest.json
├── viewer.html
├── structures/
│   ├── <candidate>.vasp
│   ├── <candidate>.mson.json
│   └── <candidate>.cif          # 可选
└── references/
    ├── clean-slab.mson.json
    ├── adsorbate.mson.json
    └── gas-reference.mson.json
```

POSCAR 和 MSON 对 adsorption 强制输出；CIF 可选。由于 LAMMPS data 无法可靠保存 Selective Dynamics 和分子/表面角色，存在这些信息时默认拒绝 LAMMPS data，并提示用户改用 POSCAR/MSON。未来若允许显式丢失信息，必须写入 manifest warning。

manifest 新增可选字段，不破坏旧 manifest：

- `configuration_status`；
- `retrieval_trace`；
- `proposal_audit`；
- `adsorption_validation`；
- `structure_context`：仅保存晶胞、真空方向、结构角色、固定层、覆盖度和表面侧；
- `reference_artifacts`；
- `viewer` artifact；
- fixed-layer policy 和 pose transform。

`structure_context` 是结构生成结果的上下文，不是计算任务描述。项目不得在此保存或推荐 INCAR、赝势、KPOINTS、泛函、偶极修正、色散修正、磁序或 Hubbard U，也不得据此提交或运行任何电子结构计算。

## 13. 人工修订追溯

### 13.1 Sidecar v2

新 sidecar 支持一次声明多个原子：

```json
{
  "schema": "llm-matgen-structure-revision",
  "version": 2,
  "parent_sha256": "...",
  "revised_sha256": "...",
  "created_at": "2026-09-07T00:00:00+00:00",
  "reason": "人工修正初始吸附构型",
  "changes": [
    {
      "index_1based": 12,
      "element": "O",
      "old_cartesian": [0.0, 0.0, 1.8],
      "new_cartesian": [0.1, 0.0, 1.9],
      "old_fractional": [0.0, 0.0, 0.2],
      "new_fractional": [0.01, 0.0, 0.21],
      "cartesian_delta": [0.1, 0.0, 0.1],
      "reason": "调整吸附高度"
    }
  ]
}
```

### 13.2 导入验证

- 父/子文件和 sidecar 必须互不相同；
- 父/子哈希匹配；
- 原子数、元素顺序、晶格和 PBC 不变；
- Selective Dynamics 不变；
- `changes` 非空，索引唯一且合法；
- 每项旧/新 Cartesian、fractional 和 delta 自洽；
- 实际变化的原子集合与声明集合完全一致；
- 不允许未声明变化；
- reason 和带时区时间有效。

导入生成不可变 revision ID、父子结构、MSON、原 sidecar 和 manifest，并采用 staging + 原子 rename。旧版 `vasp-structure-revision` v1 单原子 sidecar 继续可导入；新输出统一使用 v2。

人工 revision 仅是正式谱系 artifact，不自动进入 eligible 历史案例。只有完成 DFT 并满足案例质量门后，才能通过案例导入/扫描进入索引。

## 14. 离线球棍查看器

### 14.1 行为

- 所有结构生成任务默认在每个 run 中生成一个 `viewer.html`；
- `--no-viewer` 可关闭；
- `--open` 隐含启用 viewer，并在成功后调用系统默认浏览器；
- 一个 viewer 切换同一 run 的全部候选；
- adsorption 额外显示 clean slab 参考结构；
- 支持球棍、元素图例、旋转、缩放、平移、晶胞、原子编号、坐标、固定状态和 XY/XZ/YZ 视角；
- viewer 只读，不直接修改结构文件。

### 14.2 离线与安全

- 固定版本 3Dmol.js 作为包资源随项目发布；
- 保存上游版本、许可证文本和资源 hash；
- 不从 CDN 加载脚本；
- JSON 数据转义 `<`、`>`、`&` 和 script 终止序列；
- 候选标签只能作为文本展示；
- HTML SHA-256 写入 manifest；
- viewer 生成失败仅产生 warning，不使结构生成失败。

### 14.3 规模限制

初始默认：

- 单结构不超过 20,000 原子；
- 单页面总计不超过 200,000 原子；
- 单原子邻接候选不超过安全上限；
- 超限时保留结构文件并记录跳过原因。

键基于共价半径估计，仅展示胞内连接；页面明确说明不绘制跨周期边界的键。后续可根据性能测试调整默认值。

## 15. CLI 设计

### 15.1 生成

```bash
llm-matgen generate adsorption \
  --slab clean-POSCAR \
  --adsorbate OH.xyz \
  --anchor 1 \
  --reference-axis 0,0,1 \
  --history-policy prefer \
  --surface-side top \
  --fixed-bottom-layers 2 \
  --output-root output
```

所有生成器增加：

- `--viewer`，默认；
- `--no-viewer`；
- `--open`，隐含启用 viewer。

### 15.2 案例库

```bash
llm-matgen cases sources
llm-matgen cases scan --source local-lab
llm-matgen cases scan --source cluster-a
llm-matgen cases status
llm-matgen cases query --features query.json
llm-matgen cases inspect REVISION_ID
```

### 15.3 Revision

```bash
llm-matgen revision import \
  --parent parent-POSCAR \
  --revised revised-POSCAR \
  --sidecar revision.json
```

已有 `search/download/properties/substrates/generate/check/export/convert/sample/filter/db/mcp/config` 命令不得被覆盖或删除。CLI help 测试改为包含当前完整命令集合。

## 16. MCP 与 LLM 编排

新增结构化工具：

- `generate_adsorption`；
- `cases_status`；
- `cases_query`；
- `cases_inspect`；
- `revision_import`。

不在首版 MCP 中暴露 `cases_scan`。远程或大目录扫描必须由用户显式通过 CLI 启动。

MCP 不应仅传递任意 CLI 字符串数组。adsorption 使用明确 JSON Schema，限制枚举、数值范围、输入 artifact 和输出根目录。返回：

- generated count；
- manifest artifact；
- 结构 artifacts；
- viewer artifact；
- structure IDs；
- 检查摘要和 fallback reason。

artifact 解析继续遵守现有输出根目录边界，禁止通过相对路径读取任意本地文件。

## 17. 失败与降级策略

| 场景 | 行为 |
| --- | --- |
| `history_policy=off` | 不打开案例库，直接算法生成 |
| `prefer` 且案例库不可用 | 记录原因，回退算法候选 |
| `require` 且无有效匹配 | 明确失败 |
| 某候选几何不合法 | 拒绝该候选，继续有界搜索 |
| 全部候选被拒绝 | 返回汇总错误与拒绝统计 |
| viewer 超限或失败 | 保留结构，记录 warning |
| SSH 扫描失败 | 不发布新 index revision |
| revision sidecar 不一致 | 不创建正式 revision |
| LAMMPS 导出会丢失固定信息 | 默认拒绝并解释替代格式 |

错误消息必须包含稳定错误类型或 code，避免测试依赖整段自然语言。

## 18. 安全与隐私

- 删除参考实现中的个人远程根目录、管理员 wrapper 和硬编码磁盘目录；
- 示例配置只能使用虚假域名、用户名和路径；
- 配置、案例数据库、SSH identity 路径和生成结果加入适当 ignore；
- 发布安全扫描覆盖 API key、私钥、个人绝对路径和远程用户名；
- SSH 数据源只读且路径受根目录约束；
- SQLite 查询全部参数化；
- staging 清理只能发生在已解析的案例库专属目录，禁止对宽泛路径递归删除；
- viewer 不联网，不执行结构标签中的 HTML；
- `--open` 只打开本次生成且已登记的 viewer；
- manifest 不记录凭据或私钥内容。

## 19. 兼容与迁移

### 19.1 代码整合

不得覆盖以下当前文件的现有功能：

- `llm_matgen/__main__.py` 中的 convert/sample/filter；
- `llm_matgen/pipeline.py` 的现有导出和 manifest 行为；
- `llm_matgen/generators/surface.py` 的近正交表面晶胞；
- `llm_matgen/trajectories/` 全部模块；
- POSCAR 元素分组修复。

新模块可从参考包移植；公共文件必须逐段合并，并通过回归测试验证。

### 19.2 数据兼容

- 旧 manifest 继续可读；
- 新 manifest 字段全部可选；
- revision sidecar v1 可导入，v2 为新默认；
- 案例 SQLite 增加显式 schema version；
- 发现旧案例库时先创建可恢复备份，再事务迁移；
- 迁移失败保留原数据库，不部分升级；
- 支持用户用 `--store-root` 指向已有数据库进行检查或迁移。

### 19.3 版本

当前项目代码版本仍为 `0.1.0`。本批功能属于向后兼容的显著功能扩展，目标版本设为 `0.2.0`。先发布 `v0.2.0-rc.1` 预发布，真实工作流验证后发布 `v0.2.0`。`pyproject.toml`、`llm_matgen.__version__`、文档和 Git tag 必须一致。

## 20. 测试矩阵

### 20.1 单元测试

- Local/SSH/InMemory source；
- 路径穿越、符号链接逃逸和异常远程输出；
- 快照稳定性与大 OUTCAR 流式解析；
- 案例质量门、特征提取和重复案例；
- SQLite 事务、索引 revision、扫描锁和恢复；
- 检索严格过滤、评分、排序和 fallback；
- 位点生成、局部表面坐标和刚体 pose；
- 吸附碰撞、接触、内部键、周期镜像、真空和去重；
- 原有 Selective Dynamics 与新增固定层的合并；
- revision v1/v2、多原子变化、未声明变化和哈希错误；
- viewer JSON 转义、原子限制、固定状态和确定性输出。

### 20.2 集成测试

- `surface → artifact → adsorption` 两步工作流；
- native 与 near-orthogonal slab 输入；
- relaxed 与 preview slab；
- top/bottom/both 和固定层组合；
- 单原子与多原子刚性吸附物；
- history off/prefer/require；
- POSCAR/MSON/CIF、reference artifacts、manifest 和 viewer；
- viewer 失败不破坏结构生成；
- revision 导入后 parent→child 谱系完整。

### 20.3 CLI/MCP 测试

- 完整顶层命令集合，包括 convert/sample/filter/cases/revision；
- adsorption 所有参数与默认值；
- `--viewer/--no-viewer/--open`；
- MCP JSON Schema 和 artifact 边界；
- MCP 不暴露 `cases_scan`；
- 多 termination 时不静默选择；
- 错误码和 JSON 输出稳定。

### 20.4 跨平台与安全测试

- Windows、Linux、macOS 的用户配置和数据目录；
- Windows/Linux 系统 SSH；
- Python 3.10–3.12；
- 包资源中 viewer/3Dmol.js/许可证齐全；
- wheel/sdist 安装后离线 viewer 可用；
- release safety 不包含真实密钥、个人路径或用户名。

### 20.5 性能测试

- 10,000 级案例索引查询；
- 大 OUTCAR 不整体载入内存；
- 候选生成受 `max_proposal_attempts` 严格限制；
- viewer 在 20,000 原子/200,000 总原子的边界行为；
- 多候选结构匹配不会出现无界内存增长。

## 21. 分阶段实施

1. 可配置数据源、跨平台配置与案例库 schema；
2. 案例提取、索引、确定性检索和审计；
3. adsorption 生成器、位点/pose 与统一服务输入；
4. 固定层、专项几何检查和统一 pipeline artifacts；
5. revision v2 与 v1 兼容；
6. 离线 viewer 及所有生成器集成；
7. CLI、MCP、文档、迁移和发布加固。

每阶段必须先增加失败测试，再实现；阶段结束运行相关测试。最后运行完整测试、构建 wheel/sdist、安装产物并执行 smoke test。

## 22. GitHub Flow 与发布管理

### 22.1 当前本地更新先入主线

评估时本地 `master` 比 `origin/master` 领先 32 个提交。先创建并推送保护分支：

```bash
git branch codex/local-updates-backup c480189
git push origin codex/local-updates-backup
```

随后按已有提交边界通过 PR 合入：

1. 轨迹过滤、RDF/SOAP-FPS、性能优化与 POSCAR 修复；
2. 近正交表面晶胞。

不得把当前 32 个提交与 adsorption 的 5,000 余行新代码合成一个巨型 PR。

### 22.2 Adsorption 功能分支

基线 PR 合并后，从最新主线创建：

```bash
git switch -c codex/adsorption-history-viewer
```

使用一个功能分支和按阶段组织的小提交，并尽早创建 Draft PR。建议提交边界：

```text
feat: add configurable adsorption case sources
feat: index and retrieve adsorption histories
feat: generate and validate adsorption structures
feat: support fixed layers and revision v2
feat: add offline structure viewer
feat: expose adsorption through cli and mcp
docs: document adsorption workflows
```

### 22.3 主分支规则

- 禁止直接 push 和 force push；
- 必须通过 PR；
- 必须通过 CI 和分支同步检查；
- 至少一次人工确认；
- CI 包含测试、构建、安装 smoke test 和发布安全扫描；
- 稳定版本用签名或受保护 tag；
- 个人项目不额外维护长期 `develop` 分支。

### 22.4 参考源码包的处理原则

下载的 `llm_matgen-0.2.0` 仅作为移植参考和测试依据，不得：

- 作为 Git subtree 引入；
- 复制到项目的 `vendor/` 目录；
- 整体覆盖当前源码树；
- 连同其中的用户路径、服务器配置或构建产物提交。

应逐模块移植 adsorption、case store、revision 和 viewer 实现，并针对当前公共接口重新整合。公共文件如 `__main__.py`、`pipeline.py`、`services/generation.py`、`io/manifest.py` 和 `pyproject.toml` 必须手工合并，保留当前主线已有能力。

3Dmol.js 可以作为固定版本离线资源随 wheel/sdist 发布，但必须同时保留其许可证文本、上游版本信息和资源哈希，并在 viewer 或发布文档中提供许可证入口。

### 22.5 版本发布顺序

这批功能足以将项目从 `0.1.0` 升级到 `0.2.0`。发布步骤固定为：

1. 合并所有功能 PR 后，将 `pyproject.toml`、`llm_matgen.__version__` 和文档版本统一更新为 `0.2.0rc1`；
2. 创建 `v0.2.0-rc.1` GitHub Pre-release；
3. 使用真实 slab、单原子/分子吸附物、本地案例库和 SSH 案例源执行验收；
4. 至少在 Windows 和 Linux 各完成一次安装与 smoke test；
5. 修复预发布问题，并重新执行全量测试、wheel/sdist 构建和安装验证；
6. 将代码版本统一更新为 `0.2.0`；
7. 从已验证的主线提交创建 `v0.2.0` tag 和正式 GitHub Release。

Git tag、release 名称、`pyproject.toml`、`llm_matgen.__version__` 和文档显示版本必须完全一致。不得在不同提交上分别创建 tag 和发布产物。

## 23. 验收标准

功能完成需同时满足：

1. 十类生成器均可生成结构和 viewer，旧九类默认结构结果不发生非预期变化；
2. LLM/MCP 可执行 surface→adsorption 两步流程；
3. 本地和 SSH 案例源均由用户 profile 配置，无个人硬编码；
4. history off/prefer/require 行为与 trace 一致；
5. 固定层在斜晶胞中按真实法向工作，并正确合并已有约束；
6. 非法吸附几何被拒绝并输出可审计原因；
7. revision v1 可读，v2 支持多原子且不能接受未声明修改；
8. viewer 离线、安全、带许可证，超限时安全降级；
9. 当前轨迹功能和近正交表面功能全部回归通过；
10. Windows/Linux 至少完成一次真实 smoke test；
11. wheel 和 sdist 可构建、安装并包含 viewer assets；
12. 发布安全扫描无密钥、个人服务器和绝对路径。

## 24. 已知风险与控制

| 风险 | 控制措施 |
| --- | --- |
| 直接覆盖旧源码导致当前功能丢失 | 仅向前移植；公共文件逐段合并 |
| 历史错误案例污染生成 | 质量门、eligible 状态、冻结 index revision、完整 trace |
| 不同表面直接复制坐标 | 使用局部表面坐标映射并重新验证 |
| SSH 路径/命令注入 | 固定命令、参数验证、根目录约束、禁止 shell=True |
| 案例库扫描中断造成半发布 | staging、事务和单调 index revision |
| 固定层破坏已有约束 | 约束取并集，验证器使用相同策略模型 |
| viewer HTML 注入或联网 | 数据转义、内嵌固定资源、无 CDN |
| viewer 导致大内存/大文件 | 原子和总量上限，失败降级 |
| 人工修订冒充已验证案例 | revision 与 eligible DFT 案例分离 |
| CLI/MCP 参数漂移 | 共享 Pydantic 模型和 schema 契约测试 |

## 25. 设计自审核

- [x] 已明确 adsorption 只接收 slab，不隐式生成表面；
- [x] 已明确 LLM/MCP 两步串联和多 termination 选择边界；
- [x] 已删除个人服务器、wrapper 和默认磁盘路径依赖；
- [x] 已覆盖本地与通用 SSH 数据源；
- [x] 已明确凭据不进入配置、manifest 或仓库；
- [x] 已统一 pipeline，避免两套输出契约；
- [x] 已处理已有 Selective Dynamics 与验证逻辑不一致风险；
- [x] 已定义 bottom 固定层在 bottom/both 吸附时的语义和警告；
- [x] 已明确 LAMMPS data 对固定信息的限制；
- [x] 已将人工 revision 与 DFT 合格历史案例分离；
- [x] 已兼容 sidecar v1 并定义 v2 多原子格式；
- [x] 已覆盖 viewer 许可证、注入、离线和规模风险；
- [x] 已保留 convert/sample/filter 和近正交 surface；
- [x] 已定义数据、CLI、MCP、跨平台、安全和性能测试；
- [x] 已给出 GitHub Flow、PR 边界和 0.2.0 发布路径；
- [x] 无 TODO、TBD、占位决策或未经确认的功能扩张。
