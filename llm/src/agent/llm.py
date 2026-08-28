import json

import httpx
from langchain_openai import ChatOpenAI

from llm.src.config import settings
from llm.src.infra.logger import get_logger
from llm.src.infra.model_context import get_request_model_name

logger = get_logger("agent.llm")

_default_llm: ChatOpenAI | None = None


def _log_request_sync(request: httpx.Request):
    """httpx sync event hook: log raw HTTP request body."""
    body = request.content.decode("utf-8", errors="replace") if request.content else ""
    logger.info("llm http request", method=str(request.method), url=str(request.url), body=body[:2000])


def _is_streaming_response(response: httpx.Response) -> bool:
    """True if the response is an SSE / chunked stream that we must NOT
    pre-read in a hook — doing so would block the caller's streaming
    iteration (and can trigger ReadTimeout on slow upstreams).
    """
    ctype = response.headers.get("content-type", "").lower()
    return "text/event-stream" in ctype


def _tee_stream_sync(response: httpx.Response) -> None:
    """Wrap response.iter_raw so each raw byte chunk is logged *as it is
    consumed* by the caller. We do NOT initiate any read ourselves — we only
    observe the stream the caller is already iterating.
    """
    original_iter_raw = response.iter_raw

    def _logging_iter_raw(*args, **kwargs):
        seq = 0
        for chunk in original_iter_raw(*args, **kwargs):
            if chunk:
                try:
                    text = chunk.decode("utf-8", errors="replace")
                except Exception:
                    text = repr(chunk)
                logger.info(
                    "llm http stream frame",
                    seq=seq,
                    size=len(chunk),
                    body=text[:2000],
                )
                seq += 1
            yield chunk

    response.iter_raw = _logging_iter_raw  # type: ignore[assignment]


def _tee_stream_async(response: httpx.Response) -> None:
    """Async counterpart of _tee_stream_sync."""
    original_aiter_raw = response.aiter_raw

    async def _logging_aiter_raw(*args, **kwargs):
        seq = 0
        async for chunk in original_aiter_raw(*args, **kwargs):
            if chunk:
                try:
                    text = chunk.decode("utf-8", errors="replace")
                except Exception:
                    text = repr(chunk)
                logger.info(
                    "llm http stream frame",
                    seq=seq,
                    size=len(chunk),
                    body=text[:2000],
                )
                seq += 1
            yield chunk

    response.aiter_raw = _logging_aiter_raw  # type: ignore[assignment]


def _log_response_sync(response: httpx.Response):
    """httpx sync event hook: log raw HTTP response body.

    For streaming responses we install a tee on iter_raw instead of
    pre-reading — that way each SSE frame is logged as it actually arrives,
    without blocking the caller.
    """
    if _is_streaming_response(response):
        logger.info(
            "llm http response (stream)",
            status=response.status_code,
        )
        _tee_stream_sync(response)
        return
    response.read()
    logger.info("llm http response", status=response.status_code, body=response.text[:2000])


async def _log_request_async(request: httpx.Request):
    """httpx async event hook: log raw HTTP request body."""
    body = request.content.decode("utf-8", errors="replace") if request.content else ""
    logger.info("llm http request", method=str(request.method), url=str(request.url), body=body[:2000])


async def _log_response_async(response: httpx.Response):
    """httpx async event hook: log raw HTTP response body.

    IMPORTANT: for SSE / streaming responses we must NOT pre-read the body —
    that would defeat streaming (caller gets the whole payload only after the
    stream finishes) and can trigger ReadTimeout on slow upstreams. Instead
    we install a tee on aiter_raw so each frame is logged as it arrives.
    """
    if _is_streaming_response(response):
        logger.info(
            "llm http response (stream)",
            status=response.status_code,
        )
        _tee_stream_async(response)
        return
    await response.aread()
    logger.info("llm http response", status=response.status_code, body=response.text[:2000])


_llm_pool: dict[str, ChatOpenAI] = {}


def get_llm_for_model(model_name: str) -> ChatOpenAI:
    """获取指定模型的 ChatOpenAI 实例，懒创建并缓存。"""
    if model_name not in _llm_pool:
        _llm_pool[model_name] = create_llm(model=model_name)
        logger.info("llm pool created", model=model_name)
    return _llm_pool[model_name]


def get_llm() -> ChatOpenAI:
    """返回默认共享实例（懒初始化）"""
    requested_model_name = get_request_model_name()
    if requested_model_name:
        # 请求级模型指定不应污染默认共享实例。
        return get_llm_for_model(requested_model_name)

    global _default_llm
    if _default_llm is None:
        _default_llm = create_llm()
        logger.info("default llm created", model=settings.model_name)
    return _default_llm


def create_llm(
    model: str | None = None,
    timeout: int = 10,
    max_retries: int = 0,
) -> ChatOpenAI:
    """按需创建独立实例，用于需要不同配置的场景"""
    model_name = model or settings.model_name
    kwargs: dict = {}

    # Qwen thinking mode conflicts with tool_choice=required —— 必须关闭。
    # 关闭方式取决于走哪个 API：
    #   Responses API      → reasoning.effort=none（OpenRouter 用法），
    #                        非 ChatOpenAI 顶层参数，走 model_kwargs 透传
    #   Chat Completions   → extra_body.chat_template_kwargs.enable_thinking=false
    #                        （vLLM 部署 qwen3 的原生参数；extra_body 是
    #                         ChatOpenAI 顶层参数，直接传，不放 model_kwargs）
    if "qwen" in model_name.lower():
        if settings.use_responses_api:
            kwargs["model_kwargs"] = {"reasoning": {"effort": "none"}}
        else:
            kwargs["extra_body"] = {
                "chat_template_kwargs": {"enable_thinking": False}
            }
        logger.info(
            "thinking mode disabled for qwen model",
            model=model_name, responses_api=settings.use_responses_api,
        )

    # 显式配置的 llm_kwargs 优先级更高；对 Qwen 可覆盖上面的默认值，对其他模型也可直接透传额外参数。
    if settings.llm_kwargs:
        kwargs.pop("model_kwargs", None)
        kwargs.pop("extra_body", None)
        kwargs.update(json.loads(settings.llm_kwargs))
        logger.info("llm kwargs loaded", model=model_name, llm_kwargs=kwargs)

    if settings.debug_llm_http:
        kwargs["http_client"] = httpx.Client(
            event_hooks={"request": [_log_request_sync], "response": [_log_response_sync]},
        )
        kwargs["http_async_client"] = httpx.AsyncClient(
            event_hooks={"request": [_log_request_async], "response": [_log_response_async]},
        )

    return ChatOpenAI(
        model=model_name,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=timeout,
        temperature=0,
        top_p=1.0,
        max_retries=max_retries,
        # 显式选择 API：默认走 Chat Completions —— vLLM 的 Responses API
        # 不接受历史里的纯文本 assistant 消息，多轮对话会报 400。
        use_responses_api=settings.use_responses_api,
        **kwargs,
    )
