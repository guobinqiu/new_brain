from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os

from fastapi import Header, HTTPException


def require_admin_jwt(authorization: str | None = Header(None)) -> None:
    token = _bearer_token(authorization)
    payload = _verify_token(token)
    if payload.get("type") != "admin":
        raise HTTPException(403, "admin token required")


def _verify_token(token: str) -> dict:
    password = os.getenv("RAG_ADMIN_PASSWORD", "")
    if not password:
        raise HTTPException(503, "admin authentication is unavailable")
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(401, "invalid token")
    signing_input = ".".join(parts[:2])
    expected = hmac.new(hashlib.sha256(password.encode("utf-8")).digest(), signing_input.encode("utf-8"), hashlib.sha256).digest()
    if not hmac.compare_digest(_b64(expected), parts[2]):
        raise HTTPException(401, "invalid token")
    try:
        return json.loads(_b64_decode(parts[1]).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(401, "invalid token") from exc


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(401, "missing bearer token")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "missing bearer token")
    return token


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
