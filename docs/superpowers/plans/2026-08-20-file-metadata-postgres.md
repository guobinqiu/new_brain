# 文件元数据迁移 PostgreSQL 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将文件元数据从 MinIO 列表迁移到 PostgreSQL，新增一等 database 组件，支持软删除与双向 keyset 翻页。

**Architecture:** 新增 `database` 组件（Database Protocol + PostgresDatabase + FakeDatabase），与 store/dense 等平级，由 DI 容器装配、Application 统一管理生命周期。`app_files` 单表存文件元数据（app_id 隔离、软删除 deleted_at、upsert 复活）。`GET /api/files` 改读 PG 双向 keyset 分页（纯 id 数字游标）。index 成功 upsert、delete 软删、app 销毁物理清理。

**Tech Stack:** PostgreSQL 16、psycopg3（psycopg[binary] + psycopg-pool）、FastAPI、Vue 3。

**设计文档：** docs/superpowers/specs/2026-08-20-file-metadata-postgres-design.md

## Global Constraints

- 全流程 TDD：先写失败测试，确认失败，再实现，确认通过，最后 commit。
- 后端测试命令：`cd backend && .venv/bin/python -m pytest <test路径> -v`（unit 测试默认带 `-m unit`；e2e 带 `-m e2e`）。
- e2e 测试不得依赖真实 PostgreSQL：注入 `FakeDatabase`。
- 游标 = 表主键 `id`（BIGSERIAL 数字字符串）；`files[].id` = 业务 `file_id`（UUID）。二者不同。
- 分页语义：列表按 `created_at DESC, id DESC`（新→旧）；`next` = 更旧方向（`id < cursor`）；`prev` = 更新方向（`id > cursor`，取回反转）。
- 不加 COUNT、不加页码、不加 database.enable 开关。
- 14 个 config/*.yaml 必须全部加 `database:` 段，否则 schema 校验失败。
- 变量命名统一：`prev_cursor` / `next_cursor` / `has_more`。
- FileRecord/FilePage 定义于 backend/database/base.py；store 层 list_files/count_files 死代码与 backend/files 包在 Task 2 一并删除（保持每 commit 全绿）。

---

### Task 1: 依赖与配置模型（pyproject + schema + 14 个 profile）

**Files:**
- Modify: `backend/pyproject.toml`（dependencies 段）
- Modify: `backend/schema.py`
- Modify: `backend/config/*.yaml`（14 个文件）
- Create: `backend/tests/unit/test_database_config.py`
- Modify: `backend/tests/unit/test_config_profiles.py`

**Interfaces:**
- Produces: `schema.DatabaseConfig(type, url, pool_size=5, import_path=None)`；`AppConfig.database: DatabaseConfig`。

- [ ] **Step 1: 写失败测试** `backend/tests/unit/test_database_config.py`

```python
import pytest

from schema import parse_app_config


def _base_raw(url=None):
    return {
        "database": {"type": "postgres", "url": url or "postgresql://rag:rag@localhost:5432/rag", "pool_size": 3},
        "dense": {"name": "test_dense", "model_path": "/tmp/dense"},
        "sparse": {"type": "bm25", "tokenizer": "jieba"},
        "store": {"type": "qdrant", "url": "http://localhost:6333"},
        "search": {},
        "rerank": None,
        "ocr": {"name": "test_ocr", "model_path": "/tmp/ocr"},
        "auth": {"admin": {"username": "admin", "password": "x"}},
    }


def test_database_config_parsed():
    config = parse_app_config(_base_raw())
    assert config.database.type == "postgres"
    assert config.database.url == "postgresql://rag:rag@localhost:5432/rag"
    assert config.database.pool_size == 3


def test_database_url_required():
    raw = _base_raw()
    raw["database"] = {"type": "postgres"}
    with pytest.raises(ValueError):
        parse_app_config(raw)


def test_database_type_whitelisted():
    raw = _base_raw()
    raw["database"] = {"type": "mysql", "url": "mysql://x"}
    with pytest.raises(ValueError):
        parse_app_config(raw)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_database_config.py -v`
Expected: FAIL（`AttributeError: 'AppConfig' object has no attribute 'database'`）

- [ ] **Step 3: 实现 schema.py 与 pyproject.toml**

`backend/pyproject.toml` dependencies 列表追加（`minio>=7.2.0` 之后）：

```toml
    "psycopg[binary]>=3.2.0",
    "psycopg-pool>=3.2.0",
```

`backend/schema.py` 新增 dataclass（放在 `StoreConfig` 之后）：

```python
@dataclass(frozen=True)
class DatabaseConfig:
    type: str
    url: str
    pool_size: int = 5
    import_path: str | None = None
```

`AppConfig` 加字段（`store` 之后）：

```python
    database: DatabaseConfig
```

`parse_app_config` 开头（`store = raw.get("store") or {}` 之后）：

```python
    database = raw.get("database") or {}
```

`store_type = _required(...)` 之后加：

```python
    database_type = _parse_sparse_backend_type(database)
```

无需新函数：直接复用现有模式，在 `_validate_supported("store.type", ...)` 那行后加：

```python
    database_name = database.get("type") or database.get("name")
    if database_name is None:
        raise ValueError("database.type is required")
    _validate_supported("database.type", database_name, {"postgres", "database/postgres"})
    _required(database, "url", "database")
```

`AppConfig(...)` 构造中 `store=StoreConfig(...)` 之后加：

```python
        database=DatabaseConfig(
            type=database_name,
            url=_required(database, "url", "database"),
            pool_size=int(database.get("pool_size", 5)),
            import_path=database.get("import_path"),
        ),
```

- [ ] **Step 4: 更新 14 个 config yaml**

对 `backend/config/` 下全部 14 个文件，在顶层（`logging:` 之前）插入：

```yaml
database:
  type: postgres
  url: postgresql://rag:rag@localhost:5432/rag
  pool_size: 5
  import_path: database.postgres.PostgresDatabase
```

例外：`docker-cpu.yaml` 与 `docker-gpu.yaml` 的 url 用 `postgresql://rag:rag@postgres:5432/rag`（compose 服务名）。

- [ ] **Step 5: 运行测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_database_config.py tests/unit/test_config_loader.py -v`
Expected: PASS（`test_config_loader.py` 应继续通过，说明默认配置可解析）

- [ ] **Step 6: 在 test_config_profiles.py 加 profile 完整性断言**

`backend/tests/unit/test_config_profiles.py` 末尾（`_is_component_group` 之前）加：

```python
def test_profiles_define_database_component():
    for path in CONFIG_DIR.glob("*.yaml"):
        config = _read_config(path.name)

        assert config["database"]["type"] == "postgres"
        assert "url" in config["database"]
        assert "import_path" in config["database"]
        assert "." in config["database"]["import_path"]
```

- [ ] **Step 7: 运行 profile 测试**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_config_profiles.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
cd /Users/guobin/workspace/qdrant
git add backend/pyproject.toml backend/schema.py backend/config backend/tests/unit/test_database_config.py backend/tests/unit/test_config_profiles.py
git commit -m "feat: 新增 database 配置模型与 psycopg 依赖"
```

---

### Task 2: 数据模型扩展 + Database Protocol + FakeDatabase

**Files:**
- Modify: `backend/database/base.py`（新建文件，含 FileRecord + FilePage + Database Protocol + FakeDatabase）
- Modify: `backend/store/base.py`（删除 list_files/count_files 声明与 `from files.base import FilePage`）
- Modify: `backend/store/qdrant.py`、`backend/store/chroma.py`、`backend/store/milvus.py`（删除 list_files/count_files 方法及 `from store.files import ...`）
- Delete: `backend/files/`（含 base.py、__init__.py）
- Delete: `backend/store/files.py`
- Delete: `backend/tests/unit/test_files_repository.py`
- Create: `backend/database/__init__.py`
- Create: `backend/tests/unit/test_database_base.py`（新增）

**Interfaces:**
- Consumes: `schema.DatabaseConfig`（Task 1）
- Produces:
  - `database.base.FileRecord`（+`s3_url`/`size`）、`FilePage`（+`prev_cursor`）——无其他层 import 这两个类型
  - `database.base.Database` Protocol：`start/stop/ready`、`upsert_file(app_id, file_id, filename, s3_url, *, size=None, chunk_count=0)`、`soft_delete_file(app_id, file_id) -> int`、`list_files(app_id, limit=50, cursor=None, direction="next") -> FilePage`、`purge_app(app_id) -> int`
  - `database.base.FakeDatabase`（内存实现，供测试注入）

- [ ] **Step 1: 写失败测试** `backend/tests/unit/test_database_base.py`

```python
import pytest

from database.base import FakeDatabase


def _seed(db):
    for i, fname in enumerate(["a.txt", "b.txt", "c.txt", "d.txt"]):
        db.upsert_file("app1", f"f{i}", fname, f"s3://b/{fname}", size=10 + i, chunk_count=1)


def test_upsert_and_soft_delete():
    db = FakeDatabase()
    _seed(db)
    assert db.soft_delete_file("app1", "f1") == 1
    assert db.soft_delete_file("app1", "f1") == 0  # 幂等
    page = db.list_files("app1")
    assert [r.id for r in page.files] == ["f3", "f2", "f0"]  # f1 已软删，新→旧


def test_upsert_restores_soft_deleted():
    db = FakeDatabase()
    _seed(db)
    db.soft_delete_file("app1", "f0")
    db.upsert_file("app1", "f0", "a.txt", "s3://b/a.txt", size=99, chunk_count=5)
    page = db.list_files("app1")
    assert any(r.id == "f0" and r.chunk_count == 5 for r in page.files)


def test_list_first_page_and_next():
    db = FakeDatabase()
    _seed(db)  # 4 条
    page = db.list_files("app1", limit=2)
    assert [r.id for r in page.files] == ["f3", "f2"]
    assert page.next_cursor is not None
    assert page.prev_cursor is None
    assert page.has_more is True

    page2 = db.list_files("app1", limit=2, cursor=page.next_cursor, direction="next")
    assert [r.id for r in page2.files] == ["f1", "f0"]
    assert page2.has_more is False
    assert page2.next_cursor is None
    assert page2.prev_cursor is not None


def test_list_prev_page():
    db = FakeDatabase()
    _seed(db)
    page = db.list_files("app1", limit=2)
    page2 = db.list_files("app1", limit=2, cursor=page.next_cursor, direction="next")
    back = db.list_files("app1", limit=2, cursor=page2.prev_cursor, direction="prev")
    assert [r.id for r in back.files] == ["f3", "f2"]
    assert back.prev_cursor is None  # 已到最新边界
    assert back.has_more is True


def test_purge_app():
    db = FakeDatabase()
    _seed(db)
    assert db.purge_app("app1") == 4
    assert db.list_files("app1").files == []


def test_prev_requires_cursor():
    db = FakeDatabase()
    with pytest.raises(ValueError):
        db.list_files("app1", direction="prev")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_database_base.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'database'`）

- [ ] **Step 3: 实现 database/base.py 数据模型**

`backend/database/base.py` 顶部（Database Protocol 之前）加入（文件头不再出现 `files.base` import，不再修改 `backend/files/base.py`）：

```python
from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True)
class FileRecord:
    id: str
    filename: str
    chunk_count: int
    created_at: str | None = None
    s3_url: str | None = None
    size: int | None = None


@dataclass(frozen=True)
class FilePage:
    files: list[FileRecord]
    next_cursor: str | None
    has_more: bool
    prev_cursor: str | None = None
```

- [ ] **Step 4: 实现 database 包**

`backend/database/__init__.py`：

```python
from database.base import Database, FakeDatabase

__all__ = ["Database", "FakeDatabase"]
```

`backend/database/base.py`：

```python
from __future__ import annotations

from typing import Protocol


class Database(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    @property
    def ready(self) -> bool: ...

    def upsert_file(self, app_id: str, file_id: str, filename: str, s3_url: str, *, size: int | None = None, chunk_count: int = 0) -> None: ...
    def soft_delete_file(self, app_id: str, file_id: str) -> int: ...
    def list_files(self, app_id: str, limit: int = 50, cursor: str | None = None, direction: str = "next") -> FilePage: ...
    def purge_app(self, app_id: str) -> int: ...


class FakeDatabase:
    """内存实现，供测试注入 application.database，避免 e2e 依赖真实 PG。

    分页语义与 PostgresDatabase 完全一致：列表按 (created_at, id) DESC（新→旧）；
    next = id < cursor；prev = id > cursor 取回反转。
    """

    def __init__(self):
        self._rows: dict[tuple[str, str], dict] = {}
        self._next_id = 1
        self.ready = True

    def start(self) -> None:
        self.ready = True

    def stop(self) -> None:
        self.ready = False

    def upsert_file(self, app_id, file_id, filename, s3_url, *, size=None, chunk_count=0) -> None:
        key = (app_id, file_id)
        row = self._rows.get(key)
        if row is None:
            row = {
                "id": str(self._next_id),
                "app_id": app_id,
                "file_id": file_id,
                "filename": filename,
                "s3_url": s3_url,
                "size": size,
                "chunk_count": chunk_count,
                "created_at": "2026-08-20T00:00:00+00:00",
                "deleted_at": None,
            }
            self._next_id += 1
            self._rows[key] = row
        else:
            row.update(filename=filename, s3_url=s3_url, size=size, chunk_count=chunk_count, deleted_at=None)

    def soft_delete_file(self, app_id, file_id) -> int:
        row = self._rows.get((app_id, file_id))
        if row is None or row["deleted_at"] is not None:
            return 0
        row["deleted_at"] = "2026-08-20T00:00:00+00:00"
        return 1

    def list_files(self, app_id, limit=50, cursor=None, direction="next") -> FilePage:
        if limit <= 0:
            raise ValueError("limit must be greater than 0")
        limit = min(limit, 200)
        rows = [r for r in self._rows.values() if r["app_id"] == app_id and r["deleted_at"] is None]
        rows.sort(key=lambda r: (r["created_at"], int(r["id"])), reverse=True)  # 新→旧
        cursor_id = int(cursor) if cursor is not None else None
        if direction == "prev":
            if cursor_id is None:
                raise ValueError("cursor is required for prev direction")
            raw = [r for r in rows if int(r["id"]) > cursor_id]
            raw.sort(key=lambda r: (r["created_at"], int(r["id"])))  # 旧→新
            raw = raw[: limit + 1]
            page_rows = list(reversed(raw))
            prev_cursor = str(page_rows[0]["id"]) if len(raw) > limit else None
            last_id = int(page_rows[-1]["id"]) if page_rows else None
            has_more = last_id is not None and any(int(r["id"]) < last_id for r in rows)
            next_cursor = str(last_id) if has_more else None
        else:
            if cursor_id is not None:
                rows = [r for r in rows if int(r["id"]) < cursor_id]
            page_rows = rows[: limit + 1]
            has_more = len(page_rows) > limit
            page_rows = page_rows[:limit]
            prev_cursor = str(page_rows[0]["id"]) if cursor_id is not None and page_rows else None
            next_cursor = str(page_rows[-1]["id"]) if has_more else None
        return FilePage(
            files=[
                FileRecord(
                    id=r["file_id"],
                    filename=r["filename"],
                    chunk_count=r["chunk_count"],
                    created_at=r["created_at"],
                    s3_url=r["s3_url"],
                    size=r["size"],
                )
                for r in page_rows
            ],
            prev_cursor=prev_cursor,
            next_cursor=next_cursor,
            has_more=has_more,
        )

    def purge_app(self, app_id) -> int:
        keys = [k for k in self._rows if k[0] == app_id]
        for k in keys:
            del self._rows[k]
        return len(keys)
```

- [ ] **Step 5: 删除 store 死代码与 files 包**

- `backend/store/base.py`：删除 `list_files` 声明、`count_files` 声明、`from files.base import FilePage`（保留 get_search_documents/get_total_chunks/list_chunks 等其余接口）
- `backend/store/qdrant.py`、`chroma.py`、`milvus.py`：删除各自 `list_files`、`count_files` 方法及顶部 `from store.files import ...`
- 删除 `backend/store/files.py`、`backend/files/`、`backend/tests/unit/test_files_repository.py`
- 注意：`get_total_chunks` 有真实调用方（search/pipeline.py:46、main.py:782），必须保留。

- [ ] **Step 6: 运行测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_database_base.py -v`
Expected: PASS（新数据模型与 FakeDatabase 测试）

Run: `cd backend && .venv/bin/python -m pytest tests/unit -v`
Expected: PASS（确认无残留 files/store.files 引用，预期全绿）

- [ ] **Step 7: Commit**

```bash
cd /Users/guobin/workspace/qdrant
git add backend/database backend/store backend/tests/unit/test_database_base.py
git rm -r backend/files backend/store/files.py backend/tests/unit/test_files_repository.py
git commit -m "feat: FileRecord/FilePage 迁入 database 组件，Database Protocol + FakeDatabase，清理 store 死代码"
```

---

### Task 3: PostgresDatabase 实现

**Files:**
- Create: `backend/database/postgres.py`
- Create: `backend/tests/unit/test_database_postgres.py`

**Interfaces:**
- Consumes: `Database` Protocol、`FilePage`/`FileRecord`（Task 2）
- Produces: `database.postgres.PostgresDatabase(url, pool_size=5)`，实现 Database Protocol。建表 SQL（`app_files` + 部分索引）在 `start()` 幂等执行。

- [ ] **Step 1: 写失败测试** `backend/tests/unit/test_database_postgres.py`

用假连接池驱动 `list_files` 的分页逻辑（不连真实 PG）：

```python
from database.postgres import PostgresDatabase, FIRST_PAGE_SQL, NEXT_PAGE_SQL, PREV_PAGE_SQL


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConn:
    def __init__(self, page_rows, probe_rows=None):
        self._page_rows = page_rows
        self._probe_rows = probe_rows
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if sql.startswith("SELECT 1"):
            return FakeCursor(self._probe_rows or [])
        return FakeCursor(self._page_rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakePool:
    def __init__(self, page_rows, probe_rows=None):
        self._page_rows = page_rows
        self._probe_rows = probe_rows
        self.conn = None

    def connection(self):
        self.conn = FakeConn(self._page_rows, self._probe_rows)
        return self.conn


def _row(i, file_id):
    return {
        "id": i,
        "app_id": "app1",
        "file_id": file_id,
        "filename": f"{file_id}.txt",
        "s3_url": f"s3://b/{file_id}.txt",
        "size": 10,
        "chunk_count": 1,
        "created_at": __import__("datetime").datetime(2026, 8, 20, tzinfo=__import__("datetime").timezone.utc),
    }


def _db(rows, probe_rows=None):
    db = PostgresDatabase(url="postgresql://x")
    db._pool = FakePool(rows, probe_rows)
    db.ready = True
    return db


def test_first_page_uses_first_page_sql():
    db = _db([_row(4, "f4"), _row(3, "f3"), _row(2, "f2")])  # limit=2 → 多取1判断 has_more
    page = db.list_files("app1", limit=2)
    assert [r.id for r in page.files] == ["f4", "f3"]
    assert page.has_more is True
    sql, params = db._pool.conn.executed[0]
    assert sql == FIRST_PAGE_SQL
    assert params == ("app1", 3)


def test_next_page_uses_next_page_sql():
    db = _db([_row(2, "f2"), _row(1, "f1")])
    page = db.list_files("app1", limit=2, cursor="3", direction="next")
    assert [r.id for r in page.files] == ["f2", "f1"]
    assert page.has_more is False
    sql, params = db._pool.conn.executed[0]
    assert sql == NEXT_PAGE_SQL
    assert params == ("app1", 3, 3)


def test_prev_page_reverses_rows():
    # prev 查询 ASC 取回 [2,3,4]，反转后本页 [4,3]；取到 limit+1 条 → 还有更新的
    db = _db([_row(2, "f2"), _row(3, "f3"), _row(4, "f4")], probe_rows=[_row(1, "f1")])
    page = db.list_files("app1", limit=2, cursor="1", direction="prev")
    assert [r.id for r in page.files] == ["f4", "f3"]
    assert page.prev_cursor is not None
    assert page.has_more is True  # 探测到 id < 3 的记录（更旧方向）
    sql, params = db._pool.conn.executed[0]
    assert sql == PREV_PAGE_SQL
    assert params == ("app1", 1, 3)


def test_prev_at_newest_boundary_has_no_prev_cursor():
    db = _db([_row(3, "f3"), _row(4, "f4")], probe_rows=[])  # 已到最新边界，且无更旧记录
    page = db.list_files("app1", limit=2, cursor="1", direction="prev")
    assert [r.id for r in page.files] == ["f4", "f3"]
    assert page.prev_cursor is None
    assert page.has_more is False


def test_prev_requires_cursor():
    db = _db([])
    try:
        db.list_files("app1", direction="prev")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_record_maps_file_id_and_iso_created_at():
    db = _db([_row(1, "f1")])
    page = db.list_files("app1")
    record = page.files[0]
    assert record.id == "f1"
    assert record.created_at == "2026-08-20T00:00:00+00:00"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_database_postgres.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'database.postgres'`）

- [ ] **Step 3: 实现 PostgresDatabase** `backend/database/postgres.py`

```python
from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from database.base import FilePage, FileRecord

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS app_files (
    id          BIGSERIAL PRIMARY KEY,
    app_id      VARCHAR(64)   NOT NULL,
    file_id     UUID          NOT NULL,
    filename    VARCHAR(1024) NOT NULL,
    s3_url      TEXT          NOT NULL,
    size        BIGINT,
    chunk_count INTEGER       NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    deleted_at  TIMESTAMPTZ,
    CONSTRAINT uq_app_files_app_file UNIQUE (app_id, file_id)
)
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_app_files_listing
    ON app_files (app_id, created_at DESC, id DESC)
    WHERE deleted_at IS NULL
"""

UPSERT_FILE_SQL = """
INSERT INTO app_files (app_id, file_id, filename, s3_url, size, chunk_count)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (app_id, file_id) DO UPDATE SET
    filename = EXCLUDED.filename,
    s3_url = EXCLUDED.s3_url,
    size = EXCLUDED.size,
    chunk_count = EXCLUDED.chunk_count,
    deleted_at = NULL,
    updated_at = now()
"""

SOFT_DELETE_SQL = """
UPDATE app_files SET deleted_at = now(), updated_at = now()
WHERE app_id = %s AND file_id = %s AND deleted_at IS NULL
"""

PURGE_APP_SQL = "DELETE FROM app_files WHERE app_id = %s"

_LIST_SELECT = "id, app_id, file_id, filename, s3_url, size, chunk_count, created_at"

FIRST_PAGE_SQL = f"""
SELECT {_LIST_SELECT} FROM app_files
WHERE app_id = %s AND deleted_at IS NULL
ORDER BY created_at DESC, id DESC
LIMIT %s
"""

NEXT_PAGE_SQL = f"""
SELECT {_LIST_SELECT} FROM app_files
WHERE app_id = %s AND deleted_at IS NULL AND id < %s
ORDER BY created_at DESC, id DESC
LIMIT %s
"""

PREV_PAGE_SQL = f"""
SELECT {_LIST_SELECT} FROM app_files
WHERE app_id = %s AND deleted_at IS NULL AND id > %s
ORDER BY created_at ASC, id ASC
LIMIT %s
"""


class PostgresDatabase:
    def __init__(self, url: str, pool_size: int = 5):
        self.url = url
        self.pool_size = pool_size
        self._pool: ConnectionPool | None = None
        self.ready = False

    def start(self) -> None:
        self._pool = ConnectionPool(
            self.url,
            min_size=1,
            max_size=self.pool_size,
            open=False,
            kwargs={"row_factory": dict_row},
        )
        self._pool.open()
        self._pool.wait()
        with self._pool.connection() as conn:
            conn.execute(CREATE_TABLE_SQL)
            conn.execute(CREATE_INDEX_SQL)
        self.ready = True

    def stop(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None
        self.ready = False

    def upsert_file(self, app_id, file_id, filename, s3_url, *, size=None, chunk_count=0) -> None:
        with self._pool.connection() as conn:
            conn.execute(UPSERT_FILE_SQL, (app_id, file_id, filename, s3_url, size, chunk_count))

    def soft_delete_file(self, app_id, file_id) -> int:
        with self._pool.connection() as conn:
            cur = conn.execute(SOFT_DELETE_SQL, (app_id, file_id))
            return cur.rowcount

    def purge_app(self, app_id) -> int:
        with self._pool.connection() as conn:
            cur = conn.execute(PURGE_APP_SQL, (app_id,))
            return cur.rowcount

    def list_files(self, app_id, limit=50, cursor=None, direction="next") -> FilePage:
        if limit <= 0:
            raise ValueError("limit must be greater than 0")
        limit = min(limit, 200)
        cursor_id = int(cursor) if cursor is not None else None
        if direction == "prev":
            if cursor_id is None:
                raise ValueError("cursor is required for prev direction")
            with self._pool.connection() as conn:
                raw = conn.execute(PREV_PAGE_SQL, (app_id, cursor_id, limit + 1)).fetchall()
            rows = list(reversed(raw))
            prev_cursor = str(rows[0]["id"]) if len(raw) > limit else None
            has_more = False
            next_cursor = None
            if rows:
                last_id = rows[-1]["id"]
                with self._pool.connection() as conn:
                    probe = conn.execute(
                        "SELECT 1 FROM app_files WHERE app_id = %s AND deleted_at IS NULL AND id < %s LIMIT 1",
                        (app_id, last_id),
                    ).fetchone()
                has_more = probe is not None
                next_cursor = str(last_id) if has_more else None
        else:
            if cursor_id is None:
                with self._pool.connection() as conn:
                    rows = conn.execute(FIRST_PAGE_SQL, (app_id, limit + 1)).fetchall()
            else:
                with self._pool.connection() as conn:
                    rows = conn.execute(NEXT_PAGE_SQL, (app_id, cursor_id, limit + 1)).fetchall()
            has_more = len(rows) > limit
            page_rows = rows[:limit]
            prev_cursor = str(page_rows[0]["id"]) if cursor_id is not None and page_rows else None
            next_cursor = str(page_rows[-1]["id"]) if has_more else None
        page_rows = rows[:limit]
        return FilePage(
            files=[_record(row) for row in page_rows],
            prev_cursor=prev_cursor,
            next_cursor=next_cursor,
            has_more=has_more,
        )


def _record(row: dict) -> FileRecord:
    created_at = row["created_at"]
    return FileRecord(
        id=row["file_id"],
        filename=row["filename"],
        chunk_count=row["chunk_count"],
        created_at=created_at.isoformat() if created_at else None,
        s3_url=row["s3_url"],
        size=row["size"],
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_database_postgres.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/guobin/workspace/qdrant
git add backend/database/postgres.py backend/tests/unit/test_database_postgres.py
git commit -m "feat: PostgresDatabase 连接池与 app_files 建表/增删查"
```

---

### Task 4: 容器与 Application 接入（container + bootstrap + monitor）

**Files:**
- Modify: `backend/container.py`
- Modify: `backend/bootstrap.py`
- Modify: `backend/main.py`（monitor 组件行）
- Modify: `backend/tests/unit/test_container.py`（如需新增断言）
- Modify: `backend/tests/unit/test_bootstrap.py`（如需新增断言）
- Modify: `backend/tests/e2e/test_config_api.py`

**Interfaces:**
- Consumes: `PostgresDatabase`（Task 3）、`DatabaseConfig`（Task 1）
- Produces: `container.build_database(config) -> Database`；`Application.database` 属性；`/api/monitor` components 含 `{"name": "database", ...}`。

- [ ] **Step 1: 写失败测试**（conftest 注入 FakeDatabase + monitor 契约）

先修改 `backend/tests/conftest.py` 的 `api_client` fixture 中 `main.application = main.Application()` 为：

```python
    from database.base import FakeDatabase
    main.application = main.Application(database=FakeDatabase())
```

（`anonymous_api_client` 保持不动。）

`backend/tests/e2e/test_config_api.py` 中 `test_monitor_returns_runtime_data_and_index_contract` 的 `components` 断言处追加：

```python
        assert "database" in components
```

先运行确认失败：

Run: `cd backend && .venv/bin/python -m pytest tests/e2e/test_config_api.py::TestConfigAPI::test_monitor_returns_runtime_data_and_index_contract -v`
Expected: FAIL（`TypeError: Application.__init__() got an unexpected keyword argument 'database'`）

- [ ] **Step 2: 实现 container.py**

`backend/container.py` 头部 import 加：

```python
from database.base import Database
from database.postgres import PostgresDatabase
```

`ApplicationContainer` 中 `store_timeout` 之后加：

```python
    database_type = providers.Callable(lambda app_config: _component_key(app_config.database.type), config)
    database_url = providers.Callable(lambda app_config: app_config.database.url, config)
    database_pool_size = providers.Callable(lambda app_config: app_config.database.pool_size, config)
```

`store = providers.Selector(...)` 之后加：

```python
    database = providers.Selector(
        database_type,
        postgres=providers.Singleton(PostgresDatabase, url=database_url, pool_size=database_pool_size),
    )
```

文件末尾 `build_ocr` 之后加：

```python
def build_database(config: AppConfig) -> Database:
    if config.database.import_path:
        cls = _load_class(config.database.import_path)
        return cls(url=config.database.url, pool_size=config.database.pool_size)
    return _resolve(create_container(config).database, "database", config.database.type)
```

- [ ] **Step 3: 实现 bootstrap.py**

`backend/bootstrap.py` 头部 import 加：

```python
from database.base import Database
```

`__init__` 签名加参数（`ocr` 之后）：

```python
        database: Database | None = None,
```

`__init__` 体（`self.ocr = ...` 之后）：

```python
        self.database = database or self.container.database()
```

`init_connections` 中（`self._start_component("search", self.search)` 之后）：

```python
        self._start_component("database", self.database)
```

`stop` 中（`self.store.stop()` 之后）：

```python
        self.database.stop()
```

- [ ] **Step 4: 实现 main.py monitor 行**

`backend/main.py` monitor 端点中 `_component_status(application.ocr, ...)` 之后加：

```python
            {
                "name": "database",
                "status": _component_status(application.database, enabled=True, error=application.component_errors.get("database")),
            },
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/e2e/test_config_api.py tests/unit/test_container.py tests/unit/test_bootstrap.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/guobin/workspace/qdrant
git add backend/container.py backend/bootstrap.py backend/main.py backend/tests
git commit -m "feat: database 组件接入 DI 容器、Application 生命周期与 monitor"
```

---

### Task 5: GET /api/files 改读 PG + FakeDatabase 注入

**Files:**
- Modify: `backend/main.py`（files 端点、删除 MinIO 列表函数）
- Modify: `backend/tests/conftest.py`
- Modify: `backend/tests/e2e/test_files_api.py`
- Modify: `backend/tests/unit/test_qdrant_api_contract.py`（删除 test_list_storage_files_uses_minio_object_pagination）

**Interfaces:**
- Consumes: `Application.database.list_files`（Task 4）
- Produces: `GET /api/files?limit&cursor&direction` 响应 `{"files": [{id, filename, s3_url, size, created_at, chunk_count}], "prev_cursor", "next_cursor", "has_more"}`。

- [ ] **Step 1: 写失败测试**（重写 e2e 列表测试，数据经 `main.application.database`（FakeDatabase）注入）

> 注：conftest 的 FakeDatabase 注入已在 Task 4 Step 1 完成，此处不再重复。
> 注：保留 `test_delete_file_api`/`test_delete_nonexistent`（monkeypatch `_delete_storage_file`，函数保留），仅替换两个列表测试。

`backend/tests/e2e/test_files_api.py` 替换两个列表测试：

```python
    def test_list_files_api_uses_cursor_pagination(self, app_api_client, api_client, monkeypatch):
        """``GET /api/files`` returns PG-backed file pages via keyset cursors."""
        import main

        db = main.application.database
        for i, name in enumerate(["first.txt", "second.txt"]):
            db.upsert_file(app_api_client.app_id, f"file-{name}", name, f"s3://rag-dev/uploads/{app_api_client.app_id}/f/{name}", size=i + 1)

        first_page = api_client.get("/api/files", params={"app_id": app_api_client.app_id, "limit": 1})

        assert first_page.status_code == 200
        first_body = first_page.json()
        assert len(first_body["files"]) == 1
        assert first_body["prev_cursor"] is None
        assert first_body["next_cursor"]
        assert first_body["has_more"] is True

        second_page = api_client.get("/api/files", params={"app_id": app_api_client.app_id, "limit": 1, "cursor": first_body["next_cursor"], "direction": "next"})

        assert second_page.status_code == 200
        second_body = second_page.json()
        assert len(second_body["files"]) == 1
        assert {first_body["files"][0]["id"], second_body["files"][0]["id"]} == {"file-first.txt", "file-second.txt"}
        assert second_body["has_more"] is False
        assert second_body["next_cursor"] is None

        back = api_client.get("/api/files", params={"app_id": app_api_client.app_id, "limit": 1, "cursor": second_body["prev_cursor"], "direction": "prev"})

        assert back.status_code == 200
        assert back.json()["files"][0]["id"] == first_body["files"][0]["id"]
        assert back.json()["prev_cursor"] is None

    def test_list_files_api(self, app_api_client, api_client, monkeypatch):
        """``GET /api/files`` lists indexed files from PG."""
        import main

        main.application.database.upsert_file(app_api_client.app_id, "file-a", "test_ai.txt", f"s3://rag-dev/uploads/{app_api_client.app_id}/file-a/test_ai.txt", size=7)

        resp = api_client.get("/api/files", params={"app_id": app_api_client.app_id})

        assert resp.status_code == 200
        files = resp.json()["files"]
        assert any(item["id"] == "file-a" and item["filename"] == "test_ai.txt" for item in files)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/e2e/test_files_api.py -v`
Expected: FAIL（files 端点仍走 MinIO `_list_storage_files`，返回空 / 字段不符）

- [ ] **Step 3: 实现 files 端点**

`backend/main.py` 中 `@app.get("/api/files")` 改为：

```python
@app.get("/api/files")
def files(limit: int = 50, cursor: str | None = None, direction: str = "next", app_id: str | None = None, principal: Principal = Depends(require_jwt)):
    _require_ready()
    try:
        page = application.database.list_files(
            _database_principal(principal, app_id).app_id,
            limit=limit,
            cursor=cursor,
            direction=direction,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "files": [_file_record(record) for record in page.files],
        "prev_cursor": page.prev_cursor,
        "next_cursor": page.next_cursor,
        "has_more": page.has_more,
    }
```

新增辅助函数（替换原 `_storage_file_record`）：

```python
def _file_record(record) -> dict[str, Any]:
    return {
        "id": record.id,
        "filename": record.filename,
        "s3_url": record.s3_url,
        "size": record.size,
        "created_at": record.created_at,
        "chunk_count": record.chunk_count,
    }
```

删除不再使用的函数：`_list_storage_files`、`_storage_file_record`、`_file_id_from_object_name`（保留 `_delete_storage_file`、`_upload_file_to_storage`、`_minio_client`、`_storage_prefix`、`_storage_file_prefix`——upload/delete 仍用）。

同步删除 `test_qdrant_api_contract.py::test_list_storage_files_uses_minio_object_pagination`（被测函数已删）。保留 `test_upload_file_to_storage_puts_object_in_bucket` / `test_client_delete_file_removes_index_only` / `test_storage_presign...`（对应函数保留）。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/e2e/test_files_api.py tests/unit/test_qdrant_api_contract.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/guobin/workspace/qdrant
git add backend/main.py backend/tests/conftest.py backend/tests/e2e/test_files_api.py
git commit -m "feat: /api/files 改读 PG 双向 keyset 分页，e2e 注入 FakeDatabase"
```

---

### Task 6: index / delete 接口接入（upsert、软删、app 清理）

**Files:**
- Modify: `backend/indexing/service.py`
- Modify: `backend/indexing/consumer.py`
- Modify: `backend/main.py`（`_index_object`、`_delete_index_file`、app 删除端点）
- Modify: `backend/tests/unit/test_index_consumer.py`
- Modify: `backend/tests/unit/test_app_management.py`

**Interfaces:**
- Consumes: `Application.database.upsert_file/soft_delete_file/purge_app`（Task 4）
- Produces: `indexing.service.index_presigned_object` 返回值改为 `(chunk_count, file_size)`。

- [ ] **Step 1: 写失败测试**（consumer 成功路径调用 upsert）

`backend/tests/unit/test_index_consumer.py` 加：

```python
def test_consumer_upserts_database_record_on_success():
    import indexing.consumer as consumer_mod

    calls = []
    db = type("FakeDB", (), {
        "upsert_file": lambda self, app_id, file_id, filename, s3_url, **kw: calls.append((app_id, file_id, filename, s3_url, kw)),
    })()
    app = type("FakeApp", (), {"database": db})()
    consumer = consumer_mod.InlineIndexConsumer(app)
    consumer._upsert_record({"app_id": "app1", "file_id": "f1", "chunk_count": 3, "size": 10, "s3_url": "s3://b/a.txt", "filename": "a.txt"})
    assert calls == [("app1", "f1", "a.txt", "s3://b/a.txt", {"size": 10, "chunk_count": 3})]
```

（测试先定下 `_upsert_record` 静态方法契约；实现时在 `_run_job` 成功路径调用它。）

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_index_consumer.py::test_consumer_upserts_database_record_on_success -v`
Expected: FAIL（`AttributeError: type object 'InlineIndexConsumer' has no attribute '_upsert_record'`）

- [ ] **Step 3: 实现 service.py 返回 size**

`backend/indexing/service.py` 中 `index_file` 之后新增，`index_presigned_object` 改为：

```python
def index_presigned_object(application, file_id: str, presigned_url: str, s3_url: str, filename: str | None = None) -> tuple[int, int]:
    """返回 ``(chunk_count, file_size)``。"""
    resolved_filename = filename or filename_from_s3_url(s3_url)
    ext = Path(resolved_filename).suffix.lower()
    validate_supported_file_extension(ext)
    path = Path(download_presigned_file(presigned_url, ext))
    try:
        file_size = path.stat().st_size
        count = index_file(application, file_id, path, resolved_filename, extra_metadata={"s3_url": s3_url})
        return count, file_size
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
```

- [ ] **Step 4: 实现 consumer.py**

`backend/indexing/consumer.py` 的 `_run_job` 成功分支改为：

```python
        result = await asyncio.wait_for(
            loop.run_in_executor(
                self.executor,
                ctx.run,
                functools.partial(_index_object, self.application, job),
            ),
            timeout=self.timeout,
        )
        self._upsert_record(result)
        return

`InlineIndexConsumer` 的 `_upsert_record` 实现为**实例方法**：

```python
    def _upsert_record(self, result: dict) -> None:
        self.application.database.upsert_file(
            result["app_id"],
            result["file_id"],
            result["filename"],
            result["s3_url"],
            size=result["size"],
            chunk_count=result["chunk_count"],
        )
```

（原 staticmethod + `__application` 的写法已废弃。）
```

`_index_object` 改为返回 size 与来源字段：

```python
    with application.store.app_context(app_id):
        count, file_size = index_presigned_object(application, file_id, presigned_url, s3_url, filename)
    logger.info(...)  # 原样保留
    return {
        "app_id": app_id,
        "file_id": file_id,
        "chunk_count": count,
        "size": file_size,
        "s3_url": s3_url,
        "filename": filename,
    }
```

- [ ] **Step 5: 实现 main.py 同步索引 upsert**

`backend/main.py` `_index_object` 中 `count = index_presigned_object(...)` 改为：

```python
            count, file_size = index_presigned_object(
                application,
                file_id=file_id,
                presigned_url=req.presigned_url,
                s3_url=req.s3_url,
                filename=filename,
            )
            application.database.upsert_file(
                effective_principal.app_id,
                file_id,
                filename,
                req.s3_url,
                size=file_size,
                chunk_count=count,
            )
```

- [ ] **Step 6: 实现 delete 软删**

`backend/main.py` `_delete_index_file` 改为：

```python
def _delete_index_file(file_id: str, principal: Principal) -> dict[str, Any]:
    _require_ready()
    scoped_store = _scoped_store(principal)
    deleted_chunks = scoped_store.delete_file_chunks(file_id)
    application.database.soft_delete_file(principal.app_id, file_id)
    return {"deleted_chunks": deleted_chunks}
```

- [ ] **Step 7: 实现 app 级清理**

`backend/main.py` 中删除 app（`DELETE /api/apps/{app_id}`）与删除 database（`DELETE /api/apps/{app_id}/database`）端点的删除逻辑处，各加一行：

```python
    application.database.purge_app(app_id)
```

（在两个端点各自的 collection 删除调用之后、返回之前。）

- [ ] **Step 8: 运行测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_index_consumer.py tests/unit/test_index_enqueue.py tests/e2e/test_files_api.py tests/e2e/test_upload_api.py tests/unit/test_app_management.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
cd /Users/guobin/workspace/qdrant
git add backend/indexing backend/main.py backend/tests
git commit -m "feat: index 成功 upsert 文件记录、delete 软删、app 销毁物理清理"
```

---

### Task 7: 前端 UploadView 按钮翻页

**Files:**
- Modify: `frontend/src/views/UploadView.vue`
- Modify: `frontend/src/i18n/locales/zh.json`
- Modify: `frontend/src/i18n/locales/en.json`

**Interfaces:**
- Consumes: `GET /api/files?limit&cursor&direction`（Task 5）

- [ ] **Step 1: 修改 UploadView.vue 模板**

删除 `<el-button v-if="filesHasMore ..." @click="fetchNextFiles">`（loadMore 按钮），在 `</el-table>` 之后加：

```vue
        <div class="docs-pager">
          <el-button :disabled="!filesPrevCursor || filesLoading" @click="fetchFiles('prev')">{{ t('common.prevPage') }}</el-button>
          <el-button :disabled="!filesNextCursor || filesLoading" @click="fetchFiles('next')">{{ t('common.nextPage') }}</el-button>
        </div>
```

- [ ] **Step 2: 修改 UploadView.vue 脚本**

删除 `filesCursor`、`filesHasMore`、`filesTableRef`、`onFilesScroll`、`fetchNextFiles`；替换为：

```js
const filesPrevCursor = ref(null)
const filesNextCursor = ref(null)

async function fetchFiles(direction) {
  if (filesLoading.value) return
  filesLoading.value = true
  try {
    const params = { limit: 50 }
    if (activeAppStore.appId) params.app_id = activeAppStore.appId
    if (direction === 'next' && filesNextCursor.value) params.cursor = filesNextCursor.value
    if (direction === 'prev' && filesPrevCursor.value) {
      params.cursor = filesPrevCursor.value
      params.direction = 'prev'
    }
    const res = await axios.get(`${API}/files`, { params })
    files.value = res.data.files || []
    filesPrevCursor.value = res.data.prev_cursor || null
    filesNextCursor.value = res.data.next_cursor || null
  }
  catch (err) { console.error(err) }
  finally { filesLoading.value = false }
}
```

`uploadSelectedFiles`/`deleteFile` 里调用 `await fetchFiles()`（不带 direction → 回到第一页）；`onMounted(fetchFiles)` 保持不变。

删除模板中表格上的 `@scroll="onFilesScroll"`。

- [ ] **Step 3: 加 i18n key**

`zh.json` 的 `common` 段加：

```json
"prevPage": "上一页",
"nextPage": "下一页"
```

`en.json` 的 `common` 段加：

```json
"prevPage": "Previous",
"nextPage": "Next"
```

- [ ] **Step 4: 验证**

Run: `cd frontend && npm run build`
Expected: 构建成功（无语法错误）。前端无测试框架，手工验证：登录 → 上传 3+ 文件 → 文件列表显示第一页（limit 50 内全部）→ 上一页按钮禁用 → 点击下一页翻页。

- [ ] **Step 5: Commit**

```bash
cd /Users/guobin/workspace/qdrant
git add frontend/src/views/UploadView.vue frontend/src/i18n/locales
git commit -m "feat: 文件列表改左右按钮翻页（keyset 双向）"
```

---

### Task 8: 部署（compose postgres 服务 + 文档）

**Files:**
- Modify: `deploy/cpu/docker-compose.yml`
- Modify: `deploy/gpu/docker-compose.yml`
- Modify: `backend/tests/unit/test_deploy_layout.py`
- Modify: `README.md`
- Modify: `docs/architecture.md`

- [ ] **Step 1: 写失败测试**（deploy 布局）

`backend/tests/unit/test_deploy_layout.py` 加：

```python
def test_deploy_runs_postgres_service():
    for compose_file in ("deploy/cpu/docker-compose.yml", "deploy/gpu/docker-compose.yml"):
        compose = (ROOT / compose_file).read_text(encoding="utf-8")

        assert "postgres:16-alpine" in compose
        assert "pg_isready" in compose
        assert "../../pg_data:/var/lib/postgresql/data" in compose
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_deploy_layout.py::test_deploy_runs_postgres_service -v`
Expected: FAIL

- [ ] **Step 3: 修改两个 compose**

`deploy/cpu/docker-compose.yml` 与 `deploy/gpu/docker-compose.yml` 的 `services:` 下、`qdrant:` 之前插入：

```yaml
  postgres:
    image: postgres:16-alpine
    container_name: rag-postgres
    environment:
      TZ: ${TZ:-Asia/Shanghai}
      POSTGRES_USER: rag
      POSTGRES_PASSWORD: rag
      POSTGRES_DB: rag
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U rag -d rag"]
      interval: 5s
      timeout: 3s
      retries: 10
    ports:
      - "15432:5432"
    volumes:
      - ../../pg_data:/var/lib/postgresql/data
    restart: unless-stopped
```

`backend:` 服务加（`restart` 之前）：

```yaml
    depends_on:
      postgres:
        condition: service_healthy
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_deploy_layout.py -v`
Expected: PASS

- [ ] **Step 5: 更新文档**

`README.md` 的"数据目录"一节加：

```text
pg_data/           # PostgreSQL 文件元数据（app_files 表）
```

`docs/architecture.md` 新增"database 组件"小节，说明：PG 承载文件元数据、软删除、upsert 复活、双向 keyset 纯 id 游标、e2e 用 FakeDatabase。

- [ ] **Step 6: Commit**

```bash
cd /Users/guobin/workspace/qdrant
git add deploy/cpu/docker-compose.yml deploy/gpu/docker-compose.yml backend/tests/unit/test_deploy_layout.py README.md docs/architecture.md
git commit -m "feat: 部署增加 postgres 服务与文档说明"
```

---

## 回归验证（全部完成后执行）

Run: `cd backend && .venv/bin/python -m pytest -m "not benchmark" -v`
Expected: 全绿（新增测试 + 存量回归）

如遇失败，按 superpowers:systematic-debugging 处理，禁止猜修复。
