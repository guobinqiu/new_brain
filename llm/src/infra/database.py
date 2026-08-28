import psycopg_pool

from llm.src.config import settings
from llm.src.infra.logger import get_logger

logger = get_logger("database")

_pool: psycopg_pool.AsyncConnectionPool | None = None

async def init_pool():
    global _pool
    _pool = psycopg_pool.AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=settings.db_pool_min,
        max_size=settings.db_pool_max,
        open=False,
    )
    await _pool.open()
    logger.info("pool initialized", min_size=settings.db_pool_min, max_size=settings.db_pool_max)

async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        logger.info("pool closed")

def get_pool() -> psycopg_pool.AsyncConnectionPool:
    if _pool is None:
        raise RuntimeError("连接池未初始化")
    return _pool
