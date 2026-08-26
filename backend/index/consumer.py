"""进程内索引消费器。"""
from __future__ import annotations

import logging
import queue as _queue
import threading

from index.service import index_presigned_object

logger = logging.getLogger("rag.index_consumer")

# 模块级单例，由 ``InlineIndexConsumer.start`` 注册；``index_queue()`` 负责读取，
# enqueue_index_job（queue.py）通过它拿到活队列。
_consumer = None

# 进程内队列不是真 broker，这两个值不进运维配置面，硬编码默认值。
_DEFAULT_MAX_PENDING_JOBS = 10      # 等待队列容量：满了入队端点返回 429
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

    ``queue``/``retry_max`` 是测试注入用的可选参数；不传时使用模块级硬编码
    默认值（10 / 2）。
    """

    def __init__(self, application, *, queue=None, retry_max=None):
        self.application = application
        self.queue = (
            queue if queue is not None else _queue.Queue(maxsize=_DEFAULT_MAX_PENDING_JOBS)
        )
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.retry_max = retry_max if retry_max is not None else _DEFAULT_JOB_RETRY_MAX

    def _upsert_record(self, result: dict) -> None:
        self.application.database.upsert_file(
            result["app_id"],
            result["file_id"],
            result["filename"],
            result["s3_url"],
            size=result["size"],
            chunk_count=result["chunk_count"],
        )

    def start(self) -> None:
        _register_consumer(self)
        self.thread = threading.Thread(target=self._loop, name="index-consumer", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=1.0)
        # 与 start() 的注册对称：注销单例，让 shutdown 之后的 enqueue_index_job
        # 抛 RuntimeError，而不是把任务悄悄放进死队列。
        _register_consumer(None)

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                job = self.queue.get(timeout=0.1)
            except _queue.Empty:
                continue
            self._run_job(job)

    def _run_job(self, job) -> None:
        app_id = job["app_id"]
        file_id = job["file_id"]
        filename = job.get("filename")
        retry_count = job.get("retry_count", 0)
        self.application.database.mark_file_indexing(app_id, file_id)
        try:
            result = _index_object(self.application, job)
            self._upsert_record(result)
            return
        except ValueError as exc:
            # 不可重试（app 数据库未初始化、不支持的文件类型）：直接丢弃。
            self.application.database.mark_file_failed(app_id, file_id, str(exc))
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
        except Exception as exc:  # noqa: BLE001 - 可重试分支
            reason = f"index failed: {exc!r}"

        # 可重试分支：一般异常。
        if retry_count < self.retry_max:
            job["retry_count"] = retry_count + 1
            try:
                self.queue.put_nowait(job)
            except _queue.Full:
                self.application.database.mark_file_failed(app_id, file_id, "index queue full while retrying")
                logger.error(
                    "Re-enqueue failed (queue full), dropping job",
                    extra={
                        "event": "index_reenqueue_dropped",
                        "app_id": app_id,
                        "file_id": file_id,
                    },
                )
        else:
            self.application.database.mark_file_failed(app_id, file_id, reason)
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
    """执行单个索引任务；app 集合不存在时抛 ``ValueError``。"""
    app_id = job["app_id"]
    file_id = job["file_id"]
    presigned_url = job["presigned_url"]
    s3_url = job["s3_url"]
    filename = job.get("filename")
    if not application.store.app_collection_exists(app_id):
        raise ValueError("app database is not initialized")
    with application.store.app_context(app_id):
        count, file_size = index_presigned_object(application, file_id, presigned_url, s3_url, filename)
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
    return {
        "app_id": app_id,
        "file_id": file_id,
        "chunk_count": count,
        "size": file_size,
        "s3_url": s3_url,
        "filename": filename,
    }
