from fastapi import HTTPException

from rag.api.runtime import runtime


def health():
    return {"status": "ok"}


def ready():
    if not runtime.application.ready:
        raise HTTPException(503, "search is not initialized")
    return {"status": "ready"}
