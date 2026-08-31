from fastapi import Header, HTTPException, Request

from rag.api.runtime import runtime
from rag.api.schemas import LoginRequest
from rag.auth import Principal, authenticate_client_signature, authenticate_password, issue_token, principal_from_authorization


def require_jwt(authorization: str | None = Header(None)) -> Principal:
    return principal_from_authorization(runtime.application.config.auth, authorization)


async def require_aksk(request: Request) -> Principal:
    if not runtime.application.database.ready:
        raise HTTPException(503, "database is not initialized")
    return authenticate_client_signature(runtime.application.config.auth, request, await request.body(), runtime.application.database.get_app)


def login(req: LoginRequest):
    principal = authenticate_password(runtime.application.config.auth, req.username, req.password)
    return {
        "access_token": issue_token(runtime.application.config.auth, principal),
        "token_type": "Bearer",
    }
