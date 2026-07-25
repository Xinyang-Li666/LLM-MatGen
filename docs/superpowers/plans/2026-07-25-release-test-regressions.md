# 发布前 CLI 与 MP 下载回归修复实施计划

> 执行原则：两个失败均先保留可复现测试，再做最小兼容修复；不回退当前 Materials Project API 所需的新字段名。

## 已复现状态

执行：

```powershell
python -m pytest tests/test_cli/test_help.py tests/test_sources/test_mp.py -q
```

当前结果为 `2 failed, 21 passed`：

1. CLI parser 已公开 `mcp`，旧测试仍严格断言只有九个顶层命令。
2. MP 请求端已改用当前字段 `database_IDs`，但响应解析也被改成只读该字段，旧 fixture 的
   `database_version="2026.07"` 因此丢失为 `None`。

## 文件范围

- 修改：`tests/test_cli/test_help.py`
- 修改：`tests/test_sources/test_mp.py`
- 修改：`llm_matgen/sources/mp.py`
- 更新：`docs/superpowers/plans/2026-07-25-public-documentation-release.md`

## Task 1：同步 CLI 公共命令契约

1. 修改 `test_cli_exposes_documented_top_level_commands` 的严格集合，加入 `mcp`。
2. 增加 `test_mcp_help_is_available_without_starting_server`：
   - 解析 `["mcp", "--help"]`；
   - 断言退出码为 0；
   - 不导入或启动 MCP stdio server；
   - 不要求安装可选 MCP 运行依赖。
3. 运行：

   ```powershell
   python -m pytest tests/test_cli/test_help.py -q
   ```

## Task 2：先补齐 MP 新旧字段兼容测试

1. 保留现有旧字段测试，明确重命名为
   `test_mp_download_accepts_legacy_database_version`。
2. 新增当前 API 文档测试：
   - 响应只含 `database_IDs`；
   - 下载成功；
   - metadata 中仍写入现有公共键 `database_version`，避免破坏缓存格式。
3. 新增 fallback 测试：
   - 响应无上述两个字段但有 `last_updated`；
   - `SourceStructure.database_version` 使用 `last_updated` 字符串。
4. 新增优先级测试：
   - 同时存在 `database_version` 和 `database_IDs` 时优先保留旧的显式
     `database_version`；
   - 这保证旧 client、录制 fixture 和既有缓存行为稳定。
5. 运行新增测试，确认当前解析实现至少在旧字段与优先级用例上失败。

## Task 3：集中实现响应版本标记兼容

1. 保持 `_fetch_download_document()` 的请求字段为：

   ```python
   ["material_id", "structure", "database_IDs", "last_updated"]
   ```

   不把已被当前 MP API 拒绝的 `database_version` 放回请求字段。
2. 在 `MPCollector` 增加单一辅助函数，例如 `_document_database_version(document)`。
3. 按以下顺序提取：
   - `database_version`；
   - `database_IDs`；
   - `last_updated`；
   - 均不存在时为 `None`。
4. 标量保持 `str(value)` 兼容；映射/列表使用稳定序列化，避免字典顺序导致相同响应生成不同 metadata。
5. `_write_download()` 只调用该辅助函数，不再散落字段 fallback。
6. 不修改 `SourceStructure.database_version` 和 metadata 的公共字段名，避免缓存迁移和下游 API 破坏。

## Task 4：验证缓存复用与错误隔离

1. 确认旧 metadata 文件仍能由 `_load_reusable_download()` 读取。
2. 确认匹配缓存不会发起第二次 API 请求。
3. 确认单个下载失败仍保留其他 material 的成功结果。
4. 运行：

   ```powershell
   python -m pytest tests/test_sources/test_mp.py -q
   ```

## Task 5：纳入发布门禁

1. 在 `docs/superpowers/plans/2026-07-25-public-documentation-release.md` 的完整测试任务中明确加入：
   - CLI 顶层命令必须包含 `mcp`；
   - MP 下载必须同时兼容旧 `database_version` 响应与新 `database_IDs` 响应。
2. 运行聚焦测试：

   ```powershell
   python -m pytest tests/test_cli/test_help.py tests/test_sources/test_mp.py -q
   ```

3. 再运行完整发布测试：

   ```powershell
   python -m pytest --import-mode=importlib -q
   python -m compileall -q llm_matgen integrations
   ```

## 完成条件

- 聚焦测试由 `2 failed, 21 passed` 变为全通过。
- `mcp --help` 不启动服务且不依赖可选运行包。
- 当前 MP API 请求不再包含无效的 `database_version` 字段。
- 旧响应、当前响应和 `last_updated` fallback 都能生成稳定 metadata。
- 既有 MP 下载缓存无需迁移即可继续复用。
