from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager

import httpx

from services.inference.app.config import VolcengineConfig
from shared.tracing import get_trace_id
from shared.upstream import UpstreamServiceError, upstream_error


logger = logging.getLogger("services.inference.providers.volcengine")


class _VolcengineModel:
    def __init__(self, config: VolcengineConfig, model: str, base_url: str, timeout: float, http_client: httpx.Client | None):
        self.config = config
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = http_client or httpx.Client(timeout=timeout)
        self.ready = True

    def ping(self) -> bool:
        return self.ready

    def close(self) -> None:
        self._client.close()
        self.ready = False

    def stop(self) -> None:
        self.close()

    @contextmanager
    def _call(self, payload: dict):
        started = time.perf_counter()
        response = None
        provider_request_id = None
        error = None
        try:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            request = self._client.build_request(
                "POST", self.base_url + self.path, content=body,
                headers={"Content-Type": "application/json"}, timeout=self.timeout,
            )
            self._authorize(request)
            response = self._client.send(request)
            provider_request_id = response.headers.get("x-request-id")
            response.raise_for_status()
            result = response.json()
            if isinstance(result, dict):
                provider_request_id = provider_request_id or result.get("request_id") or result.get("id")
            yield result
        except UpstreamServiceError as exc:
            error = exc
            raise
        except Exception as exc:
            error = upstream_error(
                "inference", exc,
                retryable=self._retryable(response) if response is not None else False,
            )
            raise error from exc
        finally:
            logger.log(
                logging.ERROR if error else logging.INFO,
                f"Volcengine {self.operation} request {'failed' if error else 'completed'}",
                exc_info=error is not None,
                extra={
                    "event": f"volcengine_{self.operation}_{'error' if error else 'success'}",
                    "service": "inference", "operation": self.operation, "model": self.model,
                    "trace_id": get_trace_id(),
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                    "status_code": response.status_code if response is not None else None,
                    "provider_request_id": provider_request_id,
                    "retryable": error.retryable if error else None,
                    "error": error.error if error else None,
                    "upstream_response": response.text if error and response is not None else None,
                },
            )
