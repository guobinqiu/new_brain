import hmac

from fastapi import Header, HTTPException, Request

from services.rag.core.api.schemas import LoginRequest
from services.rag.core.auth import Principal, authenticate_api_key, authenticate_password, issue_token, principal_from_authorization


def require_jwt(request: Request, authorization: str | None = Header(None)) -> Principal:
    return principal_from_authorization(request.app.state.config.auth, authorization)


async def require_api_key(request: Request, authorization: str | None = Header(None)) -> Principal:
    return authenticate_api_key(authorization, lambda api_key: _get_app_by_api_key(request.app.state, api_key))


async def require_principal(request: Request, authorization: str | None = Header(None)) -> Principal:
    return await require_api_key(request, authorization)


def login(state, req: LoginRequest):
    principal = authenticate_password(state.config.auth, req.username, req.password)
    return {
        "access_token": issue_token(state.config.auth, principal),
        "token_type": "Bearer",
    }


def _get_app_by_api_key(state, api_key: str):
    if state.config.database is None:
        return next((
            app for app in state.config.auth.apps
            if hmac.compare_digest(app.api_key.encode("utf-8"), api_key.encode("utf-8"))
        ), None)
    try:
        return state.db_client.get_app_by_api_key(api_key)
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc
