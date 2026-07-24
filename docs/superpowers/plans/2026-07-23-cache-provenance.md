# SQLite 快照缓存与 provenance 实施计划

## 目标

实现不会覆盖历史来源信息的本地缓存。相同 MP material ID 在不同数据库版本或结构哈希下保存为不同 snapshot。

## 文件映射

```text
llm_matgen/database/__init__.py
llm_matgen/database/models.py
llm_matgen/database/schema.py
llm_matgen/database/store.py
llm_matgen/database/migrations.py
tests/test_database/test_schema.py
tests/test_database/test_store.py
tests/test_database/test_migrations.py
tests/test_database/test_import_export.py
```

## 接口

```python
class MaterialSnapshot(BaseModel):
    snapshot_id: UUID
    material_id: str
    source_db_version: str | None
    structure_hash: str | None
    formula: str
    elements: list[str]
    n_elements: PositiveInt
    properties: PropertySet
    property_origins: dict[str, str]
    raw_json: dict[str, JsonValue] | None
    fetched_at: datetime

class LocalStore:
    def insert_snapshot(self, snapshot: MaterialSnapshot) -> UUID: ...
    def insert_batch(self, snapshots: Sequence[MaterialSnapshot]) -> BatchResult: ...
    def get_snapshot(self, snapshot_id: UUID) -> MaterialSnapshot | None: ...
    def get_latest(self, material_id: str) -> MaterialSnapshot | None: ...
    def query(self, query: LocalMaterialQuery) -> list[MaterialSnapshot]: ...
    def delete_snapshot(self, snapshot_id: UUID) -> bool: ...
    def export_json(self, path: Path, snapshot_ids: Sequence[UUID] | None = None) -> None: ...
    def import_json(self, path: Path) -> BatchResult: ...
```

## Task 1：数据库连接与 schema 版本

1. 写失败测试：新数据库创建、foreign keys 开启、`PRAGMA user_version` 正确。
2. 实现连接上下文、WAL 模式、busy timeout 和 schema 初始化。
3. 禁止跨线程共享同一 connection；LocalStore 每个操作获取短连接。
4. 添加只读路径、损坏数据库错误测试。
5. 提交：`feat: initialize versioned sqlite store`。

## Task 2：MaterialSnapshot 序列化

1. 写 Pydantic 模型失败测试：UUID、UTC 时间、property origins、raw JSON。
2. 实现 `MaterialSnapshot` 和 `LocalMaterialQuery`。
3. 添加 NaN/Infinity 属性拒绝、元素去重且稳定排序测试。
4. 提交：`feat: define material snapshot models`。

## Task 3：插入与历史保留

1. 写失败测试：插入、读取、相同 material ID 不同数据库版本共存。
2. 实现事务化 `insert_snapshot()`。
3. 完全相同 `(material_id, source_db_version, structure_hash, fetched_at)` 重复导入返回 existing，不复制。
4. 添加事务异常回滚测试。
5. 提交：`feat: persist immutable material snapshots`。

## Task 4：批量写入与部分失败

1. 写失败测试：批量成功、单项 schema 失败、atomic true/false 两种模式。
2. 实现 `BatchResult(inserted, existing, failed)`。
3. atomic=true 任一失败全部回滚；false 使用 savepoint 隔离单项。
4. 提交：`feat: add controlled batch snapshot writes`。

## Task 5：最新版本与本地查询

1. 写 `get_latest()` 按 fetched_at、source_db_version、snapshot_id 稳定选取测试。
2. 实现元素包含、n_elements、带隙、形成能、formula pattern 和 limit 查询。
3. 元素查询使用规范化关联表或 JSON1 能力检测；不得使用易误匹配的字符串 LIKE。
4. 添加 null 属性、边界相等、非法范围和 SQL 特殊字符测试。
5. 提交：`feat: query cached material snapshots`。

## Task 6：JSON 导入导出

1. 写导出 schema version、快照列表、checksum 测试。
2. 实现原子写出和 SHA-256。
3. 写 round-trip、checksum 不符、未知 schema version、重复 snapshot 测试。
4. 导入不得执行 raw JSON 中的任何路径或 SQL 字段。
5. 提交：`feat: import and export snapshot archives`。

## Task 7：迁移框架

1. 写空 v1 → v2 示例迁移测试和迁移失败回滚测试。
2. 实现顺序迁移注册表，每步一个事务，完成后更新 user_version。
3. 数据库版本高于程序支持版本时以只读错误退出，不尝试降级。
4. 提交：`feat: add transactional database migrations`。

## Task 8：接入 MPCollector 和 CLI db

1. 写 fetch properties 后保存 snapshot 的服务测试。
2. 接入 `db import/query/export/list/stats` CLI。
3. `query` 默认返回 latest，可用 `--all-snapshots` 查看历史。
4. CLI 输出包含 material ID、snapshot ID、数据库版本和 fetched_at。
5. 提交：`feat: connect snapshot cache to cli`。

## Task 9：验收

1. 运行 `pytest tests/test_database tests/test_sources/test_mp.py tests/test_cli -q`。
2. 建立两个模拟 MP 数据库版本，确认同一 material ID 两份结构均可复现读取。
3. 并发启动两个写入进程，确认无损坏并正确处理 busy timeout。
4. 覆盖率不低于 90%，所有迁移分支有测试。
5. 提交：`test: verify snapshot cache provenance`。

## 本计划完成条件

- 缓存更新不会覆盖历史 snapshot。
- 属性来源、数据库版本、结构哈希和检索时间完整保存。
- 查询、导入、导出无 SQL/路径注入入口。
- 迁移失败可完整回滚。

## 执行状态

- Task 1（数据库连接与 schema 版本）：✅ 已完成
- Task 2–9：待执行
