"""agent/nodes/rag_prefetch.py: Pre-fetch RAG results before LLM.

Calls RagClient.search() with the user's last message, formats results,
and stores them in state["rag_context"] for the llm node to inject.
"""

from __future__ import annotations

from typing import Any

from llm.src.agent.stream import safe_get_writer
from llm.src.infra.logger import get_logger

logger = get_logger("agent.nodes.rag_prefetch")


async def rag_prefetch_node(state: dict[str, Any]) -> dict[str, Any]:
    """Pre-fetch RAG results for the current user question.

    Reads the last HumanMessage, calls RagClient.search(),
    and returns rag_context string for llm node.
    """
    messages = state.get("messages") or []
    if not messages:
        return {"rag_context": ""}

    # Find the last HumanMessage
    query = ""
    for msg in reversed(messages):
        if hasattr(msg, "type") and msg.type == "human":
            query = msg.content if isinstance(msg.content, str) else str(msg.content)
            break

    if not query.strip():
        return {"rag_context": ""}

    from llm.src.api.auth import get_current_credential

    credential = get_current_credential()
    if credential is None:
        logger.error("rag_prefetch missing app credential")
        return {"rag_context": ""}

    # Lazy-import get_rag_client for testability
    from llm.src.rag.client import get_rag_client
    client = get_rag_client()

    # If mock, still call to get mock data
    try:
        from llm.src.rag.schemas import SearchRequest
        req = SearchRequest(query=query, top_k=3, mode="hybrid", rerank=True)
        result = await client.search(
            req,
            app_id=credential.app_id,
            access_key=credential.access_key,
            secret_key=credential.secret_key,
        )
    except Exception as e:
        logger.error("rag_prefetch search failed", error=str(e))
        return {"rag_context": ""}

    if not result.documents:
        # Still inject a marker so LLM knows RAG was attempted but found nothing
        return {"rag_context": "[RAG 检索完成，未找到相关文档]"}

    # Format documents as context
    context_parts = []
    for doc in result.documents:
        context_parts.append(doc.content)
    context = "\n\n".join(context_parts)

    writer = safe_get_writer()
    if writer is not None:
        try:
            writer({
                "type": "rag_context",
                "count": len(result.documents),
                "elapsed_ms": result.elapsed_ms,
            })
        except Exception as e:
            logger.debug("writer.push rag_context failed", error=str(e)[:200])

    logger.info("rag_prefetch done", query_len=len(query), doc_count=len(result.documents))
    return {"rag_context": context}
