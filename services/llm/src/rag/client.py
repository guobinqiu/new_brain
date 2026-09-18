"""rag/client.py: Bearer API key + httpx 的 RAG 客户端。

公共 API：
    RagClient(...)                  — 单 client，可 aclose()
    get_rag_client() -> RagClient   — 模块级单例（lifespan 启动时构造）
    RagResult / Document            — 响应数据类

关键不变量：
  - PATH 固定为 /api/v1/rag/search，不拼 query。
  - 5xx / TimeoutException / ConnectError → rag_retry 自愈；
    401 / 403 / 其他 4xx → 不重试。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import httpx

from services.llm.src.infra.logger import get_logger
from services.llm.src.infra.retry import rag_retry
from services.llm.src.rag.schemas import Document, SearchRequest

logger = get_logger("rag.client")

RAG_DEFAULT_TOP_K = 5
PATH = "/api/v1/rag/search"


# ──────────────────────────── RagResult ────────────────────────────


@dataclass
class RagResult:
    """RAG 客户端返回结构。"""

    success: bool = True
    status_code: int = 200
    documents: list[Document] = field(default_factory=list)
    elapsed_ms: float = 0.0
    raw: dict = field(default_factory=dict)
    error: str = ""


# ──────────────────────────── RagClient ────────────────────────────


class RagClient:
    """Bearer API key + httpx 的 RAG HTTP 客户端。

    构造参数（全部 keyword-only）：
        base_url, timeout=10.0, max_retries=DEPRECATED

    注意：重试由 infra.retry.rag_retry 装饰器承担（驱动来源 settings.rag_max_retries），
    `max_retries` 形参保留仅为向后兼容（test_client.py 旧测试仍传入），不生效。
    """

    def __init__(
        self,
        *,
        base_url: str,
        timeout: float = 10.0,
        max_retries: int = 2,  # noqa: ARG003  DEPRECATED: 见类 docstring
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

        # httpx.AsyncClient 单例：连接池复用 + 避免 leak
        # 注意：测试用 install_mock_transport fixture 通过 monkeypatch 替换
        # httpx.AsyncClient，因此这里直接用裸 httpx.AsyncClient。
        self._client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=20,
            ),
        )

    async def aclose(self) -> None:
        """释放 httpx 连接池。重复调用安全。"""
        try:
            await self._client.aclose()
        except Exception as e:
            # 连接已关闭时不抛错（acquire/release 跨 task 场景常见）—— 仅记录调试
            logger.debug("rag httpx client aclose failed (already closed?)", error=str(e)[:200])

    # ─────────────────────── search ───────────────────────

    @rag_retry
    async def _do_post(self, url: str, body_bytes: bytes, headers: dict) -> httpx.Response:
        """实际发出 HTTP POST。

        5xx 由 rag_retry 装饰器重试（raise_for_status 抛 HTTPStatusError），
        4xx 不重试（不抛错 → 不触发重试条件）。
        """
        resp = await self._client.post(url, content=body_bytes, headers=headers)
        if resp.status_code >= 500:
            # 让 rag_retry 看见 HTTPStatusError → 重试
            resp.raise_for_status()
        return resp

    async def search(self, req: SearchRequest, *, app_id: str, api_key: str) -> RagResult:
        """单次 RAG 检索。

        构造 JSON body 字节级发送 → 解 JSON → 解析 results[] 为 Document。
        """
        # 1. 构造请求体（紧凑序列化，无空格；model_dump 已 exclude_none）
        payload = req.model_dump(exclude_none=True)
        body_bytes = json.dumps(
            payload, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "traceparent": _traceparent_header(),
        }
        url = self._base_url + PATH

        # 2. 发出请求（瞬态故障由 rag_retry 自愈）
        try:
            resp = await self._do_post(url, body_bytes, headers)
        except httpx.HTTPStatusError as e:
            # 5xx 重试耗尽：保留真实状态码（rag_retry 已尝试 max_attempts 次）
            status_code = e.response.status_code if e.response else 500
            return RagResult(
                success=False,
                status_code=status_code,
                documents=[],
                elapsed_ms=0.0,
                raw={},
                error=str(e),
            )
        except Exception as e:
            # 其他异常（连接错误、超时重试耗尽等）→ status_code=0
            logger.error("rag http call failed", exc_info=e)
            return RagResult(
                success=False,
                status_code=0,
                documents=[],
                elapsed_ms=0.0,
                raw={},
                error=str(e),
            )

        # 3. 状态码处理
        status = resp.status_code
        if status >= 400:
            # 401/403/422 不重试（已由 rag_retry 跳过），5xx 在 rag_retry 已重试
            body_snip = (resp.text or "")[:200]
            logger.warning("rag response error", status_code=status, body=body_snip)
            return RagResult(
                success=False,
                status_code=status,
                documents=[],
                elapsed_ms=0.0,
                raw={},
                error=f"http {status}: {body_snip}",
            )

        # 4. 解析响应
        try:
            data = resp.json()
        except Exception as e:
            return RagResult(
                success=False,
                status_code=status,
                documents=[],
                elapsed_ms=0.0,
                raw={},
                error=f"invalid json: {e}",
            )

        logger.info(
            "rag response",
            status_code=status,
            elapsed_ms=data.get("elapsed_ms"),
            doc_count=len(data.get("results", []) or []),
            documents=_documents_for_log(data.get("results", []) or []),
        )

        docs: list[Document] = []
        for raw_doc in data.get("results", []) or []:
            try:
                docs.append(Document(**raw_doc))
            except Exception as e:
                logger.warning("skip malformed document", error=str(e), doc=raw_doc)

        return RagResult(
            success=True,
            status_code=status,
            documents=docs,
            elapsed_ms=float(data.get("elapsed_ms") or 0.0),
            raw=data,
            error="",
        )

# ──────────────────────────── 单例 ────────────────────────────


_client: RagClient | None = None


def _build_client_from_settings() -> RagClient:
    """从 settings 构造 RagClient 单例。"""
    # 延迟导入 config 避免循环
    from services.llm.src.config import settings

    return RagClient(
        base_url=settings.rag_base_url,
        timeout=settings.rag_timeout,
    )


def get_rag_client() -> RagClient:
    """模块级单例。第一次调用时构造。"""
    global _client
    if _client is None:
        _client = _build_client_from_settings()
    return _client


def _documents_for_log(documents: list[dict]) -> list[dict]:
    rows = []
    for index, doc in enumerate(documents, start=1):
        content = str(doc.get("content") or "")
        rows.append({
            "rank": index,
            "id": doc.get("id"),
            "score": doc.get("score"),
            "content": content,
        })
    return rows


def _reset_client_for_tests() -> None:
    """测试 fixture 用：清空单例，强制下次 get_rag_client() 重建。"""
    global _client
    _client = None


def _traceparent_header() -> str:
    from services.llm.src.infra.logger import get_trace_id

    trace_id = get_trace_id()
    if len(trace_id) == 32 and all(ch in "0123456789abcdef" for ch in trace_id):
        return f"00-{trace_id}-0000000000000001-01"
    return "00-00000000000000000000000000000000-0000000000000001-01"
