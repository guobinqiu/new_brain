from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Callable, Literal

from fastapi import HTTPException, Request

from auth.registry import AppCredential, AppRegistry


TIMESTAMP_SKEW_SECONDS = 300


@dataclass(frozen=True)
class Principal:
    type: Literal["admin", "app"]
    app_id: str


def issue_token(config, principal: Principal) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"type": principal.type, "app_id": principal.app_id}
    signing_input = ".".join([_b64_json(header), _b64_json(payload)])
    signature = hmac.new(_jwt_secret(config), signing_input.encode("utf-8"), hashlib.sha256).digest()
    return ".".join([signing_input, _b64(signature)])


def verify_token(config, token: str) -> Principal:
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(401, "invalid token")
    signing_input = ".".join(parts[:2])
    expected = hmac.new(_jwt_secret(config), signing_input.encode("utf-8"), hashlib.sha256).digest()
    if not hmac.compare_digest(_b64(expected), parts[2]):
        raise HTTPException(401, "invalid token")
    try:
        payload = json.loads(_b64_decode(parts[1]).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(401, "invalid token") from exc
    principal_type = payload.get("type")
    app_id = payload.get("app_id")
    if principal_type not in ("admin", "app") or not isinstance(app_id, str):
        raise HTTPException(401, "invalid token")
    if principal_type == "app" and not app_id:
        raise HTTPException(401, "invalid token")
    return Principal(type=principal_type, app_id=app_id)


def authenticate_password(config, username: str | None, password: str | None) -> Principal:
    if not hmac.compare_digest(username or "", config.admin.username):
        raise HTTPException(401, "invalid username or password")
    if not hmac.compare_digest(password or "", config.admin.password):
        raise HTTPException(401, "invalid username or password")
    return Principal(type="admin", app_id="")


def authenticate_client_signature(
    config,
    request: Request,
    body: bytes,
    credential_lookup: Callable[[str], AppCredential | None] | None = None,
) -> Principal:
    app_id = request.headers.get("x-app-id", "")
    access_key = request.headers.get("x-access-key", "")
    timestamp = request.headers.get("x-timestamp", "")
    signature = request.headers.get("x-signature", "")
    if not all((app_id, access_key, timestamp, signature)):
        raise HTTPException(401, "missing signature headers")
    credential = credential_lookup(app_id) if credential_lookup is not None else _app_credential(config, app_id)
    if credential is None or access_key != credential.access_key:
        raise HTTPException(401, "invalid access key")
    _validate_timestamp(timestamp)
    expected = sign_request(credential.secret_key, request.method.upper(), request.url.path, timestamp, body, app_id)
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(401, "invalid signature")
    return Principal(type="app", app_id=app_id)


def sign_request(secret_key: str, method: str, path: str, timestamp: str, body: bytes, app_id: str) -> str:
    body_sha256 = hashlib.sha256(body).hexdigest()
    string_to_sign = "\n".join([method, path, timestamp, body_sha256, app_id])
    return hmac.new(secret_key.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()


def principal_from_authorization(config, authorization: str | None) -> Principal:
    if not authorization:
        raise HTTPException(401, "missing bearer token")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "missing bearer token")
    return verify_token(config, token)


def _validate_timestamp(timestamp: str) -> None:
    try:
        value = int(timestamp)
    except ValueError as exc:
        raise HTTPException(401, "invalid timestamp") from exc
    if abs(int(time.time()) - value) > TIMESTAMP_SKEW_SECONDS:
        raise HTTPException(401, "invalid timestamp")


def _jwt_secret(config) -> bytes:
    value = config.admin.password.encode("utf-8")
    return hashlib.sha256(value).digest()


def _app_credential(config, app_id: str):
    return AppRegistry(config.registry_file).get_app(app_id)


def _b64_json(value: dict) -> str:
    return _b64(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
