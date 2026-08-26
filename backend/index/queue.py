"""进程内索引入队（架构 C）。

把 job 字典放入已注册 ``InlineIndexConsumer`` 持有的 queue.Queue。
没有 broker、没有任务记录、没有 ``job_id``。
"""
from __future__ import annotations

import queue


class IndexQueueRejected(Exception):
    """进程内索引队列无法接受任务（已满）时抛出。"""


def enqueue_index_job(*, app_id, file_id, presigned_url, s3_url, filename) -> dict:
    """把索引任务入队到活消费器的队列。

    返回 ``{"file_id": file_id}``。队列已满时抛 ``IndexQueueRejected``
    （API 层映射为 429）。
    """
    # 运行时 import，避免与 index.consumer 循环导入。
    from index.consumer import index_queue

    job = {
        "app_id": app_id,
        "file_id": file_id,
        "presigned_url": presigned_url,
        "s3_url": s3_url,
        "filename": filename,
        "retry_count": 0,
    }
    try:
        index_queue().put_nowait(job)
    except queue.Full as exc:
        raise IndexQueueRejected("index queue full") from exc
    return {"file_id": file_id}
