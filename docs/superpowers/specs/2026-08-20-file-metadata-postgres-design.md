# 文件元数据迁移 PostgreSQL 设计

日期：2026-08-20
状态：已批准

## 1. 背景与目标

**背景**：`GET /api/files`（管理台文件列表）目前从 MinIO `list_objects` 按 object key 游标分页读取。缺点：列表反映的是"已上传对象"而非"已索引文件"、无删除状态（删索引后对象可能残留）、依赖对象路径 `uploads/{app_id}/{file_id}/{filename}` 硬编码层级反解。

**目标**：
1. PostgreSQL 作为一等组件（`database`），与 `store`/`dense` 等平级，DI 容器装配、`Application` 统一管理生命周期。
2. 文件元数据存 PG 单表，支持**软删除**。
3. 对接 index（写入/恢复记录）与 delete index（软删记录）接口。
4. `GET /api/files` 改为读 PG，**双向 keyset 分页，纯 id 数字游标**（上一页/下一页按钮）。
5. 前端文件列表改为左右按钮翻页，去掉滚动触底加载。

**非目标**：
- chunk 内容不迁 PG（仍在向量库）。
- 存量 MinIO 数据不迁移导入。
- 不做 `database.enable` 开关（组件必填）。
- 不引入 ORM / Alembic（裸 psycopg3 + 连接池）。

## 2. 已确认决策

| # | 决策 |
|---|---|
| 1 | PG 仅存文件元数据。 |
| 2 | 软删除语义：PG 记录软删（`deleted_at`）+ 向量库 chunks 硬删（现状不变）。 |
| 3 | 存量数据不迁移。 |
| 4 | 访问层：裸 `psycopg3` + `psycopg_pool.ConnectionPool`。 |
| 5 | 前端：左右按钮翻页，非滚动加载。 |
| 6 | 分页：双向 keyset，游标为**纯 id 数字**（BIGSERIAL 主键，与插入时间同序），列表按 `created_at DESC, id DESC` 展示。 |
| 7 | 不显示总数（不加 COUNT）。 |
| 8 | database 组件必填，无 enable 开关。 |

## 3. 架构与组件化

### 模块结构

```
backend/database/
├── base.py      # Database Protocol + FakeDatabase（测试用内存实现）
└── postgres.py  # PostgresDatabase：连接池 + 全部 SQL
```

### 各层改动

| 层 | 改动 |
|---|---|
| `schema.py` | 新增 `DatabaseConfig(url, pool_size=5, import_path=None)`；`AppConfig` 加 `database` 字段；解析校验 `database.url` 必填。 |
| `config/*.yaml` | 14 个 profile 统一加 `database:` 段（local→`localhost:5432`；docker→compose 服务名 `postgres`）。 |
| `container.py` | `database` provider：`Selector` 按 type（`postgres`）选 `PostgresDatabase`；`build_database()` 支持 `import_path`。 |
| `bootstrap.py` | `Application.__init__` 加 `self.database`；`init_connections()` 中 `_start_component("database", ...)`；`stop()` 逆序停；`component_errors` 机制自动覆盖。 |
| `main.py` | ① `/api/monitor` 组件列表加 database 行；② index/delete/files 三处接入（见 §5）。 |
| `files/base.py` | `FileRecord` 加 `s3_url`/`size`（默认 None）；`FilePage` 加 `prev_cursor`（默认 None），向后兼容 store 层。 |

### Database Protocol（`database/base.py`）

```python
class Database(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    @property
    def ready(self) -> bool: ...

    def upsert_file(self, app_id, file_id, filename, s3_url, *, size=None, chunk_count=0) -> None
    def soft_delete_file(self, app_id, file_id) -> int   # 受影响行数（0=不存在或已软删）
    def list_files(self, app_id, limit=50, cursor=None, direction="next") -> FilePage
    def purge_app(self, app_id) -> int   # app 级物理清理
```

## 4. 建表 SQL（`start()` 时幂等执行）

```sql
CREATE TABLE IF NOT EXISTS app_files (
    id          BIGSERIAL PRIMARY KEY,
    app_id      VARCHAR(64)   NOT NULL,          -- 租户隔离
    file_id     UUID          NOT NULL,
    filename    VARCHAR(1024) NOT NULL,
    s3_url      TEXT          NOT NULL,          -- 追溯来源
    size        BIGINT,
    chunk_count INTEGER       NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    deleted_at  TIMESTAMPTZ,                     -- 软删除标记
    CONSTRAINT uq_app_files_app_file UNIQUE (app_id, file_id)
);

CREATE INDEX IF NOT EXISTS idx_app_files_listing
    ON app_files (app_id, created_at DESC, id DESC)
    WHERE deleted_at IS NULL;                    -- 部分索引，列表/翻页查询专用
```

**关键 SQL**：

- **upsert**（索引成功；重复/重新索引时恢复软删记录）：
  `INSERT INTO app_files (app_id, file_id, filename, s3_url, size, chunk_count) VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (app_id, file_id) DO UPDATE SET filename=EXCLUDED.filename, s3_url=EXCLUDED.s3_url, size=EXCLUDED.size, chunk_count=EXCLUDED.chunk_count, deleted_at=NULL, updated_at=now()`

- **软删**：`UPDATE app_files SET deleted_at=now(), updated_at=now() WHERE app_id=$1 AND file_id=$2 AND deleted_at IS NULL`

- **物理清理**（app 销毁）：`DELETE FROM app_files WHERE app_id=$1`

## 5. 接口接入

### index（写入/恢复记录）

- **同步 `_index_object`**：`index_presigned_object` 成功后调 `application.database.upsert_file(app_id, file_id, filename, s3_url, size=os.path.getsize(tmp), chunk_count=count)`。
- **异步 `_create_index_job`**：consumer 消费成功处 upsert（job 已含 `app_id/file_id/s3_url/filename`，`chunk_count` 来自 `index_presigned_object` 返回值；失败重试耗尽**不写记录**）。
- 重新索引同一 `file_id` → upsert 自动"复活"记录。

### delete（软删记录）

- `DELETE /api/open/files/{file_id}`（AK/SK）与 `DELETE /api/files/{file_id}`（管理台）共用 `_delete_index_file`：
  - 现状：`store.delete_file_chunks(file_id)` 硬删向量库 chunks。
  - 新增：`application.database.soft_delete_file(app_id, file_id)`。
  - 管理台版仍删 MinIO 对象（现状不变）。

### `GET /api/files`（改读 PG）

```
GET /api/files?limit=50[&cursor={id}&direction=next|prev]
```

响应（`prev_cursor`/`next_cursor` 为 null 表示对应方向没有更多页；`has_more` 保留 = `next_cursor` 非空）：

```json
{
  "files": [{"id", "filename", "s3_url", "size", "created_at", "chunk_count"}],
  "prev_cursor": 58,
  "next_cursor": 20,
  "has_more": true
}
```

### app 级销毁

`DELETE /api/apps/{app_id}` 与 drop database 端点调 `database.purge_app(app_id)` 物理清该 app 的 PG 记录。

## 6. 双向 keyset 分页（纯 id 数字游标）

游标 = BIGSERIAL 主键 `id`。`id` 自增单调、与 `created_at` 同序（`created_at` 均由服务端 `datetime.now(utc)` 生成，不回填），因此列表按 `created_at DESC, id DESC` 展示时，用 `id` 做翻页锚点语义等价且性能平稳。

```sql
-- 下一页（direction=next）：id 小于游标
WHERE app_id=$1 AND deleted_at IS NULL AND id < $2
ORDER BY created_at DESC, id DESC
LIMIT $3 + 1

-- 上一页（direction=prev）：id 大于游标，反着取再反转
WHERE app_id=$1 AND deleted_at IS NULL AND id > $2
ORDER BY created_at ASC, id ASC
LIMIT $3 + 1
```

- 多取 1 条判断 has_more。
- 翻页后 `prev_cursor` 取该页第一条的 id（prev 方向为反转后的首行），`next_cursor` 取该页最后一条的 id。
- 服务端无状态：游标即定位值；无 COUNT、无页码。
- 注意：`(created_at DESC, id DESC)` 排序保持稳定，即使 created_at 相同也由 id 决定次序，不重不漏。

## 7. 前端改动（`frontend/src/views/UploadView.vue`）

- 文件列表去掉滚动触底加载逻辑。
- 底部加"上一页 / 下一页"两个按钮：
  - `prev_cursor` 为 null → 上一页按钮禁用；`next_cursor` 为 null → 下一页按钮禁用。
  - 点击后请求 `GET /api/files?cursor={X}&direction=prev|next`。
- 无总数、无页码显示。

## 8. 部署改动

- `deploy/cpu` 与 `deploy/gpu` 的 `docker-compose.yml` 加 `postgres` 服务：
  - `postgres:16-alpine`，健康检查（`pg_isready`），数据卷 `../../pg_data`，backend `depends_on` postgres（healthy）。
- 14 个 `config/*.yaml` 加 `database.url`（native 用 `localhost:5432`；docker 用 `postgres:5432`）。
- `backend/pyproject.toml` 加 `psycopg[binary]`、`psycopg-pool` 依赖。
- README、`docs/architecture.md` 补充 database 组件说明。

## 9. 测试策略

| 层级 | 方案 |
|---|---|
| unit | `database/postgres.py` SQL 拼接（mock `ConnectionPool`）；游标方向/边界。 |
| e2e | `FakeDatabase`（`database/base.py` 内内存实现）注入 `application.database`，**不依赖真实 PG**；更新 `test_files_api.py`（改断言 fake database 结果）、`test_config_api.py::test_monitor_returns...`（components 含 database）。 |
| 现有回归 | `files/base.py` 字段扩展均为默认值，store 层测试不受影响。 |

## 10. 风险与注意

- 列表语义变化：`/api/files` = "已成功索引的文件"（原 = "MinIO 已上传对象"），索引失败的文件不出现在列表（已确认接受）。
- psycopg3 为新增后端依赖，`uv.lock` 需重新生成。
- 14 个 profile + compose 全部要同步加 database 段，遗漏会导致启动失败（schema 校验必填）。
- consumer 线程（`ThreadPoolExecutor`）调用 database：`psycopg_pool.ConnectionPool` 线程安全，无需额外加锁。
