"""Checkpoint 垃圾回收：定期删除长时间无活动的会话线程。

LangGraph 的 AsyncPostgresSaver 只写不清——三张表（checkpoints /
checkpoint_blobs / checkpoint_writes）会随会话数无限增长。本模块提供一个
随 app 起停的后台周期任务，删除「最后活动时间」早于保留窗口的整条 thread。

关键设计：
- 删除统一走 checkpointer.adelete_thread()，它一次删干净一个 thread 的全部
  三张表（官方 API，避免自己拼 SQL 漏表产生孤儿 blob/writes）。
- 三张表都没有 created_at 时间列，唯一时间来源是 checkpoint_id（UUID v6，
  前 60 bit 是 100ns 间隔、从 1582-10-15 起的时间戳）。筛选阶段在 SQL 里把
  每个 thread 的 MAX(checkpoint_id) 还原成 timestamptz，与保留窗口比较。
"""
from __future__ import annotations

import asyncio

from llm.src.agent.registry import get_checkpointer, set_checkpointer
from llm.src.config import settings
from llm.src.infra.database import get_pool
from llm.src.infra.logger import get_logger

logger = get_logger("api.checkpoint_gc")

_gc_task: asyncio.Task | None = None

# UUID v6 时间还原：
#   - 去掉 '-' 后，前 12 个 hex 是 time_high(8) + 跨 version 位的 time_mid/low。
#   - v6 布局：32 bit time_high | 16 bit time_mid | 4 bit version | 12 bit time_low
#     拼回 60 bit 的 100ns 计数（自 1582-10-15 00:00:00 UTC）。
#   - 转成 Unix 秒：(ticks / 1e7) - 12219292800（1582→1970 的秒差）。
# 该表达式对单个 checkpoint_id（thread 内最新的一行）求值，开销可忽略。
_V6_TO_EPOCH_SQL = """
(
  (
    (
      ('x' || substr(replace(latest, '-', ''), 1, 8))::bit(32)::bigint << 28
    ) |
    (
      ('x' || substr(replace(latest, '-', ''), 9, 4))::bit(16)::bigint << 12
    ) |
    (
      ('x' || substr(replace(latest, '-', ''), 14, 3))::bit(12)::bigint
    )
  )::numeric / 1e7 - 12219292800
)
"""

# 找出最后活动时间早于阈值的 thread_id。
# inner: 每个 thread 取 MAX(checkpoint_id)（v6 时间有序，MAX 即最新）。
# ruff: noqa: S608 —— checkpoint_id 是数据库里现存的 UUID v6 字段，全表 GROUP BY 后直接
# 走 ORM 还原时间戳（f-string 嵌入的是常数 _V6_TO_EPOCH_SQL 表达式，无任何用户输入）。
_SELECT_STALE_SQL = f"""
SELECT thread_id
FROM (
    SELECT thread_id, MAX(checkpoint_id) AS latest
    FROM checkpoints
    WHERE checkpoint_ns = ''
    GROUP BY thread_id
) t
WHERE to_timestamp({_V6_TO_EPOCH_SQL}) < now() - make_interval(days => %s)
"""


# ── 生命周期 ──────────────────────────────────────────────────

def start_gc_loop() -> None:
    """应用启动时调用，启动后台周期清理任务。"""
    global _gc_task  # noqa: PLW0603
    if _gc_task is not None:
        return
    _gc_task = asyncio.create_task(_gc_loop())
    logger.info(
        "checkpoint gc loop started",
        retention_days=settings.checkpoint_retention_days,
        interval_sec=settings.checkpoint_gc_interval_sec,
    )


async def shutdown_gc() -> None:
    """应用关闭时调用，停止后台清理任务。"""
    global _gc_task  # noqa: PLW0603
    if _gc_task is not None:
        _gc_task.cancel()
        _gc_task = None
        logger.info("checkpoint gc loop stopped")


# ── 内部实现 ──────────────────────────────────────────────────

async def _gc_loop() -> None:
    """后台协程：每隔 interval 秒清理一次过期 thread。"""
    interval = settings.checkpoint_gc_interval_sec
    while True:
        await asyncio.sleep(interval)
        try:
            await run_gc_once()
        except asyncio.CancelledError:
            logger.info("checkpoint gc cancelled")
            raise
        except Exception:
            # 系统层兜底：清理失败不应中断 app，下个周期重试。
            logger.exception("checkpoint gc failed, will retry next cycle")


async def run_gc_once(*, dry_run: bool = False) -> int:
    """执行一次清理，返回（dry_run 时为待删、否则为已删）的 thread 数。

    可被定时任务调用，也可手动调用（如运维脚本 / 接口触发）。
    dry_run=True 时只统计、不真删（运维预览用）。
    """
    retention_days = settings.checkpoint_retention_days
    stale_ids = await _find_stale_threads(retention_days)
    if not stale_ids:
        logger.info("checkpoint gc: no stale threads", retention_days=retention_days)
        return 0

    if dry_run:
        logger.info(
            "checkpoint gc dry-run", retention_days=retention_days, stale=len(stale_ids)
        )
        return len(stale_ids)

    checkpointer = get_checkpointer()
    deleted = 0
    for thread_id in stale_ids:
        try:
            await checkpointer.adelete_thread(thread_id)
            deleted += 1
        except asyncio.CancelledError:
            logger.info("checkpoint gc cancelled mid-delete", deleted=deleted)
            raise
        except Exception:
            # 单个 thread 删除失败不影响其余，记录后继续。
            logger.warning(
                "checkpoint gc: delete thread failed",
                thread_id=thread_id,
                exc_info=True,
            )

    logger.info(
        "checkpoint gc done",
        retention_days=retention_days,
        stale=len(stale_ids),
        deleted=deleted,
    )
    return deleted


async def _find_stale_threads(retention_days: int) -> list[str]:
    """查出最后活动时间早于保留窗口的 thread_id 列表。"""
    pool = get_pool()
    async with pool.connection() as conn:
        rows = await conn.execute(_SELECT_STALE_SQL, (retention_days,))
        results = await rows.fetchall()
    # row_factory=dict_row：取首列值（兼容 dict / tuple 两种行）。
    return [row["thread_id"] if isinstance(row, dict) else row[0] for row in results]


# ── 手动触发入口（CLI）────────────────────────────────────────
# 用法（容器内，经 justfile）：
#   just gc            # 真删一次（保留窗口取 settings.checkpoint_retention_days）
#   just gc --dry-run  # 只统计待删数量、不真删（预览）
#
# 不经 FastAPI lifespan，故 get_pool / get_checkpointer 依赖的两件初始化
# （连接池、checkpointer）要自己装配——复刻 bench_model.py 的离线套路。

async def _main() -> None:
    import sys

    from psycopg_pool import AsyncConnectionPool

    from infra import database
    from llm.src.infra.logger import configure_logging

    dry_run = "--dry-run" in sys.argv

    configure_logging()
    pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=1,
        max_size=2,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0},
    )
    await pool.open(wait=True, timeout=30)
    # get_pool() 读 infra.database 的模块级全局，离线脚本直接注入。
    database._pool = pool  # noqa: SLF001

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    set_checkpointer(AsyncPostgresSaver(pool))

    try:
        n = await run_gc_once(dry_run=dry_run)
        verb = "待删" if dry_run else "已删"
        logger.info("checkpoint gc cli done", dry_run=dry_run, threads=n)
        print(f"[checkpoint gc] {verb} {n} 条 thread"
              f"（retention={settings.checkpoint_retention_days}d）")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_main())
