from fastapi import APIRouter, Depends, Request
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from llm.src.agent.registry import get_checkpointer, get_graph
from llm.src.api.middleware import limiter
from llm.src.api.requests import ThreadId
from llm.src.config import settings
from llm.src.infra.database import get_pool
from llm.src.infra.logger import get_logger

logger = get_logger("api.threads")
router = APIRouter(prefix="/threads", tags=["threads"])


class ThreadSummary(BaseModel):
    thread_id: str
    message_count: int
    created_at: str | None = None
    updated_at: str | None = None


class ThreadListResponse(BaseModel):
    threads: list[ThreadSummary]
    total: int


@router.get("", response_model=ThreadListResponse)
@limiter.limit(settings.rate_limit_history)
async def list_threads(request: Request):
    """列出所有对话线程，按最后更新时间倒序。"""
    pool = get_pool()
    async with pool.connection() as conn:
        rows = await conn.execute("""
            SELECT
                thread_id,
                COUNT(*) AS checkpoint_count,
                MIN(checkpoint_id) AS created_at,
                MAX(checkpoint_id) AS updated_at
            FROM checkpoints
            WHERE checkpoint_ns = ''
            GROUP BY thread_id
            ORDER BY MAX(checkpoint_id) DESC
        """)
        results = await rows.fetchall()

    threads = [
        ThreadSummary(
            thread_id=row[0],
            message_count=row[1],
            created_at=row[2],
            updated_at=row[3],
        )
        for row in results
    ]

    return ThreadListResponse(threads=threads, total=len(threads))


@router.delete("/{thread_id}")
@limiter.limit(settings.rate_limit_history)
async def delete_thread(request: Request, thread_id: ThreadId):
    """删除指定对话线程的所有检查点数据。"""
    checkpointer = get_checkpointer()

    # 先确认 thread 存在
    pool = get_pool()
    async with pool.connection() as conn:
        row = await conn.execute(
            "SELECT 1 FROM checkpoints WHERE thread_id = %s LIMIT 1",
            (thread_id,),
        )
        exists = await row.fetchone()

    if not exists:
        logger.warning("thread not found for deletion", thread_id=thread_id)
        return {"deleted": False, "detail": "对话不存在"}

    # 使用 checkpointer 官方 API 删除
    await checkpointer.adelete_thread(thread_id)
    logger.info("thread deleted", thread_id=thread_id)

    return {"deleted": True, "thread_id": thread_id}


def _chat_graph():
    return get_graph("chat")


@router.get("/{thread_id}/history")
@limiter.limit(settings.rate_limit_history)
async def get_history(request: Request, thread_id: ThreadId, graph=Depends(_chat_graph)):  # noqa: B008
    """获取指定对话的消息历史。

    B008：FastAPI 框架强制要求 Depends() 在参数默认位置（C 端解析依赖图）。
    """
    config = {"configurable": {"thread_id": thread_id}}
    state = await graph.aget_state(config)

    if not state.values:
        return {"thread_id": thread_id, "messages": []}

    messages = [
        {
            "role": "user" if isinstance(msg, HumanMessage) else "ai",
            "content": msg.content,
        }
        for msg in state.values["messages"]
    ]
    return {"thread_id": thread_id, "messages": messages}
