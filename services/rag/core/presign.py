import json
from pathlib import Path
from urllib.parse import urlparse

import httpx
from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

from shared.deadline import request_timeout
from shared.upstream import upstream_error


_templates = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False)


def load_presign_template(api_key: str) -> str:
    path = Path(__file__).resolve().parents[1] / "config" / "presign.jinja"
    return path.read_text(encoding="utf-8").replace("YOUR_APP_API_KEY", json.dumps(api_key)[1:-1])


def render_config(template: str, variables: dict) -> dict:
    return json.loads(_templates.from_string(template).render(**variables))


def build_request(template: str, variables: dict) -> dict:
    config = render_config(template, variables)
    return _request_options(config)


def _request_options(config: dict) -> dict:
    headers = config.get("headers", {})
    request = {
        "method": config["method"], "url": config["url"],
        "headers": headers, "params": config.get("params", {}),
    }
    if "body" in config:
        content_type = httpx.Headers(headers).get("content-type", "application/json").split(";", 1)[0].strip().lower()
        if content_type == "application/json" or content_type.endswith("+json"):
            request["json"] = config["body"]
        elif content_type == "application/x-www-form-urlencoded":
            request["data"] = config["body"]
        else:
            request["content"] = config["body"]
    return request


def response_url(payload, path: str) -> str:
    value = payload
    for key in path.split(".") if path else []:
        value = value[int(key)] if isinstance(value, list) else value[key]
    if not isinstance(value, str) or urlparse(value).scheme not in {"http", "https"} or not urlparse(value).netloc:
        raise ValueError(f"presign response field {path!r} must contain an HTTP download URL")
    return value


def fetch_presigned_url(template: str, variables: dict, *, timeout: float) -> str:
    config = render_config(template, variables)
    request = _request_options(config)
    try:
        with httpx.Client(timeout=request_timeout(timeout)) as client:
            response = client.request(**request)
            response.raise_for_status()
            return response_url(response.json(), config["response_url_path"])
    except httpx.HTTPError as exc:
        retryable = isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500
        error = upstream_error("presign", exc, retryable=retryable)
        if isinstance(exc, httpx.HTTPStatusError) and error.error is None:
            error.error = exc.response.text
        raise error from exc
