import asyncio

from langchain_core.messages import AIMessage, SystemMessage

from services.llm.src.agent.llm import get_llm
from services.llm.src.agent.stream import safe_get_writer, write_reply
from services.llm.src.config import settings
from services.llm.src.infra.logger import get_logger
from services.llm.src.infra.metrics import Timer, mark_llm_error, mark_llm_ok

logger = get_logger("agent.nodes.llm")

_semaphore: asyncio.Semaphore | None = None


def init_semaphore(limit: int):
    global _semaphore
    _semaphore = asyncio.Semaphore(limit)
    logger.info("semaphore initialized", limit=limit)


def get_semaphore() -> asyncio.Semaphore:
    """获取并发 semaphore；未初始化时按应用配置创建。"""
    global _semaphore
    if _semaphore is None:
        limit = settings.llm_concurrency_limit
        _semaphore = asyncio.Semaphore(limit)
        logger.info("semaphore auto-initialized", limit=limit)
    return _semaphore


async def llm_node(state: dict) -> dict:
    """llm 节点：流式调用 LLM，逐 token 推送给前端。

    如果 state 含 rag_context，将其注入为 system message 前缀。
    """
    logger.info("llm_node start")

    messages = list(state.get("messages") or [])
    rag_context = state.get("rag_context") or ""

    # Inject RAG context as system message if available
    if rag_context:
        system_msg = SystemMessage(
            content=(
                "你是一个智能助手。以下是与用户问题相关的参考资料，请基于这些资料回答用户问题。\n\n"
                "## 参考资料\n\n"
                f"{rag_context}\n\n"
                "请用自然、准确的中文回答用户问题。如果参考资料中没有相关信息，请基于你的知识回答。"
            )
        )
        messages = [system_msg] + messages

    base_llm = get_llm()
    writer = safe_get_writer()

    full_content = ""

    async with get_semaphore():
        with Timer() as t:
            try:
                async for chunk in base_llm.astream(messages):
                    # 逐 token 推送
                    token = chunk.content
                    if token:
                        full_content += token
                        write_reply(writer, token)

                mark_llm_ok()
            except Exception as e:
                mark_llm_error(str(e))
                raise

    logger.info(
        "llm_node tokens",
        tokens_in=0,
        tokens_out=0,
        cost=0.0,
    )

    # 构造 AIMessage 用于 state.messages（langchain 需要完整消息对象）
    response = AIMessage(content=full_content)

    return {
        "messages": [response],
        "llm_ms": t.ms,
        "tokens_in": 0,
        "tokens_out": 0,
        "cost": 0.0,
    }
