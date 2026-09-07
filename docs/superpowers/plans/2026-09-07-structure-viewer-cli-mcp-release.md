# 离线结构查看器、CLI/MCP 整合与 0.2.0 加固计划

> 依赖：案例库、adsorption 生成计划及 `2026-09-07-adsorption-gap-hardening.md` 完成；依据整合设计第 14–20、23 节。

## 目标

为十类生成器提供安全离线 viewer，将 adsorption/cases/revision 接入当前 CLI、服务与 MCP，更新文档并完成可安装发布验证。

## Task 1：引入受许可约束的离线 viewer 资源 `[completed]`

**Files:**

- Create: `llm_matgen/viewer/__init__.py`
- Create: `llm_matgen/viewer/assets/viewer.html`
- Create: `llm_matgen/viewer/assets/3Dmol-min.js`
- Create: `llm_matgen/viewer/assets/3Dmol-LICENSE.txt`
- Modify: `pyproject.toml`
- Create: `tests/test_viewer.py`

1. 写失败测试覆盖有序结构、空/非有限结构、单结构/总原子限制、过密邻接、fixed 标记、JSON script 转义、原子写入和 SHA-256。
2. 从参考提交 `f7c6c37` 逐文件复核后复制固定 3Dmol.js 2.0.4 和 BSD-3-Clause 许可证；记录上游 URL、版本和 SHA-256，且不得改写 minified 第三方代码。
3. 参考其 `structure_payload()`/`write_viewer()` 的 cKDTree 邻接、原子预算、JSON 转义和原子替换写入，但重新适配当前 pipeline 接口。
4. 实现一个 run 一个 HTML，数据内嵌、无 CDN、标签使用 `textContent`，仅绘制胞内键；限制候选标签长度和页面总序列化字节数。
5. 将 assets 加入 setuptools package-data 和 sdist manifest。
6. 运行 viewer/package 测试并提交：`feat: add licensed offline structure viewer`。

## Task 2：把 viewer 接入统一 pipeline

**Files:**

- Modify: `llm_matgen/pipeline.py`
- Modify: `llm_matgen/io/manifest.py`
- Modify: `tests/test_pipeline.py`
- Create: `tests/test_viewer_pipeline.py`

1. 写失败测试覆盖默认生成、禁用、多个候选、adsorption clean slab reference、超限 warning 和 viewer exception 降级。
2. 为 `GenerationPipeline.run()` 增加明确 `viewer: bool = True` 选项，并在 `PipelineResult` 增加 `viewer_path: Path | None`。
3. 只预览成功导出的结构；viewer artifact 写入 manifest。
4. viewer 失败追加 warning，不改变可用结构的 `ok`。
5. 运行 pipeline 和所有 generator export 测试。
6. 提交：`feat: generate one viewer per structure run`。

## Task 3：扩展统一服务的类型化输入

**Files:**

- Modify: `llm_matgen/services/generation.py`
- Modify: `llm_matgen/sources/models.py`
- Modify: `llm_matgen/sources/local.py`
- Create: `tests/test_services/test_adsorption_generation.py`

1. 写失败测试覆盖一元 structure、二元 interface 和 structure+molecule adsorption，不允许输入角色或数量错配。
2. 将 `GeneratorEntry.binary` 替换为 `inputs: tuple[GeneratorInputSpec, ...]`，每项声明 role/kind/cardinality。
3. 增加 molecule resolver，支持 XYZ/MSON，保留结构 resolver 行为。
4. 服务层统一应用输入/输出原子数和结构数量限制。
5. adsorption 不再通过 CLI 直接绕开 service/pipeline。
6. 运行 service 测试并提交：`refactor: resolve typed generator inputs uniformly`。

## Task 4：整合 CLI 且保留现有命令

**Files:**

- Modify: `llm_matgen/__main__.py`
- Modify: `tests/test_cli/test_generate.py`
- Create: `tests/test_cli/test_adsorption_commands.py`
- Create: `tests/test_cli/test_revision_commands.py`
- Modify: `tests/test_cli/test_help.py`

1. 写失败测试覆盖 adsorption 参数、cases、revision、`--viewer/--no-viewer/--open` 和完整顶层命令集合。
2. `--open` 隐含 viewer；只有生成成功且路径登记在本次 result 时才打开。
3. 保留 convert/sample/filter/db/mcp/config 和近正交 surface 参数。
4. CLI adsorption 调用统一 GenerationService；revision/cases 调用对应应用服务。
5. 输出 JSON 包含 manifest、structures、viewer、检查摘要和 fallback reason。
6. 运行全部 CLI 测试并提交：`feat: expose adsorption revision and viewer commands`。

## Task 5：提供结构化 MCP 工具

**Files:**

- Modify: `llm_matgen/orchestration/tools.py`
- Modify: `llm_matgen/mcp/server.py`
- Create: `tests/test_mcp_adsorption.py`
- Create: `tests/test_mcp_server.py`

1. 写失败测试覆盖 `generate_adsorption/cases_status/cases_query/cases_inspect/revision_import` 的 JSON Schema、边界和 artifact refs。
2. adsorption 工具使用 Pydantic/JSON Schema 参数，不接受任意 CLI argument 数组。
3. MCP 工具列表明确不包含 `cases_scan`。
4. artifact 必须位于注册 output root；路径逃逸和未登记文件失败。
5. surface 多 termination 返回候选 metadata，不自动选择。
6. 运行 MCP/orchestration 测试并提交：`feat: expose typed adsorption mcp tools`。

## Task 6：更新自然语言 harness 与 skill

**Files:**

- Modify: `tests/nl-tests/harness.py`
- Modify: `integrations/skills/llm-matgen/SKILL.md`
- Modify: `docs/examples/natural-language-workflows.md`
- Modify: `tests/test_documentation.py`

1. 写失败契约测试，要求 adsorption schema、surface→adsorption 两步、多 termination 用户选择和 viewer 返回行为。
2. 更新自然语言参数映射，不添加内置 OpenAI key 或 provider 依赖。
3. skill 指示客户端管理模型和凭据，LLM-MatGen 只执行确定性工具。
4. 添加 history off/prefer/require 示例和失败提示。
5. 运行文档/harness 测试并提交：`docs: teach llm clients the adsorption workflow`。

## Task 7：更新公共文档和发布安全规则

**Files:**

- Modify: `README.md`
- Modify: `docs/user-guide.zh-CN.md`
- Modify: `docs/llm-matgen-design.md`
- Modify: `docs/api.md`
- Modify: `docs/mcp.md`
- Modify: `.gitignore`
- Modify: `llm_matgen/release_safety.py`
- Modify: `tests/test_release_safety.py`

1. 写失败测试要求十类生成器、viewer、case profiles、revision v2、责任边界和 LAMMPS 限制出现在公共文档。
2. 文档示例只使用虚假域名、用户名、路径和 key 占位符。
3. ignore 用户配置、case SQLite、revision store、输出 viewer 和临时 staging。
4. 发布扫描增加个人绝对路径、SSH wrapper、私钥头和已知凭据模式。
5. 保留 3Dmol license 和来源说明，不将其误报为待删除第三方文件。
6. 运行文档与 release safety 测试并提交：`docs: document adsorption cases revisions and viewer`。

## Task 8：统一版本并验证构建产物

**Files:**

- Modify: `pyproject.toml`
- Modify: `llm_matgen/__init__.py`
- Modify: `README.md`
- Modify: `docs/user-guide.zh-CN.md`
- Modify: `tests/test_package.py`

1. 先将预发布版本设为 PEP 440 `0.2.0rc1`，用户显示/tag 使用 `v0.2.0-rc.1`。
2. 在 dev extra 增加 `build>=1.2`，避免发布环境缺少 `python -m build`。
3. 运行 `python -m build`。
4. 在新临时虚拟环境安装 wheel，运行 `llm-matgen --help`、生成最小结构、确认 viewer assets 可读。
5. 检查 wheel/sdist 内容不含下载源码包、个人配置、案例 DB、输出或凭据。
6. 提交：`chore: prepare llm-matgen 0.2.0 release candidate`。

## Task 9：完整回归与跨平台验收

1. 运行 `python -m pytest -q`，要求 tracked 测试全部通过。
2. 分别运行 generator、trajectory、adsorption、CLI、MCP、documentation 和 release safety 测试组，记录数量。
3. 运行 `python -m compileall -q llm_matgen integrations` 和 `git diff --check`。
4. Windows 本地完成 surface→adsorption→viewer、local cases 和 revision v2 smoke test。
5. Linux 完成 wheel 安装、SSH fixture/测试服务器只读 scan 和同一生成 smoke test。
6. 对真实 SSH 测试只记录脱敏结果，不保存 host/user/path/credential。
7. 所有验收通过后，按 GitHub 发布计划创建预发布；正式版前将版本从 `0.2.0rc1` 更新为 `0.2.0` 并重复构建/安装测试。

## 完成标准

- 十类生成器通过统一 service/pipeline；
- 每个生成 run 默认产生安全离线 viewer；
- CLI/MCP 参数类型化且保留现有全部命令；
- MCP 不会触发远程案例扫描；
- wheel/sdist 包含 viewer 与许可证；
- tracked 全量测试、构建、安装和 Windows/Linux smoke test 通过；
- 发布物无个人路径、服务器和凭据。
