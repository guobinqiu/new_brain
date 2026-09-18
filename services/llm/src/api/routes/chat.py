"""api/routes/chat.py: POST /api/v1/llm/chat/stream（SSE）。"""

from __future__ import annotations

import inspect
import json
import time
from collections.abc import AsyncIterator
from functools import lru_cache

import langsmith
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

from services.llm.src.agent.registry import get_graph
from services.llm.src.api.auth import require_api_key
from services.llm.src.api.middleware import limiter
from services.llm.src.api.requests import AgentRequest
from services.llm.src.config import settings
from services.llm.src.infra.logger import get_logger, get_trace_id, set_thread_id

logger = get_logger("api.chat")
router = APIRouter()


async def _chat_graph():
    """解析 chat graph 依赖。

    生产：`get_graph("chat")` 返回 graph 对象（同步）。
    测试：`monkeypatch` 把 `get_graph` 改成 async，返回 coroutine。
    为同时兼容两种场景，对返回结果做 `isawaitable` 检查。
    """
    g = get_graph("chat")
    if inspect.isawaitable(g):
        g = await g
    return g


class ChatRequest(AgentRequest):
    pass


def _sse(payload: dict) -> str:
    """构造 SSE 单条事件（data: <json>\\n\\n）。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@lru_cache(maxsize=1)
def _get_tracing_client():
    return langsmith.Client(api_key=settings.langchain_api_key)


# ───────────────────── /api/v1/llm/chat/stream ─────────────────────


@router.post("/api/v1/llm/chat/stream", dependencies=[Depends(require_api_key)])
@limiter.limit(settings.rate_limit_chat)
async def chat_stream(request: Request, req: ChatRequest, graph=Depends(_chat_graph)):  # noqa: B008
    """SSE 流式。

    B008：FastAPI 框架强制要求 Depends() 在参数默认位置（C 端解析依赖图）。
    """
    set_thread_id(req.thread_id)
    logger.info("chat stream request", msg_len=len(req.message))

    config = {"configurable": {"thread_id": req.thread_id}}
    input_data = {"messages": [HumanMessage(content=req.message)]}

    async def event_generator() -> AsyncIterator[str]:
        t0 = time.perf_counter()
        ttft_ms: float | None = None
        streamed_text_parts: list[str] = []
        try:
            with langsmith.tracing_context(
                enabled=settings.langchain_tracing_v2,
                project_name=settings.langchain_project,
                client=_get_tracing_client() if settings.langchain_tracing_v2 else None,
            ):
                async for mode, payload in graph.astream(
                    input_data,
                    config=config,
                    stream_mode=["custom"],
                ):
                    if mode == "custom":
                        if not isinstance(payload, dict):
                            continue
                        if payload.get("type") == "token":
                            content = payload.get("content") or ""
                            if content:
                                if ttft_ms is None:
                                    ttft_ms = (time.perf_counter() - t0) * 1000
                                streamed_text_parts.append(content)
                                yield _sse(payload)
            if ttft_ms is not None:
                logger.info("server ttft", ttft_ms=round(ttft_ms, 1))
            yield _sse({"type": "done"})
        except Exception as e:
            logger.error("stream error", error=str(e), exc_info=True)
            yield _sse({
                "type": "error",
                "message": str(e),
                "trace_id": get_trace_id(),
            })

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
