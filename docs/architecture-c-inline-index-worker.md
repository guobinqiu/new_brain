# 架构 C（最简版）：进程内 asyncio.Queue 索引消费器

> 本文件是架构设计方案，不是实现计划。面向后续 TDD/coder 拆任务执行。
> 落地后需同步更新 `docs/architecture.md` §2.4（写入流程）与 §2.7（索引 Worker），以及 `README.md` 的 Redis/Celery 描述。
> 本版在上一版（同文件已覆盖）基础上**彻彻底底简化**：去掉 Redis 队列、任务记录、SSE、前端索引列表。

---

## 1. 背景与动机

### 1.1 为什么要改（根因）

单卡 GPU 31G，vllm 占 25G。当前索引走 Celery：**backend 进程**与**独立 index-worker 进程**各加载一份 dense/sparse/ocr 模型（每份约 3G，dense+sparse 共用 bge-m3 权重，实际比 3×3G 小，但第二份重复加载仍把剩余显存填满）。worker 跑 embedding 时连约 20MB 推理 transient 显存都没有 → OOM。

分离进程的代价就是**模型加载两套**。去掉独立 worker、改成 backend 进程内异步消费，模型一份，省掉第二份显存，回到可容纳推理 transient 的水平。

### 1.2 为什么再简化（上一版过重）

上一版「内联消费器」仍保留 Redis 队列（BLMOVE + processing list + 启动期 reaper）、hash/zset 任务记录、SSE Pub/Sub、前端索引列表。单卡单实例场景下这些都是过度设计：

- **Redis 队列**：进程内队列即可，不需要跨进程 broker。
- **任务记录 / 列表 / 状态查询**：单卡队列不积压，用户不靠列表运维索引；记录是历史包袱。
- **SSE 实时事件**：没有列表页就没有消费者；删除。
- **崩溃恢复 reaper**：进程内队列重启即清空，没有 processing list 残留要回收；接受重启丢任务。

### 1.3 保留的（不可丢失）

1. **异步索引**：上传后立即返回，索引后台跑，不阻塞 API。
2. **模型一份**：backend 持有 `application`（dense/sparse/ocr/store/rerank/search），索引与查询共享同一实例。
3. **索引核心逻辑**：`indexing/service.py` 的 `index_presigned_object` / `index_file` 不变；`tasks.py` 的 `_index_object` 核心逻辑（`app_collection_exists` 检查 + `with app.store.app_context(app_id)` + `index_presigned_object`）迁入新消费器。
4. **上传功能**：`POST /api/upload` 存 minio 保留；`POST /api/presign` 保留。
5. **重试 / 超时**：作为消费方内部职责实现（`asyncio.wait_for` 超时 + `retry_count` 重试），不对外暴露。

### 1.4 去掉的

- 独立 `index-worker` 容器（两份 compose 的服务块）。
- Celery（`celery_app.py`、`tasks.py` 的 celery task/signal、`celery[redis]` 依赖）。
- Redis（容器、`redis-py` 依赖、`_redis_ready` 健康检查、`repository.py` 全部）。
- 任务记录（hash/zset）、任务列表 API（`GET /api/index/jobs`）、任务状态 API（`GET /api/index/jobs/{job_id}`、`POST /api/index/jobs/status`、`/api/open/index/jobs/status`）。
- SSE 端点（`GET /api/index/jobs/stream`）与 Redis Pub/Sub。
- 前端 `IndexJobsView` 页面、菜单项、路由、i18n key。
- 速率限流（`INDEX_RATE_LIMIT_PER_MINUTE`，YAGNI；队列 maxsize 即背压）。
- `job_id` 概念（无记录无列表，job_id 无意义；改用 `file_id` 作为对外句柄）。

---

## 2. 目标架构流程

```text
前端 UploadView（不变）
  └─ POST /api/upload          → {file_id, s3_url, filename}   # 存 minio
  └─ POST /api/presign         → {presigned_url}
  └─ POST /api/index/jobs      → {file_id}                     # 触发索引（fire-and-forget，前端不读返回值）
     └─ backend (async, 事件循环线程):
          _require_ready / 校验扩展名 / _database_principal
          await asyncio.to_thread(_require_app_database, principal)   # Qdrant I/O 卸载，不阻塞事件循环
          enqueue_index_job(...)                                       # queue.put_nowait(job)
          return {"file_id": file_id}

backend 进程内 InlineIndexConsumer（lifespan 启动，常驻，并发=1）
  └─ _loop():
       job = await asyncio.wait_for(queue.get(), timeout=1.0)   # 空闲轮询，便于 shutdown
       await _run_job(job):
         ├─ asyncio.wait_for(
         │     loop.run_in_executor(index_executor, ctx.run, partial(_index_object, application, job)),
         │     timeout=INDEX_JOB_TIMEOUT_SECONDS(1800)
         │   )
         │   ├─ 成功: log "object_indexed" + chunk_count; 结束
         │   ├─ asyncio.TimeoutError → 可重试分支
         │   ├─ ValueError           → 不可重试：log + 丢弃（不重试）
         │   └─ 其它 Exception       → 可重试分支
         └─ 可重试分支:
              if retry_count < INDEX_JOB_RETRY_MAX(2):
                  job["retry_count"] += 1; queue.put_nowait(job)   # 重新入队尾（静默，无 SSE）
              else:
                  log "index_failed_final" + reason + retry_count  # 放弃
```

**对外契约**：上传完即可，索引后台默默跑；前端无索引页。客户端用 `file_id` 通过 `/api/open/search`（或 `/api/search`）验证索引是否就绪（与现状 e2e 一致：`test_upload_api.py:94` 索引后 search 命中）。

---

## 3. 关键决策表

| 关键问题 | 决策（一句话） |
|---|---|
| 上传→索引触发 | **方案 (a)**：保留 `POST /api/index/jobs`（含 `/api/open/index/jobs`），简化为「入队 asyncio.Queue」，返回 `{file_id}`；上传链路前端零改动（UploadView 已 fire-and-forget） |
| 队列实现 | 进程内 `asyncio.Queue(maxsize=INDEX_MAX_PENDING_JOBS)`，单例，lifespan 内创建 |
| 队列放什么 | `{app_id, file_id, presigned_url, s3_url, filename, retry_count}`；**无 job_id** |
| maxsize | 默认 10（原 200；进程内、单消费者，长队列无意义，10 足够背压）；env `INDEX_MAX_PENDING_JOBS` 可覆盖 |
| 队列满 | `put_nowait` 抛 `asyncio.QueueFull` → `IndexQueueRejected` → 接口返回 **429** |
| 后台消费 task | lifespan startup 起 1 个 asyncio task 消费，shutdown 设 `asyncio.Event` + gather 取消；并发=1 |
| 同步 embedding 不阻塞事件循环 | 专用 `ThreadPoolExecutor(max_workers=1)` + `loop.run_in_executor`（**不用** `asyncio.to_thread`，见 §4.3） |
| 超时 | `asyncio.wait_for(..., timeout=INDEX_JOB_TIMEOUT_SECONDS=1800)`；超时算一次 retry |
| 重试 | `retry_count` 在 job 字典里；`< INDEX_JOB_RETRY_MAX(2)` 时 `put_nowait` 重新入队尾；≥2 放弃记日志；中间静默 |
| 不可恢复错误 | `ValueError`（app 库未初始化、文件格式不支持）直接丢弃，不重试 |
| app_context 跨线程 | `_index_object` 内 `with application.store.app_context(app_id):` 自包含；`run_in_executor` 传 `contextvars.copy_context().run` 做隔离兜底 |
| 任务记录 / 列表 / 状态 / SSE | 全删；无 job_id、无 hash/zset、无 Pub/Sub、无 SSE 端点 |
| 健康检查 | 删 `_redis_ready` 与 `_components()` 的 Redis 行；`/api/health`、`/api/ready` 不变（ready 仍查 `application.ready`） |
| GPU 推理并发锁 | **默认不加锁**（遵「最简」）；查询 embed 与索引 embed 并发命中同卡同实例的安全性列为**待确认 spike**；若不安全则回退引入 `inference_lock`（见 §7 风险 1） |
| 速率限流 | 删除 `INDEX_RATE_LIMIT_PER_MINUTE`（YAGNI；maxsize 即背压） |
| 重启丢任务 | asyncio.Queue 进程内，重启清空；接受（单卡队列不积压，文件在 minio，用户重新触发） |

### 3.1 待确认决策（需 spike / 与负责人确认，不伪装成结论）

1. **外部 SDK 是否依赖 `job_id` 返回或状态接口**：删 `job_id` 返回值（改 `{file_id}`）与删 `GET /api/open/index/jobs/status` 是 open API 的 breaking change。需确认有无外部客户端轮询任务状态；若有且必须保留，则**回退**为：保留一个进程内有界「当前状态」内存映射（非 Redis、非历史），作为本版增量。默认按「删除」实施。
2. **GPU 推理并发安全性（spike）**：bge-m3（torch）+ rapidocr（onnxruntime-gpu）+ bge-reranker-v2-m3 在本部署 torch/onnxruntime/cuda 版本下，**同一模型实例被两个线程并发调用**（查询 embed_query vs 索引 embed_documents）是否安全？验证方法：1 路持续 search + 1 路持续 index 大文件，观察 CUDA error / 显存叠加 OOM / 结果错乱。若不安全（预期）→ 必须加 `inference_lock`（共享 `threading.Lock`，在 dense/sparse/ocr/rerank 模型包装方法内加锁），此时改动面扩大到 `backend/dense/`、`backend/sparse/`、`backend/ocr/`、`backend/rerank/`。
3. **`wait_for` 超时孤儿线程**：`run_in_executor` 无法中断跑同步函数的线程；超时后 asyncio 侧放弃，但 `index_executor`（max_workers=1）里那个线程会继续跑完当前 embed/OCR/下载，结果被丢弃。靠 max_workers=1 串行化保证不与重试/下一个任务并发命中 GPU；靠 `add_file_chunks` 按 `file_id` delete-then-upsert 幂等保证重试不产生脏数据。确认该取舍可接受。

---

## 4. 消费循环设计（伪代码 + 数据结构）

> 以下为伪代码 / 数据结构示意，明确标注，非实现代码。

### 4.1 job 字典

```python
# 入队时构造；retry 时原地改 retry_count 后重新入队
job = {
    "app_id": str,
    "file_id": str,
    "presigned_url": str,
    "s3_url": str,
    "filename": str | None,
    "retry_count": int,   # 入队时 0
}
```

### 4.2 InlineIndexConsumer（新建 `backend/indexing/consumer.py`）

```python
# 伪代码示意
class InlineIndexConsumer:
    def __init__(self, application):
        self.application = application
        self.queue = asyncio.Queue(maxsize=_max_pending_jobs())   # env INDEX_MAX_PENDING_JOBS 默认 10
        self.stop_event = asyncio.Event()
        self.task = None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="index-worker")

    async def start(self):
        _register_consumer(self)          # 供 enqueue_index_job 取 queue
        self.task = asyncio.create_task(self._loop())

    async def stop(self):
        self.stop_event.set()
        if self.task:
            await asyncio.gather(self.task, return_exceptions=True)
        self.executor.shutdown(wait=False)

    async def _loop(self):
        while not self.stop_event.is_set():
            try:
                job = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            await self._run_job(job)

    async def _run_job(self, job):
        app_id, file_id, filename = job["app_id"], job["file_id"], job["filename"]
        retry_count = job.get("retry_count", 0)
        timeout = _job_timeout_seconds()         # env INDEX_JOB_TIMEOUT_SECONDS 默认 1800
        loop = asyncio.get_running_loop()
        ctx = contextvars.copy_context()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    self.executor,
                    ctx.run,
                    functools.partial(_index_object, self.application, job),
                ),
                timeout=timeout,
            )
            # 成功：_index_object 内部已 log "object_indexed"
            return
        except ValueError as exc:
            logger.warning("Index failed (non-retryable)", exc_info=True,
                           extra={"event": "index_failed", "app_id": app_id,
                                  "file_id": file_id, "error": str(exc)})
            return  # 不可恢复，丢弃不重试
        except asyncio.TimeoutError:
            reason = f"index timeout after {timeout}s"
        except Exception as exc:
            reason = f"index failed: {exc!r}"
        # 可重试分支
        max_retries = _job_retry_max()           # env INDEX_JOB_RETRY_MAX 默认 2
        if retry_count < max_retries:
            job["retry_count"] = retry_count + 1
            try:
                self.queue.put_nowait(job)        # 重新入队尾；同事件循环线程，安全
            except asyncio.QueueFull:
                logger.error("Re-enqueue failed (queue full), dropping job",
                             extra={"event": "index_reenqueue_dropped",
                                    "app_id": app_id, "file_id": file_id})
        else:
            logger.error("Index job exhausted retries, giving up",
                         extra={"event": "index_failed_final", "app_id": app_id,
                                "file_id": file_id, "filename": filename,
                                "retry_count": retry_count, "error": reason})
```

### 4.3 为什么不用 `asyncio.to_thread`（偏离用户提示的理由）

用户提示「同步 embedding 用 `asyncio.to_thread` 不阻塞事件循环」。`asyncio.to_thread` 用的是**默认 executor**（多 worker）。`asyncio.wait_for` 超时后，to_thread 的线程**继续跑**（无法中断），而下一个 job 的 to_thread 会在另一个 worker 线程并发跑 → 两个线程同时命中 GPU embedding → 正是要避免的并发。

**改用专用 `ThreadPoolExecutor(max_workers=1)` + `loop.run_in_executor`**：超时孤儿线程占用唯一 worker，重试 / 下一个任务在 executor 内部队列**排队等待**孤儿结束才跑 → 天然串行，永不并发命中 GPU。代价：失去 to_thread 自带的 `copy_context` 传播，故手动传 `contextvars.copy_context().run` 兜底（`_index_object` 自身已 `with app_context`，ctx.run 仅防御）。

### 4.4 _index_object（从 `tasks.py:47-64` 迁入 `consumer.py`）

```python
# 伪代码示意（核心逻辑不变，仅 application 由外部传入）
def _index_object(application, job) -> dict:
    app_id = job["app_id"]; file_id = job["file_id"]
    presigned_url = job["presigned_url"]; s3_url = job["s3_url"]; filename = job["filename"]
    if not application.store.app_collection_exists(app_id):
        raise ValueError("app database is not initialized")
    with application.store.app_context(app_id):
        count = index_presigned_object(application, file_id, presigned_url, s3_url, filename)
    logger.info("Object indexed",
                extra={"event": "object_indexed", "app_id": app_id, "file_id": file_id,
                       "document_filename": filename, "s3_url": s3_url, "chunk_count": count})
    return {"app_id": app_id, "file_id": file_id, "chunk_count": count}
```

- `app_collection_exists(app_id)`：`store/qdrant.py:95-97`，显式传 app_id，不依赖 ContextVar。
- `app_context(app_id)`：`store/qdrant.py:108-109` → `collection_names.app_collection(app_id)`（`collection_names.py:29-36`），contextmanager set/reset `_current_app_id` ContextVar。
- 跨线程：`run_in_executor` + `ctx.run` 给本次执行一份独立 context 副本；`with app_context` 在副本内 set，finally reset，线程复用也不泄漏。

### 4.5 enqueue_index_job（重写 `backend/indexing/queue.py`）

```python
# 伪代码示意
def enqueue_index_job(*, app_id, file_id, presigned_url, s3_url, filename):
    job = {"app_id": app_id, "file_id": file_id, "presigned_url": presigned_url,
           "s3_url": s3_url, "filename": filename, "retry_count": 0}
    try:
        index_queue().put_nowait(job)        # index_queue() 取 consumer 单例的 queue
    except asyncio.QueueFull as exc:
        raise IndexQueueRejected("index queue full") from exc
```

- 调用方 `main._create_index_job` 是 **async** 端点（事件循环线程），`put_nowait` 与 consumer 的 `get` 同线程 → asyncio.Queue 安全。
- `IndexQueueRejected` → `main._create_index_job` 返回 **429**（沿用 `main.py:433-434` 的映射）。
- 删 `IndexQueueUnavailable`（无 Redis，不存在「队列不可用」；同步移除 main.py 里对应 except 分支）。

---

## 5. 改动清单（文件级，含行号）

### 5.1 新增

| 文件 | 职责 |
|---|---|
| `backend/indexing/consumer.py` | `InlineIndexConsumer`（启停、`_loop`、`_run_job`、超时/重试/不可恢复分支）、`_index_object`（从 `tasks.py` 迁入）、`_index_executor`、env 读取（`_max_pending_jobs`/`_job_timeout_seconds`/`_job_retry_max`）、`index_queue()`/`_register_consumer()` 单例接入 |
| `backend/tests/unit/test_index_consumer.py` | 消费循环、超时→重试、重试上限→放弃、`ValueError` 不重试、重新入队队尾、队列满丢任务、`stop_event` 优雅停、`app_context` 隔离 |
| `backend/tests/unit/test_index_enqueue.py` | `enqueue_index_job` → `put_nowait`；`QueueFull` → `IndexQueueRejected`；`maxsize` 取 env |

### 5.2 修改

| 文件 | 改动（行号） |
|---|---|
| `backend/indexing/queue.py` | 重写：仅保留 `enqueue_index_job`（put_nowait，无 job_id 参数）+ `IndexQueueRejected`。删 `get_index_job`/`list_index_jobs`/`CeleryJobAdapter`/`_celery_status`/`_celery_app`/`_send_task_retry_policy`/`_enforce_queue_limits`/`_job_result_ttl`/`_job_failure_ttl`/`_redis_url`/`IndexQueueUnavailable`（全文件约 L18-170） |
| `backend/indexing/__init__.py` | 保持导出 `create_file_id`/`enqueue_index_job`/`index_file`/`index_presigned_object`；`enqueue_index_job` 仍从 `indexing.queue` 导入，兼容 `main.py:24` |
| `backend/main.py` | 见 §5.4 详细行号 |
| `backend/pyproject.toml` | 删 `redis>=5.0.0`（L36）、`celery[redis]>=5.4.0`（L37） |
| `deploy/cpu/docker-compose.yml` | 删 `redis` 块（L35-45）、`index-worker` 块（L88-125）；backend env 删 `REDIS_URL`(L71)、`INDEX_QUEUE_NAME`(L72)、`INDEX_JOB_RESULT_TTL_SECONDS`(L74)、`INDEX_JOB_FAILURE_TTL_SECONDS`(L75)、`INDEX_RATE_LIMIT_PER_MINUTE`(L77)；留 `INDEX_JOB_TIMEOUT_SECONDS`(L73)、`INDEX_JOB_RETRY_MAX`(L76)、`INDEX_MAX_PENDING_JOBS`(L78) |
| `deploy/gpu/docker-compose.yml` | 删 `redis` 块（L35-45）、`index-worker` 块（L95-139）；backend env 同上删减（L71-78） |
| `justfile` | 删 L5 的 celery worker recipe（`cd backend && ... celery -A indexing.celery_app:celery_app worker ...`） |
| `frontend/src/router/index.js` | 删 `IndexJobsView` import（L8）、`/index` 路由（L22） |
| `frontend/src/App.vue` | 删菜单项 `:index="/apps/${app.app_id}/index"`（L61）；从 `SUB_PAGES` 删 `'/index'`（L116） |
| `frontend/src/i18n/locales/zh.json` | 删 `nav.index`(L14)、`monitor.indexJobs`/`indexJobsLimitNote`/`noIndexJobs`/`indexQueueUnavailable`/`jobStatus`/`jobColumns`(L70-89 区域)；改 `upload.indexSubmitted`(L63) 文案，去掉「可在索引页查看状态」 |
| `frontend/src/i18n/locales/en.json` | 同上对应 key（L14、L70-89 区域、L63） |
| `backend/tests/unit/test_qdrant_api_contract.py` | 保留 sync 索引 / 上传 / presign / search trace / file_id 生成 / 路由断言等用例；改 `test_create_index_job_enqueues_async_job`(L80) 断言入队 kwargs 无 job_id、响应 `{file_id}`；保留 `test_create_index_job_returns_429_when_queue_rejects`(L126)、`test_admin_index_job_requires_file_id`(L152)；删 `test_index_jobs_status_*`(L164-298)、`test_index_jobs_returns_recent_job_list`(L314)、`test_index_jobs_reports_queue_unavailable`(L358)、`test_monitor_components_include_redis`(L371)、`test_generated_job_id_is_uuid_hex`(L446)、`test_index_queue_rejects_when_rate_limit_exceeds`(L418)；改 `test_index_queue_rejects_when_pending_jobs_exceeds`(L399) 为 asyncio.Queue 满 → 429；改 `test_sync_and_async_index_routes_are_separate`(L481) 去掉 `/api/open/index/jobs/status` 与 `/api/index/jobs/{job_id}` 断言 |
| `backend/tests/e2e/test_upload_api.py` | `test_async_index_job_returns_job_id`(L119) → 改名 `..._returns_file_id`，断言 `resp.json() == {"file_id": "550e8400e29b41d4a716446655440000"}`；`test_async_index_job_accepts_caller_uuid_file_id`(L142) 断言响应 `{file_id}` 且 `enqueued[0]["file_id"]` 正确；两处去掉 `create_job_id` monkeypatch |

### 5.3 删除（整文件）

| 文件 | 理由 |
|---|---|
| `backend/indexing/repository.py` | Redis 任务记录 + Pub/Sub + redis client 单例，全删 |
| `backend/indexing/celery_app.py` | Celery 配置，全删 |
| `backend/indexing/tasks.py` | celery task/signal/`_worker_application`/`_ensure_application` 全删；`_index_object` 已迁入 `consumer.py` |
| `backend/tests/unit/test_worker_model_loading.py` | 验证独立 worker 不加载 rerank/search，内联后语义消失 |
| `backend/tests/unit/test_index_tasks.py` | 验证 celery 父/子进程模型加载策略，内联后语义消失 |
| `backend/tests/unit/test_index_jobs_events_sse.py` | SSE 链路删除 |
| `backend/tests/unit/test_index_jobs_status_api.py` | 状态 API 删除 |
| `backend/tests/unit/test_index_queue.py` | celery send_task / AsyncResult / rollback / publish / redis 单例等用例全作废（enqueue 用例由新 `test_index_enqueue.py` 替代） |
| `frontend/src/views/IndexJobsView.vue` | 索引列表页删除 |

### 5.4 `backend/main.py` 详细行号

| 行号 | 改动 |
|---|---|
| L25 | `from indexing.queue import IndexQueueRejected, IndexQueueUnavailable, get_index_job, list_index_jobs` → 仅留 `IndexQueueRejected` |
| L26 | `from indexing.repository import redis_url, _index_events_channel` → 整行删（repository 已删） |
| L90-91 | `class IndexJobsStatusRequest` → 删 |
| L137-156 | `lifespan`：`yield` 前加 `index_consumer = InlineIndexConsumer(application); await index_consumer.start()`；`yield` 后加 `await index_consumer.stop()`（在 `stop_event.set()` 与 `application.stop()` 之间） |
| L179-180 | `def create_job_id` → 删（无 job_id） |
| L404-406 / L399-401 | `create_index_job` / `client_create_index_job` → 改 `async def` |
| L409-441 | `_create_index_job` → 改 `async def`；删 `job_id = create_job_id()`(L418)；`_require_app_database`(L421) 包 `await asyncio.to_thread(...)`；`enqueue_index_job(...)` 调用去 `job_id=` 参数；返回 `{"file_id": file_id}`（替 L430 `{"job_id": job.id}`）；删 `except IndexQueueUnavailable`(L435-436) |
| L444-453 | `index_jobs`（GET /api/index/jobs 列表）→ 整段删 |
| L456-494 | `index_jobs_stream`（SSE）→ 整段删 |
| L497-504 | `client_index_jobs_status` / `admin_index_jobs_status` → 整段删 |
| L507-509 | `index_job_status`（GET /api/index/jobs/{job_id}）→ 整段删 |
| L512-528 | `_index_jobs_status` / `_index_job_status` → 整段删 |
| L654-687 | `_components()`：删 Redis 行（L662-666） |
| L710-717 | `_redis_ready` → 删 |
| L1055-1092 | `_job_error` / `_job_status` / `_job_app_id` / `_index_job_record` → 整段删 |
| L24 | `from indexing import create_file_id, enqueue_index_job, index_file, index_presigned_object` → 不变 |
| 新增 import | `from indexing.consumer import InlineIndexConsumer` |

> 注：`main._index_object`(L368，sync 索引端点体) 与 `consumer._index_object`(迁自 tasks.py) 是不同模块的同名函数，互不冲突，均保留。

### 5.5 不变

- `backend/indexing/service.py`（`index_presigned_object`/`index_file` 同步执行体，被 consumer 经 executor 调用）
- `backend/bootstrap.py`（`Application` 仍 `start()` 全量；consumer 复用 `main.application`）
- `backend/collection_names.py`、`backend/store/*.py`、`backend/document_parser.py`、`backend/dense|sparse|ocr|rerank/*`（**除非** §3.1 spike 2 判定需要 `inference_lock`）
- `backend/main.py` 的 `POST /api/upload`(L329)、`POST /api/presign`(L531)、`POST /api/index`(L363)、`POST /api/open/index`(L358)、sync `_index_object`(L368)、`index_chunks`(L318)、`/api/health`(L168)、`/api/ready`(L172)
- 前端 `UploadView.vue`（上传链路不动，仍调 `/api/index/jobs`；仅 i18n `upload.indexSubmitted` 文案微调）

---

## 6. 环境变量与部署变化

### 6.1 环境变量

| 变量 | 现状 | 本版 |
|---|---|---|
| `REDIS_URL` | Redis broker/backend | **删** |
| `INDEX_QUEUE_NAME` | Redis list 名 | **删**（进程内队列无名） |
| `INDEX_JOB_RESULT_TTL_SECONDS` | 任务记录 TTL | **删**（无记录） |
| `INDEX_JOB_FAILURE_TTL_SECONDS` | 失败记录 TTL | **删** |
| `INDEX_RATE_LIMIT_PER_MINUTE` | 每分钟入队限流 | **删**（YAGNI） |
| `INDEX_ENQUEUE_MAX_RETRIES` / `INDEX_ENQUEUE_RETRY_INTERVAL_*` | producer 侧重试 | **删**（put_nowait 同步，无 broker 重试） |
| `INDEX_JOB_TIMEOUT_SECONDS` | 任务超时 | **留**，语义不变（`asyncio.wait_for` timeout，默认 1800） |
| `INDEX_JOB_RETRY_MAX` | 最大重试 | **留**，语义不变（默认 2） |
| `INDEX_MAX_PENDING_JOBS` | 队列上限 | **留**，语义改为 `asyncio.Queue(maxsize=...)`；默认从 200 调为 **10**（compose 显式设 200 时仍生效，仅允许更多缓冲） |
| `INDEX_WORKER_CONCURRENCY` | celery worker 并发 | **删**（compose 已仅在 worker 块用） |

### 6.2 部署变化

- 两份 compose 删 `redis`、`index-worker` 两个服务块；`backend` 服务的 GPU reservation（`gpu:85-91`）不变，删 worker 后 GPU 只被 backend 一份占用，根因消除。
- `backend` env 按 §6.1 删减。
- `justfile` 删 celery 本地启动 recipe。
- `pyproject.toml` 删 `redis`、`celery[redis]` 依赖（镜像变小）。
- **部署迁移步骤**：
  1. 停止提交新索引任务（短暂维护窗）。
  2. 等现有 celery `index` 队列排空（或人工确认无在跑任务；进程内队列与旧 Redis 队列无关联，无需 `DEL`）。
  3. 部署新 backend 镜像（compose 已删 redis/index-worker、env 已删减）。
  4. `docker compose up -d` → backend 启动 → `lifespan` 起 `InlineIndexConsumer` → application ready 后开始消费。
  5. 验证：上传一份测试文件，观察日志出现 `object_indexed` + `chunk_count`，`/api/open/search` 命中该 `file_id`。
- **回滚**：还原 compose（加回 redis + index-worker 块、env）+ 还原代码（git revert）。本版不保留双路径开关（最简）。

---

## 7. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| **查询与索引并发 GPU 推理竞态**（CUDA error / 显存叠加 OOM） | 进程崩溃 / 结果错乱 | **默认不锁**；§3.1 spike 2 验证。若不安全 → 加 `inference_lock`（共享 `threading.Lock`，在 dense/sparse/ocr/rerank 模型包装方法内加锁，覆盖所有调用点）。这是本版唯一可能扩大改动面的待确认项 |
| `wait_for` 超时无法硬杀 executor 线程 | 孤儿线程占用唯一 worker，重试排队等待 | max_workers=1 串行不并发命中 GPU；`add_file_chunks` 按 `file_id` delete-then-upsert 幂等，重试覆盖孤儿写入；最终 retry_count 上限 → 放弃 |
| 重启丢队列任务 | 未索引的文件丢失索引 | 接受权衡；文件在 minio，用户重新上传/触发；单卡队列不积压，丢的概率低 |
| `asyncio.Queue` 非线程安全 | enqueue 从非事件循环线程调用会 race | `create_index_job`/`client_create_index_job` 改 `async`，enqueue 在事件循环线程执行；`_require_app_database`（Qdrant I/O）经 `asyncio.to_thread` 卸载 |
| 队列满 | 新上传的索引请求被拒 | `put_nowait` → `QueueFull` → `IndexQueueRejected` → 接口 429；前端 UploadView 捕获并 toast 提示（现状已有 `err.response?.data?.detail` 兜底，`UploadView.vue:142`） |
| 删 `job_id` / 状态 API 是 open API breaking change | 外部 SDK 轮询任务状态失效 | §3.1 待确认 1；若必须保留 → 增设进程内有界「当前状态」内存映射（非 Redis、非历史） |
| `app_context` ContextVar 跨线程误用 | 写错 collection | `_index_object` 内 `with app.store.app_context(app_id):` 自包含；`run_in_executor` 传 `copy_context().run` 隔离兜底；contextmanager finally reset，线程复用不泄漏 |
| 消费 task 异常退出 | 索引停摆（查询不受影响） | `_loop` 内对 `_run_job` 的异常已在 `_run_job` 内全捕获（TimeoutError/ValueError/Exception 都有分支）；`_loop` 自身异常由 lifespan `gather(..., return_exceptions=True)` 兜住，可加 try/except 重启（可选） |

---

## 8. 测试策略

### 8.1 新增

- **`test_index_enqueue.py`**：
  - `enqueue_index_job` 调用后 `index_queue()` 内出现对应 job 字典（含 `retry_count=0`，无 `job_id`）。
  - 队列满时 `put_nowait` 抛 `QueueFull` → `IndexQueueRejected`。
  - `maxsize` 取 `INDEX_MAX_PENDING_JOBS` env（默认 10）。
- **`test_index_consumer.py`**：
  - 成功路径：`_index_object` mock 返回 `{chunk_count: N}` → 消费后 log `object_indexed`，队列空。
  - 超时：`_index_object` sleep > timeout → `asyncio.TimeoutError` → `retry_count<max` 时 job 重新入队尾且 `retry_count+1`。
  - 重试上限：`retry_count==max` 时超时/异常 → log `index_failed_final`，不重新入队。
  - 不可恢复：`_index_object` 抛 `ValueError` → 直接丢弃，不重试，不重新入队。
  - 重新入队时队列满 → log `index_reenqueue_dropped`，不抛。
  - 优雅停：`stop_event.set()` 后 `_loop` 在 ≤1s 内退出。
  - `app_context` 隔离：并发两个不同 app_id 的 job（mock executor 串行），断言各自 `current_collection()` 对应自己的 collection。
  - 串行：mock executor max_workers=1，断言不并发（可记录调用时间区间不重叠）。

### 8.2 改写

- `test_qdrant_api_contract.py`：按 §5.2 表所列，保留 sync 相关用例，改/删 async job 与 redis/rate-limit 相关用例。
- `test_upload_api.py` e2e：按 §5.2 表，改 async job 返回值为 `{file_id}`。

### 8.3 集成 / 手测（迁移后）

- 真实上传一份 PDF（含图，触发 OCR），观察日志 `object_indexed` + `chunk_count`，`/api/open/search` 命中。
- 索引大文件期间并发 `search`，观察查询正常返回、无 CUDA error（同时验证 §3.1 spike 2）。
- `kill -9` backend 模拟重启，确认队列丢失可接受、重启后消费器正常启动。

---

## 9. 实施步骤（每步可独立验证）

> 顺序：先加新代码（不动旧链路）→ 切入队与端点 → 起消费器 → 删旧代码/部署。每步可独立测试。

### Step 1：新建消费器与入队（不接入）
- 新建 `backend/indexing/consumer.py`（`InlineIndexConsumer` + 迁入 `_index_object` + env 读取 + `index_queue()`/`_register_consumer`）。
- 重写 `backend/indexing/queue.py`：`enqueue_index_job` 改 `put_nowait`、保留 `IndexQueueRejected`、删其余。
- 新增 `test_index_consumer.py`、`test_index_enqueue.py`。
- **不**改 `main.py`、**不**接入 lifespan。
- **验证**：新单测全过；旧链路（celery）仍在跑，未受影响。

### Step 2：切换 main 端点 + 起消费器（核心切换）
- `main.py` 按 §5.4 改：imports、`lifespan` 起/停 consumer、`create_index_job`/`client_create_index_job`/`_create_index_job` 改 async + 返回 `{file_id}` + 去 job_id、删列表/状态/SSE 端点、删 `_redis_ready`/`_components` Redis 行/`_job_*` helper/`create_job_id`/`IndexJobsStatusRequest`。
- 改 `test_qdrant_api_contract.py`、`test_upload_api.py` 对应用例。
- **验证**：全量单测 + e2e 通过；本地起 backend，上传文件 → 日志 `object_indexed` → search 命中；并发 search+index 无 CUDA error（spike 2 顺带验证）。

### Step 3：删旧代码 + 部署 + 依赖
- 删 `indexing/repository.py`、`indexing/celery_app.py`、`indexing/tasks.py`；删 4 个作废测试文件。
- `pyproject.toml` 删 `redis`、`celery[redis]`。
- 两份 compose 删 redis/index-worker 块 + env 删减；`justfile` 删 celery recipe。
- 前端删 `IndexJobsView.vue` + 路由 + 菜单 + SUB_PAGES + i18n key + 改 `upload.indexSubmitted` 文案。
- **验证**：`pytest` 全过；`docker compose up -d` 起来无 redis/index-worker；镜像变小；前端无索引页、上传仍可触发索引。

### Step 4：spike 结论回填（条件）
- 若 §3.1 spike 2 判定 GPU 并发不安全 → 加 `inference_lock`（新建 `backend/inference_lock.py` + 在 dense/sparse/ocr/rerank 包装方法内加锁 + 单测）。作为独立后续步骤。
- 若 SDK 团队确认需要状态接口（§3.1 待确认 1）→ 增设进程内当前状态映射。
- 同步更新 `docs/architecture.md` §2.4/§2.7、`README.md`。

---

## 附：上传→索引触发方案推荐

**推荐方案 (a)：保留 `POST /api/index/jobs`（含 `/api/open/index/jobs`），简化为「入队 asyncio.Queue」，返回 `{file_id}`。**

理由：
- 现状 `UploadView.vue:132-139` 已是 upload → presign → `POST /api/index/jobs` 三步链，且**不读返回值**（fire-and-forget）。保留该端点 → 上传链路前端**零改动**。
- 方案 (b)（把索引触发合并进上传、删 `POST /api/index/jobs`）需同时改 `UploadView.vue`（去掉第三步调用）和 backend 上传端点（或新建合并端点），两端都动，且把「上传存储」与「索引」耦合，反而更复杂。
- 保留端点还兼容外部 SDK 通过 `/api/open/index/jobs` 触发索引的既有路径（仅返回值形状由 `{job_id}` 变 `{file_id}`，见 §3.1 待确认 1）。
- `presign` 步骤保留不动（不在本次简化范围）。
