from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from typing import Callable, Literal

from fastapi import HTTPException

from shared.config import AppCredential

APP_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,63}$")


@dataclass(frozen=True)
class Principal:
    type: Literal["admin", "app"]
    app_id: str


def validate_app_id(app_id: str) -> str:
    if not APP_ID_PATTERN.fullmatch(app_id):
        raise ValueError("app_id must start with a letter and contain only letters, numbers, or underscore")
    return app_id


def issue_token(config, principal: Principal) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"type": principal.type, "app_id": principal.app_id}
    signing_input = ".".join([_b64_json(header), _b64_json(payload)])
    signature = hmac.new(_jwt_secret(config), signing_input.encode("utf-8"), hashlib.sha256).digest()
    return ".".join([signing_input, _b64(signature)])


def verify_token(config, token: str) -> Principal:
    secret = _jwt_secret(config)
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(401, "invalid token")
    signing_input = ".".join(parts[:2])
    expected = hmac.new(secret, signing_input.encode("utf-8"), hashlib.sha256).digest()
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
    _jwt_secret(config)
    if not hmac.compare_digest(username or "", config.admin.username):
        raise HTTPException(401, "invalid username or password")
    if not hmac.compare_digest(password or "", config.admin.password):
        raise HTTPException(401, "invalid username or password")
    return Principal(type="admin", app_id="")


def authenticate_api_key(
    authorization: str | None,
    credential_lookup: Callable[[str], AppCredential | None],
) -> Principal:
    token = bearer_token(authorization)
    credential = credential_lookup(token)
    if credential is None:
        raise HTTPException(401, "invalid api key")
    return Principal(type="app", app_id=credential.app_id)


def principal_from_authorization(config, authorization: str | None) -> Principal:
    return verify_token(config, bearer_token(authorization))


def bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(401, "missing bearer token")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "missing bearer token")
    return token


def _jwt_secret(config) -> bytes:
    if not config.admin.password:
        raise HTTPException(503, "admin authentication is unavailable")
    value = config.admin.password.encode("utf-8")
    return hashlib.sha256(value).digest()


def _b64_json(value: dict) -> str:
    return _b64(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
