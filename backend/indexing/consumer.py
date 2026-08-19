"""进程内索引消费器（架构 C）。

backend 进程内使用 queue.Queue + 单工作线程消费索引任务，替代原 Celery
index-worker。``_index_object`` 从原 ``indexing/tasks.py`` 的 celery 封装迁移而来；
该文件连同 ``indexing/celery_app.py``、``indexing/repository.py`` 已一并删除。
"""
from __future__ import annotations

import asyncio
import contextvars
import functools
import logging
import queue as _queue
from concurrent.futures import ThreadPoolExecutor

from indexing.service import index_presigned_object

logger = logging.getLogger("rag.index_consumer")

# 模块级单例，由 ``InlineIndexConsumer.start`` 注册；``index_queue()`` 负责读取，
# enqueue_index_job（queue.py）通过它拿到活队列。
_consumer = None

# 进程内队列不是真 broker，这三个值不进运维配置面，硬编码默认值。
_DEFAULT_MAX_PENDING_JOBS = 10      # 等待队列容量：满了入队端点返回 429
_DEFAULT_JOB_TIMEOUT_SECONDS = 1800 # 单任务 30 分钟超时，超时按可重试失败处理
_DEFAULT_JOB_RETRY_MAX = 2          # 可重试失败最多重入队 2 次，仍失败则放弃


def index_queue() -> _queue.Queue:
    """返回已注册消费器持有的 queue.Queue。"""
    if _consumer is None:
        raise RuntimeError("no inline index consumer registered")
    return _consumer.queue


def _register_consumer(consumer) -> None:
    """模块级单例注册；传 ``None`` 清空（测试隔离用）。"""
    global _consumer
    _consumer = consumer


class InlineIndexConsumer:
    """单工作线程的进程内索引消费器。

    ``queue``/``timeout``/``retry_max`` 是测试注入用的可选参数；不传时使用
    模块级硬编码默认值（10 / 1800 / 2）。
    """

    def __init__(self, application, *, queue=None, timeout=None, retry_max=None):
        self.application = application
        self.queue = (
            queue if queue is not None else _queue.Queue(maxsize=_DEFAULT_MAX_PENDING_JOBS)
        )
        self.stop_event = asyncio.Event()
        self.task = None
        self.timeout = timeout if timeout is not None else _DEFAULT_JOB_TIMEOUT_SECONDS
        self.retry_max = retry_max if retry_max is not None else _DEFAULT_JOB_RETRY_MAX
        # max_workers=1 串行化索引，超时后的孤儿线程不会与下一个任务的 GPU 工作重叠（设计 §4.3）。
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="index-worker")

    async def start(self) -> None:
        _register_consumer(self)
        self.task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self.stop_event.set()
        if self.task is not None:
            await asyncio.gather(self.task, return_exceptions=True)
        self.executor.shutdown(wait=False)
        # 与 start() 的注册对称：注销单例，让 shutdown 之后的 enqueue_index_job
        # 抛 RuntimeError，而不是把任务悄悄放进死队列。
        _register_consumer(None)

    async def _loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self.stop_event.is_set():
            try:
                job = await loop.run_in_executor(
                    None, lambda: self.queue.get(timeout=1.0)
                )
            except _queue.Empty:
                continue
            await self._run_job(job)

    async def _run_job(self, job) -> None:
        app_id = job["app_id"]
        file_id = job["file_id"]
        filename = job.get("filename")
        retry_count = job.get("retry_count", 0)
        loop = asyncio.get_running_loop()
        # copy_context() 给这次 executor 调用独立的 ContextVar 作用域；
        # _index_object 自己也会进 app_context，这里是兜底。
        ctx = contextvars.copy_context()
        try:
            await asyncio.wait_for(
                loop.run_in_executor(
                    self.executor,
                    ctx.run,
                    functools.partial(_index_object, self.application, job),
                ),
                timeout=self.timeout,
            )
            return
        except ValueError as exc:
            # 不可重试（app 数据库未初始化、不支持的文件类型）：直接丢弃。
            logger.warning(
                "Index failed (non-retryable)",
                exc_info=True,
                extra={
                    "event": "index_failed",
                    "app_id": app_id,
                    "file_id": file_id,
                    "error": str(exc),
                },
            )
            return
        except asyncio.TimeoutError:
            reason = f"index timeout after {self.timeout}s"
        except Exception as exc:  # noqa: BLE001 - 可重试分支
            reason = f"index failed: {exc!r}"

        # 可重试分支：超时或一般异常。
        if retry_count < self.retry_max:
            job["retry_count"] = retry_count + 1
            try:
                self.queue.put_nowait(job)
            except _queue.Full:
                logger.error(
                    "Re-enqueue failed (queue full), dropping job",
                    extra={
                        "event": "index_reenqueue_dropped",
                        "app_id": app_id,
                        "file_id": file_id,
                    },
                )
        else:
            logger.error(
                "Index job exhausted retries, giving up",
                extra={
                    "event": "index_failed_final",
                    "app_id": app_id,
                    "file_id": file_id,
                    # "filename" 是 LogRecord 的保留字段，不能用作 extra 键，
                    # 因此与成功路径日志一致，改用 document_filename。
                    "document_filename": filename,
                    "retry_count": retry_count,
                    "error": reason,
                },
            )


def _index_object(application, job) -> dict:
    """从 indexing/tasks.py L47-64 迁移而来；入参为 job 字典 + application。

    app 集合不存在时抛 ``ValueError``（不可重试）。
    """
    app_id = job["app_id"]
    file_id = job["file_id"]
    presigned_url = job["presigned_url"]
    s3_url = job["s3_url"]
    filename = job.get("filename")
    if not application.store.app_collection_exists(app_id):
        raise ValueError("app database is not initialized")
    with application.store.app_context(app_id):
        count = index_presigned_object(application, file_id, presigned_url, s3_url, filename)
    logger.info(
        "Object indexed",
        extra={
            "event": "object_indexed",
            "app_id": app_id,
            "file_id": file_id,
            "document_filename": filename,
            "s3_url": s3_url,
            "chunk_count": count,
        },
    )
    return {"app_id": app_id, "file_id": file_id, "chunk_count": count}
