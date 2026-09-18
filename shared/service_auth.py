from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException


def service_auth_headers(api_key: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def require_service_api_key(authorization: str | None = Header(None)) -> None:
    expected = os.getenv("SERVICE_API_KEY", "")
    if not expected:
        return
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="invalid service api key")
