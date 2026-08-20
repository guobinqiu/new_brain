# 架构 D：Postgres 文件元数据表

> 本文件是架构设计方案，不是实现计划。面向后续 TDD/coder 拆任务执行。
> 落地后需同步更新 `docs/architecture.md`（新增 §2.9「文件元数据表」，并在 §2.6/§2.8 补充 files 列表与删除语义变化），以及 `docs/api.md` 的「上传文件列表」「删除索引文件」两节。
> 前置依赖：架构 C（`docs/architecture-c-inline-index-worker.md`）已落地，索引为进程内 `InlineIndexConsumer`（单并发、fire-and-forget、无任务记录）。

---

## 1. 背景与动机

### 1.1 现状痛点

架构 C 把索引收敛为 backend 进程内队列后，索引状态完全不可见（只能靠搜索验证）；文件列表能力也一直残缺：

- `GET /api/files`（`main.py` L651 → `_list_storage_files` L825-850）直接 `client.list_objects` 列 MinIO，游标分页按对象名字典序。对象 key 是 `uploads/{app_id}/{file_id}/{filename}`，`file_id` 是随机 uuid4 hex → **顺序无意义**。
- 无业务字段：原文件名只能从 key 尾段取，无索引状态、无 chunk 数、无过滤能力、时间来自对象 last_modified。
- 索引状态不可见：上传三步链（upload → presign → index/jobs）之后，用户没有任何入口知道索引是排队中、处理中、成功还是失败。

### 1.2 目标

1. 引入 **Postgres** 单表 `files` 作为文件元数据真相源：文件列表、索引状态、chunk 数、时间全部走 db。
2. 分页改为 db keyset 分页，按上传时间倒序，游标稳定。
3. 写路径全挂接：上传、入队、消费（成功/失败/重试）、删除（对内/对外）都维护 `status`。
4. 前端文件列表展示状态徽标、chunk 数、时间，并对进行中的任务轮询刷新。
5. MinIO 历史文件启动回填，不劣于现状。
6. 元数据作为独立服务可直接对外查询（运营/排障/BI，见 §12）。

### 1.3 不做的（YAGNI）

- 不引入 Redis/消息队列；不加 SQLAlchemy 等 ORM（理由见 §5.1）。
- 不做基于 `SKIP LOCKED` 的多消费者队列改造（本轮仍是架构 C 的进程内队列；§1.4-2 只是要求数据库层不堵死这条路）。
- 不做任务队列持久化、不做索引任务的取消 API、不做 SSE 状态推送（架构 C 已砍，本轮不复活；轮询够用）。
- 不改 `POST /api/upload`、`POST /api/presign`、`POST /api/index(/open)/jobs` 的请求/响应契约（响应仍是 `{file_id, s3_url, filename}` / `{file_id}`）。
- 不处理「open 删除后向量与状态不一致」（见 §6.4 已知限制，与现状一致）。
- 不清理 `store.list_files` 遗留接口（`store/base.py` L34、`store/files.py`、`files.base.FileRecord`——向量库推导文件列表的旧路径，`main.py` 已不调用；列为本设计之外的可选清理项）。

### 1.4 存储引擎决策记录：为什么 Postgres（用户拍板）

早期草案曾按嵌入式单文件库（SQLite）设计（零依赖、零运维），多轮讨论后**改为 Postgres**，理由如下，落定不再反复：

1. **多实例是硬需求**：滚动发版期间会有两个 backend 同时存活，单文件库的 db 文件无法跨实例共享（文件锁在网络文件系统上不可靠），该路线是死路。
2. **索引消费的扩展路**：将来索引消费可能多并发/多实例，Postgres 行级锁 + `SELECT ... FOR UPDATE SKIP LOCKED` 是多消费者任务分发的成熟模式，扩展路是通的。
3. **元数据可直接对外查询**：Postgres 作为独立服务，运营/排障/BI/上游对账可直连查询（failed 文件、索引吞吐、app 维度统计、s3_url 对账），不用为每个运营问题写 API。这是明确要求的能力（§12）。
4. **运维生态**：pg_dump 备份、监控、工具链成熟。

历史佐证：`backend/files/__pycache__/postgres.cpython-311.pyc` 遗迹表明项目早期实现过 postgres 文件层；`.gitignore` L19 也早有 `postgres_data/` 条目。本设计的 `files/db.py` 相当于以新表结构重启该分层。

成本对价：多一个容器（§5.3）、一条 `psycopg` 依赖（§5.1）、一个 `DATABASE_URL` 配置；单实例形态下这些成本恒定且小，换来上述四项能力。

---

## 2. 目标架构流程

```text
POST /api/upload（内部，main.py L329）
  └─ 存 MinIO（uploads/{app_id}/{file_id}/{filename}）      # 不变
  └─ INSERT files 行 status='uploaded'                       # 新增；db 失败只 log 不阻断

POST /api/index/jobs | /api/open/index/jobs（_create_index_job L409）
  └─ enqueue_index_job(...) → queue.Queue                    # 不变（满→429）
  └─ UPSERT files 行 status='pending'                        # 新增；db 失败只 log

InlineIndexConsumer._run_job（consumer.py L86）
  └─ begin_processing(job):                                  # 新增
       UPDATE ... WHERE (app_id, file_id) 置 'processing'
       ├─ 影响 0 行（行不存在）→ 跳过本任务（log index_job_skipped_no_record，见 §6.3）
       └─ 影响 1 行           → 继续消费
  └─ asyncio.wait_for(_index_object(...), timeout=1800)
       ├─ 成功           → UPDATE status='done', chunk_count=N, error=NULL
       ├─ ValueError     → UPDATE status='failed', error=str(exc)   # 不可重试
       ├─ Timeout/Exception 且 retry_count < 2
       │    └─ 重新入队（静默）；status 保持 'processing'（见 §4.2）
       │    └─ 重入队遇 queue full → UPDATE status='failed', error=...
       └─ Timeout/Exception 且 retry_count == 2
            → UPDATE status='failed', error=reason

GET /api/files（L651）
  └─ SELECT ... WHERE app_id=%(app_id)s AND (created_at, file_id) < (%(c)s, %(f)s)
       ORDER BY created_at DESC, file_id DESC LIMIT n+1      # 替换 _list_storage_files

DELETE /api/files/{file_id}（对内，L681）
  └─ 删向量 chunks（不变）→ 删 MinIO 对象（不变）→ DELETE files 行（新增，最后）
DELETE /api/open/files/{file_id}（对外，L676）
  └─ 只删向量 chunks（不变）；不动 MinIO、不动 db 行

启动（lifespan）
  └─ init_pool(): 连接池建立（连不上则 log，RAG 主功能继续）
  └─ init_db(): schema_migrations 表 + 按序应用迁移（advisory lock 串行化）
  └─ 后台回填线程：list MinIO uploads/ → INSERT ... ON CONFLICT DO NOTHING status='unknown'
```

**三真相源原则**（本设计的失败语义基线）：

- **MinIO 是对象真相源**：对象在，文件就存在（内部上传）；对象删了，文件就没了。
- **向量库是索引真相源**：chunks 在，就搜得到。
- **Postgres 是元数据真相源**：列表、状态、时间的唯一读路径；db 写失败不阻断主流程，读失败即端点 500。

---

## 3. 关键决策表

| 关键问题 | 决策（一句话） |
|---|---|
| 数据库 | Postgres 16（compose 服务 `postgres:16-alpine`，§5.3）；`psycopg[binary,pool]`（psycopg3）裸 SQL，**无 ORM**（§5.1） |
| 表 | 一张 `files` 表，复合主键 `(app_id, file_id)` |
| status 枚举 | `uploaded / pending / processing / done / failed / unknown` 六态（§4.2） |
| 重试中状态 | **保持 `processing`**：静默重试是内部机制，不回 `pending`，避免状态抖动；重试次数记 `retry_count` 字段 |
| 连接管理 | `psycopg_pool.ConnectionPool`，min_size=1 / max_size=5，lifespan 启动开池、关闭收池；每操作 `with pool.connection()` 借还，块退出自动 commit/回滚（§5.2） |
| 隔离级别 | pg 默认 **READ COMMITTED**，够用：全部写都是主键定行的单语句事务，不存在跨语句读-改-写竞态（§5.2） |
| updated_at 刷新 | **应用层**：每条 UPDATE 显式带 `updated_at = now()`（库端时钟，多实例无时钟偏差）；不用触发器——SQL 收敛在 `files/db.py` 可见即可见，简单够用 |
| 建表迁移 | lifespan 内 `init_db()`：`schema_migrations` 表 + 启动按序应用未执行版本，`pg_advisory_lock` 串行化（滚动发版两实例安全，§5.4） |
| upload 写库 | 存 MinIO 成功后 INSERT `status='uploaded'`；db 失败记日志（`files_db_write_failed`）不阻断返回 |
| 入队写库 | `enqueue_index_job` 成功后 UPSERT `status='pending'`；外部上游文件（未走 upload）的行由此创建，`s3_url` 指向上游自己的对象存储（语义：索引时用的 s3_url） |
| 消费写库 | 消费前 `begin_processing`（UPDATE 影响 0 行→跳过任务）；成功→`done`+`chunk_count`；ValueError→`failed`+`error`；重试耗尽→`failed`+`error`；重入队 queue full 丢弃→`failed`+`error`；重试期间不动 db |
| 删除写库 | 对内 delete：向量→MinIO→db 行，三处都删，db 最后；对外 delete：只删向量，**不动 db 行**（对象在即显示，与现状语义一致） |
| 读路径 | `GET /api/files` 全量切 db；**不保留 MinIO fallback**（双路径复杂度 > 收益；回填可自愈） |
| 分页 | keyset：`ORDER BY created_at DESC, file_id DESC`，行值比较 `(created_at, file_id) < (...)`（pg 原生支持）；cursor 明文 `"{created_at}|{file_id}"`（ISO UTC） |
| 时间存储 | `TIMESTAMPTZ` + 库端 `DEFAULT now()`；响应与游标统一 UTC ISO 字符串（db 层读出时转换，§7.2）；展示时区交给前端（与 §17「存储层保存 UTC」一致） |
| 历史数据 | 启动后台 daemon 线程回填：list MinIO `uploads/` 全量 `INSERT ... ON CONFLICT DO NOTHING`，`status='unknown'`，`created_at` 用对象 last_modified |
| 前端 | 列表加 status 徽标 + chunk_count 列 + failed error tooltip；存在 `pending/processing` 行时每 5s 轮询刷新，否则停 |
| 与在途任务的删除竞态 | 消费前检查行存在才执行 → 删除即取消（§6.3 取舍） |
| 对外直连 | 端口照现有 minio/qdrant 暴露风格映射 `15432:5432`；只读角色建议不强制（§12） |

### 3.1 待确认决策（需与负责人确认，不伪装成结论）

1. **回填是否查向量库区分 `done`/`unknown`**：默认回填一律 `unknown`（历史文件索引状态不可知，前端显示「未知」徽标）。可选增强：回填时对每个 file_id 调 `get_total_chunks([file_id])`，>0 标 `done`。代价是启动时 N 次向量库查询。**默认不查**。
2. **open delete 后管理台是否继续显示该文件**：默认继续显示（db 行不动，对象/行都在，与现状「MinIO 对象在就显示」一致；但状态 `done` 与向量已删的事实不符，属已知限制）。若上游期望删后即隐，需改 open delete 也删 db 行——会引入「行删了但对象还在，下次回填又 INSERT 回来（unknown）」的循环，需要配套 `deleted` 标记，复杂化。**默认不动**。
3. **消费前「行不存在→跳过」的误伤面**：唯一现实诱因除删除外，是 `index/jobs` 的 upsert 恰好 db 写失败（行没建出来）→ 任务被跳过、索引不执行，但 API 已返回 202。概率极低（pg 单行写失败）且后果可自愈（重新触发）。若不可接受，改软删除标记方案（§6.3 备选）。**默认跳过**。

---

## 4. 数据模型设计

### 4.1 表结构 DDL（schema v1）

```sql
CREATE TABLE IF NOT EXISTS files (
    app_id TEXT NOT NULL,
    file_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    s3_url TEXT NOT NULL,
    size BIGINT,                          -- 字节；外部上游文件未知为 NULL
    content_type TEXT,                    -- 仅内部 upload 提供；其余 NULL
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('uploaded','pending','processing','done','failed','unknown')),
    chunk_count INTEGER,                  -- 仅 done 有值
    error TEXT,                           -- 仅 failed 有值；重试中间态不写
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),   -- 首见时间，不随更新变
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),   -- 应用层每次 UPDATE 显式带 now()
    PRIMARY KEY (app_id, file_id)
);

-- 列表分页专用索引（app 内按时间倒序 + file_id 决胜）
CREATE INDEX IF NOT EXISTS idx_files_app_created
    ON files (app_id, created_at DESC, file_id DESC);
```

字段说明与取舍：

- **复合主键 `(app_id, file_id)`** 而非 `file_id` 单列：file_id 虽是 uuid4 hex 全局唯一，但业务所有读写都以 app 为边界（`_database_principal` 强制 app 上下文）；open API 允许调用方自带 file_id，复合主键天然按 app 分区，避免跨 app 理论撞号场景的歧义。
- **`size`/`content_type` 可空**：内部 upload 有（`_upload_file_to_storage` L891 入参）；open 外部文件 job 字典里没有，NULL。
- **`size` 用 BIGINT**：文件字节数理论可超 2^31；pg BIGINT 8 字节直接覆盖。
- **`retry_count`**：consumer 放弃时写入最终重试次数（诊断用）；不驱动任何逻辑。
- **不存 `bucket`**：`s3_url` 是 `s3://{bucket}/{key}` 完整形式，bucket 可从中解析（`parse_s3_url`）。
- **时间用 `TIMESTAMPTZ` + 库端 `now()`**：绝对时刻存储，多实例写无时钟偏差；比较/排序即时间序（不再依赖字符串字典序）。会话时区（容器 `TZ=Asia/Shanghai`）只影响显示，不影响存储与比较；对外输出统一 UTC ISO（§7.2）。
- **`updated_at` 应用层刷新**：每条 UPDATE 语句显式带 `updated_at = now()`；不建触发器（SQL 全部收敛在 `files/db.py`，触发器会把写路径藏到库端，排查反而绕）。
- **不改 `FileRecord`**（`files/base.py`，被 `store/files.py` 遗留路径使用）：db 行用新 dataclass `FileMeta`（§4.3）。

### 4.2 状态机

```text
                 POST /api/upload
                      │ INSERT
                      ▼
                 [uploaded] ──────────── 三步链断在 presign/index 时的稳态
                      │ POST index/jobs 成功入队（UPSERT）
                      ▼
[pending] ◀──重新入队不回此态── [processing] ── ValueError ──▶ [failed]
    │  ▲                         │    │
    │  └──（仅首次入队/重新入队）  │    ├── 成功 ──▶ [done]（chunk_count=N, error=NULL）
    │                            │    ├── 超时/异常且 retry<2 ── 静默重入队，status 不变
    ▼                            │    ├── 超时/异常且 retry==2 ──▶ [failed]（error=reason）
（消费开始）──────────────────────┘    └── 重入队遇 queue full ──▶ [failed]（error=...）

[unknown]：启动回填 MinIO 历史对象（ON CONFLICT DO NOTHING），不经状态机
[done] ── 同 file_id 再次 POST index/jobs ──▶ [pending]（重新索引，UPSERT 覆盖）
任意态 ── 对内 DELETE ──▶ 行删除（消费前检查使在途任务随之失效）
```

**重试中保持 `processing` 的理由**：

1. 重试是静默重入队（架构 C §4.2，max 2），对调用方不可见；「这次提交正在被处理」比「任务在队列里的精确位置」对用户更有信息量。
2. `pending↔processing` 往返抖动会让前端轮询看到假进度，且重试窗口最长 3×30min，抖动没有任何可操作性。
3. 终态 `failed` 的 `error` 已含 reason 与 retry_count，诊断信息不丢失。

**`uploaded` 与 `unknown` 的区别**：`uploaded` 是系统自己刚写的（已知未入队）；`unknown` 是回填推断的（历史对象，索引状态不可知）。前端两者都显示中性徽标，但语义分开，避免把「我们没赶上入队」和「历史遗留」混为一谈。

### 4.3 模块布局与数据结构

沿用既有的 `backend/files/` 包（该包当前只剩 `base.py` 的 `FileRecord/FilePage`，是历史预留的文件元数据分层——且 `__pycache__/postgres.cpython-311.pyc` 遗迹表明此处曾有过 postgres 实现，本设计重启该分层）：

```text
backend/files/
  __init__.py     # 导出 FileMeta
  base.py         # 现有 FileRecord/FilePage 不动；新增 FileMeta dataclass
  db.py           # 新增：连接池 / init_db()迁移 / 全部 CRUD（本设计唯一新模块）
```

```python
# 伪代码 / 数据结构示意，非实现代码
@dataclass(frozen=True)
class FileMeta:
    app_id: str
    file_id: str
    filename: str
    s3_url: str
    size: int | None
    content_type: str | None
    status: str            # 六态之一
    chunk_count: int | None
    error: str | None
    retry_count: int
    created_at: str        # UTC ISO（db 层读出时统一转换，§7.2）
    updated_at: str        # UTC ISO
```

---

## 5. db 访问层设计

### 5.1 为什么 psycopg3 裸 SQL（明确推荐）

| 维度 | psycopg3 裸 SQL（推荐） | SQLAlchemy |
|---|---|---|
| 依赖 | 一条 `psycopg[binary,pool]`：驱动 + 预编译二进制 + 官方连接池全含，无编译环境要求 | Core/ORM 全家桶；uv.lock 里虽有（langchain 传递依赖），但要正经用就得声明为直接依赖，版本策略、镜像体积、审计面都变大 |
| 模型复杂度 | 一张表、约 8 个 CRUD 函数，SQL 全部手写可读 | ORM 映射、Session 管理、engine 配置全是为此刻不需要的抽象付的税 |
| 团队惯例 | 项目现有风格偏标准库与薄封装（`app_registry.py` 文件存储、`log_buffer.py` 环形缓冲） | 无既有 SQLAlchemy 代码可对齐 |
| 演进 | 单表 CRUD 裸 SQL 十年不动；真到多表/复杂查询时再评估引入 | — |

**结论：psycopg3 裸 SQL。** 唯一约束：所有 SQL 收敛在 `files/db.py` 一个模块内，禁止散落到 `main.py`/`consumer.py`。

### 5.2 连接池

**模块级单例 `psycopg_pool.ConnectionPool`，lifespan 启停，每操作借还**：

- 线程模型：FastAPI sync 端点跑在线程池（默认 ~40 线程）、consumer 跑在专属单线程 executor、启动/回填各自线程。连接池线程安全、按需借还，天然适配多线程；不再有「跨线程持连」问题。
- 容量：`min_size=1, max_size=5`。写仅发生在上传/入队/状态流转/删除（人速），读是列表页轮询（5s 一拍）——5 连接余量充足，单实例够用。将来多实例扩容时，每实例各自 1-5 连接，pg 默认 `max_connections=100` 可容纳十余实例。
- 事务语义：`with pool.connection() as conn:` 块退出自动 commit、异常自动回滚；每个 CRUD 函数一个块，单语句即单事务。不存在多表多语句事务需求。
- 隔离级别：pg 默认 **READ COMMITTED** 够用——所有写都是主键定行的单语句 UPSERT/UPDATE，无跨语句读-改-写；keyset 读是单 SELECT。不显式改隔离级别。
- 断连自愈：psycopg_pool 借出/归还时检测坏连接并自动重建；pg 重启或闪断后 backend 无需重启。
- 借不到连接（池满）：`pool.connection()` 阻塞等待（默认行为）。当前写入频率下不可能触达 max_size；这是有界的自然背压，无需额外配置。

```python
# 伪代码示意（files/db.py）
_pool: ConnectionPool | None = None

def init_pool():    # lifespan startup 调用
    global _pool
    _pool = ConnectionPool(
        os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        min_size=1, max_size=5, open=True,   # open=True 立即建连，连不上此处抛错
    )

def close_pool():   # lifespan shutdown 调用
    if _pool is not None:
        _pool.close()

@contextmanager
def conn():
    with _pool.connection() as c:   # 借出 → 执行 → 自动 commit/rollback → 归还
        yield c
```

### 5.3 部署形态（compose）

两套 compose（`deploy/cpu/`、`deploy/gpu/`）各新增 `postgres` 服务，backend 加环境变量与启动依赖：

```yaml
  postgres:
    image: postgres:16-alpine          # 选定 16（成熟大版本，alpine 体积小）；暂不上 17，无必要尝鲜
    container_name: rag-postgres
    environment:
      TZ: ${TZ:-Asia/Shanghai}
      POSTGRES_USER: ${POSTGRES_USER:-rag}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-ragpass}
      POSTGRES_DB: ${POSTGRES_DB:-rag}
    ports:
      - "15432:5432"                   # 照 minio 19000 的避让风格改前缀（5432 本机易撞）；部署机无冲突可改 "5432:5432"
    volumes:
      - ../../postgres_data:/var/lib/postgresql/data   # 照 qdrant_data/minio_data 绑定挂载惯例
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 5s
      timeout: 3s
      retries: 12
      start_period: 10s
    restart: unless-stopped
```

backend 服务追加（其余不动）：

```yaml
  backend:
    environment:
      # ...现有 S3_*/LANGSMITH_* 等保持不变...
      DATABASE_URL: ${DATABASE_URL:-postgresql://rag:ragpass@postgres:5432/rag}
    depends_on:
      postgres:
        condition: service_healthy
```

风格依据（逐条对照现有 compose）：

- **凭据**：backend 侧现有 `${S3_ACCESS_KEY:-minioadmin}` 模式（默认值 + .env 可覆盖）；postgres 服务与 backend env 都采用该模式。默认凭据 `rag/ragpass` 仅供内网/开发，对公网暴露前必须改（§12）。
- **数据卷**：现有两套 compose 全部是相对路径绑定挂载（`../../qdrant_data`、`../../minio_data`、`../../milvus_data/*`），无 named volume 先例——**照搬绑定挂载** `../../postgres_data`，不引入 named volume 破坏惯例。`.gitignore` L19 已有 `postgres_data/`，零改动。
- **端口**：qdrant(6333)/milvus(19530) 原端口直暴露、minio(9000→19000) 加前缀避让——两者都暴露，postgres 照做；因 5432 是本机高频端口（开发者本地常装 pg），选 minio 式避让 `15432:5432`。该映射同时服务 §12 的运营直连。
- **healthcheck/depends_on**：现有 compose 无任何 healthcheck、backend 也无任何 depends_on（minio 都没配）——本设计**新增此模式**，理由：pg 与 minio 不同，是 backend 启动即需的强依赖（lifespan 开池+建表+回填），启动顺序错位只会带来无意义的首轮 500；只挂 postgres 一家，minio 保持现状不动。
- **网络**：不加 `networks:` 定义，走默认网络，backend 经服务名 `postgres:5432` 访问（连接串里的主机名即服务名）。

**远端部署影响（写入核对清单，§11）**：多一个 `rag-postgres` 容器；宿主机仓库根新增 `postgres_data/` 数据目录（元数据量级，占用极小）；如需运营直连需放行 15432 端口。

### 5.4 启动迁移

```sql
-- 迁移账本（先于一切业务表存在）
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

```python
# 伪代码示意，位于 lifespan（main.py L134），configure_logging 之后、回填与 consumer 启动之前
MIGRATIONS = [(1, DDL_V1)]   # v1 = files 表 + idx_files_app_created（§4.1）

try:
    files_db.init_pool()      # 连接池；连不上抛错被此处兜住
    files_db.init_db()        # 见下
except Exception:
    logger.exception("files db init failed", extra={"event": "files_db_init_failed"})
    # 不抛出：db 故障时 RAG 主功能（索引/搜索）继续，files 端点运行时报 500

def init_db():
    with conn() as c:
        c.execute("SELECT pg_advisory_lock(70365001)")   # 固定 key；滚动发版两实例串行化
        try:
            c.execute(SCHEMA_MIGRATIONS_DDL)
            applied = {v for (v,) in c.execute("SELECT version FROM schema_migrations").fetchall()}
            for version, sql in MIGRATIONS:
                if version in applied:
                    continue
                with c.transaction():                    # 单迁移单事务
                    c.execute(sql)
                    c.execute("INSERT INTO schema_migrations (version) VALUES (%(v)s)", {"v": version})
        finally:
            c.execute("SELECT pg_advisory_unlock(70365001)")
```

- `IF NOT EXISTS` + 账本判重，幂等；已应用版本直接跳过，毫秒级。
- **advisory lock 是滚动发版的正确性前提**：两实例同启都跑 `init_db`，锁保证迁移串行、账本无竞态。key 取任意固定常量（如 70365001），写死在 `db.py`。
- 未来加列即追加 `(2, "ALTER TABLE ...")`，按序应用；本次只有 v1。

---

## 6. 写路径设计（逐条）

### 6.1 upload（`POST /api/upload`，main.py L329-355）

`_upload_file_to_storage`（L891）成功返回 s3_url 后、`return` 前，INSERT：

```python
# 伪代码示意
try:
    files_db.insert_uploaded(
        app_id=effective_principal.app_id, file_id=file_id,
        filename=file.filename, s3_url=s3_url,
        size=len(content), content_type=file.content_type or "application/octet-stream",
    )   # status='uploaded'；created_at/updated_at 走库端 DEFAULT now()
except Exception:
    logger.exception("files db write failed", extra={
        "event": "files_db_write_failed", "op": "insert_uploaded",
        "app_id": ..., "file_id": file_id})
    # 不阻断：文件已在 MinIO（对象真相源成立），元数据行缺失由启动回填自愈为 unknown
```

**决策：db 写失败不阻断上传。** 反向方案（先插记录再传对象、或失败时补偿删对象）都要引入跨系统补偿逻辑，收益为零——元数据丢了可以回填，对象丢了用户要重传。

### 6.2 `POST /api/index/jobs` 与 `POST /api/open/index/jobs`（`_create_index_job` L409-437）

`enqueue_index_job(...)`（L421）成功后、`return` 前，UPSERT：

```sql
-- mark_pending：外部上游文件（未走 upload）的行由此创建
INSERT INTO files (app_id, file_id, filename, s3_url, status)
VALUES (%(app_id)s, %(file_id)s, %(filename)s, %(s3_url)s, 'pending')
ON CONFLICT (app_id, file_id) DO UPDATE SET
    status = 'pending',
    error = NULL,
    updated_at = now();
```

- **时机：enqueue 成功之后**。若反过来（先 pending 后 enqueue），入队 429 时要把状态改回去，多一条失败路径。代价是 enqueue 成功但 upsert 失败时行缺失——由 consumer 侧策略兜底（§6.3）与回填自愈（仅内部文件）。
- `s3_url` 语义确认为「**索引时用的 s3_url**」：内部文件指我们的 MinIO；外部文件指上游自己的对象存储（`index_presigned_object` 只下载解析，**不转存**到我们的 MinIO——`service.py` L32-43 无上传动作）。因此外部文件行天然没有 size/content_type。
- 同 file_id 重复提交（重新索引）：UPSERT 把 `done/failed` 打回 `pending`，与向量库 `add_file_chunks` 按 file_id delete-then-upsert 的幂等语义对齐。`created_at` 不动（INSERT 分支才产生）；`retry_count` 保留旧值（诊断历史，不驱动逻辑）。
- db 失败：log（`files_db_write_failed`），**不影响 202 返回**——索引本身不依赖 db。

### 6.3 consumer（`indexing/consumer.py` `_run_job` L86-150）

四条路径各挂一个 db 更新，全部包 try/except（失败 log `files_db_write_failed`，绝不影响索引流程）：

```python
# 伪代码示意
async def _run_job(self, job):
    ...
    if not files_db.begin_processing(job):        # ① UPDATE ... WHERE (app_id,file_id) SET status='processing'
        logger.warning("Index job skipped (no db row; deleted?)", extra={
            "event": "index_job_skipped_no_record", "app_id": app_id, "file_id": file_id})
        return                                    #    影响 0 行=行不存在 → 返回 False，跳过整个任务
    try:
        result = await asyncio.wait_for(..., timeout=self.timeout)
        files_db.mark_done(job, chunk_count=result["chunk_count"])   # ② status='done', chunk_count, error=NULL
        return
    except ValueError as exc:
        files_db.mark_failed(job, error=str(exc))                    # ③ 不可重试 → failed
        ...
        return
    except asyncio.TimeoutError:
        reason = f"index timeout after {self.timeout}s"
    except Exception as exc:
        reason = f"index failed: {exc!r}"

    if retry_count < self.retry_max:
        job["retry_count"] = retry_count + 1
        try:
            self.queue.put_nowait(job)           # 静默重入队；db 不动，status 保持 processing
        except _queue.Full:
            files_db.mark_failed(job, error="re-enqueue failed (queue full)")   # ④ 丢弃也算终态失败
            ...
    else:
        files_db.mark_failed(job, error=reason, retry_count=retry_count)        # ⑤ 重试耗尽
        ...
```

要点：

- **消费前检查（`begin_processing`）是删除竞态的取消机制**：对内 delete 删行后，队列里该 file_id 的在途/重试任务消费时直接跳过，不会把 chunks 写回去、也不会把已删行 UPSERT 复活。pg 下实现为单条 `UPDATE ... WHERE app_id=%s AND file_id=%s`，**以影响行数（0/1）作为「行是否存在」的判定**——语义与「先 SELECT 再 UPDATE」严格等价，且少一次往返、无检查-更新间隙。取舍见 §3.1-3：唯一误伤是「upsert 恰好写失败导致行不存在」的极端 db 故障窗口，接受。备选方案（软删除 `deleted` 标记 + UPSERT 带 `WHERE`）复杂度更高，不采用。
- **重试期间不动 db**：`processing` 语义覆盖整个「已开始处理直至终态」区间（§4.2）。
- **`mark_done/mark_failed` 用纯 UPDATE ... WHERE**（与 `begin_processing` 的行数判定配套）：正常流程行一定存在（begin_processing 已确认），UPDATE 只是防御 `processing` 之后行被并发删除的窗口——此时 UPDATE 影响 0 行即可，**不要 INSERT 复活**（实现上用 `UPDATE ... WHERE`，不用 INSERT ON CONFLICT）。
- `_index_object`（L153）本体不动；`chunk_count` 从其返回值取（L178 已返回）。

### 6.4 delete（对内 L681-695 / 对外 L676-678）

**对内 `DELETE /api/files/{file_id}`**（现状：删向量 → 删 MinIO 对象，两步都已存在）追加第三步：

```python
# 伪代码示意，delete_file（L681）尾部
result = _delete_index_file(file_id, effective_principal)     # 不变：向量 chunks
_delete_storage_file(effective_principal.app_id, file_id)     # 不变：MinIO 对象前缀
files_db.delete_file_row(effective_principal.app_id, file_id) # 新增：db 行，最后执行，幂等
```

- 顺序理由：向量与对象是既有主流程；db 行最后删，保证「行存在 ⟹ 对象删除尚未完成或失败」的可诊断性（行还在就能在列表看到残留并重删）。db 删除失败 log 不阻断（对象已删，回填不会复活它——对象不在了）。
- **修复既有不对称的边界**：现状对内删除删 MinIO 原文、open 删除只删向量（§2.8 已记载，是刻意设计，本设计不改变对象层面的不对称，只把 db 对齐到对象语义）。

**对外 `DELETE /api/open/files/{file_id}`**：不动 db 行。理由：open 删除语义是「清掉我写入的向量」，对象的去留由对象拥有方决定；db 行跟对象走（对象在即显示）。已知限制：内部上传的文件被 open 删除向量后，列表仍显示且状态 `done`，但搜不到——与现状（MinIO 对象在就显示）一致，见 §3.1-2。

### 6.5 失败语义总表

| 场景 | 主流程（对象/向量/队列） | db | 用户可见 |
|---|---|---|---|
| upload：MinIO 成功、INSERT 失败 | 成功 | 无行 | 文件可用（可手动入队）；下次启动回填为 `unknown` 自愈 |
| index/jobs：enqueue 429 | 拒绝（429） | 不写 | 前端 toast 报错；行停留 `uploaded`，可重试 |
| index/jobs：enqueue 成功、upsert 失败 | 成功（202） | 无行 | 极端窗口：任务被消费前检查跳过（§3.1-3），重新触发可恢复 |
| consumer：任一状态写失败 | 索引照常执行 | 状态停留旧值 | 状态滞后；不影响索引结果；回填/重新触发自愈 |
| pg 宕机/闪断期间 | 索引/搜索照常 | 写失败只 log | files 端点 500；恢复后连接池自动重连，无需重启 backend |
| delete：向量/对象成功、删行失败 | 成功 | 行残留 | 列表显示已删文件（`done` 但搜不到）；对象已不在，回填不会复活，重删一次即净 |
| files 列表：pg 不可达 | — | 500 | 端点 500；无 MinIO fallback（§7.3） |

---

## 7. 读路径设计

### 7.1 `GET /api/files` 切 db + keyset 分页

替换 `_list_storage_files`（L825-850）为 `files_db.list_files`：

```sql
SELECT app_id, file_id, filename, s3_url, size, content_type,
       status, chunk_count, error, retry_count, created_at, updated_at
FROM files
WHERE app_id = %(app_id)s
  AND (%(cursor_created_at)s IS NULL
       OR (created_at, file_id) < (%(cursor_created_at)s, %(cursor_file_id)s))
ORDER BY created_at DESC, file_id DESC
LIMIT %(limit)s;          -- 应用层已 +1，多取 1 条判定 has_more
```

- **cursor 编码**：明文 `"{created_at}|{file_id}"`（created_at 为 UTC ISO 字符串；与现状 cursor=object_name 的明文风格一致，可调试）。服务端 `cursor.split("|", 1)` 后 `datetime.fromisoformat` 解析（带 `+00:00` 偏移可直接解析）；格式非法/时间不可解析 → `ValueError` → 400（沿用 L656-657 的映射）。
- **行值比较 `(a, b) < (x, y)`**：pg 原生支持，语义等价于 `a < x OR (a = x AND b < y)`，与 `ORDER BY created_at DESC, file_id DESC` 严格互补，keyset 无翻页重影。
- **`created_at` 是 `TIMESTAMPTZ`**：比较按绝对时刻，不依赖任何字符串编码性质；游标里的 ISO 带偏移也不影响正确性。`file_id` 是 uuid hex 定宽，决胜列稳定。
- `limit` 处理沿用现状：`<=0` 报错、clamp 到 200（L826-828 逻辑搬进 `files_db.list_files`）。
- `app_id` 过滤：`_database_principal(principal, app_id)`（L655）不变，admin 缺 app_id 仍 400。

### 7.2 响应结构

外层形状不变（前端零破坏），每条 record 增字段：

```json
{
  "files": [
    {
      "id": "550e8400e29b41d4a716446655440000",
      "filename": "example.pdf",
      "s3_url": "s3://rag-dev/uploads/imsdom/550e.../example.pdf",
      "size": 1024,
      "status": "done",
      "chunk_count": 12,
      "error": null,
      "created_at": "2026-08-18T09:00:00.123456+00:00",
      "updated_at": "2026-08-18T09:03:41.000000+00:00"
    }
  ],
  "next_cursor": null,
  "has_more": false
}
```

- 现有五字段（`id/filename/s3_url/size/created_at`）保留，前端旧列不破。`created_at` 由 MinIO 对象时间变为 db 记录时间（回填行用对象 last_modified，语义连续）。
- 新增 `status/chunk_count/error/updated_at`。`content_type/retry_count` **不进响应**（无消费方，留 db 备查/直查，§12）。
- **时间输出统一 UTC ISO**：db 会话时区可能是 `Asia/Shanghai`（容器 TZ），psycopg 读出的带偏移 datetime 在 db 层构造 `FileMeta` 时统一 `astimezone(timezone.utc).isoformat(timespec="microseconds")`——响应恒为 `+00:00` 结尾的 UTC 字符串。前端时间展示沿用 `shortTime()` 本地化（与 chunk metadata 的 `created_at` 处理一致）。

### 7.3 不保留 MinIO fallback

- 双读路径（db 空/坏时退回 list_objects）意味着两套分页、两套 record 组装、两套测试，维护成本远超「db 服务短时不可用」这一低概率故障的收益。
- 自愈通道已存在：启动回填 `ON CONFLICT DO NOTHING` 会把 MinIO 里有而 db 没有的对象补回（status=`unknown`）。
- pg 不可达时 `GET /api/files` 返回 500（`pool.connection()` 抛 `psycopg.OperationalError`），索引/搜索不受影响。灾难恢复 = 修 pg + 重启 backend 触发回填。

---

## 8. 历史数据回填

**策略：启动后台一次性回填，`INSERT ... ON CONFLICT DO NOTHING`，`status='unknown'`。** 不接受「历史文件不显示」——那是对现状的功能性倒退（现状至少列得出 MinIO 对象）。

```python
# 伪代码示意，lifespan 内 init_db 成功后起 daemon 线程（name="files-backfill"）
def _backfill_storage_files():
    try:
        client, bucket = _minio_client(), os.getenv("S3_BUCKET", "rag-dev")
        if not client.bucket_exists(bucket):
            return
        count = 0
        for item in client.list_objects(bucket, prefix="uploads/", recursive=True):
            object_name = item.object_name
            if object_name.endswith("/"):
                continue
            parts = object_name.split("/")
            if len(parts) < 4 or parts[0] != "uploads":   # 与 _file_id_from_object_name（L886）同规则
                continue
            files_db.insert_unknown_if_absent(            # INSERT ... ON CONFLICT (app_id,file_id) DO NOTHING
                app_id=parts[1], file_id=parts[2],
                filename=Path(object_name).name,
                s3_url=f"s3://{bucket}/{object_name}",
                size=item.size,
                created_at=item.last_modified,            # 保留对象时间为行 created_at（TIMESTAMPTZ）
            )
            count += 1
        logger.info("files backfill done", extra={"event": "files_backfill_done", "count": count})
    except Exception:
        logger.exception("files backfill failed", extra={"event": "files_backfill_failed"})
        # 不重试：MinIO 暂不可达时下次重启再补；ON CONFLICT DO NOTHING 保证幂等
```

- **范围**：仅 `uploads/` 前缀（内部上传）。外部上游文件（不在我们 MinIO）现状本来就不在列表里，回填后不劣于现状。
- **幂等/可重入**：主键冲突跳过；重启、并发（回填线程与 API 写入交错、多实例同时回填）都安全。
- **自愈副作用（正向）**：§6.1 中「upload 成功但 INSERT 失败」的漏网文件，下次启动被回填捡回（`unknown`）。
- MinIO 客户端复用 `_minio_client()`（L812）；backfill 放 daemon 线程不阻塞 startup（MinIO 慢/不可达不影响 ready）。
- 同 file_id 的目录下多对象（理论上 `{file_id}/` 前缀可有多对象，`_delete_storage_file` 按前缀删）：每个对象一行会撞主键——DO NOTHING 保留先见者，可接受（单 file_id 多对象非正常路径）。

---

## 9. 前端改动（`frontend/src/views/UploadView.vue`）

### 9.1 列表列（模板 L43-62）

| 列 | 改动 |
|---|---|
| file_id / filename / s3_url / created_at / size / actions | 不变 |
| **status（新增，filename 后）** | `el-tag` 徽标：`uploaded`→info、`pending`→warning、`processing`→warning + loading 图标、`done`→success、`failed`→danger、`unknown`→info |
| **chunk_count（新增，status 后）** | 空值显示 `-` |
| error | 不单列；`failed` 行的 filename 或 status 徽标挂 `el-tooltip` 显示 `row.error` |

i18n 新增 key（zh/en 各 6+2）：`upload.status.uploaded/pending/processing/done/failed/unknown`、`upload.columns.status/chunks`（并入现有 `upload.*` 命名空间，zh.json L55-62、en.json L55-62 区域）。

### 9.2 轮询刷新

```text
规则：
- 页面挂载时 fetchFiles()（现状 onMounted L201 不变）
- 之后每 5s 检查一次：若 files 中存在 status ∈ {pending, processing} 的行 → fetchFiles()（重置刷新第一页）
- 首页无进行中状态 → 停止 interval（不空转）
- uploadFiles 成功（L145）与 deleteFile 成功（L183）后的 fetchFiles() 会带回 pending → 下一拍恢复轮询
- onUnmounted 清 interval
```

取舍：轮询用「重置到第一页」而非原地刷新（列表 max-height 360px、管理台单页场景，重置最简单且 newest-first 语义下新状态恰好在顶部）。5s 间隔是可调常量（`POLL_INTERVAL_MS = 5000`），不做成配置。上传三步链路（L132-139）与删除链路（L175-189）**零改动**。

---

## 10. 改动清单（文件级，含行号）

### 10.1 新增

| 文件 | 职责 |
|---|---|
| `backend/files/db.py` | 唯一 db 模块：`init_pool()/close_pool()/conn()`、`init_db()`（迁移+advisory lock）；`insert_uploaded / mark_pending / begin_processing / mark_done / mark_failed / delete_file_row / insert_unknown_if_absent / list_files / get_row`（签名见 §4-§7 伪代码；SQL 收敛于此） |
| `backend/tests/unit/test_files_db.py` | db 层单测（§14.1，连真 pg） |

### 10.2 修改

| 文件 | 改动（基于当前行号） |
|---|---|
| `deploy/cpu/docker-compose.yml` | 新增 `postgres` 服务（§5.3：镜像/凭据/卷/healthcheck/端口）；backend env 加 `DATABASE_URL`、加 `depends_on.postgres.condition=service_healthy` |
| `deploy/gpu/docker-compose.yml` | 同 cpu（逐行一致，除既有差异外） |
| `backend/pyproject.toml` | `dependencies` 加 `psycopg[binary,pool]>=3.2`（psycopg3，非旧驱动）；重新 lock |
| `backend/files/base.py` | 新增 `FileMeta` dataclass（§4.3）；`FileRecord/FilePage` 不动 |
| `backend/files/__init__.py` | 导出 `FileMeta` |
| `backend/main.py` | ① L23 附近 import `files.db as files_db`；② lifespan（L134）`init_pool()` + `init_db()` + 回填 daemon 线程（§5.4/§8），shutdown 处 `close_pool()`；③ `upload_file`（L329）存储成功后 `insert_uploaded`（§6.1）；④ `_create_index_job`（L409）enqueue 成功后 `mark_pending`（§6.2）；⑤ `delete_file`（L681）尾部 `delete_file_row`（§6.4）；⑥ `files` 端点（L651）改调 `files_db.list_files`（§7.1）；⑦ 删 `_list_storage_files`（L825-850）与 `_storage_file_record`（L866-874）、`_file_id_from_object_name`（L886-888，迁入回填逻辑内联使用可保留为私有 helper） |
| `backend/indexing/consumer.py` | `_run_job`（L86-150）挂 5 个状态更新点（§6.3：begin_processing / mark_done / mark_failed×3），每个包 try/except log；`_index_object`（L153）不动 |
| `backend/tests/conftest.py` | 会话级 fixture：探活 compose pg（默认 `localhost:15432`）→ 建独立测试库（如 `rag_test`）→ 设 `DATABASE_URL`；用例间 `TRUNCATE files` 隔离（§14 前置说明） |
| `backend/tests/unit/test_index_consumer.py` | 注入 FakeFilesDb，新增状态流转断言（§14.2） |
| `backend/tests/unit/test_qdrant_api_contract.py` | L194/238 上传相关用例加 db 断言；L252 `test_list_storage_files_uses_minio_object_pagination` 改为 db keyset 分页测试（FakeMinio 断言迁移） |
| `backend/tests/e2e/test_files_api.py` | L35-84 三个 monkeypatch `_list_storage_files` 的用例改为走真 db（测试库预插行）；L86-97 delete 用例加行删除断言 |
| `frontend/src/views/UploadView.vue` | §9：status/chunk_count 列、error tooltip、5s 条件轮询、onUnmounted 清理 |
| `frontend/src/i18n/locales/zh.json` / `en.json` | §9.1 新 key |
| `docs/api.md` | 「上传文件列表」（L380-404）响应示例加新字段；「删除索引文件」（L425-447）补 db 行为说明 |
| `docs/architecture.md` | 新增 §2.9「文件元数据表」（编号顺延 §2.8）；§2.6 末段与 §2.8 删除语义段同步改写 |

### 10.3 明确不动

- `backend/indexing/queue.py`、`indexing/service.py`、`store/**`（含遗留 `store/files.py`、`store.list_files` 接口——可选清理，另立任务）
- `POST /api/upload / presign / index / index/jobs / open/*` 的请求响应契约
- `.gitignore`（`postgres_data/` 已在 L19，零改动）
- 两套 compose 中 qdrant/minio/frontend/etcd/milvus 服务及 backend 的既有卷挂载（backend 代码卷不再承载 db 数据，`backend/data/` 与本设计无关）

---

## 11. 环境变量与部署

| 变量 | 现状 | 本设计 |
|---|---|---|
| `DATABASE_URL` | 无 | **新增**，唯一连接配置（单变量风格）：`postgresql://user:pass@host:5432/db`。compose backend env 默认 `postgresql://rag:ragpass@postgres:5432/rag`（.env 可覆盖）；本地裸跑 backend 指向 `localhost:15432` |
| `POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB` | 无 | **新增**（仅 compose postgres 服务用，默认 `rag`/`ragpass`/`rag`；须与 `DATABASE_URL` 一致，`.env` 一处覆盖即可） |
| `S3_ENDPOINT_URL / S3_ACCESS_KEY / S3_SECRET_KEY / S3_BUCKET` | 已有（main.py L812-829） | 复用（回填线程读取），语义不变 |

部署步骤（两套 compose 同）：

1. 拉代码 → `docker compose up -d`：postgres 首启初始化数据目录（`postgres_data/`）→ healthy → backend 启动 → lifespan 开池 + 迁移（v1 建表）→ 回填线程把 MinIO 历史对象补为 `unknown`。
2. 验证：`GET /api/files` 返回历史文件（status=unknown）；上传新文件 → 行 status `uploaded→pending→processing→done`；`docker compose exec postgres psql -U rag -d rag -c "select status,count(*) from files group by status"` 抽查。
3. 回滚：还原代码 + 重启 backend 即可——postgres 容器与卷留存无副作用（旧代码不读它；重滚后再升级，迁移账本与数据续用，回填幂等续跑）。

**远端部署核对清单**（在既有清单上追加）：

- [ ] 新增 `rag-postgres` 容器（`postgres:16-alpine`），healthcheck 通过
- [ ] 宿主机仓库根新增 `postgres_data/` 数据目录（确认磁盘分区与备份策略覆盖）
- [ ] backend env `DATABASE_URL` 就位（默认值或 .env 覆盖）
- [ ] 若需运营/BI 直连（§12）：放行 15432 端口 + 改默认密码/建只读角色；不需要则可删端口映射
- [ ] 备份策略：元数据量小，`pg_dump` 定时（cron）落 `postgres_data` 之外的位置即可

---

## 12. 元数据直连查询（运营 / 排障 / BI / 上游对账）

Postgres 作为独立服务（§1.4-3），元数据可绕开 backend API 直连查询。这是本设计明确要求的能力，边界如下：

**可达性**：

- compose 内网：仅 backend 经 `postgres:5432` 写入（唯一写路径）。
- 宿主机/远端：照现有 minio(19000)/qdrant(6333) 的暴露风格映射 `15432:5432`（§5.3）；运营/BI 从宿主机或内网直连。生产不需要时删掉 ports 映射即可，backend 不受影响。
- **直连只读**：写操作仍只经 backend API（三真相源原则，直连不产生第二写路径）；排障时的修复动作走「重发 index/jobs / 调 delete API」，不直连 UPDATE。

**只读接入建议（不强制）**：为运营/BI 单独建只读角色，避免分发超级用户凭据；将来量大再上 replica：

```sql
CREATE ROLE rag_ro LOGIN PASSWORD '<改密码>';
GRANT CONNECT ON DATABASE rag TO rag_ro;
GRANT USAGE ON SCHEMA public TO rag_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO rag_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO rag_ro;  -- 覆盖未来新表
```

**运营 SQL 速查**（连接：`psql "postgresql://rag_ro:<pwd>@<host>:15432/rag"`）：

```sql
-- 失败文件清单（最近 50）
SELECT app_id, file_id, filename, error, retry_count, updated_at
FROM files WHERE status = 'failed' ORDER BY updated_at DESC LIMIT 50;

-- 索引吞吐（近 24h 每小时完成数）
SELECT date_trunc('hour', updated_at) AS hour, count(*) AS done
FROM files WHERE status = 'done' AND updated_at > now() - interval '24 hours'
GROUP BY 1 ORDER BY 1;

-- app 维度统计
SELECT app_id, count(*) AS total,
       count(*) FILTER (WHERE status = 'done')     AS done,
       count(*) FILTER (WHERE status = 'failed')   AS failed,
       count(*) FILTER (WHERE status IN ('pending','processing')) AS in_flight,
       coalesce(sum(chunk_count), 0)               AS chunks
FROM files GROUP BY app_id ORDER BY total DESC;

-- 按文件查状态（对账/排障）
SELECT * FROM files WHERE file_id = '<file_id>';

-- 排障：疑似卡死的行
SELECT app_id, file_id, filename, updated_at FROM files
WHERE status = 'processing' AND updated_at < now() - interval '1 hour';

-- s3_url 对账：非本集群对象存储的外部文件（前缀按部署 S3_BUCKET 调整）
SELECT app_id, file_id, s3_url FROM files
WHERE s3_url NOT LIKE 's3://rag-dev/%' LIMIT 100;
```

---

## 13. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 多线程并发写（API 线程池 + consumer + 回填；多实例叠加） | 行锁等待 | 全部写为主键定行的**单语句事务**，持锁微秒级；READ COMMITTED 下单行单语句无死锁环；连接池 max_size=5 有界并发 |
| pg 不可达/宕机 | files 端点 500；状态写失败 | 写失败只 log 不阻断（§6.5）；连接池自动重连，恢复即自愈；`depends_on: service_healthy` 保证启动序；无 fallback（§7.3） |
| 滚动发版两实例并发跑迁移/回填 | 迁移竞态、主键冲突 | `pg_advisory_lock` 串行化迁移（§5.4）；回填 `ON CONFLICT DO NOTHING` 幂等；两实例共享同一 db 天然一致（这正是 §1.4-1 的选型动机） |
| 回填线程与 API 写交错 | 主键冲突 | `ON CONFLICT DO NOTHING` 幂等 |
| 消费前「行不存在→跳过」误伤 upsert 失败的外部任务 | 该任务索引不执行但已 202 | §3.1-3 已接受；概率=pg 单行写失败；重新触发即恢复 |
| 重试孤儿线程（架构 C 遗留）与状态窗口 | 超时孤儿线程晚到的 `add_file_chunks` 可能在 `failed` 写入后落库 | 既有幂等（delete-then-upsert）使数据不脏；状态可能滞后显示，`mark_done` 若在行被改 `failed` 后到达会覆盖为 `done`——以最后完成者为准，可接受（孤儿成功=向量实际在库） |
| pg 数据目录损坏/误删 | 列表 500/空 | 无 fallback（§7.3 定策）；`pg_dump` 定期备份（元数据量小）；内部文件可 `TRUNCATE files` + 重启回填重建（状态归 `unknown`） |
| 状态长期停留 `processing` | 消费器崩溃/重启丢队列任务（架构 C 已接受丢任务） | db 行停留 `processing` 反而把「丢了」暴露出来（现状完全不可见）；运维可对该 file_id 重发 index/jobs 打回 `pending`，或直连 SQL 巡检（§12） |
| 15432 端口暴露面 | 凭据泄露则元数据可读 | 默认凭据仅内网/开发用；公网暴露前必须改密码 + 只读角色（§12）；不暴露则删 ports 映射 |

---

## 14. 测试策略

**前置说明（单测连真 pg，不用内存库/mock）**：本地/CI 都有 docker compose，`conftest.py` 会话级 fixture 直接连 compose 里的 postgres（宿主机视角 `localhost:15432`）——建独立测试库 `rag_test`、设 `DATABASE_URL`、用例间 `TRUNCATE files` 隔离，最简单且测的就是生产行为。探活失败（没起 compose）则 skip db 单测并给出提示，而非全红。consumer/回填测试仍用注入的 FakeFilesDb，不依赖 pg。

### 14.1 新增单测

**`tests/unit/test_files_db.py`**（真 pg，`rag_test` 库）：

- `init_db` 幂等（连跑两次不抛）；`schema_migrations` 含 v1；并发双 `init_db`（模拟两实例）不炸（advisory lock 生效）。
- `insert_uploaded` → 行 status=uploaded、字段齐、created_at/updated_at 非空。
- `mark_pending`：新 file_id 建行（外部文件路径）；已有行（uploaded/done/failed）→ pending 且 created_at 不变。
- `begin_processing`：行存在 → True + processing；不存在 → False 且无行写入。
- `mark_done`：done + chunk_count、error 清空；行不存在时 UPDATE 影响 0 行**且不插入**（不复活已删行）。
- `mark_failed`：failed + error。
- `list_files` keyset：预插 N 行（含同 created_at 不同 file_id 的 tie），翻页遍历无重无漏、has_more/next_cursor 正确、ORDER BY 时间倒序；坏 cursor 抛 ValueError；limit<=0 / >200 clamp。
- `insert_unknown_if_absent`：ON CONFLICT DO NOTHING 幂等；不覆盖已有行；created_at 取传入值（对象时间）。
- 时间输出：`FileMeta.created_at/updated_at` 恒为 `+00:00` 结尾的 UTC ISO（即便会话时区非 UTC）。

### 14.2 consumer 与回填（注入 Fake，不依赖 pg）

**`test_index_consumer.py` 扩展**（FakeFilesDb 注入 consumer，记录调用序列）：

- 成功路径调用序：`begin_processing → mark_done(chunk_count)`。
- ValueError：`begin_processing → mark_failed(error)`，不重入队。
- 超时/异常：`begin_processing` 后首次失败**无** mark 调用（保持 processing）→ 重试耗尽 → `mark_failed`。
- 重入队 queue full：`mark_failed("re-enqueue ...")`。
- `begin_processing` 返回 False：不调用 `_index_object`，任务丢弃，log `index_job_skipped_no_record`。
- FakeFilesDb 抛异常：索引流程照常完成（db 故障不阻断）。

**回填单测**（FakeMinio list_objects）：对象→行映射（app_id/file_id/filename/size/last_modified）、目录对象跳过、非法 key 跳过、DO NOTHING 不覆盖 API 已写的行。

### 14.3 e2e / 手测

- 上传 → presign → index/jobs → 轮询 `GET /api/files` 直到 `done`，断言 chunk_count 与搜索命中一致（复用 `_index_ready_file` 模式）。
- 对内删除 → 行消失 + MinIO 对象消失 + 搜索不命中；构造「删除时任务在队列」场景（大文件索引中删除）→ 任务被跳过、行不复活。
- 重启 backend → 回填后历史文件以 `unknown` 出现。
- （可选，验证 §1.4-1 动机）`docker compose up -d --scale backend=2` 双实例并发上传/回填，观察状态正确、无重复行。
- 前端：状态徽标流转、5s 轮询启停（无进行中任务时 network 面板无请求）。

---

## 15. 实施步骤（每步可独立验证）

### Step 1：pg 基座（连接池 + 建表，不接主链路）
- 两套 compose 加 `postgres` 服务；`pyproject.toml` 加 `psycopg[binary,pool]` 并 lock（重建 backend 镜像）。
- 新建 `backend/files/db.py`（池/迁移/全部 CRUD）+ `files/base.py` 加 `FileMeta`；新建 `test_files_db.py`；conftest 加测试库 fixture。
- 不改 `main.py`/`consumer.py`。
- **验证**：`docker compose up -d postgres` → healthy；`pytest tests/unit/test_files_db.py` 全过；`psql` 连入 `\dt` 见 `files`/`schema_migrations`；主链路无任何变化（全量 unit 回归）。

### Step 2：写路径挂接 + 迁移 + 回填
- `main.py`：lifespan `init_pool/init_db` + 回填线程、upload INSERT、jobs `mark_pending`、delete 删行、shutdown `close_pool`。
- `consumer.py`：`_run_job` 挂 5 个状态更新点 + 消费前检查。
- 扩展 `test_index_consumer.py`、改 `test_qdrant_api_contract.py` 上传相关用例。
- **验证**：全量 unit 过；compose 起 backend 上传文件，psql 观察 `uploaded→pending→processing→done`；日志无 `files_db_write_failed`。

### Step 3：读路径切换
- `GET /api/files` 改 `files_db.list_files`；删 `_list_storage_files/_storage_file_record`；改写 `test_files_api.py` e2e；更新 `docs/api.md`。
- **验证**：e2e 过；前端旧列表（未升级）仍正常展示（五字段兼容）；分页游标翻页稳定。

### Step 4：前端
- `UploadView.vue` 状态列/徽标/tooltip/轮询；zh/en i18n。
- **验证**：手测上传→徽标流转→轮询停止；删除即消失。

### Step 5：文档与部署收尾
- `docs/architecture.md` 新增 §2.9、修订 §2.6/§2.8；按 §11 核对清单过一遍远端部署项。
- **验证**：文档 review；两套 compose 拉起回归一遍 §14.3 手测清单。

依赖关系：Step 1 → Step 2 → Step 3 → Step 4 → Step 5 串行（Step 2/3 同改 `main.py`，不并行；Step 4 依赖 Step 3 的响应结构；Step 5 收尾）。
