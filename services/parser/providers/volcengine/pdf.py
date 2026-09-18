from services.parser.common.validation import InvalidDocumentError
from dataclasses import dataclass
import base64
import json
import logging
import time
from pathlib import Path

import httpx

from shared.upstream import UpstreamServiceError, upstream_error
from shared.tracing import get_trace_id
from shared.config import VolcengineParserConfig
from shared.retry import retry_call
from services.parser.common.schema import Block
from services.parser.providers.volcengine.normalizer import normalize_response_result


logger = logging.getLogger("services.parser.providers.volcengine")


def _retryable_response(response: httpx.Response | None) -> bool:
    return response is None or 500 <= response.status_code < 600


@dataclass
class VolcengineResponseResult:
    result: dict | None
    response: httpx.Response | None
    started: float
    first_text: float | None = None
    completed: float | None = None


class VolcengineDocumentParser:
    def __init__(self, config: VolcengineParserConfig, *, http_client: httpx.Client | None = None):
        self.config = config
        self._client = http_client
        self.ready = False

    def start(self) -> None:
        if self._client is None:
            self._client = httpx.Client(timeout=self.config.timeout)
        self.ready = True

    def stop(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        self.ready = False

    def _log_call(self, started: float, response: httpx.Response | None, error: UpstreamServiceError | None = None, *, result=None, first_text=None, completed=None) -> None:
        result = result if isinstance(result, dict) else {}
        usage = result.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        output_details = usage.get("output_tokens_details")
        thinking = result.get("thinking")
        upstream_response = None
        if error and response is not None:
            try:
                upstream_response = response.text
            except httpx.ResponseNotRead:
                upstream_response = result
        logger.log(
            logging.ERROR if error else logging.INFO,
            "Volcengine document request failed" if error else "Volcengine document request completed",
            exc_info=error is not None,
            extra={
                "event": "volcengine_error" if error else "volcengine_success",
                "service": "parser",
                "operation": "parse_file",
                "model": self.config.model,
                "trace_id": get_trace_id(),
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "reasoning_tokens": output_details.get("reasoning_tokens") if isinstance(output_details, dict) else None,
                "total_tokens": usage.get("total_tokens"),
                "thinking": thinking.get("type") if isinstance(thinking, dict) else None,
                "requested_thinking": "enabled" if self.config.thinking else "disabled",
                "requested_service_tier": self.config.service_tier,
                "service_tier": result.get("service_tier"),
                "stream": self.config.stream,
                "first_text_ms": round((first_text - started) * 1000, 1) if first_text is not None else None,
                "output_ms": round((completed - first_text) * 1000, 1) if first_text is not None and completed is not None else None,
                "status_code": response.status_code if response is not None else None,
                "provider_request_id": response.headers.get("x-request-id") if response is not None else None,
                "retryable": error.retryable if error else None,
                "error": error.error if error else None,
                "upstream_response": upstream_response,
            },
        )

    def _parse_pdf(self, path: Path, *, original_filename: str | None = None) -> VolcengineResponseResult:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        started = time.perf_counter()
        response = None
        result = None
        first_text = None
        completed = None
        with self._client.stream(
            "POST",
            f"{self.config.base_url.rstrip('/')}/responses",
            headers={"Authorization": f"Bearer {self.config.api_key}", "Accept": "text/event-stream" if self.config.stream else "application/json"},
            json={
                "model": self.config.model,
                "thinking": {"type": "enabled" if self.config.thinking else "disabled"},
                "service_tier": self.config.service_tier,
                "stream": self.config.stream,
                "input": [{"role": "user", "content": [
                    {"type": "input_file", "filename": original_filename or path.name, "file_data": f"data:application/pdf;base64,{encoded}"},
                    {"type": "input_text", "text": self.config.prompt},
                ]}],
            },
            timeout=self.config.timeout,
        ) as response:
            if not response.is_success:
                response.read()
                response.raise_for_status()
            if self.config.stream:
                for event_data in _iter_sse_data(response):
                    if event_data == "[DONE]":
                        continue
                    data = json.loads(event_data)
                    event_type = data["type"]
                    if event_type == "response.output_text.delta" and data["delta"] and first_text is None:
                        first_text = time.perf_counter()
                    elif event_type in {"response.completed", "response.incomplete", "response.failed"}:
                        result = data["response"]
                        completed = time.perf_counter()
                        break
                    elif event_type == "error":
                        result = data
                        raise UpstreamServiceError(service="parser", error=data.get("message"), retryable=False, status_code=502)
                if result is None:
                    raise UpstreamServiceError(service="parser", error="Volcengine stream ended without a final response", retryable=True, status_code=502)
            else:
                response.read()
                result = response.json()
        return VolcengineResponseResult(result=result, response=response, started=started, first_text=first_text, completed=completed)

    def parse_file(self, filepath: str, *, original_filename: str | None = None) -> list[Block]:
        return retry_call(
            lambda: self._parse_file_once(filepath, original_filename=original_filename),
            self.config.retry,
            operation_name="parser.volcengine.parse_file",
        )

    def _parse_file_once(self, filepath: str, *, original_filename: str | None = None) -> list[Block]:
        if not self.ready:
            self.start()
        path = Path(filepath)
        if path.stat().st_size >= 50 * 1024 * 1024:
            raise InvalidDocumentError("Volcengine Base64 PDF input must be smaller than 50 MB")
        started = time.perf_counter()
        response = None
        result = None
        first_text = None
        completed = None
        try:
            parsed = self._parse_pdf(path, original_filename=original_filename)
            started = parsed.started
            response = parsed.response
            result = parsed.result
            first_text = parsed.first_text
            completed = parsed.completed
            blocks = normalize_response_result(result)
        except UpstreamServiceError as exc:
            self._log_call(started, response, exc, result=result, first_text=first_text, completed=completed)
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, httpx.HTTPStatusError):
                response = exc.response
            retryable = _retryable_response(response) if isinstance(exc, httpx.HTTPStatusError) else False
            error = upstream_error("parser", exc, retryable=retryable)
            self._log_call(started, response, error, result=result, first_text=first_text, completed=completed)
            raise error from exc
        self._log_call(started, response, result=result, first_text=first_text, completed=completed)
        return blocks


def _iter_sse_data(response: httpx.Response):
    data_lines = []
    for line in response.iter_lines():
        if not line:
            if data_lines:
                yield "\n".join(data_lines)
                data_lines = []
            continue
        if line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").strip())
    if data_lines:
        yield "\n".join(data_lines)
